# Plan: Feedback Queue (反馈队列)

## Summary
允许用户在提交反馈后、agent 返回之前继续追加反馈。前端维护本地队列，agent 返回时一次性将所有排队反馈合并发送。每个队列项目独立组装，系统级提示词（NEW TASK、反馈提醒、上下文刷新）作为全局项目只添加一次。

## User Story
As a user, I want to submit additional feedback after my first submission while the agent is still processing, So that I can add more thoughts without waiting for the agent to return.

## Problem -> Solution
**Before**: Submit → button disabled, textarea disabled → wait for agent → button re-enabled → submit again
**After**: Submit → button/textarea stay enabled, queue indicator shown → submit more → agent returns → all queued items sent at once

## Metadata
- **Complexity**: Medium
- **Estimated Files**: 8

---

## UX Design

### Before
```
[WAITING] → click Submit → [PROCESSING] → [SUBMITTED: button disabled]
                                          → user waits...
                                          → agent returns → [WAITING]
```

### After
```
[WAITING] → click Submit → [SUBMITTED] → [QUEUED: button enabled, "1 item queued"]
                          → click Submit again → [QUEUED: "2 items queued"]
                          → agent returns → sends all → [WAITING]
```

### Interaction Changes
| Touchpoint | Before | After |
|---|---|---|
| Submit button after first submit | Disabled | Enabled |
| Textarea after first submit | Disabled | Enabled |
| Queue indicator | None | Badge showing queued count |
| Agent return behavior | Just re-enables UI | Drains queue + sends all items |

---

## Architecture

### Design Decision: Frontend Queue

The queue lives **on the frontend**, not the backend. Reasons:

1. After `feedback_completed.set()`, `wait_for_feedback` returns and the MCP tool completes. The old session will be replaced by a new one. Backend-queued items on the old session would be lost.
2. When the agent calls `interactive_feedback` again, a **new session** is created. The frontend can send accumulated queue items to the new session.
3. Simpler backend changes — no cross-session queue management needed.

### Prompt Attachment Strategy (关键设计)

当前单条反馈的提示词组装：
```
[NEW TASK 指令]        ← 仅 clear_context=true 时，插入位置 0
[用户反馈 + 图片]      ← create_feedback_text() 生成
[反馈提醒]             ← _get_feedback_reminder()
[上下文刷新提醒]       ← _get_context_refresh_reminder()，clear_context 时跳过
```

**多条队列项目的组装策略**：
```
[NEW TASK 指令]        ← 任意项目有 clear_context 时，只添加一次
[反馈 1 文字 + 图片]   ← 第一条反馈（首次提交）
[反馈 2 文字 + 图片]   ← 第二条反馈（队列）
[反馈 3 文字 + 图片]   ← 第三条反馈（队列）
[反馈提醒]             ← 只添加一次，追加在最后
[上下文刷新提醒]       ← 只添加一次，clear_context 时跳过
```

**理由**：
- NEW TASK 是系统级指令，只需出现一次，放在最前给 agent 最强信号
- 反馈提醒是引导 agent 行为的，重复多次没有意义
- 上下文刷新提醒同理，且 clear_context 时 NEW TASK 已包含重读指令
- 每条用户反馈保持独立，agent 可以看到完整的反馈历史

### Data Flow

```
User submits (1st) → submit_feedback → backend sets event → FEEDBACK_SUBMITTED notification
                                      → frontend enters QUEUED state

User submits (2nd) → frontend adds to local queue → queue count: 1
                    → sends submit_feedback(queued=true) → backend enqueues

User submits (3rd) → frontend adds to local queue → queue count: 2
                    → sends submit_feedback(queued=true) → backend enqueues

Agent returns → new session → session_updated
              → frontend sends drain_queue with all queued items
              → backend stores in session.feedback_queue
              → wait_for_feedback returns with queued_items included
              → _assemble_feedback_items assembles all items with shared prompt attachments
              → agent receives: [NEW TASK] + [feedback1] + [feedback2] + [feedback3] + [reminder]
```

---

## Step-by-Step Tasks

### Task 1: Frontend State — Add FEEDBACK_QUEUED

**File**: `src/mcp_feedback_enhanced/web/static/js/modules/utils.js`

Add new constant after FEEDBACK_SUBMITTED:
```js
FEEDBACK_QUEUED: 'feedback_queued',
```

### Task 2: Backend — Queue Infrastructure

**File**: `src/mcp_feedback_enhanced/web/models/feedback_session.py`

