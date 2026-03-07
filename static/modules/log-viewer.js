/**
 * Backend Log Viewer Module
 * Provides log inspection directly in static UI.
 */
export class LogViewer {
    constructor(app) {
        this.app = app;
        this.autoRefreshEnabled = true;
        this.autoRefreshMs = 10000;
        this.autoRefreshTimer = null;
        this.isLoading = false;

        this.card = null;
        this.container = null;
        this.levelFilter = null;
        this.limitFilter = null;
        this.searchInput = null;
        this.refreshButton = null;
        this.autoRefreshButton = null;
        this.searchButton = null;
        this.downloadButton = null;
        this.logFilePath = null;
        this.lastUpdated = null;
        this.statusBadge = null;
    }

    initialize() {
        this.card = document.getElementById('backendLogViewerCard');
        this.container = document.getElementById('backendLogContainer');
        this.levelFilter = document.getElementById('backendLogLevelFilter');
        this.limitFilter = document.getElementById('backendLogLimit');
        this.searchInput = document.getElementById('backendLogSearch');
        this.refreshButton = document.getElementById('refreshBackendLogsBtn');
        this.autoRefreshButton = document.getElementById('toggleBackendLogAutoRefreshBtn');
        this.searchButton = document.getElementById('searchBackendLogsBtn');
        this.downloadButton = document.getElementById('downloadBackendLogsBtn');
        this.logFilePath = document.getElementById('backendLogFilePath');
        this.lastUpdated = document.getElementById('backendLogLastUpdated');
        this.statusBadge = document.getElementById('backendLogStatusBadge');

        if (!this.card || !this.container) {
            return;
        }

        this.bindEvents();
        this.activate();
    }

