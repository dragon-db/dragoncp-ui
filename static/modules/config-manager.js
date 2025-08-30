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
        } else if (this.app.websocket.isWebSocketConnected) {
            statusIndicator.className = 'status-indicator status-connected';
            statusText.textContent = 'Connected';
            
            const timeoutMinutes = Math.floor(this.app.websocket.websocketTimeout / 60000);
            // Use the same calculation as status bar for consistency
            const timeLeft = this.app.websocket.getTimeRemaining();
            
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
            statusText.textContent = 'Disconnected';
            statusDetails.innerHTML = `
                <i class="bi bi-x-circle"></i> 
                App connection not active. Click "Auto Connect" for real-time updates and full features.
            `;
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
            statusText.textContent = 'Disconnected';
            statusDetails.innerHTML = `
                <i class="bi bi-x-circle"></i> 
                App connection not active. Click "Auto Connect" for real-time updates and full features.
            `;
        }
    }
}
