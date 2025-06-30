/**
 * DragonCP Web UI - Frontend JavaScript
 * Handles all UI interactions, API calls, and WebSocket communication
 */

class DragonCPUI {
    constructor() {
        this.socket = io();
        this.currentState = {
            connected: false,
            mediaType: null,
            selectedFolder: null,
            selectedSeason: null,
            breadcrumb: []
        };
        this.activeTransfers = new Map();
        
        this.initializeEventListeners();
        this.initializeWebSocket();
        this.loadConfiguration();
        this.initializeConnection();
    }

    initializeEventListeners() {
        // Status bar buttons
        document.getElementById('autoConnectBtn').addEventListener('click', () => {
            this.autoConnect();
        });

        document.getElementById('disconnectBtn').addEventListener('click', () => {
            this.disconnectFromServer();
        });

        // Configuration button
        document.getElementById('configBtn').addEventListener('click', () => {
            const configModal = new bootstrap.Modal(document.getElementById('configModal'));
            configModal.show();
        });

        // Configuration modal
        document.getElementById('saveConfig').addEventListener('click', () => {
            this.saveConfiguration();
        });

        document.getElementById('resetConfigBtn').addEventListener('click', () => {
            this.resetConfiguration();
        });

        // Add input change listeners for config fields
        this.addConfigFieldListeners();
    }