    bindEvents() {
        this.refreshButton?.addEventListener('click', () => this.refreshLogs());
        this.searchButton?.addEventListener('click', () => this.refreshLogs());
        this.autoRefreshButton?.addEventListener('click', () => {
            this.setAutoRefresh(!this.autoRefreshEnabled);
        });

        this.levelFilter?.addEventListener('change', () => {
            this.updateStatusBadge();
            this.refreshLogs();
        });

        this.limitFilter?.addEventListener('change', () => this.refreshLogs());

        this.searchInput?.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                this.refreshLogs();
            }
        });

        this.downloadButton?.addEventListener('click', () => this.downloadLogs());
    }

    activate() {
        if (!this.card) return;
        this.card.style.display = 'block';
        this.updateStatusBadge();
        this.refreshLogs();
        this.startAutoRefresh();
    }

    deactivate() {
        this.stopAutoRefresh();
    }

    setAutoRefresh(enabled) {
        this.autoRefreshEnabled = Boolean(enabled);

        if (this.autoRefreshEnabled) {
            this.startAutoRefresh();
        } else {
            this.stopAutoRefresh();
        }

        this.updateAutoRefreshButton();
    }

    startAutoRefresh() {
        this.stopAutoRefresh();
        if (!this.autoRefreshEnabled) return;

        this.autoRefreshTimer = setInterval(() => {
            this.refreshLogs({ silent: true });
        }, this.autoRefreshMs);

        this.updateAutoRefreshButton();
    }

    stopAutoRefresh() {
        if (this.autoRefreshTimer) {
            clearInterval(this.autoRefreshTimer);
            this.autoRefreshTimer = null;
        }
        this.updateAutoRefreshButton();
    }

    updateAutoRefreshButton() {
        if (!this.autoRefreshButton) return;

        if (this.autoRefreshEnabled && this.autoRefreshTimer) {
            this.autoRefreshButton.innerHTML = '<i class="bi bi-pause-fill"></i>';
            this.autoRefreshButton.title = 'Pause auto-refresh';
        } else {
            this.autoRefreshButton.innerHTML = '<i class="bi bi-play-fill"></i>';
            this.autoRefreshButton.title = 'Resume auto-refresh';
        }
    }

    updateStatusBadge() {
        if (!this.statusBadge || !this.levelFilter) return;

        const selected = this.levelFilter.value;
        const labels = {
            ERROR: 'errors',
            WARNING: 'warnings',
            INFO: 'info',
            DEBUG: 'debug',
            ALL: 'all'
        };
        this.statusBadge.textContent = labels[selected] || 'errors';
    }

    buildRequestUrl() {
        const params = new URLSearchParams();
        params.set('level', this.levelFilter?.value || 'ERROR');
        params.set('limit', this.limitFilter?.value || '200');

        const search = (this.searchInput?.value || '').trim();
        if (search) {
            params.set('search', search);
        }

        return `/api/logs?${params.toString()}`;
    }

    async refreshLogs(options = {}) {
        if (this.isLoading) return;
        this.isLoading = true;

        if (!options.silent) {
            this.setLoadingState(true);
        }

        try {
            const response = await this.app.api.fetch(this.buildRequestUrl());
            const payload = await response.json();

            if (!response.ok || payload.status !== 'success') {
                throw new Error(payload.message || `Failed to fetch logs (${response.status})`);
            }

            this.renderLogs(payload.lines || []);
            this.renderMetadata(payload);
        } catch (error) {
            console.error('Failed to load backend logs:', error);
            this.renderError(error.message || 'Failed to load backend logs');
        } finally {
            this.isLoading = false;
            this.setLoadingState(false);
        }
    }

    setLoadingState(isLoading) {
        if (!this.refreshButton) return;
        this.refreshButton.disabled = isLoading;
        if (isLoading) {
            this.refreshButton.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>';
        } else {
            this.refreshButton.innerHTML = '<i class="bi bi-arrow-clockwise"></i>';
        }
    }

    renderMetadata(payload) {
        if (this.logFilePath && payload.log_file) {
            this.logFilePath.textContent = payload.log_file;
        }

        if (this.lastUpdated) {
            if (payload.last_modified) {
                const timestamp = new Date(payload.last_modified);
                this.lastUpdated.textContent = `Updated ${timestamp.toLocaleString()} - showing ${payload.line_count || 0} lines`;
            } else {
                this.lastUpdated.textContent = payload.message || 'No logs available yet';
            }
        }
    }

    renderLogs(entries) {
        if (!this.container) return;
        this.container.innerHTML = '';

        if (!entries || entries.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'backend-log-empty';
            empty.textContent = 'No log entries match your current filters.';
            this.container.appendChild(empty);
            return;
        }

        const fragment = document.createDocumentFragment();
        for (const entry of entries) {
            const level = (entry.level || 'INFO').toLowerCase();
            const line = document.createElement('div');
            line.className = `backend-log-line level-${level}`;
            line.textContent = entry.text || '';
            fragment.appendChild(line);
        }

        this.container.appendChild(fragment);
        this.container.scrollTop = this.container.scrollHeight;
    }

    renderError(message) {
        if (!this.container) return;
        this.container.innerHTML = '';

        const errorBlock = document.createElement('div');
        errorBlock.className = 'backend-log-empty backend-log-error';
        errorBlock.textContent = message;
        this.container.appendChild(errorBlock);
    }

    async downloadLogs() {
        try {
            const response = await this.app.api.fetch('/api/logs/download');
            if (!response.ok) {
                throw new Error(`Download failed (${response.status})`);
            }

            const blob = await response.blob();
            const objectUrl = window.URL.createObjectURL(blob);
            const downloadAnchor = document.createElement('a');

            downloadAnchor.href = objectUrl;
            downloadAnchor.download = 'dragoncp_backend.log';
            document.body.appendChild(downloadAnchor);
            downloadAnchor.click();
            downloadAnchor.remove();

            window.URL.revokeObjectURL(objectUrl);
        } catch (error) {
            console.error('Failed to download backend logs:', error);
            if (this.app?.ui?.showAlert) {
                this.app.ui.showAlert('Failed to download backend logs', 'danger');
            }
        }
    }
}