2a. Add to `__init__` (after `self.feedback_completed`):
```python
self.feedback_queue: list[dict[str, Any]] = []
```

2b. Add `enqueue_feedback` method:
```python
async def enqueue_feedback(self, feedback, images, settings, clear_context=False):
    """將回饋加入隊列（agent 返回後批量處理）"""
    self.feedback_queue.append({
        "feedback": feedback,
        "images": self._process_images(images),
        "settings": settings or {},
        "clear_context": clear_context,
    })
    self.last_activity = time.time()
    if self.websocket:
        try:
            await self.websocket.send_json({
                "type": "notification",
                "code": "FEEDBACK_QUEUED",
                "severity": "info",
                "queue_count": len(self.feedback_queue),
            })
        except Exception:
            pass
```

2c. Add `drain_feedback_queue` method:
```python
def drain_feedback_queue(self) -> list[dict[str, Any]]:
    """取出並清空隊列中的所有回饋項目"""
    items = list(self.feedback_queue)
    self.feedback_queue.clear()
    return items
```

### Task 3: Backend — Handle Queued Submissions & Drain

**File**: `src/mcp_feedback_enhanced/web/routes/main_routes.py`

3a. Modify `submit_feedback` handler (~line 623):
```python
elif message_type == "submit_feedback":
    feedback = data.get("feedback", "")
    images = data.get("images", [])
    settings = data.get("settings", {})
    clear_context = data.get("clear_context", False)
    queued = data.get("queued", False)

    if queued and session.status == SessionStatus.FEEDBACK_SUBMITTED:
        await session.enqueue_feedback(feedback, images, settings, clear_context)
    else:
        await session.submit_feedback(feedback, images, settings, clear_context=clear_context)
```

3b. Add `drain_queue` handler:
```python
elif message_type == "drain_queue":
    items = data.get("items", [])
    for item in items:
        await session.enqueue_feedback(
            item.get("feedback", ""),
            item.get("images", []),
            item.get("settings", {}),
            item.get("clear_context", False),
        )
    await websocket.send_json({
        "type": "queue_drained",
        "count": len(items),
    })
```

### Task 4: Backend — wait_for_feedback Returns Queued Items

**File**: `src/mcp_feedback_enhanced/web/models/feedback_session.py`

Modify `wait_for_feedback` return dict (~line 498):
```python
return {
    "logs": "\n".join(self.command_logs),
    "interactive_feedback": self.feedback_result or "",
    "images": self.images,
    "settings": self.settings,
    "clear_context": getattr(self, "clear_context", False),
    "queued_items": self.drain_feedback_queue(),  # 新增
}
```

### Task 5: Backend — Assemble Queued Items with Prompt Attachments

**File**: `src/mcp_feedback_enhanced/server.py`

Modify `_assemble_feedback_items` to handle `queued_items`:
```python
def _assemble_feedback_items(result: dict) -> list[TextContent]:
    feedback_items: list[TextContent] = []
    queued_items = result.get("queued_items", [])

    if queued_items:
        # Multi-item mode: assemble each queued item independently
        # First item uses the main result's feedback
        first_item = {
            "interactive_feedback": result.get("interactive_feedback", ""),
            "command_logs": result.get("command_logs", ""),
            "images": result.get("images", []),
        }
        all_items = [first_item] + queued_items

        for item in all_items:
            item_feedback = create_feedback_text(item)
            feedback_items.append(TextContent(type="text", text=item_feedback))
            # Add images for this item
            if item.get("images"):
                mcp_images = process_images(item["images"])
                feedback_items.extend(mcp_images)

        # Apply global prompt attachments once
        # NEW TASK: if any item has clear_context
        any_clear = result.get("clear_context") or any(
            qi.get("clear_context") for qi in queued_items
        )
        if any_clear:
            clear_instruction = _get_new_task_instruction(result)
            feedback_items.insert(0, TextContent(type="text", text=clear_instruction))

        # Feedback reminder: once at the end
        reminder_text = _get_feedback_reminder(result)
        if reminder_text:
            feedback_items.append(TextContent(type="text", text=reminder_text))

        # Context refresh: once at the end, skip if clear_context
        if not any_clear:
            context_refresh_text = _get_context_refresh_reminder(result)
            if context_refresh_text:
                feedback_items.append(TextContent(type="text", text=context_refresh_text))
    else:
        # Single-item mode: original behavior (unchanged)
        if result.get("interactive_feedback") or result.get("command_logs") or result.get("images"):
            feedback_text = create_feedback_text(result)
            feedback_items.append(TextContent(type="text", text=feedback_text))

        if result.get("images"):
            mcp_images = process_images(result["images"])
            feedback_items.extend(mcp_images)

        if not feedback_items:
            feedback_items.append(TextContent(type="text", text="用戶未提供任何回饋內容。"))

        if result.get("clear_context"):
            clear_instruction = _get_new_task_instruction(result)
            feedback_items.insert(0, TextContent(type="text", text=clear_instruction))

        reminder_text = _get_feedback_reminder(result)
        if reminder_text:
            feedback_items.append(TextContent(type="text", text=reminder_text))

        if not result.get("clear_context"):
            context_refresh_text = _get_context_refresh_reminder(result)
            if context_refresh_text:
                feedback_items.append(TextContent(type="text", text=context_refresh_text))

    return feedback_items
```