    addConfigFieldListeners() {
        // Add listeners to all config input fields to show modification indicators
        const configInputs = document.querySelectorAll('#configForm input');
        configInputs.forEach(input => {
            input.addEventListener('input', () => {
                this.updateConfigFieldIndicator(input);
            });
        });
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
        });

        this.socket.on('transfer_progress', (data) => {
            this.updateTransferProgress(data);
        });

        this.socket.on('transfer_complete', (data) => {
            this.handleTransferComplete(data);
        });

        this.socket.on('disconnect', () => {
            console.log('WebSocket disconnected');
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
            { id: 'animeDestPath', name: 'ANIME_DEST_PATH', label: 'Anime Destination', value: config.ANIME_DEST_PATH, envValue: envConfig.ANIME_DEST_PATH, placeholder: '/local/path/to/anime' }
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
                this.showAlert('Configuration saved successfully!', 'success');
                this.updateStatus('Configuration saved', 'disconnected');
                
                // Reload configuration to update indicators
                await this.loadConfiguration();
                
                // Check if we have connection credentials and show auto-connect option
                if (this.hasConnectionCredentials()) {
                    this.showAutoConnectOption();
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

    async autoConnect() {
        try {
            this.updateStatus('Connecting to server...', 'connecting');
            
            const response = await fetch('/api/auto-connect');
            const result = await response.json();
            
            if (result.status === 'success') {
                this.updateStatus('Connected to server', 'connected');
                this.currentState.connected = true;
                this.showMediaInterface();
                this.loadMediaTypes();
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
            const response = await fetch('/api/disconnect');
            const result = await response.json();
            
            if (result.status === 'success') {
                this.updateStatus('Disconnected from server', 'disconnected');
                this.currentState.connected = false;
                this.hideMediaInterface();
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
        
        // Update status indicator
        statusIndicator.className = 'status-indicator';
        if (status === 'connected') {
            statusIndicator.classList.add('status-connected');
        } else if (status === 'connecting') {
            statusIndicator.classList.add('status-connecting');
        } else {
            statusIndicator.classList.add('status-disconnected');
        }
        
        // Update message
        statusMessage.textContent = message;
        
        // Update navbar status
        const navbarStatus = document.getElementById('connectionStatus');
        const navbarText = document.getElementById('connectionText');
        
        navbarStatus.className = 'status-indicator';
        if (status === 'connected') {
            navbarStatus.classList.add('status-connected');
            navbarText.textContent = 'Connected';
            autoConnectBtn.style.display = 'none';
            disconnectBtn.style.display = 'inline-block';
        } else if (status === 'connecting') {
            navbarStatus.classList.add('status-connecting');
            navbarText.textContent = 'Connecting...';
            autoConnectBtn.style.display = 'none';
            disconnectBtn.style.display = 'none';
        } else {
            navbarStatus.classList.add('status-disconnected');
            navbarText.textContent = 'Disconnected';
            autoConnectBtn.style.display = 'inline-block';
            disconnectBtn.style.display = 'none';
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
                        <p class="card-text text-muted">${mediaType.path || 'Path not configured'}</p>
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
                    <button class="btn btn-outline-primary" onclick="dragonCP.selectFolder('${folder}', '${mediaType}')">
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
                    <button class="btn btn-outline-primary" onclick="dragonCP.selectSeason('${season}', '${mediaType}', '${folderName}')">
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
                description: seasonName ? `Sync entire ${seasonName} folder` : `Sync entire ${folderName} folder`,
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
                this.activeTransfers.set(result.transfer_id, {
                    id: result.transfer_id,
                    type: transferType,
                    mediaType,
                    folderName,
                    seasonName,
                    status: 'running',
                    startTime: new Date()
                });
                this.updateTransferDisplay();
                document.getElementById('transferCard').style.display = 'block';
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
                    <button class="btn btn-outline-success" onclick="dragonCP.downloadEpisode('${episode}', '${mediaType}', '${folderName}', '${seasonName}')">
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
                this.activeTransfers.set(result.transfer_id, {
                    id: result.transfer_id,
                    type: 'file',
                    mediaType,
                    folderName,
                    seasonName,
                    episodeName,
                    status: 'running',
                    startTime: new Date()
                });
                this.updateTransferDisplay();
                document.getElementById('transferCard').style.display = 'block';
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
        const transfer = this.activeTransfers.get(data.transfer_id);
        if (transfer) {
            transfer.progress = data.progress;
            transfer.logs = data.logs;
            this.updateTransferDisplay();
            this.updateTransferLog(data.logs);
        }
    }

    handleTransferComplete(data) {
        const transfer = this.activeTransfers.get(data.transfer_id);
        if (transfer) {
            transfer.status = data.status;
            transfer.progress = data.message;
            this.updateTransferDisplay();
            
            if (data.status === 'completed') {
                this.showAlert('Transfer completed successfully!', 'success');
            } else {
                this.showAlert(`Transfer failed: ${data.message}`, 'danger');
            }
        }
    }

    updateTransferDisplay() {
        const container = document.getElementById('activeTransfers');
        container.innerHTML = '';

        if (this.activeTransfers.size === 0) {
            container.innerHTML = '<div class="text-center text-muted">No active transfers</div>';
            return;
        }

        this.activeTransfers.forEach((transfer, id) => {
            const card = document.createElement('div');
            card.className = 'card mb-3';
            
            const statusClass = transfer.status === 'running' ? 'text-primary' : 
                              transfer.status === 'completed' ? 'text-success' : 'text-danger';
            
            card.innerHTML = `
                <div class="card-body">
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <h6 class="card-title mb-0">
                            <i class="bi bi-${transfer.type === 'file' ? 'file-play' : 'folder'}"></i>
                            ${transfer.folderName}${transfer.seasonName ? '/' + transfer.seasonName : ''}
                            ${transfer.episodeName ? '/' + transfer.episodeName : ''}
                        </h6>
                        <span class="badge bg-${transfer.status === 'running' ? 'primary' : 
                                               transfer.status === 'completed' ? 'success' : 'danger'}">
                            ${transfer.status}
                        </span>
                    </div>
                    <div class="progress mb-2">
                        <div class="progress-bar ${transfer.status === 'running' ? 'progress-bar-striped progress-bar-animated' : ''}" 
                             style="width: ${transfer.status === 'completed' ? '100%' : '50%'}"></div>
                    </div>
                    <small class="text-muted">${transfer.progress || 'Initializing...'}</small>
                    ${transfer.status === 'running' ? 
                        `<button class="btn btn-sm btn-outline-danger float-end" onclick="dragonCP.cancelTransfer('${id}')">
                            <i class="bi bi-x-circle"></i> Cancel
                        </button>` : ''
                    }
                </div>
            `;
            
            container.appendChild(card);
        });
    }

    updateTransferLog(logs) {
        const logContainer = document.getElementById('transferLog');
        logContainer.innerHTML = logs.map(log => `<div>${log}</div>`).join('');
        logContainer.scrollTop = logContainer.scrollHeight;
    }

    async cancelTransfer(transferId) {
        try {
            const response = await fetch(`/api/transfer/${transferId}/cancel`, {
                method: 'POST'
            });
            
            const result = await response.json();
            
            if (result.status === 'success') {
                this.showAlert('Transfer cancelled', 'warning');
                this.activeTransfers.delete(transferId);
                this.updateTransferDisplay();
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
        const alertDiv = document.createElement('div');
        alertDiv.className = `alert alert-${type} alert-dismissible fade show position-fixed`;
        alertDiv.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px;';
        
        alertDiv.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        
        document.body.appendChild(alertDiv);
        
        // Auto-remove after 5 seconds
        setTimeout(() => {
            if (alertDiv.parentNode) {
                alertDiv.remove();
            }
        }, 5000);
    }

    hideMediaInterface() {
        document.getElementById('mediaCard').style.display = 'none';
        document.getElementById('folderCard').style.display = 'none';
        document.getElementById('transferCard').style.display = 'none';
        document.getElementById('logCard').style.display = 'none';
    }

    showMediaInterface() {
        document.getElementById('mediaCard').style.display = 'block';
        document.getElementById('folderCard').style.display = 'none';
        document.getElementById('transferCard').style.display = 'none';
        document.getElementById('logCard').style.display = 'none';
    }

    async initializeConnection() {
        try {
            this.updateStatus('Initializing application...', 'connecting');
            
            // Try to auto-connect first
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
}

// Initialize the application when the page loads
let dragonCP;
document.addEventListener('DOMContentLoaded', () => {
    dragonCP = new DragonCPUI();
}); 