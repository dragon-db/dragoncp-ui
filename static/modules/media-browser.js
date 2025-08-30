/**
 * Media Browser Module
 * Handles media type browsing, folder navigation, season management, and episode sync
 */
export class MediaBrowser {
    constructor(app) {
        this.app = app;
        
        // Browse Media state
        this.currentMediaType = null;
        this.currentPath = [];
        
        // Browse Media search and sort
        this.allFolders = []; // Store all folder data for filtering/sorting
        this.filteredFolders = []; // Store currently filtered/sorted folders
        this.searchTerm = '';
        this.sortOption = 'recent'; // 'recent' or 'alphabetical'
        
        this.currentTransferContext = null;
        this.initializeEventListeners();
    }

    initializeEventListeners() {
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
                this.app.ui.expandAllCards();
                button.classList.remove('collapsed');
                icon.className = 'bi bi-chevron-up';
                textSpan.textContent = ' Collapse All';
            } else {
                // Currently expanded, collapse all
                this.app.ui.collapseAllExcept();
                button.classList.add('collapsed');
                icon.className = 'bi bi-chevron-down';
                textSpan.textContent = ' Expand All';
            }
        });
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
                this.app.ui.showAlert('Failed to load media types', 'danger');
            }
        } catch (error) {
            console.error('Failed to load media types:', error);
            this.app.ui.showAlert('Failed to load media types', 'danger');
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
        this.app.currentState.mediaType = mediaType;
        this.app.currentState.breadcrumb = [mediaType];
        this.currentPath = [];
        
        // Reset navigation state when switching media types
        this.app.currentState.viewingSeasons = false;
        this.app.currentState.seasonsFolder = null;
        this.app.currentState.viewingTransferOptions = false;
        this.app.currentState.selectedFolder = null;
        this.app.currentState.selectedSeason = null;
        
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
            this.app.ui.showFolderLoading(true);
            
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
                this.app.ui.showFolderLoading(false);
                
                // Load sync status asynchronously and update UI
                this.loadSyncStatusAsync(mediaType);
                
            } else {
                this.app.ui.showAlert(foldersResult.message || 'Failed to load folders', 'danger');
                this.app.ui.showFolderLoading(false);
            }
        } catch (error) {
            console.error('Failed to load folders:', error);
            this.app.ui.showAlert('Failed to load folders', 'danger');
            this.app.ui.showFolderLoading(false);
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
            const syncStatusBadge = this.app.ui.generateSyncStatusBadge(folder.syncStatus);
            
            item.innerHTML = `
                <div class="d-flex align-items-center flex-grow-1">
                    <i class="bi bi-folder me-2"></i>
                    <div class="flex-grow-1">
                        <div class="d-flex align-items-center gap-2">
                            <span>${this.app.ui.escapeHtml(folder.name)}</span>
                            ${syncStatusBadge}
                        </div>
                        ${dateInfo ? `<div>${dateInfo}</div>` : ''}
                    </div>
                </div>
                <div class="btn-group btn-group-sm">
                    <button class="btn btn-outline-primary" onclick="dragonCP.selectFolder('${this.app.ui.escapeJavaScriptString(folder.name)}', '${this.currentMediaType}')">
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
        this.app.currentState.selectedFolder = folderName;
        this.app.currentState.breadcrumb.push(folderName);
        
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
            this.app.ui.showFolderLoading(true);
            
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
                this.app.ui.showFolderLoading(false);
                
                // Load sync status asynchronously for this specific folder
                this.loadSeasonSyncStatusAsync(mediaType, folderName);
                
            } else {
                this.app.ui.showAlert(seasonsResult.message || 'Failed to load seasons', 'danger');
                this.app.ui.showFolderLoading(false);
            }
        } catch (error) {
            console.error('Failed to load seasons:', error);
            this.app.ui.showAlert('Failed to load seasons', 'danger');
            this.app.ui.showFolderLoading(false);
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
        this.app.currentState.viewingSeasons = true;
        this.app.currentState.seasonsFolder = folderName;
        
        // Display seasons directly instead of using filterAndSortFolders
        this.displaySeasons(seasonData, mediaType, folderName);
        
        // Override the folder select click to use season select instead
        this.overrideForSeasons(mediaType, folderName);
    }

    displaySeasons(seasons, mediaType, folderName) {
        const container = document.getElementById('folderList');
        container.innerHTML = '';

        if (seasons.length === 0) {
            container.innerHTML = `<div class="text-center text-muted p-3">No seasons found for ${this.app.ui.escapeHtml(folderName)}</div>`;
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
            const syncStatusBadge = this.app.ui.generateSyncStatusBadge(season.syncStatus);
            
            item.innerHTML = `
                <div class="d-flex align-items-center flex-grow-1">
                    <i class="bi bi-collection me-2"></i>
                    <div class="flex-grow-1">
                        <div class="d-flex align-items-center gap-2">
                            <span>${this.app.ui.escapeHtml(season.name)}</span>
                            ${syncStatusBadge}
                        </div>
                        ${dateInfo ? `<div>${dateInfo}</div>` : ''}
                    </div>
                </div>
                <div class="btn-group btn-group-sm">
                    <button class="btn btn-outline-primary" onclick="dragonCP.selectSeason('${this.app.ui.escapeJavaScriptString(season.name)}', '${mediaType}', '${this.app.ui.escapeJavaScriptString(folderName)}')">
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
        this.app.currentState.selectedSeason = seasonName;
        this.app.currentState.breadcrumb.push(seasonName);
        
        this.showTransferOptions(mediaType, folderName, seasonName);
        this.updateBrowseMediaBreadcrumb();
    }

    showTransferOptions(mediaType, folderName, seasonName = null) {
        const container = document.getElementById('folderList');
        container.innerHTML = '';
        
        // Hide refresh button when showing transfer options
        this.hideBrowseControls();
        
        // Set state to indicate we're viewing transfer options
        this.app.currentState.viewingTransferOptions = true;

        const options = [
            {
                title: 'Sync Entire Folder',
                description: seasonName ? `Sync entire ${this.app.ui.escapeHtml(seasonName)} folder` : `Sync entire ${this.app.ui.escapeHtml(folderName)} folder`,
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
                this.app.ui.showAlert('Transfer started successfully!', 'success');
                // Refresh the database-based transfer list immediately
                this.app.transfers.loadActiveTransfers();
                document.getElementById('logCard').style.display = 'block';
            } else {
                this.app.ui.showAlert(result.message || 'Failed to start transfer', 'danger');
            }
        } catch (error) {
            console.error('Transfer error:', error);
            this.app.ui.showAlert('Failed to start transfer', 'danger');
        }
    }

    async showEpisodeSync(mediaType, folderName, seasonName) {
        try {
            const response = await fetch(`/api/episodes/${mediaType}/${encodeURIComponent(folderName)}/${encodeURIComponent(seasonName)}`);
            const result = await response.json();
            
            if (result.status === 'success') {
                this.renderEpisodeSync(result.episodes, mediaType, folderName, seasonName);
            } else {
                this.app.ui.showAlert(result.message || 'Failed to load episodes', 'danger');
            }
        } catch (error) {
            console.error('Failed to load episodes:', error);
            this.app.ui.showAlert('Failed to load episodes', 'danger');
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
                    <button class="btn btn-outline-success" onclick="dragonCP.downloadEpisode('${this.app.ui.escapeJavaScriptString(episode)}', '${mediaType}', '${this.app.ui.escapeJavaScriptString(folderName)}', '${this.app.ui.escapeJavaScriptString(seasonName)}')">
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
                this.app.ui.showAlert(`Downloading episode: ${episodeName}`, 'success');
                // Refresh the database-based transfer list immediately
                this.app.transfers.loadActiveTransfers();
                document.getElementById('logCard').style.display = 'block';
            } else {
                this.app.ui.showAlert(result.message || 'Failed to start download', 'danger');
            }
        } catch (error) {
            console.error('Download error:', error);
            this.app.ui.showAlert('Failed to start download', 'danger');
        }
    }

    async showSingleEpisodeDownload(mediaType, folderName, seasonName) {
        await this.showEpisodeSync(mediaType, folderName, seasonName);
    }

    // Navigation methods
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
        this.app.currentState.breadcrumb = [this.currentMediaType];
        this.app.currentState.selectedFolder = null;
        this.app.currentState.selectedSeason = null;
        this.loadFolders(this.currentMediaType);
        this.updateBrowseMediaBreadcrumb();
    }

    navigateToFolderLevel(breadcrumbIndex) {
        // Truncate breadcrumb to the target level
        this.app.currentState.breadcrumb = this.app.currentState.breadcrumb.slice(0, breadcrumbIndex + 1);
        
        if (breadcrumbIndex === 1) {
            // This is a folder name (like "BreakingBad")
            const folderName = this.app.currentState.breadcrumb[1];
            this.app.currentState.selectedFolder = folderName;
            this.app.currentState.selectedSeason = null;
            
            if (this.currentMediaType === 'tvshows' || this.currentMediaType === 'anime') {
                // Load seasons for this folder
                this.loadSeasons(this.currentMediaType, folderName);
            } else {
                // For movies/backup, show transfer options
                this.showTransferOptions(this.currentMediaType, folderName);
            }
        } else if (breadcrumbIndex === 2) {
            // This is typically a season name (like "Season1")
            const folderName = this.app.currentState.breadcrumb[1];
            const seasonName = this.app.currentState.breadcrumb[2];
            this.app.currentState.selectedFolder = folderName;
            this.app.currentState.selectedSeason = seasonName;
            
            // Show transfer options for this season
            this.showTransferOptions(this.currentMediaType, folderName, seasonName);
        } else {
            // Handle deeper nesting if needed
            const folderPath = this.app.currentState.breadcrumb.slice(1, breadcrumbIndex + 1).join('/');
            this.loadFolders(this.currentMediaType, folderPath);
        }
        
        this.updateBrowseMediaBreadcrumb();
    }

    resetBrowseMediaState() {
        // Reset to media type selection view
        this.showMediaTypeView();
        this.currentMediaType = null;
        this.currentPath = [];
        
        // Reset navigation state
        this.app.currentState.viewingSeasons = false;
        this.app.currentState.seasonsFolder = null;
        this.app.currentState.viewingTransferOptions = false;
        this.app.currentState.selectedFolder = null;
        this.app.currentState.selectedSeason = null;
        this.app.currentState.breadcrumb = [];
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
            const isMediaTypeActive = !this.app.currentState.breadcrumb || this.app.currentState.breadcrumb.length === 1;
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
            if (this.app.currentState.breadcrumb && this.app.currentState.breadcrumb.length > 1) {
                this.app.currentState.breadcrumb.slice(1).forEach((item, index) => {
                    const li = document.createElement('li');
                    const breadcrumbIndex = index + 1; // This is the actual index in the breadcrumb array
                    const isLast = breadcrumbIndex === this.app.currentState.breadcrumb.length - 1;
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

    // Sync Status Methods
    async refreshSyncStatus() {
        // Don't refresh if we're viewing transfer options
        if (this.app.currentState.viewingTransferOptions) {
            return;
        }
        
        // Check current context - are we viewing seasons of a specific series?
        if (this.app.currentState.viewingSeasons && this.app.currentState.seasonsFolder && this.currentMediaType) {
            // We're in a season view, refresh only this series' sync status
            await this.loadSeasonSyncStatusAsync(this.currentMediaType, this.app.currentState.seasonsFolder);
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
