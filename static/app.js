/**
 * DragonCP Web UI - Frontend JavaScript
 * Handles all UI interactions, API calls, and WebSocket communication
 */

class DragonCPUI {
    constructor() {
        this.socket = io({ autoConnect: true, reconnection: false });
        this.currentState = {
            connected: false,
            mediaType: null,
            selectedFolder: null,
            selectedSeason: null,
            breadcrumb: [],
            viewingSeasons: false,
            seasonsFolder: null,
            viewingTransferOptions: false
        };
        
        // Browse Media state
        this.currentMediaType = null;
        this.currentPath = [];
        this.transferLogs = [];
        this.autoScroll = true;
        this.currentTransferId = null;
        
        // Browse Media search and sort
        this.allFolders = []; // Store all folder data for filtering/sorting
        this.filteredFolders = []; // Store currently filtered/sorted folders
        this.searchTerm = '';
        this.sortOption = 'recent'; // 'recent' or 'alphabetical'
        
        // Tabbed transfer logs
        this.transferTabs = new Map(); // transferId -> { logs: [], autoScroll: boolean, transfer: {} }
        this.activeTabId = null;
        this.cachedActiveTransfers = [];
        
        // WebSocket timeout management
        this.websocketTimeout = 30 * 60 * 1000; // 30 minutes in milliseconds
        this.activityTimer = null;
        this.lastActivity = Date.now();
        this.isWebSocketConnected = false;
        this.wasAutoDisconnected = false;
        this.hasEverConnected = false;
        
        this.initializeEventListeners();
        this.initializeWebSocket();
        this.initializeActivityTracking();
        this.loadConfiguration();
        this.initializeConnection();
        this.initializeDiskUsageMonitoring();
        this.initializeTransferManagement();
        
        // Initialize collapsible cards functionality
        this.collapsedCards = new Set(); // Track collapsed cards
        this.initializeCollapsibleCards();
        
        // Handle window resize for tab scroll indicators
        window.addEventListener('resize', () => {
            this.updateTabScrollIndicators();
        });
    }