### Task 6: Frontend — Queue Management

**File**: `src/mcp_feedback_enhanced/web/static/js/app.js`

6a. Add to constructor (~line 54):
```js
this.feedbackQueue = [];
```

6b. Modify `submitFeedback` (line 1118) — check state before deciding flow:
```js
FeedbackApp.prototype.submitFeedback = function(options) {
    options = options || {};
    if (!this.canSubmitFeedback()) { this.handleSubmitError(); return; }
    const feedbackData = this.collectFeedbackData(options);
    if (!feedbackData) return;

    const currentState = this.uiManager ? this.uiManager.getFeedbackState() : null;
    if (currentState === 'feedback_queued' ||
        currentState === Utils.CONSTANTS.FEEDBACK_SUBMITTED) {
        // Queue mode — add to local queue
        this.feedbackQueue.push(feedbackData);
        this.recordUserMessage(feedbackData);
        this.updateQueueIndicator();
        this.webSocketManager.send({
            type: 'submit_feedback',
            feedback: feedbackData.feedback,
            images: feedbackData.images,
            settings: feedbackData.settings,
            clear_context: feedbackData.clear_context || false,
            queued: true
        });
        if (this.uiManager) this.uiManager.resetFeedbackForm(false);
        if (this.imageHandler) this.imageHandler.clearImages();
        const msg = window.i18nManager ? window.i18nManager.t('feedback.queuedSuccess') : '回饋已加入隊列';
        Utils.showMessage(msg, Utils.CONSTANTS.MESSAGE_INFO);
        return;
    }

    this.submitFeedbackInternal(feedbackData);
};
```

6c. Modify `handleFeedbackReceived` (line 769) — transition to QUEUED:
```js
FeedbackApp.prototype.handleFeedbackReceived = function(data) {
    const currentState = this.uiManager ? this.uiManager.getFeedbackState() : null;

    // If already submitted/queued, just update queue state
    if (currentState === Utils.CONSTANTS.FEEDBACK_SUBMITTED || currentState === 'feedback_queued') {
        this.uiManager.setFeedbackState('feedback_queued');
        this.updateQueueIndicator();
        return;
    }

    // First submission — show success then enter QUEUED
    this.uiManager.setFeedbackState(Utils.CONSTANTS.FEEDBACK_SUBMITTED);
    this.uiManager.setLastSubmissionTime(Date.now());
    if (this.autoSubmitManager && this.autoSubmitManager.isEnabled) {
        this.autoSubmitManager.stop();
    }
    if (data.messageCode && window.i18nManager) {
        const message = window.i18nManager.t(data.messageCode, data.params);
        Utils.showMessage(message, Utils.CONSTANTS.MESSAGE_SUCCESS);
    }
    const submittedMessage = window.i18nManager ? window.i18nManager.t('feedback.submittedWaiting') : '已送出反饋';
    this.updateSummaryStatus(submittedMessage);
    this.executeAutoCommandOnFeedbackSubmit();
    this.refreshSessionList();

    // Enter QUEUED state to allow more submissions
    var self = this;
    setTimeout(function() {
        self.uiManager.setFeedbackState('feedback_queued');
        self.updateQueueIndicator();
    }, 300);
};
```

6d. Modify `session_updated` handler (~line 860) — drain queue to new session:
```js
// Before setting WAITING state in handleSessionUpdated:
if (this.feedbackQueue.length > 0) {
    var queuedItems = this.feedbackQueue.splice(0);
    this.webSocketManager.send({ type: 'drain_queue', items: queuedItems });
}
this.feedbackQueue = [];
this.uiManager.setFeedbackState(Utils.CONSTANTS.FEEDBACK_WAITING, self.currentSessionId);
```

