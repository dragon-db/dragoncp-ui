/**
 * Transfer Manager Module
 * Handles transfer management, progress tracking, logging, and transfer operations
 */
export class TransferManager {
    constructor(app) {
        this.app = app;
        
        this.transferLogs = [];
        this.autoScroll = true;
        this.currentTransferId = null;
        
        // Tabbed transfer logs
        this.transferTabs = new Map(); // transferId -> { logs: [], autoScroll: boolean, transfer: {} }
        this.activeTabId = null;
        this.cachedActiveTransfers = [];
        
        // Throttling for active transfer refresh to reduce UI churn
        this._activeRefreshScheduled = false;
        this._lastActiveRefreshAt = 0;

        // Track last known progress percentage per transfer for smooth bar updates
        this.transferProgress = new Map();
        
        this.initializeTransferManagement();
        this.initializeEventListeners();
    }

    initializeEventListeners() {
        // Transfer management buttons
        document.getElementById('refreshTransfersBtn').addEventListener('click', () => {
            this.loadActiveTransfers();
        });

        document.getElementById('showAllTransfersBtn').addEventListener('click', () => {
            this.showAllTransfersModal();
        });

        document.getElementById('cleanupTransfersBtn').addEventListener('click', () => {
            this.cleanupOldTransfers();
        });

        document.getElementById('refreshAllTransfersBtn').addEventListener('click', () => {
            this.loadAllTransfers();
        });

        document.getElementById('transferStatusFilter').addEventListener('change', () => {
            this.loadAllTransfers();
        });

        // Log controls
        document.getElementById('clearLogBtn').addEventListener('click', () => {
            this.clearTransferLog();
        });

        document.getElementById('autoScrollBtn').addEventListener('click', () => {
            this.toggleAutoScroll();
        });

        document.getElementById('fullscreenLogBtn').addEventListener('click', () => {
            this.showFullscreenLog();
        });

        document.getElementById('closeFullscreenLog').addEventListener('click', () => {
            this.hideFullscreenLog();
        });

        // Handle window resize for tab scroll indicators
        window.addEventListener('resize', () => {
            this.updateTabScrollIndicators();
        });
    }

    scheduleActiveTransferRefresh() {
        const now = Date.now();
        const minIntervalMs = 1000; // throttle to at most once per second
        const elapsed = now - (this._lastActiveRefreshAt || 0);
        if (elapsed >= minIntervalMs) {
            this._lastActiveRefreshAt = now;
            this.loadActiveTransfers();
            return;
        }
        if (this._activeRefreshScheduled) return;
        this._activeRefreshScheduled = true;
        setTimeout(() => {
            this._activeRefreshScheduled = false;
            this._lastActiveRefreshAt = Date.now();
            this.loadActiveTransfers();
        }, Math.max(50, minIntervalMs - elapsed));
    }