    initializeActivityTracking() {
        // Track intentional user interactions with UI elements only
        this.initializeUIElementTracking();

        // Optional: More conservative page visibility handling
        // Only extend session if user was away for a significant time (10+ minutes)
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden && this.isWebSocketConnected) {
                const timeSinceActivity = Date.now() - this.lastActivity;
                const minutesSinceActivity = timeSinceActivity / (60 * 1000);
                
                // Only extend if user was away for 10+ minutes
                if (minutesSinceActivity >= 10) {
                    console.log(`Page returned after ${minutesSinceActivity.toFixed(1)} minutes - extending session`);
                    this.updateActivity();
                } else {
                    console.log(`Page returned after ${minutesSinceActivity.toFixed(1)} minutes - no session extension needed`);
                }
            }
        });
        
        // Start activity monitoring
        this.startActivityMonitoring();
        
        // Start timer display updates
        this.startTimerDisplayUpdates();
    }

    initializeUIElementTracking() {
        // Track clicks on buttons and interactive elements (but exclude config and modal buttons)
        const trackClicksOn = [
            '.card.h-100:not(.disk-usage-card)', // Media type cards only (exclude disk usage cards)
            '.list-group-item button', // Folder/season navigation buttons
            '.transfer-item button', // Transfer action buttons
            'input[type="submit"]',
            'input[type="button"]'
        ];
        
        // Track specific buttons by ID (excluding config and modal buttons)
        const trackSpecificButtons = [
            '#autoConnectBtn',
            '#disconnectBtn',
            '#refreshDiskUsageBtn',
            '#refreshTransfersBtn', 
            '#showAllTransfersBtn',
            '#cleanupTransfersBtn',
            '#refreshAllTransfersBtn',
            '#clearLogBtn',
            '#autoScrollBtn',
            '#fullscreenLogBtn',
            '#closeFullscreenLog'
        ];
        
        // Track clicks on specific selectors
        trackClicksOn.forEach(selector => {
            document.addEventListener('click', (event) => {
                if (event.target.matches(selector) || event.target.closest(selector)) {
                    console.log(`Activity triggered by selector: ${selector}, element:`, event.target);
                    this.updateActivity();
                }
            });
        });
        
        // Track clicks on specific buttons by ID
        trackSpecificButtons.forEach(buttonId => {
            document.addEventListener('click', (event) => {
                if (event.target.matches(buttonId) || event.target.closest(buttonId)) {
                    console.log(`Activity triggered by button: ${buttonId}`);
                    this.updateActivity();
                }
            });
        });

        // Track form submissions and input interactions (meaningful typing)
        document.addEventListener('submit', () => {
            this.updateActivity();
        });

        // Track typing in input fields (debounced to avoid too frequent updates)
        // But exclude typing in config modal
        let typingTimer;
        document.addEventListener('keydown', (event) => {
            // Only count typing in input fields outside of modals
            if (event.target.matches('input[type="text"], input[type="password"], input[type="number"], textarea')) {
                // Check if the input is inside a modal
                const isInModal = event.target.closest('.modal');
                if (!isInModal) {
                    clearTimeout(typingTimer);
                    typingTimer = setTimeout(() => {
                        this.updateActivity();
                    }, 2000); // Update activity after 2 seconds of typing
                }
            }
        });

        // Track touch interactions for mobile (excluding config and modal buttons)
        document.addEventListener('touchstart', (event) => {
            const touchableSelectors = trackClicksOn.join(', ') + ', ' + trackSpecificButtons.join(', ');
            if (event.target.matches(touchableSelectors) || event.target.closest(touchableSelectors)) {
                this.updateActivity();
            }
        });
    }

    updateActivity() {
        // Only track activity if WebSocket is connected
        if (!this.isWebSocketConnected) {
            console.log('Activity ignored - WebSocket not connected');
            return;
        }
        
        console.log('Timer reset - activity detected');
        this.lastActivity = Date.now();
        
        // Reset the timer
        if (this.activityTimer) {
            clearTimeout(this.activityTimer);
        }
        
        // Send activity ping to server if WebSocket is connected
        if (this.isWebSocketConnected) {
            this.socket.emit('activity');
        }
        
        // Only restart timer if WebSocket is connected
        if (this.isWebSocketConnected) {
            this.startActivityTimer();
            // Update status display with new timer
            this.updateStatusWithTimer().catch(error => {
                console.warn('Failed to update status with timer:', error);
            });
        }
    }

    startActivityMonitoring() {
        // Check activity every minute
        setInterval(async () => {
            const timeSinceActivity = Date.now() - this.lastActivity;
            const timeUntilDisconnect = this.websocketTimeout - timeSinceActivity;
            
            // Show warning at 2 minutes before timeout
            if (timeUntilDisconnect <= 2 * 60 * 1000 && timeUntilDisconnect > 1 * 60 * 1000 && this.isWebSocketConnected) {
                // Check if transfers are active before showing warning
                const hasTransfers = await this.hasActiveTransfers();
                
                if (!hasTransfers) {
                    this.showWebSocketTimeoutWarning(Math.ceil(timeUntilDisconnect / 60000));
                } else {
                    // Don't show warning if transfers are protecting the session
                    console.log('Timeout warning skipped - active transfers are protecting the session');
                }
            }
        }, 60000); // Check every minute
    }

    startActivityTimer() {
        this.activityTimer = setTimeout(() => {
            this.handleWebSocketTimeout();
        }, this.websocketTimeout);
    }

    async handleWebSocketTimeout() {
        if (this.isWebSocketConnected) {
            // Check if there are active transfers before disconnecting
            const hasActiveTransfers = await this.hasActiveTransfers();
            
            if (hasActiveTransfers) {
                console.log('Timer expired but active transfers detected - session protected');
                this.showAlert('Session timeout prevented - active file transfers are protecting your connection', 'info');
                
                // Restart the timer for another cycle
                this.startActivityTimer();
                return;
            }
            
            console.log('WebSocket timeout due to inactivity');
            this.wasAutoDisconnected = true;
            this.disconnectWebSocket();
            this.showWebSocketTimeoutNotification();
        }
    }

    async hasActiveTransfers() {
        try {
            const response = await fetch('/api/transfers/active');
            const result = await response.json();
            
            if (result.status === 'success') {
                return result.transfers && result.transfers.length > 0;
            }
            return false;
        } catch (error) {
            console.error('Error checking active transfers:', error);
            return false; // Assume no transfers if check fails
        }
    }

    showWebSocketTimeoutWarning(minutesLeft) {
        this.showAlert(`Real-time connection will disconnect in ${minutesLeft} minute(s) due to inactivity. Click the status bar to extend your session and maintain full features.`, 'warning');
    }

    showWebSocketTimeoutNotification() {
        this.showAlert('App connection lost due to inactivity. Active transfers continue running automatically in the background. Click "Auto Connect" to restore real-time features.', 'info');
        
        // Update status to show auto-disconnected state
        this.updateStatus('Disconnected due to inactivity - background monitoring active', 'auto-disconnected');
        
        // Hide UI elements that depend on WebSocket
        this.hideWebSocketDependentUI();
        
        // Update config modal status
        this.updateWebSocketConfigStatus();
    }

    hideWebSocketDependentUI() {
        // Hide media interface when WebSocket is disconnected
        const elementsToHide = [
            'browseMediaCard',
            'transferCard',
            'logCard'
        ];
        
        elementsToHide.forEach(elementId => {
            const element = document.getElementById(elementId);
            if (element) {
                element.style.display = 'none';
            }
        });
        
        console.log('UI elements hidden - WebSocket dependent features disabled');
        
        // Show a brief explanation to the user
        setTimeout(() => {
            this.showAlert('Media browsing features temporarily disabled. Active transfers continue in the background. Reconnect to restore full functionality.', 'info');
        }, 1000);
    }

    showWebSocketDependentUI() {
        // Show media interface when WebSocket is connected
        const elementsToShow = [
            'browseMediaCard'
            // Other elements will be shown based on navigation state
        ];
        
        elementsToShow.forEach(elementId => {
            const element = document.getElementById(elementId);
            if (element) {
                element.style.display = 'block';
            }
        });
        
        console.log('UI elements restored - WebSocket dependent features enabled');
    }

    disconnectWebSocket() {
        if (this.socket && this.isWebSocketConnected) {
            console.log('Intentionally disconnecting WebSocket');
            // Prevent automatic reconnection
            this.socket.disconnect();
            this.isWebSocketConnected = false;
            
            // Stop activity tracking
            console.log('Activity tracking disabled - WebSocket intentionally disconnected');
            
            // Clear activity timer
            if (this.activityTimer) {
                clearTimeout(this.activityTimer);
                this.activityTimer = null;
            }
            
            // Hide WebSocket dependent UI elements
            this.hideWebSocketDependentUI();
        }
    }

    initializeEventListeners() {
        // Status bar buttons
        document.getElementById('autoConnectBtn').addEventListener('click', () => {
            this.autoConnect();
        });

        document.getElementById('disconnectBtn').addEventListener('click', () => {
            this.disconnectFromServer();
        });

        // Status bar click to extend session
        document.getElementById('statusBar').addEventListener('click', (event) => {
            // Only extend session if clicking the status area, not the buttons
            if (event.target.closest('.status-actions')) {
                return; // Don't interfere with button clicks
            }
            
            if (this.isWebSocketConnected) {
                this.extendSession();
            }
        });

        // Configuration button (no timer reset)
        document.getElementById('configBtn').addEventListener('click', () => {
            console.log('Config button clicked - timer NOT reset');
            const configModal = new bootstrap.Modal(document.getElementById('configModal'));
            configModal.show();
            
            // Update WebSocket status when modal is shown (read-only, no timer reset)
            setTimeout(() => {
                this.updateWebSocketConfigStatusReadOnly();
            }, 100);
        });

        // Configuration modal
        document.getElementById('saveConfig').addEventListener('click', () => {
            console.log('Save config button clicked - timer NOT reset');
            this.saveConfiguration();
        });

        document.getElementById('resetConfigBtn').addEventListener('click', () => {
            console.log('Reset config button clicked - timer NOT reset');
            this.resetConfiguration();
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

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            // ESC key to close fullscreen log
            if (e.key === 'Escape') {
                const fullscreenModal = document.getElementById('fullscreenLogModal');
                if (fullscreenModal.classList.contains('show')) {
                    this.hideFullscreenLog();
                }
            }
            
            // Ctrl/Cmd + L to toggle auto-scroll
            if ((e.ctrlKey || e.metaKey) && e.key === 'l') {
                e.preventDefault();
                this.toggleAutoScroll();
            }
            
            // Ctrl/Cmd + K to clear logs
            if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
                e.preventDefault();
                this.clearTransferLog();
            }
        });

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

        // Add input change listeners for config fields
        this.addConfigFieldListeners();

        // Browse Media search and sort controls
        document.getElementById('folderSearchInput').addEventListener('input', (e) => {
            this.searchTerm = e.target.value.toLowerCase().trim();
            this.filterAndSortFolders();
            this.updateClearSearchButton();
        });

        document.getElementById('clearSearchBtn').addEventListener('click', () => {
            document.getElementById('folderSearchInput').value = '';
            this.searchTerm = '';
            this.filterAndSortFolders();
            this.updateClearSearchButton();
        });

        document.getElementById('folderSortSelect').addEventListener('change', (e) => {
            this.sortOption = e.target.value;
            this.filterAndSortFolders();
        });

        // Refresh Sync Status button
        document.getElementById('refreshSyncStatusBtn').addEventListener('click', async () => {
            const button = document.getElementById('refreshSyncStatusBtn');
            const icon = button.querySelector('i');
            
            // Check if sync status is already loading
            if (this.allFolders && this.allFolders.some(folder => folder.syncStatus && folder.syncStatus.status === 'LOADING')) {
                console.log('Sync status already loading, ignoring refresh request');
                return;
            }
            
            // Check if button is already disabled/refreshing
            if (button.disabled || button.classList.contains('refreshing')) {
                console.log('Refresh button already in progress, ignoring request');
                return;
            }
            
            // Add loading state with smooth animation
            button.disabled = true;
            button.classList.add('refreshing');
            
            // Reset icon classes and add spinning
            icon.className = 'bi bi-arrow-clockwise spinning';
            
            // Debug log to ensure classes are applied
            console.log('Refresh button spinning - Button classes:', button.className);
            console.log('Refresh button spinning - Icon classes:', icon.className);
            
            // First set all current sync statuses to loading
            if (this.allFolders) {
                this.allFolders = this.allFolders.map(folder => ({
                    ...folder,
                    syncStatus: { ...folder.syncStatus, status: 'LOADING' }
                }));
                this.filterAndSortFolders(); // Re-render with loading states
                this.updateRefreshButtonState(); // Update button state
            }
            
            try {
                await this.refreshSyncStatus();
                
                // Show success animation
                console.log('Refresh success - stopping spinner');
                icon.className = 'bi bi-check-circle-fill';
                button.classList.add('success');
                
                setTimeout(() => {
                    icon.className = 'bi bi-arrow-clockwise';
                    button.classList.remove('success');
                    console.log('Success animation complete');
                }, 1500);
            } catch (error) {
                console.error('Failed to refresh sync status:', error);
                
                // Show error animation
                console.log('Refresh error - stopping spinner');
                icon.className = 'bi bi-exclamation-triangle-fill';
                button.classList.add('error');
                
                setTimeout(() => {
                    icon.className = 'bi bi-arrow-clockwise';
                    button.classList.remove('error');
                    console.log('Error animation complete');
                }, 1500);
            } finally {
                button.disabled = false;
                button.classList.remove('refreshing');
            }
        });

        // Collapse All button
        document.getElementById('collapseAllBtn').addEventListener('click', () => {
            const button = document.getElementById('collapseAllBtn');
            const icon = button.querySelector('i');
            const textSpan = button.querySelector('span');
            
            if (button.classList.contains('collapsed')) {
                // Currently collapsed, expand all
                this.expandAllCards();
                button.classList.remove('collapsed');
                icon.className = 'bi bi-chevron-up';
                textSpan.textContent = ' Collapse All';
            } else {
                // Currently expanded, collapse all
                this.collapseAllExcept();
                button.classList.add('collapsed');
                icon.className = 'bi bi-chevron-down';
                textSpan.textContent = ' Expand All';
            }
        });


    }

    extendSession() {
        this.showAlert('Session extended successfully!', 'success');
        
        // Add visual feedback animation
        const statusBar = document.getElementById('statusBar');
        if (statusBar) {
            statusBar.classList.add('session-extended');
            setTimeout(() => {
                statusBar.classList.remove('session-extended');
            }, 600);
        }
        
        this.updateActivity(); // This will reset the timer and update the display
    }

    updateWebSocketConfigStatusReadOnly() {
        // Same as updateWebSocketConfigStatus but doesn't reset activity timer
        // This is used when opening config modal to check status without extending session
        const statusIndicator = document.getElementById('wsConfigStatusIndicator');
        const statusText = document.getElementById('wsConfigStatusText');
        const statusDetails = document.getElementById('wsConfigStatusDetails');
        
        if (!statusIndicator || !statusText || !statusDetails) return;
        
        // Check if we're in config-changed state
        const currentStatus = document.getElementById('statusIndicator')?.className;
        const isConfigChanged = currentStatus?.includes('status-config-changed');
        
        if (isConfigChanged) {
            statusIndicator.className = 'status-indicator status-config-changed';
            statusText.textContent = 'Configuration Updated';
            statusDetails.innerHTML = `
                <i class="bi bi-exclamation-triangle"></i> 
                Settings changed. Click "Apply New Settings" to reconnect with updated configuration.
            `;
        } else if (this.isWebSocketConnected) {
            statusIndicator.className = 'status-indicator status-connected';
            statusText.textContent = 'Connected';
            
            const timeoutMinutes = Math.floor(this.websocketTimeout / 60000);
            // Use the same calculation as status bar for consistency
            const timeLeft = this.getTimeRemaining();
            
            statusDetails.innerHTML = `
                <i class="bi bi-check-circle"></i> 
                Real-time updates active. Timeout: ${timeoutMinutes} min. 
                Time left: ${timeLeft} min.
            `;
        } else if (this.wasAutoDisconnected) {
            statusIndicator.className = 'status-indicator status-auto-disconnected';
            statusText.textContent = 'Auto-disconnected';
            statusDetails.innerHTML = `
                <i class="bi bi-clock"></i> 
                Disconnected due to inactivity. Active transfers continue via background API monitoring.
            `;
        } else {
            statusIndicator.className = 'status-indicator status-disconnected';
            statusText.textContent = 'Disconnected';
            statusDetails.innerHTML = `
                <i class="bi bi-x-circle"></i> 
                App connection not active. Click "Auto Connect" for real-time updates and full features.
            `;
        }
    }

    addConfigFieldListeners() {
        // Add listeners to all config input fields to show modification indicators
        const configInputs = document.querySelectorAll('#configForm input');
        configInputs.forEach(input => {
            input.addEventListener('input', () => {
                this.updateConfigFieldIndicator(input);
                
                // Special handling for timeout validation
                if (input.id === 'websocketTimeout') {
                    this.validateTimeoutInput(input);
                }
            });
        });
    }

    validateTimeoutInput(input) {
        const value = parseInt(input.value);
        const validationDiv = document.getElementById('timeoutValidation') || this.createTimeoutValidationDiv(input);
        
        if (isNaN(value)) {
            validationDiv.style.display = 'none';
            return;
        }
        
        if (value > 60) {
            validationDiv.innerHTML = `
                <div class="text-warning">
                    <i class="bi bi-exclamation-triangle"></i> 
                    Maximum timeout is 60 minutes. Value will be capped at 60 minutes.
                </div>
            `;
            validationDiv.style.display = 'block';
        } else if (value < 5) {
            validationDiv.innerHTML = `
                <div class="text-warning">
                    <i class="bi bi-exclamation-triangle"></i> 
                    Minimum timeout is 5 minutes. Value will be set to 5 minutes.
                </div>
            `;
            validationDiv.style.display = 'block';
        } else {
            validationDiv.style.display = 'none';
        }
    }

    createTimeoutValidationDiv(input) {
        const validationDiv = document.createElement('div');
        validationDiv.id = 'timeoutValidation';
        validationDiv.className = 'mt-1';
        validationDiv.style.display = 'none';
        
        // Insert after the input's parent config-field div
        const configField = input.closest('.config-field');
        configField.appendChild(validationDiv);
        
        return validationDiv;
    }

    updateConfigFieldIndicator(input) {
        const fieldId = input.id;
        const indicator = document.getElementById(fieldId + 'Indicator');
        const originalValue = document.getElementById(fieldId + 'Original');
        
        if (indicator && originalValue) {
            const currentValue = input.value;
            const originalText = originalValue.textContent.replace('Original: ', '');
            
            if (currentValue !== originalText) {
                indicator.style.display = 'block';
                input.classList.add('border-warning');
            } else {
                indicator.style.display = 'none';
                input.classList.remove('border-warning');
            }
        }
    }

    initializeWebSocket() {
        this.socket.on('connect', () => {
            console.log('WebSocket connected');
            this.isWebSocketConnected = true;
            this.wasAutoDisconnected = false;
            this.hasEverConnected = true;
            
            // Start activity tracking now that WebSocket is connected
            this.updateActivity(); // Start activity tracking
            console.log('Activity tracking enabled');
            
            this.updateWebSocketConfigStatus(); // Update config modal status
            
            // Show WebSocket dependent UI elements if server connection exists
            if (this.currentState.connected) {
                this.showWebSocketDependentUI();
            }
            
            // Immediately show timer in status
            setTimeout(() => {
                this.updateStatusWithTimer().catch(error => {
                    console.warn('Failed to update status with timer:', error);
                });
            }, 100);
        });

        this.socket.on('transfer_progress', (data) => {
            this.updateTransferProgress(data);
            // Refresh transfer management display for progress bars
            this.loadActiveTransfers();
            // Don't count transfer progress as user activity
        });

        this.socket.on('transfer_complete', (data) => {
            this.handleTransferComplete(data);
            // Refresh transfer management display
            this.loadActiveTransfers();
            // Don't count transfer completion as user activity
        });

        this.socket.on('disconnect', (reason) => {
            console.log('WebSocket disconnected:', reason);
            this.isWebSocketConnected = false;
            
            // Stop activity tracking
            console.log('Activity tracking disabled - WebSocket disconnected');
            
            // Clear activity timer
            if (this.activityTimer) {
                clearTimeout(this.activityTimer);
                this.activityTimer = null;
            }
            
            // Hide WebSocket dependent UI elements on unexpected disconnect
            if (!this.wasAutoDisconnected && reason !== 'io client disconnect') {
                this.hideWebSocketDependentUI();
                this.updateStatus('Connection lost unexpectedly', 'disconnected');
            }
            
            // Update config modal status
            this.updateWebSocketConfigStatus();
            
            // Only show reconnection message if it wasn't an auto-disconnect
            if (!this.wasAutoDisconnected) {
                console.log('WebSocket disconnected unexpectedly');
            }
        });
    }

    async loadConfiguration() {
        try {
            this.updateStatus('Loading configuration...', 'connecting');
            
            // Load all configuration (env + session overrides)
            const response = await fetch('/api/config');
            const config = await response.json();
            
            // Load environment-only config for comparison
            const envResponse = await fetch('/api/config/env-only');
            const envConfig = await envResponse.json();
            
            // Populate all form fields with current config values
            this.populateConfigFields(config, envConfig);
            
            this.updateStatus('Configuration loaded', 'disconnected');
            
        } catch (error) {
            console.error('Failed to load configuration:', error);
            this.updateStatus('Failed to load configuration', 'disconnected');
        }
    }
    
    populateConfigFields(config, envConfig) {
        // Define all possible configuration fields with their display info
        const configFields = [
            // SSH credentials
            { id: 'remoteIp', name: 'REMOTE_IP', label: 'Server Host/IP', value: config.REMOTE_IP, envValue: envConfig.REMOTE_IP, placeholder: '192.168.1.100' },
            { id: 'remoteUser', name: 'REMOTE_USER', label: 'Username', value: config.REMOTE_USER, envValue: envConfig.REMOTE_USER, placeholder: 'username' },
            { id: 'remotePassword', name: 'REMOTE_PASSWORD', label: 'Password (optional)', value: config.REMOTE_PASSWORD, envValue: envConfig.REMOTE_PASSWORD, type: 'password', placeholder: 'Leave empty if using SSH key' },
            { id: 'sshKeyPath', name: 'SSH_KEY_PATH', label: 'SSH Key Path (optional)', value: config.SSH_KEY_PATH, envValue: envConfig.SSH_KEY_PATH, placeholder: '/path/to/private/key' },
            
            // Media paths
            { id: 'moviePath', name: 'MOVIE_PATH', label: 'Movie Path', value: config.MOVIE_PATH, envValue: envConfig.MOVIE_PATH, placeholder: '/path/to/movies' },
            { id: 'tvshowPath', name: 'TVSHOW_PATH', label: 'TV Show Path', value: config.TVSHOW_PATH, envValue: envConfig.TVSHOW_PATH, placeholder: '/path/to/tvshows' },
            { id: 'animePath', name: 'ANIME_PATH', label: 'Anime Path', value: config.ANIME_PATH, envValue: envConfig.ANIME_PATH, placeholder: '/path/to/anime' },
            { id: 'backupPath', name: 'BACKUP_PATH', label: 'Backup Path', value: config.BACKUP_PATH, envValue: envConfig.BACKUP_PATH, placeholder: '/path/to/backup' },
            
            // Destination paths
            { id: 'movieDestPath', name: 'MOVIE_DEST_PATH', label: 'Movie Destination', value: config.MOVIE_DEST_PATH, envValue: envConfig.MOVIE_DEST_PATH, placeholder: '/local/path/to/movies' },
            { id: 'tvshowDestPath', name: 'TVSHOW_DEST_PATH', label: 'TV Show Destination', value: config.TVSHOW_DEST_PATH, envValue: envConfig.TVSHOW_DEST_PATH, placeholder: '/local/path/to/tvshows' },
            { id: 'animeDestPath', name: 'ANIME_DEST_PATH', label: 'Anime Destination', value: config.ANIME_DEST_PATH, envValue: envConfig.ANIME_DEST_PATH, placeholder: '/local/path/to/anime' },
            
            // Disk monitoring paths
            { id: 'diskPath1', name: 'DISK_PATH_1', label: 'Disk Path 1', value: config.DISK_PATH_1, envValue: envConfig.DISK_PATH_1, placeholder: '/path/to/disk1' },
            { id: 'diskPath2', name: 'DISK_PATH_2', label: 'Disk Path 2', value: config.DISK_PATH_2, envValue: envConfig.DISK_PATH_2, placeholder: '/path/to/disk2' },
            { id: 'diskPath3', name: 'DISK_PATH_3', label: 'Disk Path 3', value: config.DISK_PATH_3, envValue: envConfig.DISK_PATH_3, placeholder: '/path/to/disk3' },
            
            // Remote disk monitoring API
            { id: 'diskApiEndpoint', name: 'DISK_API_ENDPOINT', label: 'Remote Disk API Endpoint', value: config.DISK_API_ENDPOINT, envValue: envConfig.DISK_API_ENDPOINT, placeholder: 'https://api.example.com/disk-usage' },
            { id: 'diskApiToken', name: 'DISK_API_TOKEN', label: 'Remote Disk API Token', value: config.DISK_API_TOKEN, envValue: envConfig.DISK_API_TOKEN, type: 'password', placeholder: 'Bearer token for remote API' },
            
            // WebSocket settings
            { id: 'websocketTimeout', name: 'WEBSOCKET_TIMEOUT_MINUTES', label: 'WebSocket Timeout (minutes)', value: Math.min(60, Math.max(5, config.WEBSOCKET_TIMEOUT_MINUTES || 30)), envValue: Math.min(60, Math.max(5, envConfig.WEBSOCKET_TIMEOUT_MINUTES || 30)), type: 'number', placeholder: '30' }
        ];
        
        // Populate each field
        configFields.forEach(field => {
            const input = document.getElementById(field.id);
            const indicator = document.getElementById(field.id + 'Indicator');
            const original = document.getElementById(field.id + 'Original');
            
            if (input) {
                input.value = field.value || '';
                input.placeholder = field.placeholder || '';
                
                // Update modification indicators
                if (indicator && original) {
                    const isModified = field.value !== field.envValue;
                    if (isModified) {
                        indicator.style.display = 'block';
                        input.classList.add('border-warning');
                        original.textContent = `Original: ${field.envValue || 'Not set'}`;
                        original.style.display = 'block';
                    } else {
                        indicator.style.display = 'none';
                        input.classList.remove('border-warning');
                        original.style.display = 'none';
                    }
                }
            }
        });
        
        // Update WebSocket timeout setting and apply it
        const timeoutMinutes = Math.min(60, Math.max(5, parseInt(config.WEBSOCKET_TIMEOUT_MINUTES || 30)));
        this.websocketTimeout = timeoutMinutes * 60 * 1000; // Convert to milliseconds
        
        // Update WebSocket status display in configuration modal
        this.updateWebSocketConfigStatus();
    }
    
    async resetConfiguration() {
        try {
            this.updateStatus('Resetting configuration...', 'connecting');
            
            const response = await fetch('/api/config/reset', {
                method: 'POST'
            });
            
            const result = await response.json();
            
            if (result.status === 'success') {
                this.showAlert('Configuration reset to environment values', 'success');
                await this.loadConfiguration();
                
                // Re-initialize connection with reset values
                await this.initializeConnection();
            } else {
                this.showAlert('Failed to reset configuration', 'danger');
                this.updateStatus('Failed to reset configuration', 'disconnected');
            }
        } catch (error) {
            console.error('Failed to reset configuration:', error);
            this.showAlert('Failed to reset configuration', 'danger');
            this.updateStatus('Failed to reset configuration', 'disconnected');
        }
    }

    async saveConfiguration() {
        try {
            this.updateStatus('Saving configuration...', 'connecting');
            
            const formData = new FormData(document.getElementById('configForm'));
            const config = {};
            
            for (let [key, value] of formData.entries()) {
                config[key] = value;
            }

            const response = await fetch('/api/config', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(config)
            });

            const result = await response.json();
            
            if (result.status === 'success') {
                // Determine if critical config changes were made
                const hasCriticalChanges = this.hasCriticalConfigChanges(config);
                
                // Apply WebSocket timeout change
                let timeoutChanged = false;
                if (config.WEBSOCKET_TIMEOUT_MINUTES) {
                    const newTimeoutMinutes = Math.min(60, Math.max(5, parseInt(config.WEBSOCKET_TIMEOUT_MINUTES)));
                    const newTimeoutMs = newTimeoutMinutes * 60 * 1000;
                    
                    if (newTimeoutMs !== this.websocketTimeout) {
                        this.websocketTimeout = newTimeoutMs;
                        timeoutChanged = true;
                    }
                }
                
                this.showAlert('Configuration saved successfully!', 'success');
                
                // If critical changes were made, disconnect and show reconnect UI
                if (hasCriticalChanges || timeoutChanged) {
                    this.handleCriticalConfigChange();
                } else {
                    this.updateStatus('Configuration saved', 'disconnected');
                    
                    // Reload configuration to update indicators
                    await this.loadConfiguration();
                    
                    // Check if we have connection credentials and show auto-connect option
                    if (this.hasConnectionCredentials()) {
                        this.showAutoConnectOption();
                    }
                }
            } else {
                this.showAlert('Failed to save configuration', 'danger');
                this.updateStatus('Failed to save configuration', 'disconnected');
            }
        } catch (error) {
            console.error('Failed to save configuration:', error);
            this.showAlert('Failed to save configuration', 'danger');
            this.updateStatus('Failed to save configuration', 'disconnected');
        }
    }

    hasCriticalConfigChanges(newConfig) {
        // Define which config changes require reconnection
        const criticalFields = [
            'REMOTE_IP', 'REMOTE_USER', 'REMOTE_PASSWORD', 'SSH_KEY_PATH',
            'WEBSOCKET_TIMEOUT_MINUTES'
        ];
        
        // Check if any critical field was modified
        return criticalFields.some(field => {
            const currentValue = this.getCurrentConfigValue(field);
            const newValue = newConfig[field];
            return currentValue !== newValue;
        });
    }

    getCurrentConfigValue(fieldName) {
        // Map field names to their corresponding input IDs
        const fieldMap = {
            'REMOTE_IP': 'remoteIp',
            'REMOTE_USER': 'remoteUser', 
            'REMOTE_PASSWORD': 'remotePassword',
            'SSH_KEY_PATH': 'sshKeyPath',
            'WEBSOCKET_TIMEOUT_MINUTES': 'websocketTimeout'
        };
        
        const inputId = fieldMap[fieldName];
        const input = document.getElementById(inputId);
        return input ? input.defaultValue : '';
    }

    handleCriticalConfigChange() {
        // Disconnect WebSocket if connected
        if (this.isWebSocketConnected) {
            this.disconnectWebSocket();
        }
        
        // Close the configuration modal
        const configModal = bootstrap.Modal.getInstance(document.getElementById('configModal'));
        if (configModal) {
            configModal.hide();
        }
        
        // Update status to show config-changed state
        this.updateStatus('Configuration updated - reconnection required', 'config-changed');
        
        // Show reconnect notification
        this.showAlert('Configuration changes saved! Please reconnect to apply the new settings.', 'info');
        
        // Hide media interface (already done by disconnectWebSocket)
        
        // Update button to show "Load Updated Config" or similar
        this.showConfigChangedUI();
    }

    showConfigChangedUI() {
        const autoConnectBtn = document.getElementById('autoConnectBtn');
        if (autoConnectBtn) {
            autoConnectBtn.style.display = 'inline-block';
            autoConnectBtn.innerHTML = '<i class="bi bi-arrow-repeat"></i> Apply New Settings';
            autoConnectBtn.title = 'Reconnect with updated configuration';
            autoConnectBtn.classList.add('btn-warning');
            autoConnectBtn.classList.remove('btn-primary');
        }
    }

    async autoConnect() {
        try {
            this.updateStatus('Connecting to server...', 'connecting');
            
            // If we have a disconnected WebSocket, reconnect it
            if (!this.isWebSocketConnected) {
                this.socket.connect();
            }
            
            const response = await fetch('/api/auto-connect');
            const result = await response.json();
            
            if (result.status === 'success') {
                this.currentState.connected = true;
                
                // Reset auto-disconnect and config-changed flags
                this.wasAutoDisconnected = false;
                
                // Reload configuration to ensure we have the latest values
                await this.loadConfiguration();
                
                // Wait a moment for WebSocket to establish connection before showing timer
                // The WebSocket 'connect' event handler will call updateStatusWithTimer()
                this.updateStatus('Connected to server', 'connected');
                
                // Show WebSocket dependent UI elements
                this.showWebSocketDependentUI();
                this.showMediaInterface();
                this.loadMediaTypes();
                
                this.showAlert('Connected with updated configuration!', 'success');
            } else {
                this.updateStatus('Connection failed: ' + result.message, 'disconnected');
                this.showAlert('Auto-connection failed: ' + result.message, 'danger');
            }
        } catch (error) {
            console.error('Auto-connection failed:', error);
            this.updateStatus('Auto-connection failed', 'disconnected');
            this.showAlert('Auto-connection failed', 'danger');
        }
    }

    async disconnectFromServer() {
        try {
            // Disconnect WebSocket first
            this.disconnectWebSocket();
            
            // Then disconnect from SSH server
            const response = await fetch('/api/disconnect');
            const result = await response.json();
            
            if (result.status === 'success') {
                this.updateStatus('Disconnected from server', 'disconnected');
                this.currentState.connected = false;
                this.hideMediaInterface();
                this.wasAutoDisconnected = false;
            }
        } catch (error) {
            console.error('Disconnect failed:', error);
        }
    }

    updateStatus(message, status) {
        const statusIndicator = document.getElementById('statusIndicator');
        const statusMessage = document.getElementById('statusMessage');
        const autoConnectBtn = document.getElementById('autoConnectBtn');
        const disconnectBtn = document.getElementById('disconnectBtn');
        const statusBar = document.getElementById('statusBar');
        
        // Update status indicator
        if (statusIndicator) {
            statusIndicator.className = 'status-indicator';
            if (status === 'connected') {
                statusIndicator.classList.add('status-connected');
            } else if (status === 'connecting') {
                statusIndicator.classList.add('status-connecting');
            } else if (status === 'auto-disconnected') {
                statusIndicator.classList.add('status-auto-disconnected');
            } else if (status === 'config-changed') {
                statusIndicator.classList.add('status-config-changed');
            } else {
                statusIndicator.classList.add('status-disconnected');
            }
        }
        
        // Update message
        if (statusMessage) {
            statusMessage.textContent = message;
        }
        
        // Update status bar clickability and tooltip
        if (statusBar) {
            if (status === 'connected') {
                statusBar.classList.add('status-extendable');
                statusBar.title = 'Click to extend session timer';
            } else {
                statusBar.classList.remove('status-extendable');
                statusBar.title = '';
            }
        }
        
        // Update buttons
        if (autoConnectBtn && disconnectBtn) {
            if (status === 'connected') {
                autoConnectBtn.style.display = 'none';
                disconnectBtn.style.display = 'inline-block';
                // Show manual disconnect option for WebSocket only
                disconnectBtn.title = 'Disconnect App Connection (transfers will continue via API)';
            } else if (status === 'connecting') {
                autoConnectBtn.style.display = 'none';
                disconnectBtn.style.display = 'none';
            } else {
                autoConnectBtn.style.display = 'inline-block';
                disconnectBtn.style.display = 'none';
                
                // Reset button styling if it was changed for config updates
                autoConnectBtn.classList.remove('btn-warning');
                autoConnectBtn.classList.add('btn-primary');
                
                if (status === 'auto-disconnected') {
                    autoConnectBtn.innerHTML = '<i class="bi bi-arrow-clockwise"></i> Reconnect';
                    autoConnectBtn.title = 'Reconnect for real-time updates';
                } else if (status === 'config-changed') {
                    // Keep the special config-changed button styling
                    autoConnectBtn.classList.remove('btn-primary');
                    autoConnectBtn.classList.add('btn-warning');
                    autoConnectBtn.innerHTML = '<i class="bi bi-arrow-repeat"></i> Apply New Settings';
                    autoConnectBtn.title = 'Reconnect with updated configuration';
                } else {
                    autoConnectBtn.innerHTML = '<i class="bi bi-wifi"></i> Auto Connect';
                    autoConnectBtn.title = 'Connect to server';
                }
            }
        }
    }

    showAutoConnectOption() {
        const autoConnectBtn = document.getElementById('autoConnectBtn');
        if (this.hasConnectionCredentials()) {
            autoConnectBtn.style.display = 'inline-block';
        }
    }

    hasConnectionCredentials() {
        const host = document.getElementById('remoteIp')?.value;
        const username = document.getElementById('remoteUser')?.value;
        return host && username;
    }

    async loadMediaTypes() {
        try {
            const response = await fetch('/api/media-types');
            const mediaTypes = await response.json();
            
            // Handle both direct array response and status-wrapped response
            if (Array.isArray(mediaTypes)) {
                this.renderMediaTypes(mediaTypes);
            } else if (mediaTypes.status === 'success' && mediaTypes.data) {
                this.renderMediaTypes(mediaTypes.data);
            } else {
                this.showAlert('Failed to load media types', 'danger');
            }
        } catch (error) {
            console.error('Failed to load media types:', error);
            this.showAlert('Failed to load media types', 'danger');
        }
    }

    renderMediaTypes(mediaTypes) {
        const container = document.getElementById('mediaTypes');
        container.innerHTML = '';

        mediaTypes.forEach(mediaType => {
            const col = document.createElement('div');
            col.className = 'col-md-4 mb-3';
            
            col.innerHTML = `
                <div class="card h-100 media-type-card-custom" onclick="dragonCP.selectMediaType('${mediaType.id}')">
                    <div class="card-body text-center">
                        <i class="bi bi-${this.getMediaIcon(mediaType.id)} media-type-icon"></i>
                        <h5 class="card-title mt-3">${mediaType.name}</h5>
                    </div>
                </div>
            `;
            
            container.appendChild(col);
        });
    }

    getMediaIcon(mediaType) {
        const icons = {
            'movies': 'film',
            'tvshows': 'tv',
            'anime': 'collection-play'
        };
        return icons[mediaType] || 'folder';
    }

    async selectMediaType(mediaType) {
        this.currentState.mediaType = mediaType;
        this.currentState.breadcrumb = [mediaType];
        this.currentPath = [];
        
        // Reset navigation state when switching media types
        this.currentState.viewingSeasons = false;
        this.currentState.seasonsFolder = null;
        this.currentState.viewingTransferOptions = false;
        this.currentState.selectedFolder = null;
        this.currentState.selectedSeason = null;
        
        // Transition to folder browser view
        this.showFolderBrowserView(mediaType);
        
        // Load folders for this media type
        await this.loadFolders(mediaType);
    }

    getMediaDisplayName(mediaType) {
        const displayNames = {
            'movies': 'Movies',
            'tvshows': 'TV Shows', 
            'anime': 'Anime',
            'backup': 'Backup'
        };
        return displayNames[mediaType] || mediaType.charAt(0).toUpperCase() + mediaType.slice(1);
    }

    async loadFolders(mediaType, folderPath = '') {
        try {
            this.showFolderLoading(true);
            
            let url = `/api/folders/${mediaType}`;
            if (folderPath) {
                url += `?path=${encodeURIComponent(folderPath)}`;
            }
            
            // Load folders immediately without waiting for sync status
            const foldersResponse = await fetch(url);
            const foldersResult = await foldersResponse.json();
            
            if (foldersResult.status === 'success') {
                // Display folders immediately with loading sync status
                const foldersWithLoadingSyncStatus = foldersResult.folders.map(folder => {
                    return {
                        ...(typeof folder === 'object' ? folder : { name: folder, modification_time: 0 }),
                        syncStatus: { status: 'LOADING', type: 'unknown' }
                    };
                });
                
                this.renderFolders(foldersWithLoadingSyncStatus, mediaType);
                this.showFolderLoading(false);
                
                // Load sync status asynchronously and update UI
                this.loadSyncStatusAsync(mediaType);
                
            } else {
                this.showAlert(foldersResult.message || 'Failed to load folders', 'danger');
                this.showFolderLoading(false);
            }
        } catch (error) {
            console.error('Failed to load folders:', error);
            this.showAlert('Failed to load folders', 'danger');
            this.showFolderLoading(false);
        }
    }

    renderFolders(folders, mediaType) {
        // Store all folders data for filtering/sorting
        this.allFolders = folders.map(folder => {
            // Handle both old format (string) and new format (object)
            if (typeof folder === 'string') {
                return { name: folder, modification_time: 0 };
            }
            return folder;
        });
        
        this.currentMediaType = mediaType;
        this.filterAndSortFolders();
    }

    filterAndSortFolders() {
        if (!this.allFolders || this.allFolders.length === 0) {
            this.displayFolders([]);
            return;
        }

        // Filter folders based on search term
        let filtered = this.allFolders;
        if (this.searchTerm) {
            filtered = this.allFolders.filter(folder => 
                folder.name.toLowerCase().includes(this.searchTerm)
            );
        }

        // Sort folders based on selected option
        filtered = [...filtered]; // Create copy to avoid mutating original
        if (this.sortOption === 'alphabetical') {
            filtered.sort((a, b) => a.name.localeCompare(b.name));
        } else if (this.sortOption === 'recent') {
            filtered.sort((a, b) => b.modification_time - a.modification_time);
        }

        this.filteredFolders = filtered;
        this.displayFolders(filtered);
        this.updateFolderCount(filtered.length, this.allFolders.length);
        this.showBrowseControls();
    }

    displayFolders(folders) {
        const container = document.getElementById('folderList');
        container.innerHTML = '';

        if (folders.length === 0) {
            const message = this.searchTerm ? 
                `No folders found matching "${this.searchTerm}"` : 
                'No folders found';
            container.innerHTML = `<div class="text-center text-muted p-3">${message}</div>`;
            return;
        }

        folders.forEach((folder) => {
            const item = document.createElement('div');
            item.className = 'list-group-item d-flex justify-content-between align-items-center';
            
            // Create date string for recently modified folders
            let dateInfo = '';
            if (folder.modification_time > 0 && this.sortOption === 'recent') {
                const date = new Date(folder.modification_time * 1000);
                const now = new Date();
                const diffTime = now - date;
                const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));
                
                if (diffDays === 0) {
                    dateInfo = ' <small class="text-muted">(Today)</small>';
                } else if (diffDays === 1) {
                    dateInfo = ' <small class="text-muted">(Yesterday)</small>';
                } else if (diffDays < 7) {
                    dateInfo = ` <small class="text-muted">(${diffDays} days ago)</small>`;
                } else if (diffDays < 30) {
                    const weeks = Math.floor(diffDays / 7);
                    dateInfo = ` <small class="text-muted">(${weeks} week${weeks > 1 ? 's' : ''} ago)</small>`;
                } else {
                    dateInfo = ` <small class="text-muted">(${date.toLocaleDateString()})</small>`;
                }
            }
            
            // Generate sync status badge
            const syncStatusBadge = this.generateSyncStatusBadge(folder.syncStatus);
            
            item.innerHTML = `
                <div class="d-flex align-items-center flex-grow-1">
                    <i class="bi bi-folder me-2"></i>
                    <div class="flex-grow-1">
                        <div class="d-flex align-items-center gap-2">
                            <span>${this.escapeHtml(folder.name)}</span>
                            ${syncStatusBadge}
                        </div>
                        ${dateInfo ? `<div>${dateInfo}</div>` : ''}
                    </div>
                </div>
                <div class="btn-group btn-group-sm">
                    <button class="btn btn-outline-primary" onclick="dragonCP.selectFolder('${this.escapeJavaScriptString(folder.name)}', '${this.currentMediaType}')">
                        <i class="bi bi-arrow-right"></i>
                    </button>
                </div>
            `;
            
            container.appendChild(item);
        });
    }

    updateFolderCount(filteredCount, totalCount) {
        const countElement = document.getElementById('folderCount');
        if (countElement) {
            if (filteredCount === totalCount) {
                countElement.textContent = `${totalCount} folder${totalCount !== 1 ? 's' : ''}`;
            } else {
                countElement.textContent = `${filteredCount} of ${totalCount} folder${totalCount !== 1 ? 's' : ''}`;
            }
        }
    }

    updateClearSearchButton() {
        const clearBtn = document.getElementById('clearSearchBtn');
        if (clearBtn) {
            clearBtn.style.display = this.searchTerm ? 'block' : 'none';
        }
    }

    showBrowseControls() {
        const controlsElement = document.getElementById('browseControls');
        if (controlsElement && this.allFolders.length > 0) {
            controlsElement.style.display = 'block';
        }
    }

    hideBrowseControls() {
        const controlsElement = document.getElementById('browseControls');
        if (controlsElement) {
            controlsElement.style.display = 'none';
        }
        // Also clear search state
        this.searchTerm = '';
        this.sortOption = 'recent';
        document.getElementById('folderSearchInput').value = '';
        document.getElementById('folderSortSelect').value = 'recent';
        this.updateClearSearchButton();
    }

    async selectFolder(folderName, mediaType) {
        this.currentState.selectedFolder = folderName;
        this.currentState.breadcrumb.push(folderName);
        
        // Check if this is a TV show or anime (has seasons)
        if (mediaType === 'tvshows' || mediaType === 'anime') {
            await this.loadSeasons(mediaType, folderName);
        } else {
            // For movies, show transfer options directly
            this.showTransferOptions(mediaType, folderName);
        }
        
        this.updateBrowseMediaBreadcrumb();
    }

    async loadSeasons(mediaType, folderName) {
        try {
            this.showFolderLoading(true);
            
            // Load seasons immediately without waiting for sync status
            const seasonsResponse = await fetch(`/api/seasons/${mediaType}/${encodeURIComponent(folderName)}`);
            const seasonsResult = await seasonsResponse.json();
            
            if (seasonsResult.status === 'success') {
                // Display seasons immediately with loading sync status
                const seasonsWithLoadingSyncStatus = seasonsResult.seasons.map(season => {
                    return {
                        ...(typeof season === 'object' ? season : { name: season, modification_time: 0 }),
                        syncStatus: { status: 'LOADING', type: 'season' }
                    };
                });
                
                this.renderSeasons(seasonsWithLoadingSyncStatus, mediaType, folderName);
                this.showFolderLoading(false);
                
                // Load sync status asynchronously for this specific folder
                this.loadSeasonSyncStatusAsync(mediaType, folderName);
                
            } else {
                this.showAlert(seasonsResult.message || 'Failed to load seasons', 'danger');
                this.showFolderLoading(false);
            }
        } catch (error) {
            console.error('Failed to load seasons:', error);
            this.showAlert('Failed to load seasons', 'danger');
            this.showFolderLoading(false);
        }
    }

    renderSeasons(seasons, mediaType, folderName) {
        // Handle new metadata format for seasons too
        const seasonData = seasons.map(season => {
            // Handle both old format (string) and new format (object)
            if (typeof season === 'string') {
                return { name: season, modification_time: 0 };
            }
            return season;
        });

        // Store seasons data properly without interfering with main navigation
        this.allFolders = seasonData;
        this.currentMediaType = mediaType;
        
        // Set the current state to indicate we're viewing seasons
        this.currentState.viewingSeasons = true;
        this.currentState.seasonsFolder = folderName;
        
        // Display seasons directly instead of using filterAndSortFolders
        this.displaySeasons(seasonData, mediaType, folderName);
        
        // Override the folder select click to use season select instead
        this.overrideForSeasons(mediaType, folderName);
    }

    displaySeasons(seasons, mediaType, folderName) {
        const container = document.getElementById('folderList');
        container.innerHTML = '';

        if (seasons.length === 0) {
            container.innerHTML = `<div class="text-center text-muted p-3">No seasons found for ${this.escapeHtml(folderName)}</div>`;
            return;
        }

        seasons.forEach((season) => {
            const item = document.createElement('div');
            item.className = 'list-group-item d-flex justify-content-between align-items-center';
            
            // Create date string for recently modified seasons
            let dateInfo = '';
            if (season.modification_time > 0) {
                const date = new Date(season.modification_time * 1000);
                const now = new Date();
                const diffTime = now - date;
                const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));
                
                if (diffDays === 0) {
                    dateInfo = ' <small class="text-muted">(Today)</small>';
                } else if (diffDays === 1) {
                    dateInfo = ' <small class="text-muted">(Yesterday)</small>';
                } else if (diffDays < 7) {
                    dateInfo = ` <small class="text-muted">(${diffDays} days ago)</small>`;
                } else if (diffDays < 30) {
                    const weeks = Math.floor(diffDays / 7);
                    dateInfo = ` <small class="text-muted">(${weeks} week${weeks > 1 ? 's' : ''} ago)</small>`;
                } else {
                    dateInfo = ` <small class="text-muted">(${date.toLocaleDateString()})</small>`;
                }
            }
            
            // Generate sync status badge
            const syncStatusBadge = this.generateSyncStatusBadge(season.syncStatus);
            
            item.innerHTML = `
                <div class="d-flex align-items-center flex-grow-1">
                    <i class="bi bi-collection me-2"></i>
                    <div class="flex-grow-1">
                        <div class="d-flex align-items-center gap-2">
                            <span>${this.escapeHtml(season.name)}</span>
                            ${syncStatusBadge}
                        </div>
                        ${dateInfo ? `<div>${dateInfo}</div>` : ''}
                    </div>
                </div>
                <div class="btn-group btn-group-sm">
                    <button class="btn btn-outline-primary" onclick="dragonCP.selectSeason('${this.escapeJavaScriptString(season.name)}', '${mediaType}', '${this.escapeJavaScriptString(folderName)}')">
                        <i class="bi bi-arrow-right"></i>
                    </button>
                </div>
            `;
            
            container.appendChild(item);
        });

        // Update folder count to show season count
        this.updateFolderCount(seasons.length, seasons.length);
        this.showBrowseControls();
    }

    overrideForSeasons(mediaType, folderName) {
        // This function is no longer needed since we're using displaySeasons directly
        // Keeping it for backward compatibility but it's now a no-op
    }

    async selectSeason(seasonName, mediaType, folderName) {
        this.currentState.selectedSeason = seasonName;
        this.currentState.breadcrumb.push(seasonName);
        
        this.showTransferOptions(mediaType, folderName, seasonName);
        this.updateBrowseMediaBreadcrumb();
    }

    showTransferOptions(mediaType, folderName, seasonName = null) {
        const container = document.getElementById('folderList');
        container.innerHTML = '';
        
        // Hide refresh button when showing transfer options
        this.hideBrowseControls();
        
        // Set state to indicate we're viewing transfer options
        this.currentState.viewingTransferOptions = true;

        const options = [
            {
                title: 'Sync Entire Folder',
                description: seasonName ? `Sync entire ${this.escapeHtml(seasonName)} folder` : `Sync entire ${this.escapeHtml(folderName)} folder`,
                icon: 'folder-plus',
                action: () => this.startTransfer('folder', mediaType, folderName, seasonName)
            }
        ];

        // Add episode-specific options for TV shows and anime
        if (seasonName) {
            options.push(
                {
                    title: 'Manual Episode Sync',
                    description: 'Select specific episodes to sync',
                    icon: 'collection',
                    action: () => this.showEpisodeSync(mediaType, folderName, seasonName)
                },
                {
                    title: 'Download Single Episode',
                    description: 'Download a specific episode',
                    icon: 'download',
                    action: () => this.showSingleEpisodeDownload(mediaType, folderName, seasonName)
                }
            );
        }

        options.forEach(option => {
            const item = document.createElement('div');
            item.className = 'list-group-item d-flex justify-content-between align-items-center';
            
            item.innerHTML = `
                <div>
                    <i class="bi bi-${option.icon} me-2"></i>
                    <strong>${option.title}</strong>
                    <br>
                    <small class="text-muted">${option.description}</small>
                </div>
                <button class="btn btn-outline-success" onclick="dragonCP.executeTransferOption('${option.title}')">
                    <i class="bi bi-play"></i>
                </button>
            `;
            
            container.appendChild(item);
        });

        // Store the current transfer context
        this.currentTransferContext = { mediaType, folderName, seasonName, options };
    }

    executeTransferOption(optionTitle) {
        const context = this.currentTransferContext;
        const option = context.options.find(opt => opt.title === optionTitle);
        
        if (option && option.action) {
            option.action();
        }
    }

    async startTransfer(transferType, mediaType, folderName, seasonName = null) {
        try {
            const transferData = {
                type: transferType,
                media_type: mediaType,
                folder_name: folderName,
                season_name: seasonName
            };

            const response = await fetch('/api/transfer', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(transferData)
            });

            const result = await response.json();
            
            if (result.status === 'success') {
                this.showAlert('Transfer started successfully!', 'success');
                // Refresh the database-based transfer list immediately
                this.loadActiveTransfers();
                document.getElementById('logCard').style.display = 'block';
            } else {
                this.showAlert(result.message || 'Failed to start transfer', 'danger');
            }
        } catch (error) {
            console.error('Transfer error:', error);
            this.showAlert('Failed to start transfer', 'danger');
        }
    }

    async showEpisodeSync(mediaType, folderName, seasonName) {
        try {
            const response = await fetch(`/api/episodes/${mediaType}/${encodeURIComponent(folderName)}/${encodeURIComponent(seasonName)}`);
            const result = await response.json();
            
            if (result.status === 'success') {
                this.renderEpisodeSync(result.episodes, mediaType, folderName, seasonName);
            } else {
                this.showAlert(result.message || 'Failed to load episodes', 'danger');
            }
        } catch (error) {
            console.error('Failed to load episodes:', error);
            this.showAlert('Failed to load episodes', 'danger');
        }
    }

    renderEpisodeSync(episodes, mediaType, folderName, seasonName) {
        const container = document.getElementById('folderList');
        container.innerHTML = '';

        if (episodes.length === 0) {
            container.innerHTML = '<div class="text-center text-muted">No episodes found</div>';
            return;
        }

        episodes.forEach((episode, index) => {
            const item = document.createElement('div');
            item.className = 'list-group-item d-flex justify-content-between align-items-center';
            
            item.innerHTML = `
                <div>
                    <i class="bi bi-file-play me-2"></i>
                    ${episode}
                </div>
                <div class="btn-group btn-group-sm">
                    <button class="btn btn-outline-success" onclick="dragonCP.downloadEpisode('${this.escapeJavaScriptString(episode)}', '${mediaType}', '${this.escapeJavaScriptString(folderName)}', '${this.escapeJavaScriptString(seasonName)}')">
                        <i class="bi bi-download"></i>
                    </button>
                </div>
            `;
            
            container.appendChild(item);
        });
    }

    async downloadEpisode(episodeName, mediaType, folderName, seasonName) {
        try {
            const transferData = {
                type: 'file',
                media_type: mediaType,
                folder_name: folderName,
                season_name: seasonName,
                episode_name: episodeName
            };

            const response = await fetch('/api/transfer', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(transferData)
            });

            const result = await response.json();
            
            if (result.status === 'success') {
                this.showAlert(`Downloading episode: ${episodeName}`, 'success');
                // Refresh the database-based transfer list immediately
                this.loadActiveTransfers();
                document.getElementById('logCard').style.display = 'block';
            } else {
                this.showAlert(result.message || 'Failed to start download', 'danger');
            }
        } catch (error) {
            console.error('Download error:', error);
            this.showAlert('Failed to start download', 'danger');
        }
    }

    async showSingleEpisodeDownload(mediaType, folderName, seasonName) {
        await this.showEpisodeSync(mediaType, folderName, seasonName);
    }

    updateTransferProgress(data) {
        // Update logs for the specific transfer
        this.updateTransferTabLogs(data.transfer_id, data.logs, data.log_count, data.status || 'running');
    }

    handleTransferComplete(data) {
        // Update logs for the specific transfer
        this.updateTransferTabLogs(data.transfer_id, data.logs, data.log_count, data.status);
        
        // Show completion message
        if (data.status === 'completed') {
            this.showAlert('Transfer completed successfully!', 'success');
        } else {
            this.showAlert(`Transfer failed: ${data.message}`, 'danger');
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
            return `<div class="log-line ${logClass}">${this.escapeHtml(log)}</div>`;
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
            <span class="log-tab-title" title="${this.escapeHtml(displayName)}">${this.escapeHtml(this.truncateText(displayName, 20))}</span>
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
                return `<div class="log-line ${logClass}">${this.escapeHtml(log)}</div>`;
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
                    return `<div class="log-line ${logClass}">${this.escapeHtml(log)}</div>`;
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

    truncateText(text, maxLength) {
        if (text.length <= maxLength) return text;
        return text.substring(0, maxLength - 3) + '...';
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

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    escapeJavaScriptString(str) {
        if (typeof str !== 'string') return str;
        return str.replace(/\\/g, '\\\\')
                 .replace(/'/g, "\\'")
                 .replace(/"/g, '\\"')
                 .replace(/\n/g, '\\n')
                 .replace(/\r/g, '\\r')
                 .replace(/\t/g, '\\t');
    }

    scrollToBottom(element) {
        element.scrollTop = element.scrollHeight;
    }

    clearTransferLog() {
        if (this.transferTabs.size > 1 && this.activeTabId) {
            // Clear only the active tab's logs
            const tabData = this.transferTabs.get(this.activeTabId);
            if (tabData) {
                tabData.logs = [];
                this.displayTabContent(this.activeTabId);
                this.showAlert('Current tab logs cleared', 'info');
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
            
            this.showAlert('Transfer logs cleared', 'info');
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
                    this.showAlert('Auto-scroll enabled for current tab', 'info');
                    // Scroll to bottom to show latest logs immediately
                    const logContainer = document.getElementById(`transferLog-${this.activeTabId}`);
                    if (logContainer) {
                        logContainer.scrollTop = logContainer.scrollHeight;
                    }
                } else {
                    this.showAlert('Auto-scroll disabled for current tab', 'info');
                }
            }
        } else {
            // Toggle auto-scroll for single transfer
            this.autoScroll = !this.autoScroll;
            const autoScrollBtn = document.getElementById('autoScrollBtn');
            
            if (this.autoScroll) {
                autoScrollBtn.innerHTML = '<i class="bi bi-arrow-up-circle-fill"></i>';
                autoScrollBtn.title = 'Auto-scroll to newest enabled';
                this.showAlert('Auto-scroll to newest enabled', 'info');
                
                // Scroll to bottom to show latest logs immediately
                const logContainer = document.getElementById('transferLog');
                logContainer.scrollTop = logContainer.scrollHeight;
            } else {
                autoScrollBtn.innerHTML = '<i class="bi bi-arrow-up-circle"></i>';
                autoScrollBtn.title = 'Auto-scroll to newest disabled';
                this.showAlert('Auto-scroll disabled', 'info');
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
            fullscreenHeader.innerHTML = `<i class="bi bi-terminal"></i> ${this.escapeHtml(transferName)} - Fullscreen`;
        }
        
        // Format logs for fullscreen display (chronological order)
        const formattedLogs = logsToShow.map(log => {
            const logClass = this.getLogLineClass(log);
            return `<div class="log-line ${logClass}">${this.escapeHtml(log)}</div>`;
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
                this.showAlert(`Loaded ${result.log_count} log lines`, 'info');
            } else {
                this.showAlert('Failed to load transfer logs', 'danger');
            }
        } catch (error) {
            console.error('Failed to load transfer logs:', error);
            this.showAlert('Failed to load transfer logs', 'danger');
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
                
                this.showAlert(`Loaded ${result.log_count} log lines`, 'info');
            } else {
                this.showAlert('Failed to load transfer logs', 'danger');
            }
        } catch (error) {
            console.error('Failed to load transfer logs:', error);
            this.showAlert('Failed to load transfer logs', 'danger');
        }
    }

    async cancelTransfer(transferId) {
        try {
            const response = await fetch(`/api/transfer/${transferId}/cancel`, {
                method: 'POST'
            });
            
            const result = await response.json();
            
            if (result.status === 'success') {
                this.showAlert('Transfer cancelled', 'warning');
                // Refresh the database-based transfer list
                this.loadActiveTransfers();
            } else {
                this.showAlert('Failed to cancel transfer', 'danger');
            }
        } catch (error) {
            console.error('Cancel transfer error:', error);
            this.showAlert('Failed to cancel transfer', 'danger');
        }
    }



    formatBreadcrumbItem(item) {
        const labels = {
            'movies': 'Movies',
            'tvshows': 'TV Shows',
            'anime': 'Anime'
        };
        return labels[item] || item;
    }



    navigateToMediaType() {
        // Go back to showing all folders for this media type
        this.currentState.breadcrumb = [this.currentMediaType];
        this.currentState.selectedFolder = null;
        this.currentState.selectedSeason = null;
        this.loadFolders(this.currentMediaType);
        this.updateBrowseMediaBreadcrumb();
    }

    navigateToFolderLevel(breadcrumbIndex) {
        // Truncate breadcrumb to the target level
        this.currentState.breadcrumb = this.currentState.breadcrumb.slice(0, breadcrumbIndex + 1);
        
        if (breadcrumbIndex === 1) {
            // This is a folder name (like "BreakingBad")
            const folderName = this.currentState.breadcrumb[1];
            this.currentState.selectedFolder = folderName;
            this.currentState.selectedSeason = null;
            
            if (this.currentMediaType === 'tvshows' || this.currentMediaType === 'anime') {
                // Load seasons for this folder
                this.loadSeasons(this.currentMediaType, folderName);
            } else {
                // For movies/backup, show transfer options
                this.showTransferOptions(this.currentMediaType, folderName);
            }
        } else if (breadcrumbIndex === 2) {
            // This is typically a season name (like "Season1")
            const folderName = this.currentState.breadcrumb[1];
            const seasonName = this.currentState.breadcrumb[2];
            this.currentState.selectedFolder = folderName;
            this.currentState.selectedSeason = seasonName;
            
            // Show transfer options for this season
            this.showTransferOptions(this.currentMediaType, folderName, seasonName);
        } else {
            // Handle deeper nesting if needed
            const folderPath = this.currentState.breadcrumb.slice(1, breadcrumbIndex + 1).join('/');
            this.loadFolders(this.currentMediaType, folderPath);
        }
        
        this.updateBrowseMediaBreadcrumb();
    }



    showFolderLoading(show) {
        const spinner = document.getElementById('folderLoadingSpinner');
        const folderList = document.getElementById('folderList');
        
        if (show) {
            if (spinner) spinner.style.display = 'block';
            if (folderList) folderList.style.display = 'none';
        } else {
            if (spinner) spinner.style.display = 'none';
            if (folderList) folderList.style.display = 'block';
        }
    }

    showAlert(message, type) {
        // Dismiss any existing alerts first to prevent stacking
        const existingAlerts = document.querySelectorAll('.alert.position-fixed');
        existingAlerts.forEach(alert => {
            if (alert.parentNode) {
                alert.remove();
            }
        });
        
        const alertDiv = document.createElement('div');
        alertDiv.className = `alert alert-${type} alert-dismissible fade show position-fixed`;
        alertDiv.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px;';
        
        alertDiv.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        
        document.body.appendChild(alertDiv);
        
        // Auto-remove after 10 seconds for info/warning, 5 seconds for success
        let timeout = 10000;
        if (type === 'success') timeout = 5000;
        setTimeout(() => {
            if (alertDiv.parentNode) {
                alertDiv.remove();
            }
        }, timeout);
    }

    hideMediaInterface() {
        document.getElementById('diskUsageCard').style.display = 'none';
        document.getElementById('transferManagementCard').style.display = 'none';
        document.getElementById('browseMediaCard').style.display = 'none';
        document.getElementById('transferCard').style.display = 'none';
        document.getElementById('logCard').style.display = 'none';
        this.resetBrowseMediaState();
    }

    showMediaInterface() {
        document.getElementById('diskUsageCard').style.display = 'block';
        document.getElementById('transferManagementCard').style.display = 'block';
        document.getElementById('browseMediaCard').style.display = 'block';
        document.getElementById('transferCard').style.display = 'none';
        document.getElementById('logCard').style.display = 'none';
        this.showMediaTypeView();
        
        // Only load media types if we don't already have them
        const mediaTypesContainer = document.getElementById('mediaTypes');
        if (!mediaTypesContainer || mediaTypesContainer.children.length === 0) {
            this.loadMediaTypes();
        }
    }

    resetBrowseMediaState() {
        // Reset to media type selection view
        this.showMediaTypeView();
        this.currentMediaType = null;
        this.currentPath = [];
        
        // Reset navigation state
        this.currentState.viewingSeasons = false;
        this.currentState.seasonsFolder = null;
        this.currentState.viewingTransferOptions = false;
        this.currentState.selectedFolder = null;
        this.currentState.selectedSeason = null;
        this.currentState.breadcrumb = [];
    }

    showMediaTypeView() {
        const mediaTypeView = document.getElementById('mediaTypeView');
        const folderBrowserView = document.getElementById('folderBrowserView');
        const browseMediaBreadcrumb = document.getElementById('browseMediaBreadcrumb');
        const browseMediaTitle = document.getElementById('browseMediaTitle');
        const browseMediaIcon = document.getElementById('browseMediaIcon');
        
        if (mediaTypeView) mediaTypeView.style.display = 'block';
        if (folderBrowserView) folderBrowserView.style.display = 'none';
        if (browseMediaBreadcrumb) browseMediaBreadcrumb.style.display = 'none';
        
        if (browseMediaTitle) browseMediaTitle.textContent = 'Browse Media';
        if (browseMediaIcon) {
            browseMediaIcon.className = 'bi bi-collection-play';
        }
        
        // Hide browse controls when showing media type selection
        this.hideBrowseControls();
    }

    showFolderBrowserView(mediaType) {
        const mediaTypeView = document.getElementById('mediaTypeView');
        const folderBrowserView = document.getElementById('folderBrowserView');
        const browseMediaBreadcrumb = document.getElementById('browseMediaBreadcrumb');
        const browseMediaTitle = document.getElementById('browseMediaTitle');
        const browseMediaIcon = document.getElementById('browseMediaIcon');
        
        if (mediaTypeView) mediaTypeView.style.display = 'none';
        if (folderBrowserView) folderBrowserView.style.display = 'block';
        if (browseMediaBreadcrumb) browseMediaBreadcrumb.style.display = 'block';
        
        if (browseMediaTitle) browseMediaTitle.textContent = `Browse ${this.getMediaDisplayName(mediaType)}`;
        if (browseMediaIcon) {
            browseMediaIcon.className = 'bi bi-folder';
        }
        
        this.currentMediaType = mediaType;
        this.updateBrowseMediaBreadcrumb();
    }

    updateBrowseMediaBreadcrumb() {
        const breadcrumb = document.getElementById('breadcrumb');
        if (!breadcrumb) return;

        breadcrumb.innerHTML = '';

        // Always add "Type" as the first breadcrumb item to go back to media selection
        const typeLi = document.createElement('li');
        typeLi.className = 'breadcrumb-item';
        const typeA = document.createElement('a');
        typeA.href = '#';
        typeA.textContent = 'Type';
        typeA.onclick = (e) => {
            e.preventDefault();
            this.showMediaTypeView();
            this.resetBrowseMediaState();
        };
        typeLi.appendChild(typeA);
        breadcrumb.appendChild(typeLi);

        // Add current media type
        if (this.currentMediaType) {
            const mediaLi = document.createElement('li');
            const isMediaTypeActive = !this.currentState.breadcrumb || this.currentState.breadcrumb.length === 1;
            mediaLi.className = `breadcrumb-item ${isMediaTypeActive ? 'active' : ''}`;
            
            if (isMediaTypeActive) {
                mediaLi.textContent = this.getMediaDisplayName(this.currentMediaType);
            } else {
                const mediaA = document.createElement('a');
                mediaA.href = '#';
                mediaA.textContent = this.getMediaDisplayName(this.currentMediaType);
                mediaA.onclick = (e) => {
                    e.preventDefault();
                    // Go back to showing all folders for this media type
                    this.navigateToMediaType();
                };
                mediaLi.appendChild(mediaA);
            }
            breadcrumb.appendChild(mediaLi);

            // Add folder path items from currentState.breadcrumb (excluding media type)
            if (this.currentState.breadcrumb && this.currentState.breadcrumb.length > 1) {
                this.currentState.breadcrumb.slice(1).forEach((item, index) => {
                    const li = document.createElement('li');
                    const breadcrumbIndex = index + 1; // This is the actual index in the breadcrumb array
                    const isLast = breadcrumbIndex === this.currentState.breadcrumb.length - 1;
                    li.className = `breadcrumb-item ${isLast ? 'active' : ''}`;
                    
                    if (isLast) {
                        li.textContent = this.formatBreadcrumbItem(item);
                    } else {
                        const a = document.createElement('a');
                        a.href = '#';
                        a.textContent = this.formatBreadcrumbItem(item);
                        a.onclick = (e) => {
                            e.preventDefault();
                            this.navigateToFolderLevel(breadcrumbIndex);
                        };
                        li.appendChild(a);
                    }
                    
                    breadcrumb.appendChild(li);
                });
            }
        }
    }

    async initializeConnection() {
        try {
            this.updateStatus('Initializing application...', 'connecting');
            
            // Only auto-connect on first load
            if (!this.hasEverConnected) {
                if (!this.isWebSocketConnected) {
                    this.socket.connect();
                }
                const autoConnectResponse = await fetch('/api/auto-connect');
                const autoConnectResult = await autoConnectResponse.json();
                
                if (autoConnectResult.status === 'success') {
                    this.currentState.connected = true;
                    this.updateStatus('Connected to server', 'connected');
                    this.showAlert('Auto-connected successfully!', 'success');
                    this.showMediaInterface();
                    this.loadMediaTypes();
                    return;
                }
            }
            // If auto-connect fails, check if we have credentials
            if (this.hasConnectionCredentials()) {
                this.updateStatus('SSH credentials available. Click Auto Connect to proceed.', 'disconnected');
                this.showAutoConnectOption();
            } else {
                this.updateStatus('No SSH credentials configured. Please configure in Settings.', 'disconnected');
            }
        } catch (error) {
            console.error('Failed to initialize connection:', error);
            this.updateStatus('Failed to initialize connection', 'disconnected');
        }
    }
    
    hasConnectionCredentials() {
        const host = document.getElementById('remoteIp')?.value;
        const username = document.getElementById('remoteUser')?.value;
        return host && username;
    }

    initializeDiskUsageMonitoring() {
        this.loadDiskUsage();
        
        // Add refresh button event listener
        document.getElementById('refreshDiskUsageBtn').addEventListener('click', () => {
            this.refreshDiskUsage();
        });
    }

    async loadDiskUsage() {
        try {
            // Load both local and remote disk usage in parallel
            const [localResponse, remoteResponse] = await Promise.all([
                fetch('/api/disk-usage/local'),
                fetch('/api/disk-usage/remote')
            ]);

            const localData = await localResponse.json();
            const remoteData = await remoteResponse.json();

            this.updateDiskUsageDisplay(localData, remoteData);
            document.getElementById('diskUsageCard').style.display = 'block';

        } catch (error) {
            console.error('Failed to load disk usage:', error);
            // Don't show error for disk usage as it's not critical
        }
    }

    async refreshDiskUsage() {
        try {
            // Show loading state
            const refreshBtn = document.getElementById('refreshDiskUsageBtn');
            const originalHtml = refreshBtn.innerHTML;
            refreshBtn.innerHTML = '<i class="bi bi-arrow-clockwise spinner-border spinner-border-sm"></i>';
            refreshBtn.disabled = true;

            // Load both local and remote disk usage in parallel
            const [localResponse, remoteResponse] = await Promise.all([
                fetch('/api/disk-usage/local'),
                fetch('/api/disk-usage/remote')
            ]);

            const localData = await localResponse.json();
            const remoteData = await remoteResponse.json();

            this.updateDiskUsageDisplay(localData, remoteData);
            this.showAlert('Disk usage refreshed successfully!', 'success');

            // Restore button state
            refreshBtn.innerHTML = originalHtml;
            refreshBtn.disabled = false;

        } catch (error) {
            console.error('Failed to refresh disk usage:', error);
            this.showAlert('Failed to refresh disk usage', 'danger');
            
            // Restore button state
            const refreshBtn = document.getElementById('refreshDiskUsageBtn');
            refreshBtn.innerHTML = '<i class="bi bi-arrow-clockwise"></i>';
            refreshBtn.disabled = false;
        }
    }

    updateDiskUsageDisplay(localData, remoteData) {
        const container = document.getElementById('diskUsageInfo');
        container.innerHTML = '';

        // Display local disk usage
        if (localData.status === 'success' && localData.disk_info) {
            localData.disk_info.forEach((disk, index) => {
                this.renderDiskUsageItem(container, disk, `Local Disk ${index + 1}`, 'local');
            });
        }

        // Display remote disk usage
        if (remoteData.status === 'success' && remoteData.storage_info) {
            this.renderDiskUsageItem(container, remoteData.storage_info, 'Remote Storage', 'remote');
        } else if (remoteData.status === 'error') {
            // Check if it's a rate limiting error
            const isRateLimit = remoteData.message && remoteData.message.includes('429');
            const errorMessage = isRateLimit ? 
                'Rate limited (2 requests/minute). Please wait before refreshing.' : 
                remoteData.message;
            this.renderDiskUsageError(container, 'Remote Storage', errorMessage);
        }

        // Update last refreshed timestamp
        this.updateLastRefreshTime();
    }

    updateLastRefreshTime() {
        const now = new Date();
        const timeString = now.toLocaleTimeString();
        const dateString = now.toLocaleDateString();
        
        // Update button tooltip
        const refreshBtn = document.getElementById('refreshDiskUsageBtn');
        refreshBtn.title = `Last updated: ${timeString} - Click to refresh`;
        
        // Update footer display
        const lastUpdateElement = document.getElementById('diskUsageLastUpdate');
        if (lastUpdateElement) {
            lastUpdateElement.innerHTML = `<i class="bi bi-clock"></i> Last updated: ${dateString} at ${timeString}`;
        }
    }

    renderDiskUsageItem(container, diskInfo, label, type) {
        const col = document.createElement('div');
        col.className = 'col-lg-3 col-md-6 mb-3';

        let content = '';
        
        if (type === 'local' && diskInfo.available) {
            const usageColor = this.getDiskUsageColor(diskInfo.usage_percent);
            
            // Standardize local disk units (convert G to GB, T to TB, etc.)
            const usedSize = this.standardizeUnit(diskInfo.used_size);
            const availableSize = this.standardizeUnit(diskInfo.available_size);
            const totalSize = this.standardizeUnit(diskInfo.total_size);
            
            content = `
                <div class="card h-100 disk-usage-card">
                    <div class="card-body">
                        <div class="d-flex justify-content-between align-items-center mb-2">
                            <h6 class="card-title mb-0">
                                <i class="bi bi-hdd disk-usage-icon"></i> ${label}
                            </h6>
                            <span class="badge bg-${usageColor}">${diskInfo.usage_percent}%</span>
                        </div>
                        <div class="progress mb-2" style="height: 8px;">
                            <div class="progress-bar bg-${usageColor}" 
                                 style="width: ${diskInfo.usage_percent}%"></div>
                        </div>
                        <div class="disk-details">
                            <small class="text-muted d-block">
                                <i class="bi bi-folder"></i> ${this.escapeHtml(diskInfo.path)}
                            </small>
                            <small class="text-muted d-block">
                                <i class="bi bi-device-hdd"></i> ${diskInfo.filesystem}
                            </small>
                            <div class="d-flex justify-content-between mt-1">
                                <small><strong>Used:</strong> ${usedSize}</small>
                                <small><strong>Free:</strong> ${availableSize}</small>
                            </div>
                            <small class="text-muted">
                                <strong>Total:</strong> ${totalSize}
                            </small>
                        </div>
                    </div>
                </div>
            `;
        } else if (type === 'remote' && diskInfo.available) {
            const usageColor = this.getDiskUsageColor(diskInfo.usage_percent);
            content = `
                <div class="card h-100 disk-usage-card">
                    <div class="card-body">
                        <div class="d-flex justify-content-between align-items-center mb-2">
                            <h6 class="card-title mb-0">
                                <i class="bi bi-cloud disk-usage-icon"></i> ${label}
                            </h6>
                            <span class="badge bg-${usageColor}">${diskInfo.usage_percent}%</span>
                        </div>
                        <div class="progress mb-2" style="height: 8px;">
                            <div class="progress-bar bg-${usageColor}" 
                                 style="width: ${diskInfo.usage_percent}%"></div>
                        </div>
                        <div class="disk-details">
                            <div class="d-flex justify-content-between">
                                <small><strong>Used:</strong> ${diskInfo.used_display || (diskInfo.used_storage_value + ' ' + diskInfo.used_storage_unit)}</small>
                                <small><strong>Free:</strong> ${diskInfo.free_display || (diskInfo.free_storage_gb + ' GB')}</small>
                            </div>
                            <small class="text-muted">
                                <strong>Total:</strong> ${diskInfo.total_display || (diskInfo.total_storage_value + ' ' + diskInfo.total_storage_unit)}
                            </small>
                        </div>
                    </div>
                </div>
            `;
        } else {
            // Error state
            content = `
                <div class="card h-100 disk-usage-card border-danger">
                    <div class="card-body">
                        <h6 class="card-title text-danger">
                            <i class="bi bi-exclamation-triangle"></i> ${label}
                        </h6>
                        <small class="text-danger">
                            ${diskInfo.error || 'Unavailable'}
                        </small>
                    </div>
                </div>
            `;
        }

        col.innerHTML = content;
        container.appendChild(col);
    }

    standardizeUnit(sizeString) {
        if (!sizeString) return 'N/A';
        
        // Convert abbreviated units to full names
        return sizeString
            .replace(/(\d+)T$/, '$1 TB')
            .replace(/(\d+)G$/, '$1 GB')
            .replace(/(\d+)M$/, '$1 MB')
            .replace(/(\d+)K$/, '$1 KB')
            .replace(/(\d+\.?\d*)T$/, '$1 TB')
            .replace(/(\d+\.?\d*)G$/, '$1 GB')
            .replace(/(\d+\.?\d*)M$/, '$1 MB')
            .replace(/(\d+\.?\d*)K$/, '$1 KB');
    }

    renderDiskUsageError(container, label, errorMessage) {
        const col = document.createElement('div');
        col.className = 'col-lg-3 col-md-6 mb-3';
        
        col.innerHTML = `
            <div class="card h-100 disk-usage-card border-danger">
                <div class="card-body">
                    <h6 class="card-title text-danger">
                        <i class="bi bi-exclamation-triangle"></i> ${label}
                    </h6>
                    <small class="text-danger">
                        ${this.escapeHtml(errorMessage)}
                    </small>
                </div>
            </div>
        `;
        
        container.appendChild(col);
    }

    getDiskUsageColor(percentage) {
        if (percentage >= 90) return 'danger';
        if (percentage >= 75) return 'warning';
        if (percentage >= 50) return 'info';
        return 'success';
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
        
        // Update count badge
        const activeCount = transfers.filter(t => t.status === 'running' || t.status === 'pending').length;
        countBadge.textContent = `${activeCount} active`;
        
        container.innerHTML = '';
        
        if (transfers.length === 0) {
            noTransfersMessage.style.display = 'block';
            return;
        }
        
        noTransfersMessage.style.display = 'none';
        
        transfers.forEach(transfer => {
            const col = document.createElement('div');
            col.className = 'col-lg-6 col-xl-4';
            
            const displayTitle = transfer.parsed_title || transfer.folder_name;
            const displaySubtitle = this.buildTransferSubtitle(transfer);
            const timeAgo = this.getTimeAgo(transfer.start_time);
            
            col.innerHTML = `
                <div class="transfer-item">
                    <div class="d-flex justify-content-between align-items-start mb-2">
                        <div class="transfer-title">
                            <i class="bi bi-${this.getTransferTypeIcon(transfer.transfer_type)} transfer-type-icon"></i>
                            ${this.escapeHtml(displayTitle)}
                        </div>
                        <span class="transfer-status-badge transfer-status-${transfer.status}">
                            ${transfer.status}
                        </span>
                    </div>
                    <div class="transfer-meta">
                        <div><strong>Type:</strong> ${this.escapeHtml(transfer.media_type)}</div>
                        ${displaySubtitle ? `<div><strong>Details:</strong> ${this.escapeHtml(displaySubtitle)}</div>` : ''}
                        <div class="transfer-time"><strong>Started:</strong> ${timeAgo}</div>
                    </div>
                    <div class="transfer-progress">
                        ${this.escapeHtml(transfer.progress || 'Initializing...')}
                    </div>
                    ${transfer.status === 'running' ? this.renderTransferProgressBar(transfer) : ''}
                    <div class="transfer-actions">
                        <button class="btn btn-sm btn-outline-info" onclick="dragonCP.showTransferDetails('${transfer.id}')">
                            <i class="bi bi-eye"></i> Details
                        </button>
                        ${transfer.status === 'running' ? 
                            `<button class="btn btn-sm btn-outline-danger" onclick="dragonCP.cancelTransfer('${transfer.id}')">
                                <i class="bi bi-x-circle"></i> Cancel
                            </button>` : ''
                        }
                        ${transfer.status === 'failed' || transfer.status === 'cancelled' ? 
                            `<button class="btn btn-sm btn-outline-success" onclick="dragonCP.restartTransfer('${transfer.id}')">
                                <i class="bi bi-arrow-clockwise"></i> Restart
                            </button>` : ''
                        }
                        ${transfer.log_count > 0 ? 
                            `<button class="btn btn-sm btn-outline-secondary" onclick="dragonCP.showTransferLogs('${transfer.id}')">
                                <i class="bi bi-terminal"></i> Logs (${transfer.log_count})
                            </button>` : ''
                        }
                    </div>
                </div>
            `;
            
            container.appendChild(col);
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

    renderTransferProgressBar(transfer) {
        const progressInfo = this.parseTransferProgress(transfer);
        
        if (progressInfo.percentage > 0) {
            return `
                <div class="mt-2">
                    <div class="progress" style="height: 6px;">
                        <div class="progress-bar progress-bar-striped progress-bar-animated bg-primary" 
                             style="width: ${progressInfo.percentage}%"></div>
                    </div>
                    <div class="d-flex justify-content-between mt-1">
                        <small class="text-muted">${progressInfo.percentage}% complete</small>
                        ${progressInfo.speed ? `<small class="text-muted">${progressInfo.speed}</small>` : ''}
                    </div>
                </div>
            `;
        }
        
        return `
            <div class="mt-2">
                <div class="progress" style="height: 6px;">
                    <div class="progress-bar progress-bar-striped progress-bar-animated bg-info" 
                         style="width: 100%"></div>
                </div>
                <small class="text-muted">Processing...</small>
            </div>
        `;
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

    getTimeAgo(timeString) {
        if (!timeString) return 'Unknown';
        
        const time = new Date(timeString);
        const now = new Date();
        const diffMs = now - time;
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMins / 60);
        const diffDays = Math.floor(diffHours / 24);
        
        if (diffMins < 1) return 'Just now';
        if (diffMins < 60) return `${diffMins} min ago`;
        if (diffHours < 24) return `${diffHours} hour${diffHours > 1 ? 's' : ''} ago`;
        return `${diffDays} day${diffDays > 1 ? 's' : ''} ago`;
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
                this.showAlert('Failed to load transfers', 'danger');
            }
        } catch (error) {
            console.error('Failed to load all transfers:', error);
            this.showAlert('Failed to load transfers', 'danger');
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
                            <div class="fw-bold">${this.escapeHtml(displayTitle)}</div>
                            ${displaySubtitle ? `<small class="text-muted">${this.escapeHtml(displaySubtitle)}</small>` : ''}
                        </div>
                    </div>
                </td>
                <td>
                    <span class="badge bg-secondary">${this.escapeHtml(transfer.media_type)}</span>
                </td>
                <td>
                    <span class="transfer-status-badge transfer-status-${transfer.status}">
                        ${transfer.status}
                    </span>
                </td>
                <td>
                    <small>${this.escapeHtml(transfer.progress || 'N/A')}</small>
                </td>
                <td>
                    <small>${this.getTimeAgo(transfer.start_time)}</small>
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
                this.showAlert('Failed to load transfer details', 'danger');
            }
        } catch (error) {
            console.error('Failed to load transfer details:', error);
            this.showAlert('Failed to load transfer details', 'danger');
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
                        <div class="transfer-details-value">${this.escapeHtml(displayTitle)}</div>
                    </div>
                    ${displaySubtitle ? `
                    <div class="transfer-details-item">
                        <div class="transfer-details-label">Details</div>
                        <div class="transfer-details-value">${this.escapeHtml(displaySubtitle)}</div>
                    </div>` : ''}
                    <div class="transfer-details-item">
                        <div class="transfer-details-label">Media Type</div>
                        <div class="transfer-details-value">${this.escapeHtml(transfer.media_type)}</div>
                    </div>
                    <div class="transfer-details-item">
                        <div class="transfer-details-label">Transfer Type</div>
                        <div class="transfer-details-value">${this.escapeHtml(transfer.transfer_type)}</div>
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
                        <div class="transfer-details-value">${this.getTimeAgo(transfer.start_time)}</div>
                    </div>
                    ${transfer.end_time ? `
                    <div class="transfer-details-item">
                        <div class="transfer-details-label">Completed</div>
                        <div class="transfer-details-value">${this.getTimeAgo(transfer.end_time)}</div>
                    </div>` : ''}
                </div>
            </div>
            
            <div class="transfer-details-section">
                <h6>Paths</h6>
                <div class="transfer-details-grid">
                    <div class="transfer-details-item">
                        <div class="transfer-details-label">Source Path</div>
                        <div class="transfer-details-value">${this.escapeHtml(transfer.source_path)}</div>
                    </div>
                    <div class="transfer-details-item">
                        <div class="transfer-details-label">Destination Path</div>
                        <div class="transfer-details-value">${this.escapeHtml(transfer.dest_path)}</div>
                    </div>
                </div>
            </div>
            
            <div class="transfer-details-section">
                <h6>Progress</h6>
                <div class="transfer-details-item">
                    <div class="transfer-details-value">${this.escapeHtml(transfer.progress || 'No progress information')}</div>
                </div>
            </div>
        `;
        
        // Render logs
        const formattedLogs = transfer.logs.map(log => {
            const logClass = this.getLogLineClass(log);
            return `<div class="log-line ${logClass}">${this.escapeHtml(log)}</div>`;
        }).join('');
        
        logContainer.innerHTML = formattedLogs;
        this.scrollToBottom(logContainer);
    }

    async restartTransfer(transferId) {
        try {
            const response = await fetch(`/api/transfer/${transferId}/restart`, {
                method: 'POST'
            });
            
            const result = await response.json();
            
            if (result.status === 'success') {
                this.showAlert('Transfer restarted successfully!', 'success');
                this.loadActiveTransfers();
            } else {
                this.showAlert('Failed to restart transfer: ' + result.message, 'danger');
            }
        } catch (error) {
            console.error('Failed to restart transfer:', error);
            this.showAlert('Failed to restart transfer', 'danger');
        }
    }

    async cleanupOldTransfers() {
        try {
            const confirmed = confirm('This will permanently delete old completed transfers. Continue?');
            if (!confirmed) return;
            
            const response = await fetch('/api/transfers/cleanup', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ days: 30 })
            });
            
            const result = await response.json();
            
            if (result.status === 'success') {
                this.showAlert(`Cleaned up ${result.cleaned_count} old transfers`, 'success');
                this.loadActiveTransfers();
            } else {
                this.showAlert('Failed to cleanup transfers: ' + result.message, 'danger');
            }
        } catch (error) {
            console.error('Failed to cleanup transfers:', error);
            this.showAlert('Failed to cleanup transfers', 'danger');
        }
    }

    updateWebSocketConfigStatus() {
        const statusIndicator = document.getElementById('wsConfigStatusIndicator');
        const statusText = document.getElementById('wsConfigStatusText');
        const statusDetails = document.getElementById('wsConfigStatusDetails');
        
        if (!statusIndicator || !statusText || !statusDetails) return;
        
        // Check if we're in config-changed state
        const currentStatus = document.getElementById('statusIndicator')?.className;
        const isConfigChanged = currentStatus?.includes('status-config-changed');
        
        if (isConfigChanged) {
            statusIndicator.className = 'status-indicator status-config-changed';
            statusText.textContent = 'Configuration Updated';
            statusDetails.innerHTML = `
                <i class="bi bi-exclamation-triangle"></i> 
                Settings changed. Click "Apply New Settings" to reconnect with updated configuration.
            `;
        } else if (this.isWebSocketConnected) {
            statusIndicator.className = 'status-indicator status-connected';
            statusText.textContent = 'Connected';
            
            const timeoutMinutes = Math.floor(this.websocketTimeout / 60000);
            const timeSinceActivity = Math.floor((Date.now() - this.lastActivity) / 60000);
            const timeLeft = Math.max(0, timeoutMinutes - timeSinceActivity);
            
            statusDetails.innerHTML = `
                <i class="bi bi-check-circle"></i> 
                Real-time updates active. Timeout: ${timeoutMinutes} min. 
                Time left: ${timeLeft} min.
            `;
        } else if (this.wasAutoDisconnected) {
            statusIndicator.className = 'status-indicator status-auto-disconnected';
            statusText.textContent = 'Auto-disconnected';
            statusDetails.innerHTML = `
                <i class="bi bi-clock"></i> 
                Disconnected due to inactivity. Active transfers continue via background API monitoring.
            `;
        } else {
            statusIndicator.className = 'status-indicator status-disconnected';
            statusText.textContent = 'Disconnected';
            statusDetails.innerHTML = `
                <i class="bi bi-x-circle"></i> 
                App connection not active. Click "Auto Connect" for real-time updates and full features.
            `;
        }
    }

    startTimerDisplayUpdates() {
        // Update timer display every minute
        setInterval(() => {
            if (this.isWebSocketConnected) {
                this.updateStatusWithTimer().catch(error => {
                    console.warn('Failed to update status with timer:', error);
                });
            }
        }, 60000);
        
        // Also update every 15 seconds when time is running low (last 5 minutes)
        setInterval(() => {
            if (this.isWebSocketConnected) {
                const minutesLeft = this.getTimeRemaining();
                if (minutesLeft <= 5) {
                    this.updateStatusWithTimer().catch(error => {
                        console.warn('Failed to update status with timer:', error);
                    });
                }
            }
        }, 15000);
    }

    getTimeRemaining() {
        if (!this.isWebSocketConnected) return 0;
        
        const timeSinceActivity = Date.now() - this.lastActivity;
        const timeUntilDisconnect = this.websocketTimeout - timeSinceActivity;
        const minutesLeft = Math.max(0, Math.floor(timeUntilDisconnect / 60000));
        
        return minutesLeft;
    }

    async updateStatusWithTimer() {
        if (this.activityTimer) {
            const timeRemaining = this.getTimeRemaining();
            if (timeRemaining > 0) {
                this.updateStatus(`Session active - ${timeRemaining} minutes remaining`, 'connected');
            } else {
                this.updateStatus('Session expired - reconnecting...', 'auto-disconnected');
            }
        }
    }

    // ===== COLLAPSIBLE CARDS FUNCTIONALITY =====
    
    initializeCollapsibleCards() {
        // Load saved collapsed state from localStorage
        this.loadCollapsedState();
        
        // Add event listeners to all collapsible headers
        document.addEventListener('click', (e) => {
            const header = e.target.closest('.collapsible-header');
            if (header && !e.target.closest('.btn, .log-controls, .breadcrumb, .log-nav-tabs, #logTabs, #logTabsContainer, .nav-tabs')) {
                e.preventDefault();
                e.stopPropagation();
                this.toggleCardCollapse(header);
            }
        });
        
        // Add keyboard support for accessibility
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                const header = document.activeElement.closest('.collapsible-header');
                if (header && !e.target.closest('.btn, .log-controls, .breadcrumb, .log-nav-tabs, #logTabs, #logTabsContainer, .nav-tabs')) {
                    e.preventDefault();
                    this.toggleCardCollapse(header);
                }
            }
        });
        
        // Apply saved collapsed state to visible cards
        this.applyCollapsedState();
    }
    
    loadCollapsedState() {
        try {
            const saved = localStorage.getItem('dragoncp_collapsed_cards');
            if (saved) {
                const collapsedIds = JSON.parse(saved);
                this.collapsedCards = new Set(collapsedIds);
            }
        } catch (error) {
            console.warn('Failed to load collapsed card state:', error);
            this.collapsedCards = new Set();
        }
    }
    
    saveCollapsedState() {
        try {
            const collapsedIds = Array.from(this.collapsedCards);
            localStorage.setItem('dragoncp_collapsed_cards', JSON.stringify(collapsedIds));
        } catch (error) {
            console.warn('Failed to save collapsed card state:', error);
        }
    }
    
    applyCollapsedState() {
        // Apply collapsed state to all visible cards
        document.querySelectorAll('.collapsible-header').forEach(header => {
            const cardId = header.dataset.cardId;
            if (cardId && this.collapsedCards.has(cardId)) {
                this.collapseCard(header, false); // false = don't save state again
            }
        });
        this.updateCollapseAllButtonState();
    }
    
    toggleCardCollapse(header) {
        const cardId = header.dataset.cardId;
        const content = header.nextElementSibling;
        const card = header.closest('.card');
        
        if (content.classList.contains('collapsed')) {
            // Expand the card
            this.expandCard(header);
            this.collapsedCards.delete(cardId);
        } else {
            // Collapse the card
            this.collapseCard(header);
            this.collapsedCards.add(cardId);
        }
        
        // Save state to localStorage
        this.saveCollapsedState();
        
        // Update collapse all button state
        this.updateCollapseAllButtonState();
    }
    
    collapseCard(header, saveState = true) {
        const content = header.nextElementSibling;
        const card = header.closest('.card');
        
        // Add collapsed classes
        header.classList.add('collapsed');
        content.classList.add('collapsed');
        card.classList.add('collapsed');
        
        // Add animation class
        content.classList.add('collapsing');
        
        // Remove animation class after animation completes
        setTimeout(() => {
            content.classList.remove('collapsing');
        }, 300);
        
        if (saveState) {
            this.saveCollapsedState();
        }
    }
    
    expandCard(header, saveState = true) {
        const content = header.nextElementSibling;
        const card = header.closest('.card');
        
        // Remove collapsed classes
        header.classList.remove('collapsed');
        content.classList.remove('collapsed');
        card.classList.remove('collapsed');
        
        // Add animation class
        content.classList.add('expanding');
        
        // Remove animation class after animation completes
        setTimeout(() => {
            content.classList.remove('expanding');
        }, 300);
        
        if (saveState) {
            this.saveCollapsedState();
        }
    }
    

    
    updateCollapseAllButtonState() {
        const button = document.getElementById('collapseAllBtn');
        if (!button) return;
        
        const icon = button.querySelector('i');
        const textSpan = button.querySelector('span');
        
        // Check if all cards are collapsed
        const allCards = document.querySelectorAll('.collapsible-header');
        const allCollapsed = Array.from(allCards).every(header => {
            const cardId = header.dataset.cardId;
            return cardId && this.collapsedCards.has(cardId);
        });
        
        if (allCollapsed && allCards.length > 0) {
            button.classList.add('collapsed');
            icon.className = 'bi bi-chevron-down';
            textSpan.textContent = ' Expand All';
        } else {
            button.classList.remove('collapsed');
            icon.className = 'bi bi-chevron-up';
            textSpan.textContent = ' Collapse All';
        }
    }
    
    // Method to programmatically collapse/expand cards (useful for other parts of the app)
    setCardCollapsed(cardId, collapsed) {
        const header = document.querySelector(`[data-card-id="${cardId}"]`);
        if (header) {
            if (collapsed) {
                this.collapseCard(header);
                this.collapsedCards.add(cardId);
            } else {
                this.expandCard(header);
                this.collapsedCards.delete(cardId);
            }
            this.saveCollapsedState();
        }
    }
    
    // Method to get current collapsed state
    isCardCollapsed(cardId) {
        return this.collapsedCards.has(cardId);
    }
    
    // Method to handle dynamic card creation (for cards added after page load)
    setupCollapsibleForCard(cardElement) {
        const header = cardElement.querySelector('.collapsible-header');
        if (header) {
            const cardId = header.dataset.cardId;
            if (cardId && this.collapsedCards.has(cardId)) {
                // Apply saved collapsed state
                this.collapseCard(header, false);
            }
        }
    }
    
    // Method to refresh collapsible state for all cards
    refreshCollapsibleState() {
        document.querySelectorAll('.collapsible-header').forEach(header => {
            const cardId = header.dataset.cardId;
            if (cardId) {
                if (this.collapsedCards.has(cardId)) {
                    this.collapseCard(header, false);
                } else {
                    this.expandCard(header, false);
                }
            }
        });
    }
    
    // Method to collapse all cards except specified ones
    collapseAllExcept(exceptCardIds = []) {
        document.querySelectorAll('.collapsible-header').forEach(header => {
            const cardId = header.dataset.cardId;
            if (cardId && !exceptCardIds.includes(cardId)) {
                this.setCardCollapsed(cardId, true);
            }
        });
        this.updateCollapseAllButtonState();
    }
    
    // Method to expand all cards
    expandAllCards() {
        document.querySelectorAll('.collapsible-header').forEach(header => {
            const cardId = header.dataset.cardId;
            if (cardId) {
                this.setCardCollapsed(cardId, false);
            }
        });
        this.updateCollapseAllButtonState();
    }
    
    // Method to reset collapsible state to default
    resetCollapsibleState() {
        this.collapsedCards.clear();
        localStorage.removeItem('dragoncp_collapsed_cards');
        this.refreshCollapsibleState();
    }
    
    // Sync Status Methods
    generateSyncStatusBadge(syncStatus) {
        if (!syncStatus || !syncStatus.status) {
            return '';
        }
        
        const { status, type, most_recent_season } = syncStatus;
        
        // Get badge details based on status
        const badgeConfig = this.getSyncStatusBadgeConfig(status);
        
        // For series/anime, add additional info if available
        let additionalInfo = '';
        if (type === 'series' && most_recent_season && status !== 'NO_INFO') {
            additionalInfo = ` title="Based on most recent season: ${most_recent_season.name}"`;
        }
        
        return `<span class="badge sync-status-badge ${badgeConfig.class}"${additionalInfo}>
                    <i class="${badgeConfig.icon} me-1"></i>
                    ${badgeConfig.text}
                </span>`;
    }
    
    getSyncStatusBadgeConfig(status) {
        switch (status) {
            case 'SYNCED':
                return {
                    class: 'sync-status-synced bg-success',
                    icon: 'bi bi-check-circle-fill',
                    text: 'Synced'
                };
            case 'OUT_OF_SYNC':
                return {
                    class: 'sync-status-out-of-sync bg-warning text-dark',
                    icon: 'bi bi-exclamation-triangle-fill',
                    text: 'Out of Sync'
                };
            case 'LOADING':
                return {
                    class: 'sync-status-loading bg-info',
                    icon: 'bi bi-arrow-clockwise spinning',
                    text: 'Loading...'
                };
            case 'NO_INFO':
            default:
                return {
                    class: 'sync-status-no-info bg-secondary',
                    icon: 'bi bi-question-circle-fill',
                    text: 'No Info'
                };
        }
    }
    
    // Method to refresh sync status for current media type
    async refreshSyncStatus() {
        // Don't refresh if we're viewing transfer options
        if (this.currentState.viewingTransferOptions) {
            return;
        }
        
        // Check current context - are we viewing seasons of a specific series?
        if (this.currentState.viewingSeasons && this.currentState.seasonsFolder && this.currentMediaType) {
            // We're in a season view, refresh only this series' sync status
            await this.loadSeasonSyncStatusAsync(this.currentMediaType, this.currentState.seasonsFolder);
        } else if (this.currentMediaType) {
            // We're in the main folder view, refresh all folders
            await this.loadSyncStatusAsync(this.currentMediaType);
        }
    }
    
    // Load sync status asynchronously for all folders in a media type
    async loadSyncStatusAsync(mediaType) {
        try {
            const response = await fetch(`/api/sync-status/${mediaType}`);
            const result = await response.json();
            
            if (result.status === 'success' && this.allFolders) {
                // Update sync status for all folders
                this.allFolders = this.allFolders.map(folder => {
                    const syncStatus = result.sync_statuses[folder.name];
                    return {
                        ...folder,
                        syncStatus: syncStatus || { status: 'NO_INFO', type: 'unknown' }
                    };
                });
                
                // Re-render the current view with updated sync status
                this.filterAndSortFolders();
                this.updateRefreshButtonState();
            }
        } catch (error) {
            console.error('Failed to load sync status:', error);
            // Update all folders to show error state
            if (this.allFolders) {
                this.allFolders = this.allFolders.map(folder => ({
                    ...folder,
                    syncStatus: { status: 'NO_INFO', type: 'unknown' }
                }));
                this.filterAndSortFolders();
            }
            this.updateRefreshButtonState();
        }
    }
    
    // Load sync status asynchronously for seasons of a specific folder
    async loadSeasonSyncStatusAsync(mediaType, folderName) {
        try {
            const response = await fetch(`/api/sync-status/${mediaType}/${encodeURIComponent(folderName)}`);
            const result = await response.json();
            
            if (result.status === 'success' && this.allFolders) {
                // Update sync status for all seasons
                this.allFolders = this.allFolders.map(season => {
                    const syncStatus = result.seasons_sync_status && result.seasons_sync_status[season.name];
                    return {
                        ...season,
                        syncStatus: syncStatus || { status: 'NO_INFO', type: 'season' }
                    };
                });
                
                // Re-render the current view with updated sync status
                this.displaySeasons(this.allFolders, mediaType, folderName);
                this.updateRefreshButtonState();
            }
        } catch (error) {
            console.error('Failed to load season sync status:', error);
            // Update all seasons to show error state
            if (this.allFolders) {
                this.allFolders = this.allFolders.map(season => ({
                    ...season,
                    syncStatus: { status: 'NO_INFO', type: 'season' }
                }));
                this.displaySeasons(this.allFolders, mediaType, folderName);
            }
            this.updateRefreshButtonState();
        }
    }
    
    // Update refresh button state based on current sync status
    updateRefreshButtonState() {
        const button = document.getElementById('refreshSyncStatusBtn');
        if (!button) return;
        
        // Check if any sync status is currently loading
        const hasLoadingStatus = this.allFolders && this.allFolders.some(folder => 
            folder.syncStatus && folder.syncStatus.status === 'LOADING'
        );
        
        // Disable button if sync is loading or button is already refreshing
        if (hasLoadingStatus || button.classList.contains('refreshing')) {
            button.disabled = true;
        } else {
            button.disabled = false;
        }
    }
}

// Initialize the application when the page loads
let dragonCP;
document.addEventListener('DOMContentLoaded', () => {
    dragonCP = new DragonCPUI();
}); 