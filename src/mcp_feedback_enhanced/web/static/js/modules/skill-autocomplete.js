/**
 * MCP Feedback Enhanced - Skill Autocomplete
 * 反饋輸入框的 / 技能自動補全（fzf 風格模糊搜尋），
 * 並將 agent 摘要中的 /skillname 渲染為可點擊項。
 *
 * 設計要點：
 * - 觸發：輸入框中 caret 前有 '/' 且 '/' 前為開頭或空白時展開下拉。
 * - 模糊：子序列評分（fzf 風格），使用者不需記住精確技能名。
 * - 保證觸發（G3）：選中的技能隨反饋回傳 path+content，由 agent 直接執行，
 *   不依賴 Cursor 的 / 選擇器或任何 UI token。
 */
window.MCPFeedback = window.MCPFeedback || {};

((MCPFeedback) => {
    

    function SkillAutocomplete() {
        this.skills = [];
        this.skillMap = {};      // name(lower) -> skill
        this.dropdown = null;
        this.activeTextarea = null;
        this.queryStart = -1;    // '/' 在 textarea value 中的索引
        this.filtered = [];
        this.selectedIndex = 0;
        this._observer = null;
    }

    // ---------- 模糊評分（fzf 風格子序列匹配） ----------
    SkillAutocomplete.prototype._score = (name, query) => {
        name = String(name).toLowerCase();
        query = String(query).toLowerCase();
        if (!query) return 1;
        if (name === query) return 1000;
        if (name.indexOf(query) === 0) return 500 + (100 - name.length);
        var qi = 0, score = 0, prev = -2;
        for (var i = 0; i < name.length && qi < query.length; i++) {
            if (name[i] === query[qi]) {
                score += (prev === i - 1) ? 3 : 1; // 連續字元加分
                prev = i;
                qi++;
            }
        }
        if (qi === query.length) return score + (100 - name.length) * 0.1;
        return -1;
    };

    SkillAutocomplete.prototype._filter = function (query) {
        var scored = [];
        this.skills.forEach((s) => {
            var sc = this._score(s.name, query);
            if (sc >= 0) scored.push({ skill: s, score: sc });
        });
        scored.sort((a, b) => b.score - a.score);
        return scored.map((x) => x.skill);
    };

    // ---------- 初始化 ----------
    SkillAutocomplete.prototype.init = function (skills) {
        this.skills = skills || [];
        this.skillMap = {};
        this.skills.forEach((s) => {
            this.skillMap[String(s.name).toLowerCase()] = s;
        });

        this._setupDelegation();
        this._observeTextarea();
        this._onTextareaFound(document.querySelector('#combinedFeedbackText'));

        // 監聽摘要渲染，將 /skillname 變為可點擊
        this._observeSummaries();
        this.makeSummarySkillsClickable();
    };

    // 事件委托：監聽掛在 document 上，textarea 被 DOM 重建後無需重綁。
    SkillAutocomplete.prototype._setupDelegation = function () {
        if (this._delegated) return;
        this._delegated = true;
        document.addEventListener('input', (e) => {
            if (e.target && e.target.id === 'combinedFeedbackText') {
                this._onInput(e);
                this._updateHighlight(e.target);
                this._saveDraft(e.target);
            }
        });
        document.addEventListener('keydown', (e) => {
            if (e.target && e.target.id === 'combinedFeedbackText') {
                this._onKeydown(e);
            }
        });
        // scroll 不冒泡，用捕獲階段同步高亮層滾動
        document.addEventListener(
            'scroll',
            (e) => {
                if (e.target === document.querySelector('#combinedFeedbackText')) {
                    this._syncScroll(e.target);
                }
            },
            true
        );
    };

    // textarea 出現/重建時：建立高亮層、恢復草稿、刷新渲染
    SkillAutocomplete.prototype._observeTextarea = function () {
        if (!('MutationObserver' in window)) return;
        var observer = new MutationObserver(() => {
            this._onTextareaFound(document.querySelector('#combinedFeedbackText'));
        });
        observer.observe(document.body, { childList: true, subtree: true });
    };

    SkillAutocomplete.prototype._onTextareaFound = function (ta) {
        if (!ta || ta._skillAutocompleteReady) return;
        ta._skillAutocompleteReady = true;
        this._ensureBackdrop(ta);
        this._restoreDraft(ta);
        this._updateHighlight(ta);
    };

    // ---------- 輸入處理 ----------
    SkillAutocomplete.prototype._onInput = function (e) {
        var ta = e.target;
        var pos = ta.selectionStart;
        var val = ta.value;
        // 找到 caret 前最近的 '/'（且 '/' 與 caret 間無空白）
        var start = -1;
        for (var i = pos - 1; i >= 0; i--) {
            var ch = val[i];
            if (ch === '/') { start = i; break; }
            if (/\s/.test(ch)) break;
        }
        if (start === -1) { this._hide(); return; }
        // 避免路徑（如 /Users/...）誤觸發：'/' 前需為開頭或空白
        var before = start === 0 ? '' : val[start - 1];
        if (before && !/\s/.test(before)) { this._hide(); return; }
        var query = val.slice(start + 1, pos);
        if (/\s/.test(query) || query.indexOf('/') !== -1) { this._hide(); return; }

        this.activeTextarea = ta;
        this.queryStart = start;
        this.filtered = this._filter(query);
        if (this.filtered.length === 0) { this._hide(); return; }
        this.selectedIndex = 0;
        this._show(ta);
    };

    SkillAutocomplete.prototype._onKeydown = function (e) {
        if (!this.dropdown || this.dropdown.style.display === 'none') return;
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            this.selectedIndex = (this.selectedIndex + 1) % this.filtered.length;
            this._render();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            this.selectedIndex = (this.selectedIndex - 1 + this.filtered.length) % this.filtered.length;
            this._render();
        } else if (e.key === 'Enter' || e.key === 'Tab') {
            e.preventDefault();
            this._select(this.filtered[this.selectedIndex]);
        } else if (e.key === 'Escape') {
            this._hide();
        }
    };

    // ---------- 下拉渲染 ----------
    SkillAutocomplete.prototype._show = function (ta) {
        if (!this.dropdown) {
            this.dropdown = document.createElement('div');
            this.dropdown.id = 'skillAutocompleteDropdown';
            this.dropdown.style.cssText = [
                'position:fixed', 'z-index:99999', 'max-height:240px', 'overflow-y:auto',
                'background:#1e1e2e', 'color:#e0e0e0', 'border:1px solid #3a3a4a',
                'border-radius:6px', 'box-shadow:0 4px 16px rgba(0,0,0,0.4)',
                'font-size:13px', 'font-family:sans-serif', 'padding:4px 0'
            ].join(';');
            document.body.appendChild(this.dropdown);
        }
        var rect = ta.getBoundingClientRect();
        this.dropdown.style.left = rect.left + 'px';
        this.dropdown.style.width = rect.width + 'px';
        this.dropdown.style.top = (rect.bottom + 4) + 'px';
        this.dropdown.style.display = 'block';
        this._render();
    };

    SkillAutocomplete.prototype._render = function () {
        this.dropdown.innerHTML = '';
        this.filtered.forEach((skill, idx) => {
            var item = document.createElement('div');
            item.style.cssText = 'padding:6px 12px; cursor:pointer; white-space:nowrap;' +
                'overflow:hidden; text-overflow:ellipsis;' +
                (idx === this.selectedIndex ? ' background:#313147;' : '');
            var name = document.createElement('span');
            name.textContent = '/' + skill.name;
            name.style.color = '#4a9eff';
            name.style.fontWeight = 'bold';
            item.appendChild(name);
            if (skill.description) {
                var desc = document.createElement('span');
                desc.textContent = '  ' + skill.description;
                desc.style.color = '#9aa0b0';
                item.appendChild(desc);
            }
            if (skill.argument_hint) {
                var args = document.createElement('div');
                args.textContent = '⚙ ' + skill.argument_hint;
                args.style.cssText = 'color:#c0a060; font-size:11px; padding-left:2px;';
                item.appendChild(args);
            }
            item.addEventListener('mousedown', (ev) => {
                ev.preventDefault(); // 避免 textarea 失焦
                this._select(skill);
            });
            item.addEventListener('mouseenter', () => {
                this.selectedIndex = idx;
                this._render();
            });
            this.dropdown.appendChild(item);
        });
    };

    SkillAutocomplete.prototype._hide = function () {
        if (this.dropdown) this.dropdown.style.display = 'none';
        this.activeTextarea = null;
        this.queryStart = -1;
    };

    SkillAutocomplete.prototype._select = function (skill) {
        var ta = this.activeTextarea;
        if (!ta || !skill) return;
        var val = ta.value;
        var pos = ta.selectionStart;
        var before = val.slice(0, this.queryStart);
        var after = val.slice(pos);
        var insert = '/' + skill.name + ' ';
        ta.value = before + insert + after;
        var newPos = (before + insert).length;
        ta.setSelectionRange(newPos, newPos);
        ta.focus();
        this._hide();
        this._updateHighlight(ta);
        this._saveDraft(ta);
    };

    // ---------- 高亮鏡像層 ----------
    // textarea 原生不支援局部著色，在底層疊一個同步排版/滾動的渲染層，
    // 將 /skill 片段以彩色底色標出；textarea 背景設為透明使其透出。
    var HIGHLIGHT_PALETTE = [
        'rgba(74, 158, 255, 0.28)',
        'rgba(126, 211, 127, 0.30)',
        'rgba(255, 193, 94, 0.32)',
        'rgba(224, 110, 180, 0.30)',
        'rgba(160, 120, 255, 0.30)',
    ];

    SkillAutocomplete.prototype._colorFor = function (name) {
        var hash = 0;
        for (var i = 0; i < name.length; i++) {
            hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
        }
        return HIGHLIGHT_PALETTE[hash % HIGHLIGHT_PALETTE.length];
    };

    SkillAutocomplete.prototype._ensureBackdrop = function (ta) {
        if (ta._skillBackdrop) return;
        var wrap = document.createElement('div');
        wrap.style.cssText = 'position:relative;';
        ta.parentNode.insertBefore(wrap, ta);
        wrap.appendChild(ta);

        var bd = document.createElement('div');
        bd.setAttribute('aria-hidden', 'true');
        bd.style.cssText = [
            'position:absolute', 'top:0', 'left:0', 'width:100%', 'height:100%',
            'pointer-events:none', 'overflow:hidden', 'white-space:pre-wrap',
            'word-wrap:break-word', 'color:transparent', 'box-sizing:border-box',
        ].join(';');
        // 同步字體排版，確保高亮位置與文字重合
        var ts = window.getComputedStyle(ta);
        ['fontSize', 'fontFamily', 'fontWeight', 'lineHeight', 'padding',
         'borderWidth', 'borderStyle', 'letterSpacing'].forEach((prop) => {
            bd.style[prop] = ts[prop];
        });
        // 原背景色轉移到鏡像層，textarea 設為透明讓高亮透出，視覺不變
        bd.style.backgroundColor = ts.backgroundColor;
        wrap.insertBefore(bd, ta);

        ta.style.backgroundColor = 'transparent';
        ta.style.position = 'relative';
        ta.style.zIndex = '2';
        ta._skillBackdrop = bd;
    };

    SkillAutocomplete.prototype._updateHighlight = function (ta) {
        if (!ta) return;
        if (!ta._skillBackdrop) this._ensureBackdrop(ta);
        var bd = ta._skillBackdrop;
        if (!bd) return;
        var text = ta.value;
        if (!text) { bd.textContent = ''; return; }
        var frag = document.createDocumentFragment();
        var re = /\/([a-z0-9][a-z0-9-]*)/gi;
        var m, lastIdx = 0;
        while ((m = re.exec(text)) !== null) {
            var key = m[1].toLowerCase();
            if (!this.skillMap[key]) continue;
            var before = m.index === 0 ? '' : text[m.index - 1];
            if (before && !/\s|\(|（/.test(before)) continue;
            if (m.index > lastIdx) {
                frag.appendChild(document.createTextNode(text.slice(lastIdx, m.index)));
            }
            var span = document.createElement('span');
            span.textContent = m[0];
            span.style.backgroundColor = this._colorFor(key);
            span.style.borderRadius = '3px';
            frag.appendChild(span);
            lastIdx = m.index + m[0].length;
        }
        if (lastIdx < text.length) {
            frag.appendChild(document.createTextNode(text.slice(lastIdx)));
        }
        bd.textContent = '';
        bd.appendChild(frag);
        this._syncScroll(ta);
    };

    SkillAutocomplete.prototype._syncScroll = function (ta) {
        if (ta && ta._skillBackdrop) {
            ta._skillBackdrop.scrollTop = ta.scrollTop;
        }
    };

    // ---------- 草稿保護 ----------
    // 反饋文本實時存 localStorage，斷連/刷新後自動恢復，避免未提交內容丟失。
    SkillAutocomplete.prototype._draftKey = function () {
        var sid = 'unknown';
        try {
            sid = new URLSearchParams(window.location.search).get('session') || 'unknown';
        } catch { /* 保持預設 */ }
        return 'mcpFeedbackDraft:' + sid;
    };

    SkillAutocomplete.prototype._saveDraft = function (ta) {
        try {
            localStorage.setItem(this._draftKey(), ta.value);
        } catch { /* 隱私模式等情境下靜默失敗 */ }
    };

    SkillAutocomplete.prototype._restoreDraft = function (ta) {
        var saved = null;
        try {
            saved = localStorage.getItem(this._draftKey());
        } catch { return; }
        if (saved && !ta.value) {
            ta.value = saved;
        }
    };

    SkillAutocomplete.prototype._clearDraft = function () {
        try {
            localStorage.removeItem(this._draftKey());
        } catch { /* 忽略 */ }
    };

    // ---------- 摘要中的 /skillname 可點擊 ----------
    SkillAutocomplete.prototype.makeSummarySkillsClickable = function () {
        ['#summaryContent', '#combinedSummaryContent', '.ai-summary-content'].forEach((sel) => {
            var nodes = document.querySelectorAll(sel);
            for (var i = 0; i < nodes.length; i++) {
                this._linkifyContainer(nodes[i]);
            }
        });
    };

    SkillAutocomplete.prototype._linkifyContainer = function (container) {
        if (!container) return;
        var walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, null);
        var textNodes = [];
        var n;
        while ((n = walker.nextNode())) {
            if (n.parentElement && n.parentElement.closest && n.parentElement.closest('.skill-ref')) continue;
            textNodes.push(n);
        }
        textNodes.forEach((textNode) => {
            var text = textNode.nodeValue;
            if (!text) return;
            var re = /\/([a-z0-9][a-z0-9-]*)/gi;
            var m, lastIdx = 0, matched = false, frag = null;
            while ((m = re.exec(text)) !== null) {
                var name = m[1];
                if (!this.skillMap[name.toLowerCase()]) continue;
                var before = m.index === 0 ? '' : text[m.index - 1];
                if (before && !/\s|\(|（/.test(before)) continue; // 跳過路徑/連結
                if (!frag) frag = document.createDocumentFragment();
                matched = true;
                if (m.index > lastIdx) frag.appendChild(document.createTextNode(text.slice(lastIdx, m.index)));
                var span = document.createElement('span');
                span.className = 'skill-ref';
                span.setAttribute('data-skill', name);
                span.textContent = '/' + name;
                span.style.cssText = 'cursor:pointer; color:#4a9eff; text-decoration:underline;';
                span.addEventListener('click', ((nm) => () => { this._insertSkillIntoActiveTextarea(nm); })(name));
                frag.appendChild(span);
                lastIdx = m.index + m[0].length;
            }
            if (matched && frag) {
                if (lastIdx < text.length) frag.appendChild(document.createTextNode(text.slice(lastIdx)));
                textNode.parentNode.replaceChild(frag, textNode);
            }
        });
    };

    SkillAutocomplete.prototype._insertSkillIntoActiveTextarea = (name) => {
        var ta = document.querySelector('#combinedFeedbackText');
        if (!ta) return;
        ta.focus();
        var pos = ta.selectionStart || ta.value.length;
        var insert = '/' + name + ' ';
        ta.value = ta.value.slice(0, pos) + insert + ta.value.slice(pos);
        var newPos = pos + insert.length;
        ta.setSelectionRange(newPos, newPos);
    };

    SkillAutocomplete.prototype._observeSummaries = function () {
        if (!('MutationObserver' in window)) return;
        var targets = document.querySelectorAll('#summaryContent, #combinedSummaryContent, .ai-summary-content');
        if (!targets.length) return;
        this._observer = new MutationObserver(() => {
            this.makeSummarySkillsClickable();
        });
        for (var i = 0; i < targets.length; i++) {
            this._observer.observe(targets[i], { childList: true, subtree: true });
        }
    };

    SkillAutocomplete.prototype.parseSkills = function (text) {
        const refs = [];
        if (!text || !this.skillMap) return refs;
        const re = /\/([a-z0-9][a-z0-9-]*)/g;
        let m;
        while ((m = re.exec(text)) !== null) {
            const name = m[1];
            const key = name.toLowerCase();
            if (!this.skillMap[key]) continue;
            const before = m.index === 0 ? '' : text[m.index - 1];
            if (before && !/\s|\(|（/.test(before)) continue;
            if (refs.some((r) => r.name.toLowerCase() === key)) continue;
            let lineEnd = text.indexOf('\n', m.index);
            if (lineEnd === -1) lineEnd = text.length;
            const args = text.slice(m.index + m[0].length, lineEnd).trim();
            refs.push({ name: name, path: this.skillMap[key].path, args: args });
        }
        return refs;
    };

    MCPFeedback.SkillAutocomplete = SkillAutocomplete;

    // 自初始化：不依賴 app.js，模塊自行載入技能列表並接管 /skillname 解析
    const bootSkillAutocomplete = () => {
        const ac = new SkillAutocomplete();
        const injectSkills = () => {
            if (!window.FeedbackApp || !FeedbackApp.prototype.collectFeedbackData) return;
            const orig = FeedbackApp.prototype.collectFeedbackData;
            FeedbackApp.prototype.collectFeedbackData = function (options) {
                const data = orig.call(this, options);
                if (!data) return data;
                const ta = document.querySelector('#combinedFeedbackText');
                const text = ta ? ta.value : '';
                data.skills = ac.parseSkills(text);
                // 反饋已採集，草稿使命完成，清除以免下次會話誤恢復舊內容
                ac._clearDraft();
                return data;
            };
        };
        fetch('/api/skills')
            .then((r) => r.json())
            .then((skills) => {
                ac.init(skills || []);
                injectSkills();
            })
            .catch((e) => console.warn('技能自動補全初始化失敗:', e));
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bootSkillAutocomplete);
    } else {
        bootSkillAutocomplete();
    }
})(window.MCPFeedback);