6e. Add `updateQueueIndicator`:
```js
FeedbackApp.prototype.updateQueueIndicator = function() {
    var count = this.feedbackQueue.length;
    var indicator = Utils.safeQuerySelector('#queueIndicator');
    var countEl = Utils.safeQuerySelector('#queueCount');
    if (indicator) indicator.style.display = count > 0 ? 'flex' : 'none';
    if (countEl) countEl.textContent = count;
};
```

6f. Reset queue in `clearFeedback`:
```js
this.feedbackQueue = [];
this.updateQueueIndicator();
```

### Task 7: UI — Queue Indicator & State

**File**: `src/mcp_feedback_enhanced/web/templates/feedback.html`

Add near submit button area:
```html
<div id="queueIndicator" class="queue-indicator" style="display: none;">
    <span class="queue-badge">
        <span id="queueCount">0</span>
        <span data-i18n="feedback.queuedItems"> items queued</span>
    </span>
</div>
```

**File**: `src/mcp_feedback_enhanced/web/static/js/modules/ui-manager.js`

7a. `updateSubmitButton` — add QUEUED case:
```js
case 'feedback_queued':
    button.textContent = window.i18nManager ? window.i18nManager.t('buttons.submit') : '提交回饋';
    button.className = 'btn btn-primary';
    button.disabled = false;
    break;
```

7b. `updateFeedbackInputs` — allow input in QUEUED:
```js
const canInput = this.feedbackState === Utils.CONSTANTS.FEEDBACK_WAITING ||
                 this.feedbackState === 'feedback_queued';
```

7c. `updateImageUploadAreas` — allow upload in QUEUED:
```js
const canUpload = this.feedbackState === Utils.CONSTANTS.FEEDBACK_WAITING ||
                  this.feedbackState === 'feedback_queued';
```

### Task 8: i18n Strings

**Files**: All locale JSON files (`en.json`, `zh-TW.json`, `zh-CN.json`, `ja.json`)

```json
"feedback.queuedItems": "items queued",
"feedback.queuedSuccess": "Feedback queued, will be sent when agent returns"
```

### Task 9: Unit Tests

**File**: `tests/unit/test_feedback_queue.py`

**Backend queue tests:**
1. `enqueue_feedback` adds item to queue
2. `drain_feedback_queue` returns all items and clears
3. `drain_feedback_queue` empty returns `[]`
4. Multiple enqueue + drain preserves order
5. Queue item structure has required fields

**Assembly tests with queued items:**
6. Single item (no queued_items) — original behavior unchanged
7. Multiple items — each assembled independently
8. NEW TASK appears once when any item has clear_context
9. Feedback reminder appears once at the end
10. Context refresh appears once, skipped when any item has clear_context
11. Images from each item are included in order

---

## Image Support (已验证，无需修改)

当前代码已完整支持多图（最多 10 张），无需改动：
- HTML `<input type="file" multiple accept="image/*">` — 支持多选
- `FileUploadManager.maxFiles = 10` — 默认上限 10 张
- `ImageHandler.getImages()` → `FileUploadManager.getFiles()` — 返回全部文件
- WebSocket 发送 `images: [...]` 数组
- 后端 `_process_images` 遍历处理所有图片
- `process_images` 为每张图片创建 `MCPImage`
- `_assemble_feedback_items` 使用 `feedback_items.extend(mcp_images)` 添加所有

队列中每个项目的图片也会被独立处理，互不影响。

## NOT Building
- Backend cross-session queue persistence
- Queue size limits
- Queue item deletion/cancellation from UI
- Queue reordering
- Image support changes (already working)

---

## Validation Commands

```bash
python -m pytest tests/unit/test_feedback_queue.py -v
python -m pytest tests/unit/test_feedback_instruction.py -v
python -m pytest tests/ -v
```

## Acceptance Criteria
- [ ] After first submit, textarea and button remain enabled
- [ ] Queue indicator shows count of queued items
- [ ] Queued items are sent to agent when it returns
- [ ] NEW TASK instruction appears once (not per-item)
- [ ] Feedback reminder appears once at the end (not per-item)
- [ ] Context refresh reminder appears once, skipped when clear_context
- [ ] No regressions in existing feedback flow
- [ ] All existing tests pass
- [ ] New unit tests pass