    // Update a specific card's progress using socket data (includes percentage parsing)
    updateCardProgressFromSocket(payload) {
        const { transfer_id, logs = [], status } = payload || {};
        if (!transfer_id) return;
        const item = document.querySelector(`#transfer-item-${transfer_id}`);
        if (!item) return;
        if (item.matches(':hover') || (document.activeElement && item.contains(document.activeElement))) {
            // Don't update while interacting
            return;
        }

        // Determine percentage from latest logs if possible
        let percentage = NaN;
        let speed = null;
        for (let i = logs.length - 1; i >= 0 && i >= logs.length - 10; i--) {
            const line = logs[i] || '';
            const m = line.match(/(\d{1,3})%\s+([0-9.,]+[kmgtKMGT]?B\/s)/) || line.match(/(\d{1,3})%/);
            if (m) {
                percentage = parseInt(m[1]);
                const sm = line.match(/([0-9.,]+[kmgtKMGT]?B\/s)/);
                if (sm) speed = sm[1];
                break;
            }
        }

        // Progress text
        const progressText = item.querySelector('.transfer-progress');
        if (progressText && payload.progress) {
            progressText.textContent = payload.progress;
        }

        // Status badge
        const badge = item.querySelector('.transfer-status-badge');
        if (badge && status) {
            badge.textContent = status;
            badge.className = `transfer-status-badge transfer-status-${status}`;
        }

        // Manage progress bar presence and width (smooth, no reset)
        let progressBar = item.querySelector('.progress-bar');
        if (status === 'running') {
            if (!progressBar) {
                // create bar
                const wrapper = document.createElement('div');
                wrapper.className = 'mt-2';
                const lastKnown = this.transferProgress.get(transfer_id);
                const initial = !isNaN(percentage)
                    ? Math.max(1, Math.min(100, percentage))
                    : (typeof lastKnown === 'number' ? lastKnown : 1);
                wrapper.innerHTML = `
                    <div class="progress" style="height: 6px;">
                        <div class="progress-bar" style="width: ${initial}%"></div>
                    </div>
                    <div class="d-flex justify-content-between mt-1">
                        <small class="text-muted">${!isNaN(percentage) ? `${percentage}% complete` : 'Processing...'}</small>
                        ${speed ? `<small class=\"text-muted\">${this.app.ui.escapeHtml(speed)}</small>` : ''}
                    </div>
                `;
                progressText?.insertAdjacentElement('afterend', wrapper);
                progressBar = wrapper.querySelector('.progress-bar');
            } else {
                if (!isNaN(percentage)) {
                    const target = Math.max(0, Math.min(100, percentage));
                    this.transferProgress.set(transfer_id, target);
                    const currentVal = parseFloat((progressBar.style.width || '0').replace('%', '')) || 0;
                    if (target > currentVal) {
                        // Smooth step when a big jump occurs to avoid visual reset
                        const delta = target - currentVal;
                        const step = delta > 20 ? Math.max(5, Math.floor(delta / 2)) : delta;
                        progressBar.style.width = `${Math.min(target, currentVal + step)}%`;
                        setTimeout(() => {
                            progressBar.style.width = `${target}%`;
                        }, 100);
                    } else {
                        progressBar.style.width = `${target}%`;
                    }
                }
                const mt2 = progressBar.closest('.mt-2');
                const dflex = mt2 ? mt2.querySelector('.d-flex') : null;
                if (dflex) {
                    const smalls = dflex.querySelectorAll('small.text-muted');
                    if (smalls.length >= 1) {
                        smalls[0].textContent = !isNaN(percentage) ? `${percentage}% complete` : 'Processing...';
                    }
                    if (speed) {
                        if (smalls.length >= 2) {
                            smalls[1].textContent = speed;
                        } else {
                            const s = document.createElement('small');
                            s.className = 'text-muted';
                            s.textContent = speed;
                            dflex.appendChild(s);
                        }
                    } else if (smalls.length >= 2) {
                        dflex.removeChild(smalls[1]);
                    }
                }
            }
        } else {
            // not running: remove bar if exists
            if (progressBar) {
                const mt2 = progressBar.closest('.mt-2');
                mt2?.parentElement?.removeChild(mt2);
            }
        }
    }

    updateTransferProgress(data) {
        // Update logs for the specific transfer
        this.updateTransferTabLogs(data.transfer_id, data.logs, data.log_count, data.status || 'running');

        // Update the corresponding card's progress bar and text in-place from socket data
        try {
            this.updateCardProgressFromSocket(data);
        } catch (e) {
            // Fallback: schedule a throttled refresh of active transfers
            this.scheduleActiveTransferRefresh();
        }
    }

    handleTransferComplete(data) {
        // Update logs for the specific transfer
        this.updateTransferTabLogs(data.transfer_id, data.logs, data.log_count, data.status);
        
        // Show completion message
        if (data.status === 'completed') {
            this.app.ui.showAlert('Transfer completed successfully!', 'success');
        } else {
            this.app.ui.showAlert(`Transfer failed: ${data.message}`, 'danger');
        }

        // Update the corresponding card's progress bar and text in-place
        try {
            this.updateCardProgressFromSocket(data);
        } catch (e) {
            this.scheduleActiveTransferRefresh();
        }
    }

    updateTransferLog(logs, log_count) {
        const logContainer = document.getElementById('transferLog');
        const logCountElement = document.getElementById('logCount');
        
        // Store logs globally
        this.transferLogs = logs || [];
        
        // Update log count
        if (logCountElement) {
            logCountElement.textContent = `${this.transferLogs.length} lines`;
        }
        
        // Format and display logs with syntax highlighting (chronological order)
        const formattedLogs = this.transferLogs.map(log => {
            const logClass = this.getLogLineClass(log);
            return `<div class="log-line ${logClass}">${this.app.ui.escapeHtml(log)}</div>`;
        }).join('');
        
        logContainer.innerHTML = formattedLogs;
        
        // Auto-scroll to bottom if enabled
        if (this.autoScroll) {
            setTimeout(() => {
                logContainer.scrollTop = logContainer.scrollHeight;
            }, 10);
        }
    }

    // Tab-based transfer log management
    updateTransferTabLogs(transferId, logs, logCount, status = 'running') {
        if (!transferId) return;
        
        // Create or update tab data
        const tabData = this.transferTabs.get(transferId) || {
            logs: [],
            autoScroll: true,
            transfer: {},
            status: status
        };
        
        // Update logs (new logs are added to the end of the array)
        tabData.logs = logs || [];
        tabData.status = status;
        this.transferTabs.set(transferId, tabData);
        
        // Create or update the tab UI
        this.createOrUpdateTransferTab(transferId, tabData);
        
        // Update the display mode
        this.updateLogDisplayMode();
        
        // Update tab scroll indicators
        this.updateTabScrollIndicators();
        
        // If this is the active tab, update the content
        if (this.activeTabId === transferId) {
            this.displayTabContent(transferId);
        }
    }

    createOrUpdateTransferTab(transferId, tabData) {
        const tabsContainer = document.getElementById('logTabs');
        let tab = document.getElementById(`tab-${transferId}`);
        
        if (!tab) {
            // Create new tab and insert at the beginning (newest first)
            tab = document.createElement('a');
            tab.className = 'nav-link';
            tab.id = `tab-${transferId}`;
            // Avoid page scroll to top on click
            tab.href = 'javascript:void(0)';
            tab.setAttribute('role', 'tab');
            tab.onclick = (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.switchToTab(transferId);
            };
            // Handle mousedown to ensure reliable activation even during frequent DOM updates
            tab.onmousedown = (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.switchToTab(transferId);
            };
            
            // Insert at the beginning to show newest transfers first
            if (tabsContainer.firstChild) {
                tabsContainer.insertBefore(tab, tabsContainer.firstChild);
            } else {
                tabsContainer.appendChild(tab);
            }
        }
        
        // Get transfer display name
        const displayName = this.getTransferDisplayName(transferId, tabData.transfer);
        
        // Update tab content
        tab.innerHTML = `
            <span class="log-tab-title" title="${this.app.ui.escapeHtml(displayName)}">${this.app.ui.escapeHtml(this.app.ui.truncateText(displayName, 20))}</span>
            <span class="log-tab-status ${tabData.status}">${tabData.status}</span>
            ${tabData.status === 'completed' || tabData.status === 'failed' || tabData.status === 'cancelled' ? 
                `<button type="button" class="log-tab-close" onclick="event.preventDefault(); event.stopPropagation(); dragonCP.closeTransferTab('${transferId}')" onmousedown="event.preventDefault(); event.stopPropagation();" title="Close tab">
                    <i class="bi bi-x"></i>
                </button>` : ''
            }
        `;
        
        // Set as active if it's the first tab or if no active tab
        if (!this.activeTabId || this.transferTabs.size === 1) {
            this.switchToTab(transferId);
        }
    }

    getTransferDisplayName(transferId, transfer) {
        // Try to get name from active transfers first
        const activeTransfers = this.getActiveTransfersSync();
        const activeTransfer = activeTransfers.find(t => t.id === transferId);
        
        let displayName = '';
        if (activeTransfer) {
            displayName = activeTransfer.parsed_title || activeTransfer.folder_name || transferId;
        } else {
            // Fallback to stored transfer data or transferId
            displayName = transfer.folder_name || transfer.parsed_title || transferId;
        }
        
        // Remove year patterns like (2000) or [2000] from the display name
        return displayName.replace(/[\[\(]\d{4}[\]\)]/g, '').trim();
    }

    getActiveTransfersSync() {
        // This should return cached active transfers data
        // You might need to store this from the loadActiveTransfers() method
        return this.cachedActiveTransfers || [];
    }

    switchToTab(transferId) {
        // Update active tab
        this.activeTabId = transferId;
        
        // Update tab styling
        document.querySelectorAll('.log-nav-tabs .nav-link').forEach(tab => {
            tab.classList.remove('active');
        });
        
        const activeTab = document.getElementById(`tab-${transferId}`);
        if (activeTab) {
            activeTab.classList.add('active');
        }
        
        // Display tab content
        this.displayTabContent(transferId);
        
        // Update controls state
        this.updateLogControlsForTab(transferId);
    }

    displayTabContent(transferId) {
        const tabData = this.transferTabs.get(transferId);
        if (!tabData) return;
        
        // Get or create tab pane
        let tabPane = document.getElementById(`logContent-${transferId}`);
        const tabContent = document.getElementById('logTabContent');
        
        if (!tabPane) {
            tabPane = document.createElement('div');
            tabPane.className = 'tab-pane fade show active';
            tabPane.id = `logContent-${transferId}`;
            tabPane.innerHTML = `
                <div class="transfer-log-container">
                    <div class="transfer-log" id="transferLog-${transferId}"></div>
                </div>
            `;
            tabContent.appendChild(tabPane);
        }
        
        // Hide all tab panes
        document.querySelectorAll('.tab-pane').forEach(pane => {
            pane.classList.remove('show', 'active');
        });
        
        // Show active tab pane
        tabPane.classList.add('show', 'active');
        
        // Update log content
        const logContainer = document.getElementById(`transferLog-${transferId}`);
        if (logContainer) {
            // Display logs in chronological order
            const formattedLogs = tabData.logs.map(log => {
                const logClass = this.getLogLineClass(log);
                return `<div class="log-line ${logClass}">${this.app.ui.escapeHtml(log)}</div>`;
            }).join('');
            
            logContainer.innerHTML = formattedLogs;
            
            // Auto-scroll if enabled for this tab (scroll to bottom)
            if (tabData.autoScroll) {
                setTimeout(() => {
                    logContainer.scrollTop = logContainer.scrollHeight;
                }, 10);
            }
        }
    }

    updateLogDisplayMode() {
        const tabsContainer = document.getElementById('logTabsContainer');
        const singleLogContainer = document.getElementById('singleLogContainer');
        const tabbedLogContainer = document.getElementById('logTabContent');
        const noLogsMessage = document.getElementById('noLogsMessage');
        const logCountElement = document.getElementById('logCount');
        
        const transferCount = this.transferTabs.size;
        
        if (transferCount === 0) {
            // No transfers - show no logs message
            tabsContainer.style.display = 'none';
            singleLogContainer.style.display = 'none';
            tabbedLogContainer.style.display = 'none';
            noLogsMessage.style.display = 'block';
            logCountElement.textContent = '0 active';
        } else if (transferCount === 1) {
            // Single transfer - use single log display
            tabsContainer.style.display = 'none';
            singleLogContainer.style.display = 'block';
            tabbedLogContainer.style.display = 'none';
            noLogsMessage.style.display = 'none';
            
            // Display the single transfer's logs in the main container
            const transferId = Array.from(this.transferTabs.keys())[0];
            const tabData = this.transferTabs.get(transferId);
            
            const mainLogContainer = document.getElementById('transferLog');
            if (mainLogContainer && tabData) {
                // Display logs in chronological order for single transfer view
                const formattedLogs = tabData.logs.map(log => {
                    const logClass = this.getLogLineClass(log);
                    return `<div class="log-line ${logClass}">${this.app.ui.escapeHtml(log)}</div>`;
                }).join('');
                
                mainLogContainer.innerHTML = formattedLogs;
                
                if (tabData.autoScroll) {
                    setTimeout(() => {
                        mainLogContainer.scrollTop = mainLogContainer.scrollHeight;
                    }, 10);
                }
                
                logCountElement.textContent = `${tabData.logs.length} lines`;
            }
        } else {
            // Multiple transfers - use tabbed display
            tabsContainer.style.display = 'block';
            singleLogContainer.style.display = 'none';
            tabbedLogContainer.style.display = 'block';
            noLogsMessage.style.display = 'none';
            logCountElement.textContent = `${transferCount} active`;
        }
    }

    updateLogControlsForTab(transferId) {
        const tabData = this.transferTabs.get(transferId);
        if (!tabData) return;
        
        const autoScrollBtn = document.getElementById('autoScrollBtn');
        if (autoScrollBtn) {
            if (tabData.autoScroll) {
                autoScrollBtn.innerHTML = '<i class="bi bi-arrow-up-circle-fill"></i>';
                autoScrollBtn.title = 'Auto-scroll to newest enabled';
            } else {
                autoScrollBtn.innerHTML = '<i class="bi bi-arrow-up-circle"></i>';
                autoScrollBtn.title = 'Auto-scroll to newest disabled';
            }
        }
    }

    closeTransferTab(transferId) {
        // Remove tab data
        this.transferTabs.delete(transferId);
        
        // Remove tab UI
        const tab = document.getElementById(`tab-${transferId}`);
        if (tab) {
            tab.remove();
        }
        
        // Remove tab content
        const tabPane = document.getElementById(`logContent-${transferId}`);
        if (tabPane) {
            tabPane.remove();
        }
        
        // If this was the active tab, switch to another tab
        if (this.activeTabId === transferId) {
            const remainingTabs = Array.from(this.transferTabs.keys());
            if (remainingTabs.length > 0) {
                this.switchToTab(remainingTabs[0]);
            } else {
                this.activeTabId = null;
            }
        }
        
        // Update display mode
        this.updateLogDisplayMode();
        
        // Update tab scroll indicators after closing
        this.updateTabScrollIndicators();
    }

    updateTabScrollIndicators() {
        const tabsContainer = document.getElementById('logTabs');
        if (!tabsContainer) return;
        
        // Ensure desktop scrollability (horizontal)
        tabsContainer.style.overflowX = 'auto';
        tabsContainer.style.whiteSpace = 'nowrap';
        tabsContainer.style.webkitOverflowScrolling = 'touch';
        tabsContainer.style.flexWrap = 'nowrap';

        // Add wheel-to-horizontal behavior once (non-intrusive)
        if (!tabsContainer.dataset.wheelScrollBound) {
            tabsContainer.addEventListener('wheel', (e) => {
                if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
                    tabsContainer.scrollLeft += e.deltaY;
                    e.preventDefault();
                }
            }, { passive: false });
            tabsContainer.dataset.wheelScrollBound = 'true';
        }

        // Check if tabs are scrollable
        const isScrollable = tabsContainer.scrollWidth > tabsContainer.clientWidth;
        
        // Update the scrollable attribute for CSS indicators
        if (isScrollable) {
            tabsContainer.setAttribute('data-scrollable', 'true');
        } else {
            tabsContainer.removeAttribute('data-scrollable');
        }
        // Do not adjust scroll position here; respect user's current position
    }

    getLogLineClass(logLine) {
        const line = logLine.toLowerCase();
        if (line.includes('error') || line.includes('failed') || line.includes('exception')) {
            return 'error';
        } else if (line.includes('warning') || line.includes('warn')) {
            return 'warning';
        } else if (line.includes('success') || line.includes('completed') || line.includes('done')) {
            return 'success';
        } else if (line.includes('info') || line.includes('progress') || line.includes('transferring')) {
            return 'info';
        }
        return '';
    }

    clearTransferLog() {
        if (this.transferTabs.size > 1 && this.activeTabId) {
            // Clear only the active tab's logs
            const tabData = this.transferTabs.get(this.activeTabId);
            if (tabData) {
                tabData.logs = [];
                this.displayTabContent(this.activeTabId);
                this.app.ui.showAlert('Current tab logs cleared', 'info');
            }
        } else {
            // Clear single transfer logs
            this.transferLogs = [];
            const logContainer = document.getElementById('transferLog');
            const logCountElement = document.getElementById('logCount');
            
            logContainer.innerHTML = '';
            if (logCountElement) {
                logCountElement.textContent = '0 lines';
            }
            
            // Also clear the single tab if it exists
            if (this.transferTabs.size === 1) {
                const transferId = Array.from(this.transferTabs.keys())[0];
                const tabData = this.transferTabs.get(transferId);
                if (tabData) {
                    tabData.logs = [];
                }
            }
            
            this.app.ui.showAlert('Transfer logs cleared', 'info');
        }
    }

    toggleAutoScroll() {
        if (this.transferTabs.size > 1 && this.activeTabId) {
            // Toggle auto-scroll for the active tab
            const tabData = this.transferTabs.get(this.activeTabId);
            if (tabData) {
                tabData.autoScroll = !tabData.autoScroll;
                this.updateLogControlsForTab(this.activeTabId);
                
                if (tabData.autoScroll) {
                    this.app.ui.showAlert('Auto-scroll enabled for current tab', 'info');
                    // Scroll to bottom to show latest logs immediately
                    const logContainer = document.getElementById(`transferLog-${this.activeTabId}`);
                    if (logContainer) {
                        logContainer.scrollTop = logContainer.scrollHeight;
                    }
                } else {
                    this.app.ui.showAlert('Auto-scroll disabled for current tab', 'info');
                }
            }
        } else {
            // Toggle auto-scroll for single transfer
            this.autoScroll = !this.autoScroll;
            const autoScrollBtn = document.getElementById('autoScrollBtn');
            
            if (this.autoScroll) {
                autoScrollBtn.innerHTML = '<i class="bi bi-arrow-up-circle-fill"></i>';
                autoScrollBtn.title = 'Auto-scroll to newest enabled';
                this.app.ui.showAlert('Auto-scroll to newest enabled', 'info');
                
                // Scroll to bottom to show latest logs immediately
                const logContainer = document.getElementById('transferLog');
                logContainer.scrollTop = logContainer.scrollHeight;
            } else {
                autoScrollBtn.innerHTML = '<i class="bi bi-arrow-up-circle"></i>';
                autoScrollBtn.title = 'Auto-scroll to newest disabled';
                this.app.ui.showAlert('Auto-scroll disabled', 'info');
            }
            
            // Also update the single tab if it exists
            if (this.transferTabs.size === 1) {
                const transferId = Array.from(this.transferTabs.keys())[0];
                const tabData = this.transferTabs.get(transferId);
                if (tabData) {
                    tabData.autoScroll = this.autoScroll;
                }
            }
        }
    }

    showFullscreenLog() {
        const fullscreenModal = document.getElementById('fullscreenLogModal');
        const fullscreenLog = document.getElementById('fullscreenTransferLog');
        
        let logsToShow = [];
        let transferName = 'Transfer Log';
        
        if (this.transferTabs.size > 1 && this.activeTabId) {
            // Show logs for the active tab
            const tabData = this.transferTabs.get(this.activeTabId);
            if (tabData) {
                logsToShow = tabData.logs;
                transferName = this.getTransferDisplayName(this.activeTabId, tabData.transfer);
            }
        } else if (this.transferTabs.size === 1) {
            // Show logs for the single tab
            const transferId = Array.from(this.transferTabs.keys())[0];
            const tabData = this.transferTabs.get(transferId);
            if (tabData) {
                logsToShow = tabData.logs;
                transferName = this.getTransferDisplayName(transferId, tabData.transfer);
            }
        } else {
            // Fallback to legacy logs
            logsToShow = this.transferLogs;
        }
        
        // Update fullscreen header with transfer name
        const fullscreenHeader = fullscreenModal.querySelector('.log-fullscreen-header h5');
        if (fullscreenHeader) {
            fullscreenHeader.innerHTML = `<i class="bi bi-terminal"></i> ${this.app.ui.escapeHtml(transferName)} - Fullscreen`;
        }
        
        // Format logs for fullscreen display (chronological order)
        const formattedLogs = logsToShow.map(log => {
            const logClass = this.getLogLineClass(log);
            return `<div class="log-line ${logClass}">${this.app.ui.escapeHtml(log)}</div>`;
        }).join('');
        
        fullscreenLog.innerHTML = formattedLogs;
        fullscreenModal.classList.add('show');
        
        // Scroll to bottom to show latest logs
        fullscreenLog.scrollTop = fullscreenLog.scrollHeight;
        
        // Prevent body scroll
        document.body.style.overflow = 'hidden';
    }

    hideFullscreenLog() {
        const fullscreenModal = document.getElementById('fullscreenLogModal');
        fullscreenModal.classList.remove('show');
        
        // Restore body scroll
        document.body.style.overflow = '';
    }

    async loadTransferLogs(transferId) {
        try {
            const response = await fetch(`/api/transfer/${transferId}/logs`);
            const result = await response.json();
            
            if (result.status === 'success') {
                this.currentTransferId = transferId;
                this.updateTransferLog(result.logs, result.log_count);
                this.app.ui.showAlert(`Loaded ${result.log_count} log lines`, 'info');
            } else {
                this.app.ui.showAlert('Failed to load transfer logs', 'danger');
            }
        } catch (error) {
            console.error('Failed to load transfer logs:', error);
            this.app.ui.showAlert('Failed to load transfer logs', 'danger');
        }
    }

    async showTransferLogs(transferId) {
        try {
            const response = await fetch(`/api/transfer/${transferId}/logs`);
            const result = await response.json();
            
            if (result.status === 'success') {
                this.currentTransferId = transferId;
                
                // Get transfer details for the tab
                const transferDetails = this.cachedActiveTransfers?.find(t => t.id === transferId) || {};
                
                // Update tab logs (this will create a tab if it doesn't exist)
                this.updateTransferTabLogs(transferId, result.logs, result.log_count, result.transfer_status || 'running');
                
                // Show the log card
                document.getElementById('logCard').style.display = 'block';
                
                // Switch to this transfer's tab if using tabbed display
                if (this.transferTabs.size > 1) {
                    this.switchToTab(transferId);
                }
                
                // Scroll to the log card
                // Avoid auto-scrolling the page; just reveal content without changing viewport position
                
                this.app.ui.showAlert(`Loaded ${result.log_count} log lines`, 'info');
            } else {
                this.app.ui.showAlert('Failed to load transfer logs', 'danger');
            }
        } catch (error) {
            console.error('Failed to load transfer logs:', error);
            this.app.ui.showAlert('Failed to load transfer logs', 'danger');
        }
    }

    async cancelTransfer(transferId) {
        try {
            const response = await fetch(`/api/transfer/${transferId}/cancel`, {
                method: 'POST'
            });
            
            const result = await response.json();
            
            if (result.status === 'success') {
                this.app.ui.showAlert('Transfer cancelled', 'warning');
                // Refresh the database-based transfer list
                this.loadActiveTransfers();
            } else {
                this.app.ui.showAlert('Failed to cancel transfer', 'danger');
            }
        } catch (error) {
            console.error('Cancel transfer error:', error);
            this.app.ui.showAlert('Failed to cancel transfer', 'danger');
        }
    }

    // Transfer Management Methods
    initializeTransferManagement() {
        this.loadActiveTransfers();
        
        // Auto-refresh active transfers every 30 seconds
        setInterval(() => {
            this.loadActiveTransfers();
        }, 30000);
    }

    async loadActiveTransfers() {
        try {
            const response = await fetch('/api/transfers/active');
            const result = await response.json();
            
            if (result.status === 'success') {
                // Cache active transfers for tab display names
                this.cachedActiveTransfers = result.transfers;
                
                // Update queue status display
                if (result.queue_status) {
                    this.updateQueueStatusDisplay(result.queue_status);
                }
                
                // Update active transfer tabs
                this.updateActiveTransferTabs(result.transfers);
                
                this.updateTransferManagementDisplay(result.transfers);
                document.getElementById('transferManagementCard').style.display = 'block';
            } else {
                console.error('Failed to load active transfers:', result.message);
            }
        } catch (error) {
            console.error('Failed to load active transfers:', error);
        }
    }
    
    updateQueueStatusDisplay(queueStatus) {
        // Update the badge to show queue status
        const badge = document.getElementById('activeTransferCount');
        if (badge && queueStatus) {
            const runningCount = queueStatus.running_count || 0;
            const queuedCount = queueStatus.queued_count || 0;
            const maxConcurrent = queueStatus.max_concurrent || 3;
            
            if (queuedCount > 0) {
                badge.textContent = `${runningCount}/${maxConcurrent} running, ${queuedCount} queued`;
            } else {
                badge.textContent = `${runningCount}/${maxConcurrent} running`;
            }
        }
    }

    updateActiveTransferTabs(activeTransfers) {
        // Add or update tabs for active transfers that don't have tabs yet
        activeTransfers.forEach(transfer => {
            if (!this.transferTabs.has(transfer.id)) {
                // Create a new tab for this transfer
                const tabData = {
                    logs: [],
                    autoScroll: true,
                    transfer: transfer,
                    status: transfer.status
                };
                this.transferTabs.set(transfer.id, tabData);
                this.createOrUpdateTransferTab(transfer.id, tabData);
            } else {
                // Update existing tab status
                const tabData = this.transferTabs.get(transfer.id);
                tabData.transfer = transfer;
                tabData.status = transfer.status;
                this.createOrUpdateTransferTab(transfer.id, tabData);
            }
        });
        
        // Remove tabs for transfers that are no longer active (completed/failed/cancelled)
        const activeTransferIds = new Set(activeTransfers.map(t => t.id));
        const tabsToRemove = [];
        
        this.transferTabs.forEach((tabData, transferId) => {
            if (!activeTransferIds.has(transferId) && 
                (tabData.status === 'completed' || tabData.status === 'failed' || tabData.status === 'cancelled')) {
                // Don't auto-remove tabs for completed transfers - let user close them manually
                // But update their status
                const cachedTransfer = this.cachedActiveTransfers.find(t => t.id === transferId);
                if (cachedTransfer) {
                    tabData.status = cachedTransfer.status;
                    this.createOrUpdateTransferTab(transferId, tabData);
                }
            }
        });
        
        // Update display mode
        this.updateLogDisplayMode();
    }

    updateTransferManagementDisplay(transfers) {
        const container = document.getElementById('transferList');
        const countBadge = document.getElementById('activeTransferCount');
        const noTransfersMessage = document.getElementById('noTransfersMessage');

        // Update count badge (handled by updateQueueStatusDisplay now)
        // const activeCount = transfers.filter(t => t.status === 'running' || t.status === 'pending').length;
        // countBadge.textContent = `${activeCount} active`;

        // Handle empty state
        if (transfers.length === 0) {
            // Remove all existing items
            container.innerHTML = '';
            noTransfersMessage.style.display = 'block';
            return;
        }

        noTransfersMessage.style.display = 'none';

        // One-time migration: if old DOM (no data-transfer-id), clear to avoid duplicates
        if (!container.querySelector('.transfer-item[data-transfer-id]') && container.children.length > 0) {
            container.innerHTML = '';
        }

        // Build a set of incoming transfer IDs for diffing
        const incomingIds = new Set(transfers.map(t => t.id));

        // Remove DOM items that no longer exist
        const existingCols = Array.from(container.children);
        existingCols.forEach(col => {
            const item = col.querySelector('.transfer-item');
            const id = item?.getAttribute('data-transfer-id');
            if (id && !incomingIds.has(id)) {
                container.removeChild(col);
            }
        });

        // Update or create items
        transfers.forEach(transfer => {
            const existingItem = container.querySelector(`#transfer-item-${transfer.id}`);
            if (existingItem) {
                // Skip updating if user is interacting with this item
                if (existingItem.matches(':hover') || (document.activeElement && existingItem.contains(document.activeElement))) {
                    return;
                }

                // Update status badge
                const statusBadge = existingItem.querySelector('.transfer-status-badge');
                if (statusBadge) {
                    statusBadge.textContent = transfer.status;
                    statusBadge.className = `transfer-status-badge transfer-status-${transfer.status}`;
                }

                // Update title text
                const titleText = existingItem.querySelector('.transfer-title-text');
                if (titleText) {
                    const displayTitle = transfer.parsed_title || transfer.folder_name;
                    titleText.textContent = displayTitle || '';
                }

                // Update meta (type + details) line and started time
                const typeLine = existingItem.querySelector('.transfer-type-line');
                if (typeLine) {
                    const displaySubtitle = this.buildTransferSubtitle(transfer);
                    typeLine.innerHTML = `<strong>Type:</strong> ${this.app.ui.escapeHtml(transfer.media_type)}${displaySubtitle ? ` <span class="transfer-details">• ${this.app.ui.escapeHtml(displaySubtitle)}</span>` : ''}`;
                }
                const startedEl = existingItem.querySelector('.transfer-time');
                if (startedEl) {
                    startedEl.innerHTML = `<strong>Started:</strong> ${this.app.ui.getTimeAgo(transfer.start_time)}`;
                }

                // Update progress text
                const progressText = existingItem.querySelector('.transfer-progress');
                if (progressText) {
                    progressText.textContent = transfer.progress || 'Initializing...';
                }

                // Update or toggle progress bar without resetting width on unknown percentage
                const progressBar = existingItem.querySelector('.progress-bar');
                if (transfer.status === 'running') {
                    const progressInfo = this.parseTransferProgress(transfer);
                    if (!progressBar) {
                        // Insert progress bar right after progress text
                        const wrapper = document.createElement('div');
                        wrapper.className = 'mt-2';
                        // Use last known percentage if available to avoid reset feel
                        const lastKnown = this.transferProgress.get(transfer.id);
                        const initial = (progressInfo.percentage > 0 ? progressInfo.percentage : (typeof lastKnown === 'number' ? lastKnown : 1));
                        wrapper.innerHTML = `
                            <div class="progress" style="height: 6px;">
                                <div class="progress-bar" style="width: ${initial}%"></div>
                            </div>
                            <div class="d-flex justify-content-between mt-1">
                                <small class="text-muted">${progressInfo.percentage > 0 ? `${progressInfo.percentage}% complete` : 'Processing...'}</small>
                                ${progressInfo.speed ? `<small class="text-muted">${this.app.ui.escapeHtml(progressInfo.speed)}</small>` : ''}
                            </div>
                        `;
                        progressText?.insertAdjacentElement('afterend', wrapper);
                    } else {
                        // Only update width when we have a valid percentage; don't force back to 0
                        const info = this.parseTransferProgress(transfer);
                        if (info.percentage && info.percentage > 0) {
                            // cache last known
                            this.transferProgress.set(transfer.id, info.percentage);
                            const current = parseInt(progressBar.style.width || '0');
                            if (isNaN(current) || current !== info.percentage) {
                                progressBar.style.width = `${Math.max(0, Math.min(100, info.percentage))}%`;
                            }
                            const mt2 = progressBar.closest('.mt-2');
                            const dflex = mt2 ? mt2.querySelector('.d-flex') : null;
                            if (dflex) {
                                const smalls = dflex.querySelectorAll('small.text-muted');
                                if (smalls.length >= 1) {
                                    smalls[0].textContent = `${info.percentage}% complete`;
                                }
                                if (info.speed) {
                                    if (smalls.length >= 2) {
                                        smalls[1].textContent = info.speed;
                                    } else {
                                        const s = document.createElement('small');
                                        s.className = 'text-muted';
                                        s.textContent = info.speed;
                                        dflex.appendChild(s);
                                    }
                                }
                            }
                        }
                    }
                } else if (progressBar) {
                    // Remove progress bar when not running
                    const containerEl = progressBar.closest('.mt-2');
                    containerEl?.parentElement?.removeChild(containerEl);
                }

                // Update actions
                const actions = existingItem.querySelector('.transfer-actions');
                if (actions) {
                    actions.innerHTML = `
                        <button class="btn btn-sm btn-outline-info" onclick="dragonCP.showTransferDetails('${transfer.id}')">
                            <i class="bi bi-eye"></i> Details
                        </button>
                        ${transfer.status === 'running' ? 
                            `<button class="btn btn-sm btn-outline-danger" onclick="dragonCP.cancelTransfer('${transfer.id}')">
                                <i class="bi bi-x-circle"></i> Cancel
                            </button>` : ''
                        }
                        ${(transfer.status === 'failed' || transfer.status === 'cancelled') ? 
                            `<button class="btn btn-sm btn-outline-success" onclick="dragonCP.restartTransfer('${transfer.id}')">
                                <i class="bi bi-arrow-clockwise"></i> Restart
                            </button>` : ''
                        }
                        ${transfer.log_count > 0 ? 
                            `<button class="btn btn-sm btn-outline-secondary" onclick="dragonCP.showTransferLogs('${transfer.id}')">
                                <i class="bi bi-terminal"></i> Logs (${transfer.log_count})
                            </button>` : ''
                        }
                        ${transfer.status !== 'running' ? 
                            `<button class="btn btn-sm btn-outline-danger" onclick="dragonCP.deleteTransfer('${transfer.id}')">
                                <i class="bi bi-trash"></i> Delete
                            </button>` : ''
                        }
                    `;
                }
            } else {
                // Create new item
                const col = document.createElement('div');
                col.className = 'col-lg-6 col-xl-4';

                const displayTitle = transfer.parsed_title || transfer.folder_name;
                const displaySubtitle = this.buildTransferSubtitle(transfer);
                const timeAgo = this.app.ui.getTimeAgo(transfer.start_time);

                col.innerHTML = `
                    <div class="transfer-item" id="transfer-item-${transfer.id}" data-transfer-id="${transfer.id}">
                        <div class="d-flex justify-content-between align-items-start mb-2">
                            <div class="transfer-title">
                                <i class="bi bi-${this.getTransferTypeIcon(transfer.transfer_type)} transfer-type-icon"></i>
                                <span class="transfer-title-text">${this.app.ui.escapeHtml(displayTitle)}</span>
                            </div>
                            <span class="transfer-status-badge transfer-status-${transfer.status}">
                                ${transfer.status}
                            </span>
                        </div>
                        <div class="transfer-meta">
                            <div class="transfer-type-line"><strong>Type:</strong> ${this.app.ui.escapeHtml(transfer.media_type)}${displaySubtitle ? ` <span class=\"transfer-details\">• ${this.app.ui.escapeHtml(displaySubtitle)}</span>` : ''}</div>
                            <div class="transfer-time"><strong>Started:</strong> ${timeAgo}</div>
                        </div>
                        <div class="transfer-progress">${this.app.ui.escapeHtml(transfer.progress || 'Initializing...')}</div>
                        <!-- Progress bar inserted dynamically from socket updates to prevent resets -->
                        <div class="transfer-actions">
                            <button class="btn btn-sm btn-outline-info" onclick="dragonCP.showTransferDetails('${transfer.id}')">
                                <i class="bi bi-eye"></i> Details
                            </button>
                            ${transfer.status === 'running' ? 
                                `<button class="btn btn-sm btn-outline-danger" onclick="dragonCP.cancelTransfer('${transfer.id}')">
                                    <i class="bi bi-x-circle"></i> Cancel
                                </button>` : ''
                            }
                            ${(transfer.status === 'failed' || transfer.status === 'cancelled') ? 
                                `<button class="btn btn-sm btn-outline-success" onclick="dragonCP.restartTransfer('${transfer.id}')">
                                    <i class="bi bi-arrow-clockwise"></i> Restart
                                </button>` : ''
                            }
                            ${transfer.log_count > 0 ? 
                                `<button class="btn btn-sm btn-outline-secondary" onclick="dragonCP.showTransferLogs('${transfer.id}')">
                                    <i class="bi bi-terminal"></i> Logs (${transfer.log_count})
                                </button>` : ''
                            }
                            ${transfer.status !== 'running' ? 
                                `<button class="btn btn-sm btn-outline-danger" onclick="dragonCP.deleteTransfer('${transfer.id}')">
                                    <i class="bi bi-trash"></i> Delete
                                </button>` : ''
                            }
                        </div>
                    </div>
                `;

                container.appendChild(col);
            }
        });
    }

    buildTransferSubtitle(transfer) {
        const parts = [];
        
        if (transfer.parsed_season) {
            parts.push(`Season ${transfer.parsed_season}`);
        } else if (transfer.season_name) {
            parts.push(transfer.season_name);
        }
        
        if (transfer.parsed_episode) {
            parts.push(`Episode ${transfer.parsed_episode}`);
        } else if (transfer.episode_name) {
            parts.push(transfer.episode_name);
        }
        
        return parts.join(' - ');
    }

    getTransferTypeIcon(transferType) {
        return transferType === 'file' ? 'file-play' : 'folder';
    }

    parseTransferProgress(transfer) {
        if (!transfer.logs || transfer.logs.length === 0) {
            return { percentage: 0, speed: null };
        }
        
        // Look for rsync progress in the last few log lines
        const recentLogs = transfer.logs.slice(-10);
        let percentage = 0;
        let speed = null;
        
        for (let i = recentLogs.length - 1; i >= 0; i--) {
            const log = recentLogs[i];
            
            // Match rsync progress patterns like "1,234,567  67%  1.23MB/s"
            const progressMatch = log.match(/(\d{1,3})%\s+([0-9.,]+[kmgtKMGT]?B\/s)/);
            if (progressMatch) {
                percentage = parseInt(progressMatch[1]);
                speed = progressMatch[2];
                break;
            }
            
            // Match alternative patterns like "67% 1.23MB/s"
            const altMatch = log.match(/(\d{1,3})%.*?([0-9.,]+[kmgtKMGT]?B\/s)/);
            if (altMatch) {
                percentage = parseInt(altMatch[1]);
                speed = altMatch[2];
                break;
            }
            
            // Match just percentage
            const percentMatch = log.match(/(\d{1,3})%/);
            if (percentMatch) {
                percentage = parseInt(percentMatch[1]);
                break;
            }
        }
        
        return { percentage, speed };
    }

    async showAllTransfersModal() {
        const modal = new bootstrap.Modal(document.getElementById('allTransfersModal'));
        modal.show();
        await this.loadAllTransfers();
    }

    async loadAllTransfers() {
        try {
            const statusFilter = document.getElementById('transferStatusFilter').value;
            let url = '/api/transfers/all?limit=100';
            if (statusFilter) {
                url += `&status=${statusFilter}`;
            }
            
            const response = await fetch(url);
            const result = await response.json();
            
            if (result.status === 'success') {
                this.updateAllTransfersTable(result.transfers);
            } else {
                this.app.ui.showAlert('Failed to load transfers', 'danger');
            }
        } catch (error) {
            console.error('Failed to load all transfers:', error);
            this.app.ui.showAlert('Failed to load transfers', 'danger');
        }
    }

    updateAllTransfersTable(transfers) {
        const tableBody = document.getElementById('allTransfersTable');
        const noTransfersMessage = document.getElementById('noAllTransfersMessage');
        
        tableBody.innerHTML = '';
        
        if (transfers.length === 0) {
            noTransfersMessage.style.display = 'block';
            return;
        }
        
        noTransfersMessage.style.display = 'none';
        
        transfers.forEach(transfer => {
            const row = document.createElement('tr');
            
            const displayTitle = transfer.parsed_title || transfer.folder_name;
            const displaySubtitle = this.buildTransferSubtitle(transfer);
            const fullTitle = displaySubtitle ? `${displayTitle} - ${displaySubtitle}` : displayTitle;
            
            row.innerHTML = `
                <td>
                    <div class="d-flex align-items-center">
                        <i class="bi bi-${this.getTransferTypeIcon(transfer.transfer_type)} me-2"></i>
                        <div>
                            <div class="fw-bold">${this.app.ui.escapeHtml(displayTitle)}</div>
                            ${displaySubtitle ? `<small class="text-muted">${this.app.ui.escapeHtml(displaySubtitle)}</small>` : ''}
                        </div>
                    </div>
                </td>
                <td>
                    <span class="badge bg-secondary">${this.app.ui.escapeHtml(transfer.media_type)}</span>
                </td>
                <td>
                    <span class="transfer-status-badge transfer-status-${transfer.status}">
                        ${transfer.status}
                    </span>
                </td>
                <td>
                    <small>${this.app.ui.escapeHtml(transfer.progress || 'N/A')}</small>
                </td>
                <td>
                    <small>${this.app.ui.getTimeAgo(transfer.start_time)}</small>
                </td>
                <td>
                    <div class="btn-group btn-group-sm">
                        <button class="btn btn-outline-info" onclick="dragonCP.showTransferDetails('${transfer.id}')" title="View details">
                            <i class="bi bi-eye"></i>
                        </button>
                        ${transfer.status === 'running' ? 
                            `<button class="btn btn-outline-danger" onclick="dragonCP.cancelTransfer('${transfer.id}')" title="Cancel">
                                <i class="bi bi-x-circle"></i>
                            </button>` : ''
                        }
                        ${transfer.status === 'failed' || transfer.status === 'cancelled' ? 
                            `<button class="btn btn-outline-success" onclick="dragonCP.restartTransfer('${transfer.id}')" title="Restart">
                                <i class="bi bi-arrow-clockwise"></i>
                            </button>` : ''
                        }
                        ${transfer.status !== 'running' ? 
                            `<button class="btn btn-outline-danger" onclick="dragonCP.deleteTransfer('${transfer.id}')" title="Delete">
                                <i class="bi bi-trash"></i>
                            </button>` : ''
                        }
                    </div>
                </td>
            `;
            
            tableBody.appendChild(row);
        });
    }

    async showTransferDetails(transferId) {
        try {
            const response = await fetch(`/api/transfer/${transferId}/status`);
            const result = await response.json();
            
            if (result.status === 'success') {
                const transfer = result.transfer;
                this.renderTransferDetails(transfer);
                const modal = new bootstrap.Modal(document.getElementById('transferDetailsModal'));
                modal.show();
            } else {
                this.app.ui.showAlert('Failed to load transfer details', 'danger');
            }
        } catch (error) {
            console.error('Failed to load transfer details:', error);
            this.app.ui.showAlert('Failed to load transfer details', 'danger');
        }
    }

    renderTransferDetails(transfer) {
        const content = document.getElementById('transferDetailsContent');
        const logContainer = document.getElementById('transferDetailsLog');
        
        // Render transfer details
        const displayTitle = transfer.parsed_title || transfer.folder_name;
        const displaySubtitle = this.buildTransferSubtitle(transfer);
        
        content.innerHTML = `
            <div class="transfer-details-section">
                <h6>Transfer Information</h6>
                <div class="transfer-details-grid">
                    <div class="transfer-details-item">
                        <div class="transfer-details-label">Title</div>
                        <div class="transfer-details-value">${this.app.ui.escapeHtml(displayTitle)}</div>
                    </div>
                    ${displaySubtitle ? `
                    <div class="transfer-details-item">
                        <div class="transfer-details-label">Details</div>
                        <div class="transfer-details-value">${this.app.ui.escapeHtml(displaySubtitle)}</div>
                    </div>` : ''}
                    <div class="transfer-details-item">
                        <div class="transfer-details-label">Media Type</div>
                        <div class="transfer-details-value">${this.app.ui.escapeHtml(transfer.media_type)}</div>
                    </div>
                    <div class="transfer-details-item">
                        <div class="transfer-details-label">Transfer Type</div>
                        <div class="transfer-details-value">${this.app.ui.escapeHtml(transfer.transfer_type)}</div>
                    </div>
                    <div class="transfer-details-item">
                        <div class="transfer-details-label">Status</div>
                        <div class="transfer-details-value">
                            <span class="transfer-status-badge transfer-status-${transfer.status}">
                                ${transfer.status}
                            </span>
                        </div>
                    </div>
                    <div class="transfer-details-item">
                        <div class="transfer-details-label">Started</div>
                        <div class="transfer-details-value">${this.app.ui.getTimeAgo(transfer.start_time)}</div>
                    </div>
                    ${transfer.end_time ? `
                    <div class="transfer-details-item">
                        <div class="transfer-details-label">Completed</div>
                        <div class="transfer-details-value">${this.app.ui.getTimeAgo(transfer.end_time)}</div>
                    </div>` : ''}
                </div>
            </div>
            
            <div class="transfer-details-section">
                <h6>Paths</h6>
                <div class="transfer-details-grid">
                    <div class="transfer-details-item">
                        <div class="transfer-details-label">Source Path</div>
                        <div class="transfer-details-value">${this.app.ui.escapeHtml(transfer.source_path)}</div>
                    </div>
                    <div class="transfer-details-item">
                        <div class="transfer-details-label">Destination Path</div>
                        <div class="transfer-details-value">${this.app.ui.escapeHtml(transfer.dest_path)}</div>
                    </div>
                </div>
            </div>
            
            <div class="transfer-details-section">
                <h6>Progress</h6>
                <div class="transfer-details-item">
                    <div class="transfer-details-value">${this.app.ui.escapeHtml(transfer.progress || 'No progress information')}</div>
                </div>
            </div>
        `;
        
        // Render logs
        const formattedLogs = transfer.logs.map(log => {
            const logClass = this.getLogLineClass(log);
            return `<div class="log-line ${logClass}">${this.app.ui.escapeHtml(log)}</div>`;
        }).join('');
        
        logContainer.innerHTML = formattedLogs;
        this.app.ui.scrollToBottom(logContainer);
        
        // Add action buttons to the modal
        const modalBody = document.querySelector('#transferDetailsModal .modal-body');
        const actionButtonsDiv = document.createElement('div');
        actionButtonsDiv.className = 'mt-3 pt-3 border-top';
        actionButtonsDiv.innerHTML = `
            <h6>Actions:</h6>
            <div class="btn-group">
                ${transfer.status === 'running' ? 
                    `<button class="btn btn-outline-danger" onclick="dragonCP.cancelTransfer('${transfer.id}')" title="Cancel">
                        <i class="bi bi-x-circle"></i> Cancel
                    </button>` : ''
                }
                ${transfer.status === 'failed' || transfer.status === 'cancelled' ? 
                    `<button class="btn btn-outline-success" onclick="dragonCP.restartTransfer('${transfer.id}')" title="Restart">
                        <i class="bi bi-arrow-clockwise"></i> Restart
                    </button>` : ''
                }
                ${transfer.status !== 'running' ? 
                    `<button class="btn btn-outline-danger" onclick="dragonCP.deleteTransfer('${transfer.id}')" title="Delete">
                        <i class="bi bi-trash"></i> Delete
                    </button>` : ''
                }
            </div>
        `;
        
        // Remove any existing action buttons and add new ones
        const existingActionButtons = modalBody.querySelector('.border-top');
        if (existingActionButtons) {
            existingActionButtons.remove();
        }
        modalBody.appendChild(actionButtonsDiv);
    }

    async restartTransfer(transferId) {
        try {
            const response = await fetch(`/api/transfer/${transferId}/restart`, {
                method: 'POST'
            });
            
            const result = await response.json();
            
            if (result.status === 'success') {
                this.app.ui.showAlert('Transfer restarted successfully!', 'success');
                this.loadActiveTransfers();
            } else {
                this.app.ui.showAlert('Failed to restart transfer: ' + result.message, 'danger');
            }
        } catch (error) {
            console.error('Failed to restart transfer:', error);
            this.app.ui.showAlert('Failed to restart transfer', 'danger');
        }
    }

    async deleteTransfer(transferId) {
        try {
            const confirmed = confirm('Are you sure you want to delete this transfer? This action cannot be undone.');
            if (!confirmed) return;
            
            const response = await fetch(`/api/transfer/${transferId}/delete`, {
                method: 'POST'
            });
            
            const result = await response.json();
            
            if (result.status === 'success') {
                this.app.ui.showAlert('Transfer deleted successfully!', 'success');
                
                // Close the transfer details modal if it's open
                const transferDetailsModal = bootstrap.Modal.getInstance(document.getElementById('transferDetailsModal'));
                if (transferDetailsModal) {
                    transferDetailsModal.hide();
                }
                
                // Refresh the appropriate lists
                this.loadActiveTransfers();
                this.loadAllTransfers();
            } else {
                this.app.ui.showAlert('Failed to delete transfer: ' + result.message, 'danger');
            }
        } catch (error) {
            console.error('Failed to delete transfer:', error);
            this.app.ui.showAlert('Failed to delete transfer', 'danger');
        }
    }

    async cleanupOldTransfers() {
        try {
            const confirmed = confirm('This will remove all duplicate transfers for the same destination path, keeping only the latest successful transfer. Continue?');
            if (!confirmed) return;
            
            const response = await fetch('/api/transfers/cleanup', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            
            const result = await response.json();
            
            if (result.status === 'success') {
                this.app.ui.showAlert(`Cleaned up ${result.cleaned_count} duplicate transfers`, 'success');
                this.loadActiveTransfers();
                this.loadAllTransfers();
            } else {
                this.app.ui.showAlert('Failed to cleanup duplicate transfers: ' + result.message, 'danger');
            }
        } catch (error) {
            console.error('Failed to cleanup duplicate transfers:', error);
            this.app.ui.showAlert('Failed to cleanup duplicate transfers', 'danger');
        }
    }
}
