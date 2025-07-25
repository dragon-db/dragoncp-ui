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
            breadcrumb: []
        };
        this.transferLogs = [];
        this.autoScroll = true;
        this.currentTransferId = null;
        
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
            '.card.h-100', // Media type cards
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
            this.updateStatusWithTimer();
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
            'mediaCard',
            'folderCard', 
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
            'mediaCard'
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
                this.updateStatusWithTimer();
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
                
                // Show timer immediately
                this.updateStatusWithTimer();
                
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
                document.getElementById('mediaCard').style.display = 'block';
            } else if (mediaTypes.status === 'success' && mediaTypes.data) {
                this.renderMediaTypes(mediaTypes.data);
                document.getElementById('mediaCard').style.display = 'block';
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
                <div class="card h-100" style="cursor: pointer;" onclick="dragonCP.selectMediaType('${mediaType.id}')">
                    <div class="card-body text-center">
                        <i class="bi bi-${this.getMediaIcon(mediaType.id)}" style="font-size: 3rem; color: var(--secondary-color);"></i>
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
        
        await this.loadFolders(mediaType);
        document.getElementById('folderCard').style.display = 'block';
        this.updateBreadcrumb();
    }

    async loadFolders(mediaType, folderPath = '') {
        try {
            this.showFolderLoading(true);
            
            let url = `/api/folders/${mediaType}`;
            if (folderPath) {
                url += `?path=${encodeURIComponent(folderPath)}`;
            }
            
            const response = await fetch(url);
            const result = await response.json();
            
            if (result.status === 'success') {
                this.renderFolders(result.folders, mediaType);
            } else {
                this.showAlert(result.message || 'Failed to load folders', 'danger');
            }
        } catch (error) {
            console.error('Failed to load folders:', error);
            this.showAlert('Failed to load folders', 'danger');
        } finally {
            this.showFolderLoading(false);
        }
    }

    renderFolders(folders, mediaType) {
        const container = document.getElementById('folderList');
        container.innerHTML = '';

        if (folders.length === 0) {
            container.innerHTML = '<div class="text-center text-muted">No folders found</div>';
            return;
        }

        folders.forEach((folder, index) => {
            const item = document.createElement('div');
            item.className = 'list-group-item d-flex justify-content-between align-items-center';
            
            item.innerHTML = `
                <div>
                    <i class="bi bi-folder me-2"></i>
                    ${folder}
                </div>
                <div class="btn-group btn-group-sm">
                    <button class="btn btn-outline-primary" onclick="dragonCP.selectFolder('${this.escapeJavaScriptString(folder)}', '${mediaType}')">
                        <i class="bi bi-arrow-right"></i>
                    </button>
                </div>
            `;
            
            container.appendChild(item);
        });
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
        
        this.updateBreadcrumb();
    }

    async loadSeasons(mediaType, folderName) {
        try {
            this.showFolderLoading(true);
            
            const response = await fetch(`/api/seasons/${mediaType}/${encodeURIComponent(folderName)}`);
            const result = await response.json();
            
            if (result.status === 'success') {
                this.renderSeasons(result.seasons, mediaType, folderName);
            } else {
                this.showAlert(result.message || 'Failed to load seasons', 'danger');
            }
        } catch (error) {
            console.error('Failed to load seasons:', error);
            this.showAlert('Failed to load seasons', 'danger');
        } finally {
            this.showFolderLoading(false);
        }
    }

    renderSeasons(seasons, mediaType, folderName) {
        const container = document.getElementById('folderList');
        container.innerHTML = '';

        if (seasons.length === 0) {
            container.innerHTML = '<div class="text-center text-muted">No seasons found</div>';
            return;
        }

        seasons.forEach((season, index) => {
            const item = document.createElement('div');
            item.className = 'list-group-item d-flex justify-content-between align-items-center';
            
            item.innerHTML = `
                <div>
                    <i class="bi bi-collection me-2"></i>
                    ${season}
                </div>
                <div class="btn-group btn-group-sm">
                    <button class="btn btn-outline-primary" onclick="dragonCP.selectSeason('${this.escapeJavaScriptString(season)}', '${mediaType}', '${this.escapeJavaScriptString(folderName)}')">
                        <i class="bi bi-arrow-right"></i>
                    </button>
                </div>
            `;
            
            container.appendChild(item);
        });
    }

    async selectSeason(seasonName, mediaType, folderName) {
        this.currentState.selectedSeason = seasonName;
        this.currentState.breadcrumb.push(seasonName);
        
        this.showTransferOptions(mediaType, folderName, seasonName);
        this.updateBreadcrumb();
    }

    showTransferOptions(mediaType, folderName, seasonName = null) {
        const container = document.getElementById('folderList');
        container.innerHTML = '';

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
        // Update logs for the current transfer being viewed
        this.updateTransferLog(data.logs, data.log_count);
    }

    handleTransferComplete(data) {
        // Update logs for the current transfer
        this.updateTransferLog(data.logs, data.log_count);
        
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
        
        // Format and display logs with syntax highlighting
        const formattedLogs = this.transferLogs.map(log => {
            const logClass = this.getLogLineClass(log);
            return `<div class="log-line ${logClass}">${this.escapeHtml(log)}</div>`;
        }).join('');
        
        logContainer.innerHTML = formattedLogs;
        
        // Auto-scroll to bottom if enabled
        if (this.autoScroll) {
            this.scrollToBottom(logContainer);
        }
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
        this.transferLogs = [];
        const logContainer = document.getElementById('transferLog');
        const logCountElement = document.getElementById('logCount');
        
        logContainer.innerHTML = '';
        if (logCountElement) {
            logCountElement.textContent = '0 lines';
        }
        
        this.showAlert('Transfer logs cleared', 'info');
    }

    toggleAutoScroll() {
        this.autoScroll = !this.autoScroll;
        const autoScrollBtn = document.getElementById('autoScrollBtn');
        
        if (this.autoScroll) {
            autoScrollBtn.innerHTML = '<i class="bi bi-arrow-down-circle-fill"></i>';
            autoScrollBtn.title = 'Auto-scroll enabled';
            this.showAlert('Auto-scroll enabled', 'info');
            
            // Scroll to bottom immediately
            const logContainer = document.getElementById('transferLog');
            this.scrollToBottom(logContainer);
        } else {
            autoScrollBtn.innerHTML = '<i class="bi bi-arrow-down-circle"></i>';
            autoScrollBtn.title = 'Auto-scroll disabled';
            this.showAlert('Auto-scroll disabled', 'info');
        }
    }

    showFullscreenLog() {
        const fullscreenModal = document.getElementById('fullscreenLogModal');
        const fullscreenLog = document.getElementById('fullscreenTransferLog');
        
        // Format logs for fullscreen display
        const formattedLogs = this.transferLogs.map(log => {
            const logClass = this.getLogLineClass(log);
            return `<div class="log-line ${logClass}">${this.escapeHtml(log)}</div>`;
        }).join('');
        
        fullscreenLog.innerHTML = formattedLogs;
        fullscreenModal.classList.add('show');
        
        // Scroll to bottom in fullscreen
        this.scrollToBottom(fullscreenLog);
        
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
                this.updateTransferLog(result.logs, result.log_count);
                
                // Show the log card
                document.getElementById('logCard').style.display = 'block';
                
                // Scroll to the log card
                document.getElementById('logCard').scrollIntoView({ 
                    behavior: 'smooth',
                    block: 'nearest'
                });
                
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

    updateBreadcrumb() {
        const breadcrumb = document.getElementById('breadcrumb');
        breadcrumb.innerHTML = '';

        this.currentState.breadcrumb.forEach((item, index) => {
            const li = document.createElement('li');
            li.className = `breadcrumb-item ${index === this.currentState.breadcrumb.length - 1 ? 'active' : ''}`;
            
            if (index === this.currentState.breadcrumb.length - 1) {
                li.textContent = this.formatBreadcrumbItem(item);
            } else {
                const a = document.createElement('a');
                a.href = '#';
                a.textContent = this.formatBreadcrumbItem(item);
                a.onclick = (e) => {
                    e.preventDefault();
                    this.navigateBreadcrumb(index);
                };
                li.appendChild(a);
            }
            
            breadcrumb.appendChild(li);
        });
    }

    formatBreadcrumbItem(item) {
        const labels = {
            'movies': 'Movies',
            'tvshows': 'TV Shows',
            'anime': 'Anime'
        };
        return labels[item] || item;
    }

    navigateBreadcrumb(index) {
        this.currentState.breadcrumb = this.currentState.breadcrumb.slice(0, index + 1);
        
        if (index === 0) {
            // Back to media type selection
            this.currentState.selectedFolder = null;
            this.currentState.selectedSeason = null;
            this.loadMediaTypes();
        } else if (index === 1) {
            // Back to folder selection
            this.currentState.selectedSeason = null;
            this.loadFolders(this.currentState.mediaType);
        }
        
        this.updateBreadcrumb();
    }

    showFolderLoading(show) {
        const spinner = document.querySelector('.loading-spinner');
        const folderList = document.getElementById('folderList');
        
        if (show) {
            spinner.style.display = 'block';
            folderList.style.display = 'none';
        } else {
            spinner.style.display = 'none';
            folderList.style.display = 'block';
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
        document.getElementById('mediaCard').style.display = 'none';
        document.getElementById('folderCard').style.display = 'none';
        document.getElementById('transferCard').style.display = 'none';
        document.getElementById('logCard').style.display = 'none';
    }

    showMediaInterface() {
        document.getElementById('diskUsageCard').style.display = 'block';
        document.getElementById('transferManagementCard').style.display = 'block';
        document.getElementById('mediaCard').style.display = 'block';
        document.getElementById('folderCard').style.display = 'none';
        document.getElementById('transferCard').style.display = 'none';
        document.getElementById('logCard').style.display = 'none';
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
                                <i class="bi bi-hdd"></i> ${label}
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
                                <i class="bi bi-cloud"></i> ${label}
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
                this.updateTransferManagementDisplay(result.transfers);
                document.getElementById('transferManagementCard').style.display = 'block';
            } else {
                console.error('Failed to load active transfers:', result.message);
            }
        } catch (error) {
            console.error('Failed to load active transfers:', error);
        }
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
                this.updateStatusWithTimer();
            }
        }, 60000);
        
        // Also update every 15 seconds when time is running low (last 5 minutes)
        setInterval(() => {
            if (this.isWebSocketConnected) {
                const minutesLeft = this.getTimeRemaining();
                if (minutesLeft <= 5) {
                    this.updateStatusWithTimer();
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

    updateStatusWithTimer() {
        if (!this.isWebSocketConnected) return;
        
        const minutesLeft = this.getTimeRemaining();
        let message;
        
        // Check if transfers are protecting the session
        this.hasActiveTransfers().then(hasTransfers => {
            if (hasTransfers) {
                message = `Connected to server (session protected - active transfers running)`;
                this.updateStatus(message, 'connected');
            } else {
                if (minutesLeft <= 0) {
                    message = `Connected to server (${minutesLeft} min left)`;
                    // Show warning color for last minute
                    this.updateStatus(message, 'connecting'); // Use warning color
                } else if (minutesLeft <= 1) {
                    message = `Connected to server (${minutesLeft} min left)`;
                    // Keep connected color but user can see it's getting low
                    this.updateStatus(message, 'connected');
                } else {
                    message = `Connected to server (${minutesLeft} min left)`;
                    this.updateStatus(message, 'connected');
                }
            }
        }).catch(() => {
            // If we can't check transfers, just show normal timer
            if (minutesLeft <= 0) {
                message = `Connected to server (${minutesLeft} min left)`;
                this.updateStatus(message, 'connecting');
            } else {
                message = `Connected to server (${minutesLeft} min left)`;
                this.updateStatus(message, 'connected');
            }
        });
    }
}

// Initialize the application when the page loads
let dragonCP;
document.addEventListener('DOMContentLoaded', () => {
    dragonCP = new DragonCPUI();
}); 