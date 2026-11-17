/**
 * MCP Feedback Enhanced - 會話切換器模組
 * =====================================
 *
 * 在頂部欄提供多會話切換入口：存在多個等待回饋的會話時顯示下拉選單，
 * 選中後跳轉到對應會話的回饋頁面（/?session=<id>）。
 *
 * 資料來源：GET /api/all-sessions（與會話選擇頁共用）
 */

(function() {
    'use strict';

    window.MCPFeedback = window.MCPFeedback || {};

    /**
     * 會話切換器建構函數
     */
    function SessionSwitcher(options) {
        options = options || {};

        this.container = options.container || document.getElementById('sessionSwitcherContainer');
        this.select = options.select || document.getElementById('sessionSwitcherSelect');
        this.refreshIntervalMs = options.refreshIntervalMs || 5000;
        this.logger = (window.MCPFeedback && window.MCPFeedback.logger) || console;

        this.timer = null;
        this.sessions = [];

        if (!this.container || !this.select) {
            this.logger.warn('SessionSwitcher: 找不到容器元素，跳過初始化');
            return;
        }

        this.bindEvents();
        this.refresh();
        this.startAutoRefresh();

        this.logger.info('🔀 SessionSwitcher 初始化完成');
    }

    /** 取得 URL 中的當前會話 ID */
    SessionSwitcher.prototype.getCurrentSessionId = function() {
        return new URLSearchParams(window.location.search).get('session');
    };

    /** 過濾仍在等待回饋的會話（與會話選擇頁一致） */
    SessionSwitcher.prototype.filterActiveSessions = function(sessions) {
        return (sessions || []).filter(function(s) {
            return !s.feedback_completed &&
                   s.status !== 'completed' &&
                   s.status !== 'timeout' &&
                   s.status !== 'expired' &&
                   s.status !== 'error';
        });
    };

    /** 從專案路徑提取專案名 */
    SessionSwitcher.prototype.getProjectName = function(projectDirectory) {
        return (projectDirectory || '未知專案').split(/[/\\]/).filter(Boolean).pop() || '未知專案';
    };

    /** 拉取會話列表並更新下拉選單 */
    SessionSwitcher.prototype.refresh = function() {
        var self = this;
        return fetch('/api/all-sessions')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                self.sessions = self.filterActiveSessions(data.sessions || []);
                self.render();
                return self.sessions;
            })
            .catch(function(err) {
                self.logger.warn('SessionSwitcher: 取得會話列表失敗', err);
                return [];
            });
    };

    /** 渲染下拉選單：多會話時顯示，單會話時隱藏 */
    SessionSwitcher.prototype.render = function() {
        var self = this;
        var currentId = this.getCurrentSessionId();
        var others = this.sessions.filter(function(s) { return s.session_id !== currentId; });

        // 僅在存在其他可切換會話時顯示入口
        if (others.length === 0) {
            this.container.style.display = 'none';
            return;
        }

        this.container.style.display = '';

        // 保留當前選中項之外的選項，重建清單
        this.select.innerHTML = '';

        var placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = '🔀 ' + this.i18nText('sessionManagement.switchSession', '切换会话');
        placeholder.disabled = true;
        placeholder.selected = true;
        this.select.appendChild(placeholder);

        others.forEach(function(s) {
            var option = document.createElement('option');
            option.value = s.session_id;
            option.textContent = self.getProjectName(s.project_directory) +
                ' · ' + s.session_id.slice(0, 6);
            self.select.appendChild(option);
        });
    };

    /** i18n 文案讀取（依賴全域 i18nManager，失敗時回退默認值） */
    SessionSwitcher.prototype.i18nText = function(key, fallback) {
        if (window.i18nManager && typeof window.i18nManager.t === 'function') {
            var text = window.i18nManager.t(key);
            if (text && text !== key) return text;
        }
        return fallback;
    };

    /** 綁定選擇事件與頁面可見性刷新 */
    SessionSwitcher.prototype.bindEvents = function() {
        var self = this;

        this.select.addEventListener('change', function() {
            var target = self.select.value;
            if (!target) return;
            window.location.href = '/?session=' + encodeURIComponent(target);
        });

        // 頁面重新可見時立即刷新，減少切換延遲
        document.addEventListener('visibilitychange', function() {
            if (!document.hidden) self.refresh();
        });
    };

    /** 週期性刷新會話列表 */
    SessionSwitcher.prototype.startAutoRefresh = function() {
        var self = this;
        this.timer = setInterval(function() { self.refresh(); }, this.refreshIntervalMs);
    };

    /** 停止自動刷新（供清理使用） */
    SessionSwitcher.prototype.stop = function() {
        if (this.timer) {
            clearInterval(this.timer);
            this.timer = null;
        }
    };

    window.MCPFeedback.SessionSwitcher = SessionSwitcher;
})();
