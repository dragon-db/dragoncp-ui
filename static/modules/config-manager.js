/**
 * Configuration Manager Module
 * Handles configuration loading, saving, validation, and field management
 */
export class ConfigManager {
    constructor(app) {
        this.app = app;
        this.initializeConfigListeners();
    }

    async loadConfiguration() {
        try {
            this.app.ui.updateStatus('Loading configuration...', 'connecting');
            
            // Load all configuration (env + session overrides)
            const response = await fetch('/api/config');
            const config = await response.json();
            
            // Load environment-only config for comparison
            const envResponse = await fetch('/api/config/env-only');
            const envConfig = await envResponse.json();
            
            // Populate all form fields with current config values
            this.populateConfigFields(config, envConfig);
            
            this.app.ui.updateStatus('Configuration loaded', 'disconnected');
            
        } catch (error) {
            console.error('Failed to load configuration:', error);
            this.app.ui.updateStatus('Failed to load configuration', 'disconnected');
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
            { id: 'websocketTimeout', name: 'WEBSOCKET_TIMEOUT_MINUTES', label: 'WebSocket Timeout (minutes)', value: Math.min(60, Math.max(5, config.WEBSOCKET_TIMEOUT_MINUTES || 30)), envValue: Math.min(60, Math.max(5, envConfig.WEBSOCKET_TIMEOUT_MINUTES || 30)), type: 'number', placeholder: '30' },
            
            // Discord Notifications (these are loaded separately as they're stored in database)
            { id: 'discordNotificationsEnabled', name: 'DISCORD_NOTIFICATIONS_ENABLED', label: 'Enable Discord Notifications', value: false, envValue: false, type: 'checkbox', placeholder: '' },
            { id: 'discordWebhookUrl', name: 'DISCORD_WEBHOOK_URL', label: 'Discord Webhook URL', value: '', envValue: '', placeholder: 'https://discord.com/api/webhooks/...' },
            { id: 'discordAppUrl', name: 'DISCORD_APP_URL', label: 'Discord App URL', value: '', envValue: '', placeholder: 'http://localhost:5000' },
            { id: 'discordIconUrl', name: 'DISCORD_ICON_URL', label: 'Discord Icon URL', value: '', envValue: '', placeholder: 'https://example.com/icon.png' },
            { id: 'discordManualSyncThumbnailUrl', name: 'DISCORD_MANUAL_SYNC_THUMBNAIL_URL', label: 'Alt Thumbnail URL', value: '', envValue: '', placeholder: 'https://example.com/thumbnail.png' }
        ];
        
        // Populate each field
        configFields.forEach(field => {
            const input = document.getElementById(field.id);
            const indicator = document.getElementById(field.id + 'Indicator');
            const original = document.getElementById(field.id + 'Original');
            
            if (input) {
                if (field.type === 'checkbox') {
                    input.checked = field.value === true || field.value === 'true';
                } else {
                    input.value = field.value || '';
                    input.placeholder = field.placeholder || '';
                }
                
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
        this.app.websocket.setWebSocketTimeout(timeoutMinutes);
        
        // Update WebSocket status display in configuration modal
        this.updateWebSocketConfigStatus();
    }
    
    async resetConfiguration() {
        try {
            this.app.ui.updateStatus('Resetting configuration...', 'connecting');
            
            const response = await fetch('/api/config/reset', {
                method: 'POST'
            });
            
            const result = await response.json();
            
            if (result.status === 'success') {
                this.app.ui.showAlert('Configuration reset to environment values', 'success');
                await this.loadConfiguration();
                
                // Re-initialize connection with reset values
                await this.app.initializeConnection();
            } else {
                this.app.ui.showAlert('Failed to reset configuration', 'danger');
                this.app.ui.updateStatus('Failed to reset configuration', 'disconnected');
            }
        } catch (error) {
            console.error('Failed to reset configuration:', error);
            this.app.ui.showAlert('Failed to reset configuration', 'danger');
            this.app.ui.updateStatus('Failed to reset configuration', 'disconnected');
        }
    }

    async saveConfiguration() {
        try {
            this.app.ui.updateStatus('Saving configuration...', 'connecting');
            
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
                // Save Discord settings separately (stored in database)
                await this.saveDiscordSettings();
                
                // Save webhook settings separately (stored in database)
                await this.saveWebhookSettings();
                
                // Determine if critical config changes were made
                const hasCriticalChanges = this.hasCriticalConfigChanges(config);
                
                // Apply WebSocket timeout change
                let timeoutChanged = false;
                if (config.WEBSOCKET_TIMEOUT_MINUTES) {
                    const newTimeoutMinutes = Math.min(60, Math.max(5, parseInt(config.WEBSOCKET_TIMEOUT_MINUTES)));
                    const newTimeoutMs = newTimeoutMinutes * 60 * 1000;
                    
                    if (newTimeoutMs !== this.app.websocket.websocketTimeout) {
                        this.app.websocket.setWebSocketTimeout(newTimeoutMinutes);
                        timeoutChanged = true;
                    }
                }
                
                this.app.ui.showAlert('Configuration saved successfully!', 'success');
                
                // If critical changes were made, disconnect and show reconnect UI
                if (hasCriticalChanges || timeoutChanged) {
                    this.handleCriticalConfigChange();
                } else {
                    this.app.ui.updateStatus('Configuration saved', 'disconnected');
                    
                    // Reload configuration to update indicators
                    await this.loadConfiguration();
                    
                    // Check if we have connection credentials and show auto-connect option
                    if (this.hasConnectionCredentials()) {
                        this.showAutoConnectOption();
                    }
                }
            } else {
                this.app.ui.showAlert('Failed to save configuration', 'danger');
                this.app.ui.updateStatus('Failed to save configuration', 'disconnected');
            }
        } catch (error) {
            console.error('Failed to save configuration:', error);
            this.app.ui.showAlert('Failed to save configuration', 'danger');
            this.app.ui.updateStatus('Failed to save configuration', 'disconnected');
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
        if (this.app.websocket.isWebSocketConnected) {
            this.app.websocket.disconnectWebSocket();
        }
        
        // Close the configuration modal
        const configModal = bootstrap.Modal.getInstance(document.getElementById('configModal'));
        if (configModal) {
            configModal.hide();
        }
        
        // Update status to show config-changed state
        this.app.ui.updateStatus('Configuration updated - reconnection required', 'config-changed');
        
        // Show reconnect notification
        this.app.ui.showAlert('Configuration changes saved! Please reconnect to apply the new settings.', 'info');
        
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

    initializeConfigListeners() {
        this.addConfigFieldListeners();
        this.initializeDiscordConfigListeners();
        this.initializeWebSocketStatusListeners();
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

    updateWebSocketConfigStatusReadOnly() {
        // Same as updateWebSocketConfigStatus but doesn't reset activity timer
        // This is used when opening config modal to check status without extending session
        this.updateWebSocketConfigStatus();
        // Also load WebSocket status for connections count
        this.loadWebSocketStatus();
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
        } else if (this.app.websocket.lastConnectionError && !this.app.websocket.isWebSocketConnected) {
            // Show websocket connection errors prominently
            statusIndicator.className = 'status-indicator status-disconnected';
            statusText.textContent = 'WebSocket Connection Failed';
            
            const sshConnected = this.app.currentState?.connected || false;
            if (sshConnected) {
                statusDetails.innerHTML = `
                    <i class="bi bi-exclamation-triangle text-warning"></i> 
                    Server connected but WebSocket connection failed. Click refresh to retry connection.
                `;
            } else {
                statusDetails.innerHTML = `
                    <i class="bi bi-x-circle text-danger"></i> 
                    WebSocket connection failed. Check network connection and try again.
                `;
            }
        } else if (this.app.websocket.isWebSocketConnected) {
            statusIndicator.className = 'status-indicator status-connected';
            statusText.textContent = 'Connected';
            
            const timeoutMinutes = Math.floor(this.app.websocket.websocketTimeout / 60000);
            const timeSinceActivity = Math.floor((Date.now() - this.app.websocket.lastActivity) / 60000);
            const timeLeft = Math.max(0, timeoutMinutes - timeSinceActivity);
            
            statusDetails.innerHTML = `
                <i class="bi bi-check-circle"></i> 
                Real-time updates active. Timeout: ${timeoutMinutes} min. 
                Time left: ${timeLeft} min.
            `;
        } else if (this.app.websocket.wasAutoDisconnected) {
            statusIndicator.className = 'status-indicator status-auto-disconnected';
            statusText.textContent = 'Auto-disconnected';
            statusDetails.innerHTML = `
                <i class="bi bi-clock"></i> 
                Disconnected due to inactivity. Active transfers continue via background API monitoring.
            `;
        } else {
            statusIndicator.className = 'status-indicator status-disconnected';
            statusText.textContent = 'App Connection Not Active';
            
            // Check if SSH server is connected for better context
            const sshConnected = this.app.currentState?.connected || false;
            
            if (sshConnected) {
                statusDetails.innerHTML = `
                    <i class="bi bi-exclamation-triangle"></i> 
                    Server connected but real-time app connection not active. Click "Auto Connect" to enable WebSocket features.
                `;
            } else {
                statusDetails.innerHTML = `
                    <i class="bi bi-x-circle"></i> 
                    App connection not active. Click "Auto Connect" for real-time updates and full features.
                `;
            }
        }
        
        // Also load WebSocket connection count when updating status
        this.loadWebSocketStatus();
    }
    
    initializeDiscordConfigListeners() {
        // Discord notifications enabled toggle
        const discordEnabledToggle = document.getElementById('discordNotificationsEnabled');
        if (discordEnabledToggle) {
            discordEnabledToggle.addEventListener('change', (e) => {
                this.toggleDiscordFields(e.target.checked);
            });
        }
        
        // Test Discord notification button
        const testDiscordBtn = document.getElementById('testDiscordBtn');
        if (testDiscordBtn) {
            testDiscordBtn.addEventListener('click', () => {
                this.testDiscordNotification();
            });
        }
        
        // Load Discord settings button
        const loadDiscordSettingsBtn = document.getElementById('loadDiscordSettingsBtn');
        if (loadDiscordSettingsBtn) {
            loadDiscordSettingsBtn.addEventListener('click', () => {
                this.loadDiscordSettings();
            });
        }
        
        // Load Discord settings on config modal open
        const configModal = document.getElementById('configModal');
        if (configModal) {
            configModal.addEventListener('shown.bs.modal', () => {
                this.loadDiscordSettings();
                this.loadWebhookSettings();
            });
        }
        
        // Update wait time display when input changes
        const seriesAnimeWaitTime = document.getElementById('seriesAnimeWaitTime');
        if (seriesAnimeWaitTime) {
            seriesAnimeWaitTime.addEventListener('input', () => {
                this.updateWaitTimeDisplay();
            });
        }
    }
    
    toggleDiscordFields(enabled) {
        // Get Discord configuration field containers
        const discordConfigFields = document.getElementById('discordConfigFields');
        const discordConfigFields2 = document.getElementById('discordConfigFields2');
        const discordConfigActions = document.getElementById('discordConfigActions');
        
        // Show/hide Discord configuration fields based on enabled state
        const displayValue = enabled ? '' : 'none';
        
        if (discordConfigFields) discordConfigFields.style.display = displayValue;
        if (discordConfigFields2) discordConfigFields2.style.display = displayValue;
        if (discordConfigActions) discordConfigActions.style.display = displayValue;
    }
    
    async loadDiscordSettings() {
        try {
            const response = await fetch('/api/discord/settings');
            const result = await response.json();
            
            if (result.status === 'success') {
                const settings = result.settings;
                
                // Populate Discord configuration fields
                const discordNotificationsEnabled = document.getElementById('discordNotificationsEnabled');
                const discordWebhookUrl = document.getElementById('discordWebhookUrl');
                const discordAppUrl = document.getElementById('discordAppUrl');
                const discordIconUrl = document.getElementById('discordIconUrl');
                const discordManualSyncThumbnailUrl = document.getElementById('discordManualSyncThumbnailUrl');
                
                if (discordNotificationsEnabled) discordNotificationsEnabled.checked = settings.enabled || false;
                if (discordWebhookUrl) discordWebhookUrl.value = settings.webhook_url || '';
                if (discordAppUrl) discordAppUrl.value = settings.app_url || 'http://localhost:5000';
                if (discordIconUrl) discordIconUrl.value = settings.icon_url || '';
                if (discordManualSyncThumbnailUrl) discordManualSyncThumbnailUrl.value = settings.manual_sync_thumbnail_url || '';
                
                // Update Discord field visibility based on enabled state
                this.toggleDiscordFields(settings.enabled || false);
                
                console.log('Discord settings loaded successfully');
            } else {
                console.error('Failed to load Discord settings:', result.message);
            }
        } catch (error) {
            console.error('Error loading Discord settings:', error);
        }
    }
    
    async saveDiscordSettings() {
        const discordNotificationsEnabled = document.getElementById('discordNotificationsEnabled')?.checked || false;
        const discordWebhookUrl = document.getElementById('discordWebhookUrl')?.value || '';
        const discordAppUrl = document.getElementById('discordAppUrl')?.value || 'http://localhost:5000';
        const discordIconUrl = document.getElementById('discordIconUrl')?.value || '';
        const discordManualSyncThumbnailUrl = document.getElementById('discordManualSyncThumbnailUrl')?.value || '';
        
        const discordData = {
            enabled: discordNotificationsEnabled,
            webhook_url: discordWebhookUrl,
            app_url: discordAppUrl,
            icon_url: discordIconUrl,
            manual_sync_thumbnail_url: discordManualSyncThumbnailUrl
        };
        
        try {
            const response = await fetch('/api/discord/settings', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(discordData)
            });
            
            const result = await response.json();
            
            if (result.status === 'success') {
                console.log('Discord settings saved successfully');
                return true;
            } else {
                console.error('Failed to save Discord settings:', result.message);
                this.app.ui.showAlert(`Failed to save Discord settings: ${result.message}`, 'danger');
                return false;
            }
        } catch (error) {
            console.error('Error saving Discord settings:', error);
            this.app.ui.showAlert(`Error saving Discord settings: ${error.message}`, 'danger');
            return false;
        }
    }
    
    async testDiscordNotification() {
        const testBtn = document.getElementById('testDiscordBtn');
        const originalText = testBtn.innerHTML;
        
        // Update button to show loading state
        testBtn.innerHTML = '<i class="bi bi-hourglass-split"></i> Testing...';
        testBtn.disabled = true;
        
        try {
            // First save current Discord settings
            const saveResult = await this.saveDiscordSettings();
            if (!saveResult) {
                return;
            }
            
            // Then test Discord notification
            const response = await fetch('/api/discord/test', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            
            const result = await response.json();
            
            if (result.status === 'success') {
                this.app.ui.showAlert(result.message, 'success');
            } else {
                this.app.ui.showAlert(`Discord test failed: ${result.message}`, 'danger');
            }
        } catch (error) {
            console.error('Error testing Discord notification:', error);
            this.app.ui.showAlert(`Error testing Discord notification: ${error.message}`, 'danger');
        } finally {
            // Restore button state
            testBtn.innerHTML = originalText;
            testBtn.disabled = false;
        }
    }
    
    initializeWebSocketStatusListeners() {
        // WebSocket status refresh button
        const refreshWsStatusBtn = document.getElementById('refreshWsStatusBtn');
        if (refreshWsStatusBtn) {
            refreshWsStatusBtn.addEventListener('click', () => {
                // Clear any previous websocket connection errors when refreshing
                this.app.websocket.clearConnectionError();
                
                // Try to reconnect websocket if not connected
                if (!this.app.websocket.isWebSocketConnected) {
                    this.app.websocket.connect();
                }
                
                // Update the status display
                this.updateWebSocketConfigStatus();
                this.loadWebSocketStatus();
            });
        }
    }
    
    async loadWebSocketStatus() {
        const refreshBtn = document.getElementById('refreshWsStatusBtn');
        const connectionsCountEl = document.getElementById('wsActiveConnectionsCount');
        const statusDetailsEl = document.getElementById('wsConfigStatusDetails');
        
        // Show loading state
        if (refreshBtn) {
            const originalIcon = refreshBtn.innerHTML;
            refreshBtn.innerHTML = '<i class="bi bi-hourglass-split"></i>';
            refreshBtn.disabled = true;
        }
        
        try {
            const response = await fetch('/api/websocket/status');
            const result = await response.json();
            
            if (result.status === 'success') {
                const wsStatus = result.websocket_status;
                
                // Update connections count badge
                if (connectionsCountEl) {
                    connectionsCountEl.textContent = wsStatus.active_connections;
                    connectionsCountEl.style.display = 'inline-block';
                    
                    // Update badge color based on connection count
                    connectionsCountEl.className = 'badge ms-2';
                    if (wsStatus.active_connections === 0) {
                        connectionsCountEl.classList.add('bg-secondary');
                        connectionsCountEl.title = 'No active WebSocket connections';
                    } else if (wsStatus.active_connections === 1) {
                        connectionsCountEl.classList.add('bg-success');
                        connectionsCountEl.title = '1 active WebSocket connection';
                    } else {
                        connectionsCountEl.classList.add('bg-info');
                        connectionsCountEl.title = `${wsStatus.active_connections} active WebSocket connections`;
                    }
                }
                
                // Enhance status details with connection information
                if (statusDetailsEl && wsStatus.active_connections > 0) {
                    const existingContent = statusDetailsEl.innerHTML;
                    let connectionInfo = '';
                    
                    if (wsStatus.active_connections === 1) {
                        const conn = wsStatus.connection_details[0];
                        connectionInfo = ` Connected for ${conn.connected_minutes_ago}m, last activity ${conn.last_activity_minutes_ago}m ago.`;
                    } else {
                        connectionInfo = ` ${wsStatus.active_connections} active connections.`;
                    }
                    
                    // Only append connection info if it's not already there
                    if (!existingContent.includes('Connected for') && !existingContent.includes('active connections')) {
                        statusDetailsEl.innerHTML = existingContent + connectionInfo;
                    }
                }
                
                console.log('WebSocket Status:', wsStatus);
                
            } else {
                console.error('Failed to load WebSocket status:', result.message);
                if (connectionsCountEl) {
                    connectionsCountEl.textContent = '?';
                    connectionsCountEl.className = 'badge bg-warning ms-2';
                    connectionsCountEl.style.display = 'inline-block';
                    connectionsCountEl.title = 'Failed to load WebSocket status';
                }
            }
        } catch (error) {
            console.error('Error loading WebSocket status:', error);
            if (connectionsCountEl) {
                connectionsCountEl.textContent = '!';
                connectionsCountEl.className = 'badge bg-danger ms-2';
                connectionsCountEl.style.display = 'inline-block';
                connectionsCountEl.title = 'Error loading WebSocket status';
            }
        } finally {
            // Restore button state
            if (refreshBtn) {
                refreshBtn.innerHTML = '<i class="bi bi-arrow-clockwise"></i>';
                refreshBtn.disabled = false;
            }
        }
    }
    
    async loadWebhookSettings() {
        try {
            const response = await fetch('/api/webhook/settings');
            const result = await response.json();
            
            if (result.status === 'success') {
                const settings = result.settings;
                
                // Populate series/anime wait time field
                const seriesAnimeWaitTime = document.getElementById('seriesAnimeWaitTime');
                if (seriesAnimeWaitTime) {
                    seriesAnimeWaitTime.value = settings.series_anime_sync_wait_time || 60;
                    this.updateWaitTimeDisplay();
                }
                
                console.log('Webhook settings loaded successfully');
            } else {
                console.error('Failed to load webhook settings:', result.message);
            }
        } catch (error) {
            console.error('Error loading webhook settings:', error);
        }
    }
    
    async saveWebhookSettings() {
        const seriesAnimeWaitTime = document.getElementById('seriesAnimeWaitTime')?.value || 60;
        
        const webhookData = {
            series_anime_sync_wait_time: parseInt(seriesAnimeWaitTime)
        };
        
        try {
            const response = await fetch('/api/webhook/settings', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(webhookData)
            });
            
            const result = await response.json();
            
            if (result.status === 'success') {
                console.log('Webhook settings saved successfully');
                return true;
            } else {
                console.error('Failed to save webhook settings:', result.message);
                this.app.ui.showAlert(`Failed to save webhook settings: ${result.message}`, 'danger');
                return false;
            }
        } catch (error) {
            console.error('Error saving webhook settings:', error);
            this.app.ui.showAlert(`Error saving webhook settings: ${error.message}`, 'danger');
            return false;
        }
    }
    
    updateWaitTimeDisplay() {
        const seriesAnimeWaitTime = document.getElementById('seriesAnimeWaitTime');
        const displayEl = document.getElementById('seriesAnimeWaitTimeDisplay');
        
        if (seriesAnimeWaitTime && displayEl) {
            const seconds = parseInt(seriesAnimeWaitTime.value) || 60;
            
            // Convert seconds to human-readable format
            if (seconds < 60) {
                displayEl.textContent = `${seconds} seconds`;
            } else if (seconds < 3600) {
                const minutes = Math.floor(seconds / 60);
                const remainingSeconds = seconds % 60;
                if (remainingSeconds === 0) {
                    displayEl.textContent = `${minutes} minute${minutes !== 1 ? 's' : ''}`;
                } else {
                    displayEl.textContent = `${minutes} minute${minutes !== 1 ? 's' : ''} ${remainingSeconds} second${remainingSeconds !== 1 ? 's' : ''}`;
                }
            } else {
                const hours = Math.floor(seconds / 3600);
                const minutes = Math.floor((seconds % 3600) / 60);
                displayEl.textContent = `${hours} hour${hours !== 1 ? 's' : ''} ${minutes} minute${minutes !== 1 ? 's' : ''}`;
            }
        }
    }
}
