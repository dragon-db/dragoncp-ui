/**
 * Webhook Manager Module
 * Handles movie, series, and anime webhook notifications, auto-sync settings, and sync operations
 */
export class WebhookManager {
    constructor(app) {
        this.app = app;
        this.notifications = [];
        this.autoSyncMovies = false;
        this.autoSyncSeries = false;
        this.autoSyncAnime = false;
        
        this.initializeEventListeners();
        this.loadWebhookSettings();
    }

    initializeEventListeners() {
        // Main sync buttons
        document.getElementById('refreshSyncBtn').addEventListener('click', () => {
            this.loadNotifications();
        });

        // Auto-sync toggle buttons
        document.getElementById('autoSyncMoviesToggle').addEventListener('click', (e) => {
            e.preventDefault();
            this.toggleAutoSync('movies');
        });
        
        document.getElementById('autoSyncSeriesToggle').addEventListener('click', (e) => {
            e.preventDefault();
            this.toggleAutoSync('series');
        });
        
        document.getElementById('autoSyncAnimeToggle').addEventListener('click', (e) => {
            e.preventDefault();
            this.toggleAutoSync('anime');
        });
    }

    async loadWebhookSettings() {
        try {
            const response = await fetch('/api/webhook/settings');
            const result = await response.json();
            
            if (result.status === 'success') {
                this.autoSyncMovies = result.settings.auto_sync_movies;
                this.autoSyncSeries = result.settings.auto_sync_series;
                this.autoSyncAnime = result.settings.auto_sync_anime;
                this.updateAutoSyncButtons();
            }
        } catch (error) {
            console.error('Failed to load webhook settings:', error);
        }
    }

    async toggleAutoSync(mediaType) {
        try {
            const currentState = mediaType === 'movies' ? this.autoSyncMovies : 
                                mediaType === 'series' ? this.autoSyncSeries : 
                                this.autoSyncAnime;
            const newState = !currentState;
            
            const payload = {};
            payload[`auto_sync_${mediaType}`] = newState;
            
            const response = await fetch('/api/webhook/settings', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });
            
            const result = await response.json();
            
            if (result.status === 'success') {
                if (mediaType === 'movies') {
                    this.autoSyncMovies = newState;
                } else if (mediaType === 'series') {
                    this.autoSyncSeries = newState;
                } else {
                    this.autoSyncAnime = newState;
                }
                
                this.updateAutoSyncButtons();
                
                const mediaName = mediaType.charAt(0).toUpperCase() + mediaType.slice(1);
                const message = newState ? 
                    `${mediaName} auto-sync enabled. New ${mediaType} will sync automatically.` : 
                    `${mediaName} auto-sync disabled. ${mediaName} require manual sync.`;
                this.app.ui.showAlert(message, 'info');
            } else {
                this.app.ui.showAlert('Failed to update auto-sync setting', 'danger');
            }
        } catch (error) {
            console.error('Failed to toggle auto-sync:', error);
            this.app.ui.showAlert('Failed to update auto-sync setting', 'danger');
        }
    }

    updateAutoSyncButtons() {
        this.updateToggleButton('autoSyncMoviesToggle', this.autoSyncMovies);
        this.updateToggleButton('autoSyncSeriesToggle', this.autoSyncSeries);
        this.updateToggleButton('autoSyncAnimeToggle', this.autoSyncAnime);
    }
    
    updateToggleButton(buttonId, isEnabled) {
        const button = document.getElementById(buttonId);
        if (!button) return;
        
        const icon = button.querySelector('i');
        
        if (isEnabled) {
            icon.className = 'bi bi-toggle-on text-success';
            button.classList.remove('btn-outline-secondary');
            button.classList.add('text-success');
        } else {
            icon.className = 'bi bi-toggle-off';
            button.classList.add('btn-outline-secondary');
            button.classList.remove('text-success');
        }
    }

    async loadNotifications() {
        // Use refresh button spinner instead of in-card loading notice
        const refreshBtn = document.getElementById('refreshSyncBtn');
        const originalHtml = refreshBtn ? refreshBtn.innerHTML : null;
        if (refreshBtn) {
            refreshBtn.innerHTML = '<i class="bi bi-arrow-clockwise spinning"></i>';
            refreshBtn.disabled = true;
        }
        try {
            const response = await fetch('/api/webhook/notifications?limit=50');
            const result = await response.json();
            
            if (result.status === 'success') {
                this.notifications = result.notifications;
                this.updateNotificationsDisplay();
                this.updateNotificationCount();
                
                // Show the card
                document.getElementById('movieSyncCard').style.display = 'block';
            } else {
                console.error('Failed to load notifications:', result.message);
                this.app.ui.showAlert('Failed to load movie notifications', 'danger');
            }
        } catch (error) {
            console.error('Failed to load notifications:', error);
            this.app.ui.showAlert('Failed to load movie notifications', 'danger');
        } finally {
            if (refreshBtn) {
                refreshBtn.innerHTML = originalHtml || '<i class="bi bi-arrow-clockwise"></i>';
                refreshBtn.disabled = false;
            }
        }
    }

    updateNotificationsDisplay() {
        const container = document.getElementById('movieNotificationsList');
        const noNotificationsMessage = document.getElementById('noNotificationsMessage');
        
        container.innerHTML = '';
        
        if (this.notifications.length === 0) {
            noNotificationsMessage.style.display = 'block';
            return;
        }
        
        noNotificationsMessage.style.display = 'none';
        
        // Group series/anime notifications by series_title_slug and season_number
        const grouped = this.groupNotifications(this.notifications);
        
        grouped.forEach(item => {
            const notificationCard = this.createNotificationCard(item);
            container.appendChild(notificationCard);
        });
    }
    
    groupNotifications(notifications) {
        const groups = new Map();
        const standalone = [];
        
        notifications.forEach(notification => {
            const mediaType = notification.media_type || 'movie';
            
            // Only group series and anime, not movies
            if (mediaType === 'series' || mediaType === 'tvshows' || mediaType === 'anime') {
                const seriesKey = notification.series_title_slug || notification.series_title || 'unknown';
                const seasonNum = notification.season_number || 0;
                const groupKey = `${seriesKey}_S${seasonNum}`;
                
                if (!groups.has(groupKey)) {
                    groups.set(groupKey, {
                        isGroup: true,
                        groupKey: groupKey,
                        notifications: [],
                        mediaType: mediaType,
                        series_title: notification.series_title || notification.display_title,
                        series_title_slug: seriesKey,
                        season_number: seasonNum,
                        poster_url: notification.poster_url,
                        year: notification.year,
                        requested_by: notification.requested_by,
                        // Use the most recent notification's timestamp for sorting
                        created_at: notification.created_at,
                        tmdb_id: notification.tmdb_id,
                        imdb_id: notification.imdb_id,
                        tvdb_id: notification.tvdb_id
                    });
                }
                
                const group = groups.get(groupKey);
                group.notifications.push(notification);
                
                // Update created_at to the most recent notification time
                if (new Date(notification.created_at) > new Date(group.created_at)) {
                    group.created_at = notification.created_at;
                }
            } else {
                // Movies remain as standalone items
                standalone.push({
                    isGroup: false,
                    notification: notification
                });
            }
        });
        
        // Combine groups and standalone items
        const result = [...Array.from(groups.values()), ...standalone];
        
        // Sort by created_at (most recent first)
        result.sort((a, b) => {
            const timeA = a.isGroup ? new Date(a.created_at) : new Date(a.notification.created_at);
            const timeB = b.isGroup ? new Date(b.created_at) : new Date(b.notification.created_at);
            return timeB - timeA;
        });
        
        return result;
    }

    createNotificationCard(item) {
        // Handle both grouped and standalone notifications
        if (item.isGroup) {
            return this.createGroupedNotificationCard(item);
        } else {
            return this.createSingleNotificationCard(item.notification);
        }
    }
    
    createGroupedNotificationCard(group) {
        const cardElement = document.createElement('div');
        cardElement.className = 'movie-notification-card';
        cardElement.id = `notification-group-${group.groupKey}`;
        
        const mediaType = group.mediaType;
        const mediaIcon = this.getMediaIcon(mediaType);
        const displayTitle = group.series_title;
        const requestedBy = group.requested_by || 'Unknown';
        const timeAgo = this.app.ui.getTimeAgo(group.created_at);
        
        // Calculate aggregate status for the group
        const groupStatus = this.getGroupStatus(group.notifications);
        const statusClass = this.getStatusClass(groupStatus);
        const statusIcon = this.getStatusIcon(groupStatus);
        
        // Count episodes
        const episodeCount = group.notifications.length;
        const episodeText = episodeCount === 1 ? 'episode' : 'episodes';
        
        // Calculate total size
        const totalSize = group.notifications.reduce((sum, n) => sum + (n.release_size || 0), 0);
        const sizeFormatted = this.app.ui.humanReadableBytes(totalSize);
        
        // Create poster element
        const posterUrl = group.poster_url;
        const posterElement = posterUrl ? 
            `<img src="${this.app.ui.escapeHtml(posterUrl)}" 
                alt="${this.app.ui.escapeHtml(displayTitle)}" 
                class="movie-poster-thumb"
                onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
            <div class="movie-poster-thumb-placeholder" style="display: none;">
                <i class="${mediaIcon}" style="font-size: 1.5rem;"></i>
            </div>` : 
            `<div class="movie-poster-thumb-placeholder">
                <i class="${mediaIcon}" style="font-size: 1.5rem;"></i>
            </div>`;
        
        cardElement.innerHTML = `
            <div class="card-body">
                ${posterElement}
                <div class="movie-content">
                    <h6 class="movie-title mb-1">
                        <i class="${mediaIcon} me-2 disk-usage-icon"></i>
                        ${this.app.ui.escapeHtml(displayTitle)}
                        ${group.year ? ` <span class="text-muted">(${group.year})</span>` : ''}
                        <span class="badge bg-secondary ms-1">${this.getDisplayMediaType(mediaType)}</span>
                    </h6>
                    <div class="movie-meta">
                        <span class="requested-by">
                            <i class="bi bi-person-fill me-1"></i>
                            ${this.app.ui.escapeHtml(requestedBy)}
                        </span>
                        <span>
                            <i class="bi bi-collection me-1"></i>
                            Season ${group.season_number} · ${episodeCount} ${episodeText}
                        </span>
                        <span>
                            <i class="bi bi-hdd me-1"></i>
                            ${sizeFormatted}
                        </span>
                        <span>
                            <i class="bi bi-clock me-1"></i>
                            ${timeAgo}
                        </span>
                    </div>
                </div>
                <div class="movie-actions-section">
                    <div class="movie-status-badge">
                        <span class="badge ${statusClass}">
                            <i class="${statusIcon}"></i> ${groupStatus.toUpperCase()}
                        </span>
                    </div>
                    <div class="movie-all-actions">
                        ${this.createGroupActionButtons(group)}
                    </div>
                </div>
            </div>
        `;

        // Expose poster URL as CSS variable for mobile backdrop usage
        try {
            if (posterUrl) {
                cardElement.style.setProperty('--poster-url', `url("${posterUrl}")`);
            }
        } catch (e) {}
        
        return cardElement;
    }
    
    createSingleNotificationCard(notification) {
        const cardElement = document.createElement('div');
        cardElement.className = 'movie-notification-card';
        cardElement.id = `notification-${notification.notification_id}`;
        
        const statusClass = this.getStatusClass(notification.status);
        const statusIcon = this.getStatusIcon(notification.status);
        
        // Determine media type and get appropriate display values
        const mediaType = notification.media_type || 'movie';
        const displayTitle = this.getDisplayTitle(notification);
        const mediaIcon = this.getMediaIcon(mediaType);
        const sizeFormatted = this.formatSize(notification);
        
        // Format requested by
        const requestedBy = notification.requested_by || 'Unknown';
        
        // Format time ago
        const timeAgo = this.app.ui.getTimeAgo(notification.created_at);
        
        // Create poster element
        const posterUrl = notification.poster_url;
        const posterElement = posterUrl ? 
            `<img src="${this.app.ui.escapeHtml(posterUrl)}" 
                alt="${this.app.ui.escapeHtml(displayTitle)}" 
                class="movie-poster-thumb"
                onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
            <div class="movie-poster-thumb-placeholder" style="display: none;">
                <i class="${mediaIcon}" style="font-size: 1.5rem;"></i>
            </div>` : 
            `<div class="movie-poster-thumb-placeholder">
                <i class="${mediaIcon}" style="font-size: 1.5rem;"></i>
            </div>`;
        
        cardElement.innerHTML = `
            <div class="card-body">
                ${posterElement}
                <div class="movie-content">
                    <h6 class="movie-title mb-1">
                        <i class="${mediaIcon} me-2 disk-usage-icon"></i>
                        ${this.app.ui.escapeHtml(displayTitle)}
                        ${notification.year ? ` <span class="text-muted">(${notification.year})</span>` : ''}
                        ${mediaType !== 'movie' ? ` <span class="badge bg-secondary ms-1">${this.getDisplayMediaType(mediaType)}</span>` : ''}
                    </h6>
                    <div class="movie-meta">
                        <span class="requested-by">
                            <i class="bi bi-person-fill me-1"></i>
                            ${this.app.ui.escapeHtml(requestedBy)}
                        </span>
                        ${this.getQualityInfo(notification)}
                        <span>
                            <i class="bi bi-hdd me-1"></i>
                            ${sizeFormatted}
                        </span>
                        <span>
                            <i class="bi bi-clock me-1"></i>
                            ${timeAgo}
                        </span>
                    </div>
                </div>
                <div class="movie-actions-section">
                    <div class="movie-status-badge">
                        <span class="badge ${statusClass}">
                            <i class="${statusIcon}"></i> ${notification.status.toUpperCase()}
                        </span>
                    </div>
                    <div class="movie-all-actions">
                        ${this.createAllActionButtons(notification)}
                    </div>
                </div>
            </div>
        `;

        // Expose poster URL as CSS variable for mobile backdrop usage
        try {
            const posterUrl = notification.poster_url || '';
            if (posterUrl) {
                cardElement.style.setProperty('--poster-url', `url("${posterUrl}")`);
            }
        } catch (e) {}
        
        return cardElement;
    }
    
    getGroupStatus(notifications) {
        // Priority: syncing > failed > waiting_auto_sync > pending > completed
        const statuses = notifications.map(n => n.status);
        if (statuses.includes('syncing')) return 'syncing';
        if (statuses.includes('failed')) return 'failed';
        if (statuses.includes('waiting_auto_sync')) return 'waiting_auto_sync';
        if (statuses.includes('pending')) return 'pending';
        return 'completed';
    }
    
    createGroupActionButtons(group) {
        let buttons = [];
        const mediaType = group.mediaType;
        const groupStatus = this.getGroupStatus(group.notifications);
        
        // Show details button - this will open the grouped modal
        buttons.push(`
            <button class="btn btn-outline-secondary btn-sm" onclick="dragonCP.webhook.showGroupDetails('${this.app.ui.escapeJavaScriptString(group.groupKey)}', '${mediaType}')">
                <i class="bi bi-eye me-1"></i> Details (${group.notifications.length})
            </button>
        `);
        
        // Show sync all button if there are pending episodes
        const hasPending = group.notifications.some(n => n.status === 'pending' || n.status === 'failed');
        if (hasPending && groupStatus !== 'syncing') {
            buttons.push(`
                <button class="btn btn-primary btn-sm" onclick="dragonCP.webhook.syncAllInGroup('${this.app.ui.escapeJavaScriptString(group.groupKey)}', '${mediaType}')">
                    <i class="bi bi-play-fill me-1"></i> Sync All
                </button>
            `);
        }
        
        return buttons.join('');
    }
    
    getDisplayTitle(notification) {
        if (notification.media_type === 'movie') {
            return notification.title || notification.display_title || 'Unknown Movie';
        } else {
            return notification.display_title || notification.series_title || 'Unknown Series';
        }
    }
    
    getMediaIcon(mediaType) {
        switch (mediaType) {
            case 'series':
            case 'tvshows':
                return 'bi bi-tv';
            case 'anime':
                return 'bi bi-collection-play';
            case 'movie':
            default:
                return 'bi bi-film';
        }
    }
    
    getDisplayMediaType(mediaType) {
        switch (mediaType) {
            case 'tvshows':
                return 'TV SHOW';
            case 'series':
                return 'TV SHOW';
            case 'anime':
                return 'ANIME';
            case 'movie':
                return 'MOVIE';
            default:
                return mediaType.toUpperCase();
        }
    }
    
    getDisplayModalTitle(mediaType) {
        switch (mediaType) {
            case 'tvshows':
            case 'series':
                return 'TV Show Details';
            case 'anime':
                return 'Anime Details';
            case 'movie':
                return 'Movie Details';
            default:
                return `${mediaType.charAt(0).toUpperCase() + mediaType.slice(1)} Details`;
        }
    }
    
    formatSize(notification) {
        if (notification.media_type === 'movie') {
            return this.app.ui.humanReadableBytes(notification.size || 0);
        } else {
            // For series/anime, show episode count if available
            const episodeCount = notification.episode_count || 1;
            const episodeText = episodeCount === 1 ? 'episode' : 'episodes';
            const sizeFormatted = this.app.ui.humanReadableBytes(notification.release_size || 0);
            return `${episodeCount} ${episodeText} (${sizeFormatted})`;
        }
    }
    
    getQualityInfo(notification) {
        if (notification.media_type === 'movie') {
            return `<span>
                <i class="bi bi-badge-hd me-1"></i>
                ${this.app.ui.escapeHtml(notification.quality || 'Unknown')}
            </span>`;
        } else {
            // For series/anime, show season info
            const seasonText = notification.season_number ? `Season ${notification.season_number}` : 'Unknown Season';
            return `<span>
                <i class="bi bi-collection me-1"></i>
                ${seasonText}
            </span>`;
        }
    }

    createAllActionButtons(notification) {
        let buttons = [];
        const mediaType = notification.media_type || 'movie';
        
        // Primary action button based on status
        if (notification.status === 'pending') {
            buttons.push(`
                <button class="btn btn-primary btn-sm" onclick="dragonCP.webhook.syncNotification('${notification.notification_id}', '${mediaType}')">
                    <i class="bi bi-play-fill me-1"></i> Sync
                </button>
            `);
        } else if (notification.status === 'syncing') {
            buttons.push(`
                <button class="btn btn-secondary btn-sm" disabled>
                    <i class="bi bi-arrow-clockwise spinning me-1"></i> Syncing
                </button>
            `);
        } else if (notification.status === 'failed') {
            buttons.push(`
                <button class="btn btn-warning btn-sm" onclick="dragonCP.webhook.syncNotification('${notification.notification_id}', '${mediaType}')">
                    <i class="bi bi-arrow-clockwise me-1"></i> Retry
                </button>
            `);
        }
        
        // Always show details button
        buttons.push(`
            <button class="btn btn-outline-secondary btn-sm" onclick="dragonCP.webhook.showNotificationDetails('${notification.notification_id}', '${mediaType}')">
                <i class="bi bi-eye me-1"></i> Details
            </button>
        `);
        
        // Show delete button if not syncing
        if (notification.status !== 'syncing') {
            buttons.push(`
                <button class="btn btn-outline-danger btn-sm" onclick="dragonCP.webhook.deleteNotification('${notification.notification_id}', '${mediaType}')">
                    <i class="bi bi-trash me-1"></i> Delete
                </button>
            `);
        }
        
        return buttons.join('');
    }
    
    viewWebhookJson(notificationId) {
        // Open the webhook JSON in a new tab
        window.open(`/api/webhook/notifications/${notificationId}/json`, '_blank');
    }

    getStatusClass(status) {
        switch (status) {
            case 'pending': return 'bg-warning text-dark';
            case 'waiting_auto_sync': return 'bg-primary';
            case 'syncing': return 'bg-info';
            case 'completed': return 'bg-success';
            case 'failed': return 'bg-danger';
            default: return 'bg-secondary';
        }
    }

    getStatusIcon(status) {
        switch (status) {
            case 'pending': return 'bi bi-clock';
            case 'waiting_auto_sync': return 'bi bi-hourglass-split';
            case 'syncing': return 'bi bi-arrow-clockwise spinning';
            case 'completed': return 'bi bi-check-circle';
            case 'failed': return 'bi bi-x-circle';
            default: return 'bi bi-question-circle';
        }
    }

    updateNotificationCount() {
        const countElement = document.getElementById('syncNotificationCount');
        const pendingCount = this.notifications.filter(n => n.status === 'pending').length;
        const waitingAutoSyncCount = this.notifications.filter(n => n.status === 'waiting_auto_sync').length;
        const syncingCount = this.notifications.filter(n => n.status === 'syncing').length;
        
        let text = '';
        if (syncingCount > 0) {
            text = `${syncingCount} syncing`;
        } else if (waitingAutoSyncCount > 0) {
            text = `${waitingAutoSyncCount} scheduled`;
        } else if (pendingCount > 0) {
            text = `${pendingCount} pending`;
        } else {
            text = `${this.notifications.length} total`;
        }
        
        countElement.textContent = text;
    }

    

    async syncMovie(notificationId) {
        try {
            const notification = this.notifications.find(n => n.notification_id === notificationId);
            if (!notification) {
                this.app.ui.showAlert('Notification not found', 'danger');
                return;
            }
            
            const response = await fetch(`/api/webhook/notifications/${notificationId}/sync`, {
                method: 'POST'
            });
            
            const result = await response.json();
            
            if (result.status === 'success') {
                this.app.ui.showAlert(result.message, 'success');
                // Reload notifications to show updated status
                this.loadNotifications();
            } else {
                this.app.ui.showAlert(result.message, 'danger');
            }
        } catch (error) {
            console.error('Failed to sync movie:', error);
            this.app.ui.showAlert('Failed to start sync', 'danger');
        }
    }
    
    async syncNotification(notificationId, mediaType) {
        try {
            const notification = this.notifications.find(n => n.notification_id === notificationId);
            if (!notification) {
                this.app.ui.showAlert('Notification not found', 'danger');
                return;
            }
            
            let endpoint;
            switch (mediaType) {
                case 'series':
                case 'tvshows':
                    endpoint = `/api/webhook/series/notifications/${notificationId}/sync`;
                    break;
                case 'anime':
                    endpoint = `/api/webhook/anime/notifications/${notificationId}/sync`;
                    break;
                case 'movie':
                default:
                    endpoint = `/api/webhook/notifications/${notificationId}/sync`;
                    break;
            }
            
            const response = await fetch(endpoint, {
                method: 'POST'
            });
            
            const result = await response.json();
            
            if (result.status === 'success') {
                this.app.ui.showAlert(result.message, 'success');
                // Reload notifications to show updated status
                this.loadNotifications();
            } else {
                this.app.ui.showAlert(result.message, 'danger');
            }
        } catch (error) {
            console.error(`Failed to sync ${mediaType}:`, error);
            this.app.ui.showAlert(`Failed to start ${mediaType} sync`, 'danger');
        }
    }

    async showMovieDetails(notificationId) {
        try {
            const response = await fetch(`/api/webhook/notifications/${notificationId}`);
            const result = await response.json();
            
            if (result.status === 'success') {
                const notification = result.notification;
                this.renderMovieDetailsModal(notification);
            } else {
                this.app.ui.showAlert('Failed to load movie details', 'danger');
            }
        } catch (error) {
            console.error('Failed to load movie details:', error);
            this.app.ui.showAlert('Failed to load movie details', 'danger');
        }
    }

    renderMovieDetailsModal(notification) {
        // Create or update modal content
        let modal = document.getElementById('movieDetailsModal');
        if (!modal) {
            // Create modal if it doesn't exist
            modal = document.createElement('div');
            modal.className = 'modal fade';
            modal.id = 'movieDetailsModal';
            modal.innerHTML = `
                <div class="modal-dialog modal-xl">
                    <div class="modal-content">
                        <div class="modal-header gradient-accent">
                            <h5 class="modal-title">
                                <i class="bi bi-film me-2"></i>
                                Movie Details
                            </h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body" id="movieDetailsContent">
                        </div>
                        <div class="modal-footer" id="movieDetailsFooter">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                        </div>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);
        }
        
        // Always reset the movie modal title to prevent cross-modal mutations
        const fixedMovieTitle = modal.querySelector('.modal-title');
        if (fixedMovieTitle) {
            fixedMovieTitle.innerHTML = `
                <i class="bi bi-film me-2"></i>
                Movie Details
            `;
        }

        const content = document.getElementById('movieDetailsContent');
        const sizeFormatted = this.app.ui.humanReadableBytes(notification.size || 0);
        const languages = notification.languages && notification.languages.length > 0 
            ? notification.languages.join(', ') 
            : 'Not specified';
        const subtitles = notification.subtitles && notification.subtitles.length > 0 
            ? notification.subtitles.join(', ') 
            : 'None';
        
        // Create external links for TMDB and IMDB
        let externalLinks = '';
        if (notification.tmdb_id || notification.imdb_id) {
            externalLinks = '<div class="external-links mb-3">';
            if (notification.tmdb_id) {
                externalLinks += `
                    <a href="https://www.themoviedb.org/movie/${notification.tmdb_id}" target="_blank" class="btn btn-sm btn-outline-info me-2">
                        <i class="bi bi-box-arrow-up-right me-1"></i> TMDB
                    </a>
                `;
            }
            if (notification.imdb_id) {
                externalLinks += `
                    <a href="https://www.imdb.com/title/${notification.imdb_id}" target="_blank" class="btn btn-sm btn-outline-warning">
                        <i class="bi bi-box-arrow-up-right me-1"></i> IMDB
                    </a>
                `;
            }
            externalLinks += '</div>';
        }
        
        content.innerHTML = `
            <!-- Top Row: Poster, Title, Status, and Basic Information -->
            <div class="row g-3 mb-2 align-items-stretch">
                <div class="col-lg-3 d-flex">
                    <div class="w-100 text-center d-flex flex-column">
                        ${notification.poster_url ? 
                            `<img src="${this.app.ui.escapeHtml(notification.poster_url)}" 
                                alt="${this.app.ui.escapeHtml(notification.title)}" 
                                class="img-fluid rounded shadow-lg"
                                style="max-height: 420px; width: 100%; object-fit: cover; border: 2px solid var(--border-color);">` : 
                            `<div class="text-center text-muted p-4 border rounded flex-grow-1" style="border: 2px solid var(--border-color); background: rgba(255,255,255,0.02); min-height: 420px; display: flex; flex-direction: column; justify-content: center;">
                                <i class="bi bi-film" style="font-size: 3rem; color: var(--text-muted);"></i>
                                <div class="mt-2" style="color: var(--text-muted);">No poster available</div>
                            </div>`
                        }
                        <div class="mt-3">
                            ${externalLinks}
                        </div>
                    </div>
                </div>
                <div class="col-lg-9 d-flex flex-column">
                    <!-- Title and Status -->
                    <div class="mb-2">
                        <h3 class="mb-2" style="color: var(--text-light); font-weight: 600;">
                            ${this.app.ui.escapeHtml(notification.title)} 
                            ${notification.year ? `<span style="color: var(--text-muted); font-weight: 400;">(${notification.year})</span>` : ''}
                        </h3>
                        <div class="d-flex align-items-center gap-3">
                            <span class="badge ${this.getStatusClass(notification.status)} fs-6 px-3 py-2">
                                <i class="${this.getStatusIcon(notification.status)} me-1"></i> ${notification.status.toUpperCase()}
                            </span>
                            <small style="color: var(--text-muted);">
                                <i class="bi bi-clock me-1"></i>
                                Received ${this.app.ui.getTimeAgo(notification.created_at)}
                            </small>
                        </div>
                    </div>
                    
                    <!-- Basic Information -->
                    <div class="detail-section">
                        <h6><i class="bi bi-info-circle me-2"></i>Basic Information</h6>
                        <table class="table table-sm">
                            <tr>
                                <td>Requested by:</td>
                                <td><span style="color: var(--text-light); font-weight: 600;">${this.app.ui.escapeHtml(notification.requested_by || 'Unknown')}</span></td>
                            </tr>
                            <tr>
                                <td>Quality:</td>
                                <td><strong>${this.app.ui.escapeHtml(notification.quality || 'Unknown')}</strong></td>
                            </tr>
                            <tr>
                                <td>File Size:</td>
                                <td><strong>${sizeFormatted}</strong></td>
                            </tr>
                            <tr>
                                <td>Languages:</td>
                                <td>${this.app.ui.escapeHtml(languages)}</td>
                            </tr>
                            <tr>
                                <td>Subtitles:</td>
                                <td>${this.app.ui.escapeHtml(subtitles)}</td>
                            </tr>
                            ${notification.synced_at ? `<tr><td>Synced at:</td><td>${this.app.ui.getTimeAgo(notification.synced_at)}</td></tr>` : ''}
                        </table>
                    </div>
                </div>
            </div>
            
            <!-- Release Information Row -->
            <div class="row g-3 mb-2">
                <div class="col-12">
                    <div class="detail-section">
                        <h6><i class="bi bi-download me-2"></i>Release Information</h6>
                        <div class="d-flex flex-wrap align-items-center gap-2 mb-3">
                            <span class="badge bg-secondary">
                                <i class="bi bi-database-fill me-1"></i>
                                ${this.app.ui.humanReadableBytes(notification.release_size || 0)}
                            </span>
                            ${notification.release_indexer ? `<span class="badge bg-info text-dark">
                                <i class=\"bi bi-globe2 me-1\"></i>${this.app.ui.escapeHtml(notification.release_indexer)}
                            </span>` : ''}
                            ${notification.quality ? `<span class="badge bg-primary">
                                <i class=\"bi bi-badge-hd me-1\"></i>${this.app.ui.escapeHtml(notification.quality)}
                            </span>` : ''}
                        </div>
                        <div class="p-3 rounded" style="background: rgba(0,0,0,0.35); border: 1px solid var(--border-color);">
                            <div class="small text-muted mb-1">Release Title</div>
                            <code class="d-block" style="white-space: normal; word-break: break-all; font-family: 'Courier New', monospace;">
                                ${this.app.ui.escapeHtml(notification.release_title || 'Unknown')}
                            </code>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- File Paths Row -->
            <div class="row g-3">
                <div class="col-12">
                    <div class="detail-section">
                        <h6><i class="bi bi-folder me-2"></i>File Paths</h6>
                        <div class="row g-3">
                            <div class="col-md-6">
                                <label class="small mb-2 d-block" style="color: var(--text-muted); font-weight: 500;">
                                    <i class="bi bi-folder2 me-1"></i> Folder Path:
                                </label>
                                <div class="p-3 rounded" style="background: rgba(0,0,0,0.3); border: 1px solid var(--border-color); font-family: 'Courier New', monospace; font-size: 0.85rem; color: var(--text-light); word-break: break-all; min-height: 80px;">
                                    ${this.app.ui.escapeHtml(notification.folder_path)}
                                </div>
                            </div>
                            <div class="col-md-6">
                                <label class="small mb-2 d-block" style="color: var(--text-muted); font-weight: 500;">
                                    <i class="bi bi-file-earmark me-1"></i> File Path:
                                </label>
                                <div class="p-3 rounded" style="background: rgba(0,0,0,0.3); border: 1px solid var(--border-color); font-family: 'Courier New', monospace; font-size: 0.85rem; color: var(--text-light); word-break: break-all; min-height: 80px;">
                                    ${this.app.ui.escapeHtml(notification.file_path)}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            ${notification.error_message ? `
                <!-- Error Details Row -->
                <div class="row g-3 mt-2">
                    <div class="col-12">
                        <div class="detail-section">
                            <h6><i class="bi bi-exclamation-triangle me-2"></i>Error Details</h6>
                            <div class="alert alert-danger border-0" style="background: rgba(220, 53, 69, 0.1); color: #ff6b6b; border: 1px solid rgba(220, 53, 69, 0.3) !important;">
                                <div style="font-size: 0.9rem;">${this.app.ui.escapeHtml(notification.error_message)}</div>
                            </div>
                        </div>
                    </div>
                </div>
            ` : ''}
        `;
        
        // Update modal footer with action buttons
        const footer = document.getElementById('movieDetailsFooter');
        if (footer) {
            const isCompleted = notification.status === 'completed';
            footer.innerHTML = `
                <button type="button" class="btn btn-outline-info" onclick="dragonCP.webhook.viewWebhookJson('${notification.notification_id}')">
                    <i class="bi bi-code-square me-1"></i> View JSON
                </button>
                ${!isCompleted ? `
                    <button type="button" class="btn btn-success" onclick="dragonCP.webhook.markNotificationComplete('${notification.notification_id}', 'movie')">
                        <i class="bi bi-check-circle me-1"></i> Mark as Complete
                    </button>
                ` : ''}
                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
            `;
        }
        
        const bootstrapModal = new bootstrap.Modal(modal);
        bootstrapModal.show();
    }

    async deleteNotification(notificationId, mediaType) {
        try {
            const mediaTypeText = mediaType || 'movie';
            const confirmed = await this.app.ui.showCustomConfirm(
                `Are you sure you want to delete this ${mediaTypeText} notification? This action cannot be undone.`,
                `Delete ${mediaTypeText.charAt(0).toUpperCase() + mediaTypeText.slice(1)} Notification`,
                'Delete',
                'Cancel'
            );
            
            if (!confirmed) return;
            
            let endpoint;
            switch (mediaType) {
                case 'series':
                case 'tvshows':
                    endpoint = `/api/webhook/series/notifications/${notificationId}/delete`;
                    break;
                case 'anime':
                    endpoint = `/api/webhook/anime/notifications/${notificationId}/delete`;
                    break;
                case 'movie':
                default:
                    endpoint = `/api/webhook/notifications/${notificationId}/delete`;
                    break;
            }
            
            const response = await fetch(endpoint, {
                method: 'POST'
            });
            
            const result = await response.json();
            
            if (result.status === 'success') {
                this.app.ui.showAlert(`${mediaTypeText.charAt(0).toUpperCase() + mediaTypeText.slice(1)} notification deleted successfully`, 'success');
                this.loadNotifications();
            } else {
                this.app.ui.showAlert(result.message, 'danger');
            }
        } catch (error) {
            console.error('Failed to delete notification:', error);
            this.app.ui.showAlert('Failed to delete notification', 'danger');
        }
    }

    async markNotificationComplete(notificationId, mediaType) {
        try {
            const mediaTypeText = mediaType || 'movie';
            const confirmed = await this.app.ui.showCustomConfirm(
                `Are you sure you want to mark this ${mediaTypeText} notification as complete? This will update its status to COMPLETED.`,
                `Mark ${mediaTypeText.charAt(0).toUpperCase() + mediaTypeText.slice(1)} as Complete`,
                'Mark as Complete',
                'Cancel'
            );
            
            if (!confirmed) return;
            
            let endpoint;
            switch (mediaType) {
                case 'series':
                case 'tvshows':
                    endpoint = `/api/webhook/series/notifications/${notificationId}/complete`;
                    break;
                case 'anime':
                    endpoint = `/api/webhook/anime/notifications/${notificationId}/complete`;
                    break;
                case 'movie':
                default:
                    endpoint = `/api/webhook/notifications/${notificationId}/complete`;
                    break;
            }
            
            const response = await fetch(endpoint, {
                method: 'POST'
            });
            
            const result = await response.json();
            
            if (result.status === 'success') {
                this.app.ui.showAlert(`${mediaTypeText.charAt(0).toUpperCase() + mediaTypeText.slice(1)} notification marked as complete successfully`, 'success');
                
                // For series/anime, update the status badge and buttons in place
                if (mediaType === 'series' || mediaType === 'tvshows' || mediaType === 'anime') {
                    // Update accordion items for this notification
                    const accordionItems = document.querySelectorAll('.accordion-item');
                    accordionItems.forEach(item => {
                        // Find the accordion button with this notification's data
                        const accordionButton = item.querySelector('.accordion-button');
                        if (accordionButton) {
                            // Check if this accordion item contains our notification ID in any onclick handlers
                            const actionButtons = item.querySelectorAll('button[onclick*="' + notificationId + '"]');
                            if (actionButtons.length > 0) {
                                // Update the status badge in the accordion header
                                const statusBadge = accordionButton.querySelector('.badge');
                                if (statusBadge) {
                                    statusBadge.className = 'badge bg-success';
                                    statusBadge.innerHTML = '<i class="bi bi-check-circle"></i> COMPLETED';
                                }
                                
                                // Find and hide the "Mark as Complete" button in the accordion body
                                const markCompleteBtn = item.querySelector('button[onclick*="markNotificationComplete"][onclick*="' + notificationId + '"]');
                                if (markCompleteBtn) {
                                    markCompleteBtn.style.display = 'none';
                                }
                            }
                        }
                    });
                    
                    // Update status badge in the modal footer if present
                    const seriesModal = document.getElementById('seriesDetailsModal');
                    if (seriesModal) {
                        // Update the footer to hide the Mark as Complete button
                        const footer = document.getElementById('seriesDetailsFooter');
                        if (footer) {
                            footer.innerHTML = `
                                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                            `;
                        }
                    }
                } else {
                    // For movies, close the modal
                    const movieModal = document.getElementById('movieDetailsModal');
                    if (movieModal) {
                        const bsModal = bootstrap.Modal.getInstance(movieModal);
                        if (bsModal) bsModal.hide();
                    }
                }
                
                // Reload notifications list to reflect the change
                this.loadNotifications();
            } else {
                this.app.ui.showAlert(result.message, 'danger');
            }
        } catch (error) {
            console.error('Failed to mark notification as complete:', error);
            this.app.ui.showAlert('Failed to mark notification as complete', 'danger');
        }
    }

    async showNotificationDetails(notificationId, mediaType) {
        try {
            let endpoint;
            switch (mediaType) {
                case 'series':
                case 'tvshows':
                case 'anime':
                    // For now, use the general endpoint which handles both
                    endpoint = `/api/webhook/notifications/${notificationId}`;
                    break;
                case 'movie':
                default:
                    endpoint = `/api/webhook/notifications/${notificationId}`;
                    break;
            }
            
            const response = await fetch(endpoint);
            const result = await response.json();
            
            if (result.status === 'success') {
                const notification = result.notification;
                if (mediaType === 'series' || mediaType === 'tvshows' || mediaType === 'anime') {
                    this.renderSeriesDetailsModal(notification, mediaType);
                } else {
                    this.renderMovieDetailsModal(notification);
                }
            } else {
                this.app.ui.showAlert(`Failed to load ${mediaType} details`, 'danger');
            }
        } catch (error) {
            console.error(`Failed to load ${mediaType} details:`, error);
            this.app.ui.showAlert(`Failed to load ${mediaType} details`, 'danger');
        }
    }
    
    async showGroupDetails(groupKey, mediaType) {
        // Find the group in current notifications
        const grouped = this.groupNotifications(this.notifications);
        const group = grouped.find(g => g.isGroup && g.groupKey === groupKey);
        
        if (!group) {
            this.app.ui.showAlert('Group not found', 'danger');
            return;
        }
        
        // Render the grouped series modal
        this.renderGroupedSeriesDetailsModal(group, mediaType);
    }
    
    async syncAllInGroup(groupKey, mediaType) {
        const grouped = this.groupNotifications(this.notifications);
        const group = grouped.find(g => g.isGroup && g.groupKey === groupKey);
        
        if (!group) {
            this.app.ui.showAlert('Group not found', 'danger');
            return;
        }
        
        // Sync all pending/failed episodes in the group
        const toSync = group.notifications.filter(n => n.status === 'pending' || n.status === 'failed');
        
        if (toSync.length === 0) {
            this.app.ui.showAlert('No episodes to sync', 'info');
            return;
        }
        
        this.app.ui.showAlert(`Starting sync for ${toSync.length} episode(s)...`, 'info');
        
        for (const notification of toSync) {
            await this.syncNotification(notification.notification_id, mediaType);
            // Small delay between syncs to avoid overwhelming the server
            await new Promise(resolve => setTimeout(resolve, 500));
        }
    }
    
    renderGroupedSeriesDetailsModal(group, mediaType) {
        // Create or update dedicated series/anime modal
        let modal = document.getElementById('seriesDetailsModal');
        if (!modal) {
            modal = document.createElement('div');
            modal.className = 'modal fade';
            modal.id = 'seriesDetailsModal';
            modal.innerHTML = `
                <div class="modal-dialog modal-xl">
                    <div class="modal-content">
                        <div class="modal-header gradient-accent">
                            <h5 class="modal-title">
                                <i class="bi bi-tv me-2"></i>
                                Series Details
                            </h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body" id="seriesDetailsContent">
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                        </div>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);
        }

        // Update modal title for media type
        const modalTitle = modal.querySelector('.modal-title');
        const mediaIcon = mediaType === 'anime' ? 'bi bi-collection-play' : 'bi bi-tv';
        const displayTitle = this.getDisplayModalTitle(mediaType);
        modalTitle.innerHTML = `
            <i class="${mediaIcon} me-2"></i>
            ${displayTitle}
        `;

        const content = document.getElementById('seriesDetailsContent');
        
        // Use the first notification for common information
        const firstNotification = group.notifications[0];
        
        // Get aggregate information
        const totalSize = group.notifications.reduce((sum, n) => sum + (n.release_size || 0), 0);
        const sizeFormatted = this.app.ui.humanReadableBytes(totalSize);
        
        // Format languages (from first episode)
        let languages = 'Not specified';
        if (firstNotification.episode_files && firstNotification.episode_files.length > 0) {
            const langNames = firstNotification.episode_files[0].languages?.map(lang => lang.name || lang).filter(Boolean);
            languages = langNames && langNames.length > 0 ? langNames.join(', ') : 'Not specified';
        }
        
        // Format subtitles (from first episode)
        let subtitles = 'None';
        if (firstNotification.episode_files && firstNotification.episode_files.length > 0 && 
            firstNotification.episode_files[0].mediaInfo && firstNotification.episode_files[0].mediaInfo.subtitles) {
            subtitles = firstNotification.episode_files[0].mediaInfo.subtitles.join(', ') || 'None';
        }
        
        // Create external links if available
        let externalLinks = '';
        if (group.tmdb_id || group.imdb_id || firstNotification.tvdb_id) {
            externalLinks = '<div class="external-links mb-3">';
            if (group.tmdb_id) {
                externalLinks += `
                    <a href="https://www.themoviedb.org/tv/${group.tmdb_id}" target="_blank" class="btn btn-sm btn-outline-info me-2">
                        <i class="bi bi-box-arrow-up-right me-1"></i> TMDB
                    </a>
                `;
            }
            if (group.imdb_id) {
                externalLinks += `
                    <a href="https://www.imdb.com/title/${group.imdb_id}" target="_blank" class="btn btn-sm btn-outline-warning me-2">
                        <i class="bi bi-box-arrow-up-right me-1"></i> IMDB
                    </a>
                `;
            }
            if (firstNotification.tvdb_id) {
                externalLinks += `
                    <a href="https://thetvdb.com/?tab=series&id=${firstNotification.tvdb_id}" target="_blank" class="btn btn-sm btn-outline-success me-2">
                        <i class="bi bi-box-arrow-up-right me-1"></i> TVDB
                    </a>
                `;
            }
            externalLinks += '</div>';
        }
        
        // Sort episodes by episode number
        const sortedNotifications = [...group.notifications].sort((a, b) => {
            const aNum = a.episodes && a.episodes[0] ? a.episodes[0].episodeNumber : 0;
            const bNum = b.episodes && b.episodes[0] ? b.episodes[0].episodeNumber : 0;
            return aNum - bNum;
        });
        
        // Create accordion for episodes
        const episodeAccordionHtml = this.createEpisodeAccordion(sortedNotifications, mediaType, group.groupKey);
        
        content.innerHTML = `
            <!-- Top Row: Poster and Basic Information -->
            <div class="row g-3 mb-2 align-items-stretch">
                <div class="col-lg-3 d-flex">
                    <div class="w-100 text-center d-flex flex-column">
                        ${group.poster_url ? 
                            `<img src="${this.app.ui.escapeHtml(group.poster_url)}" 
                                alt="${this.app.ui.escapeHtml(group.series_title)}" 
                                class="img-fluid rounded shadow-lg"
                                style="max-height: 420px; width: 100%; object-fit: cover; border: 2px solid var(--border-color);">` : 
                            `<div class="text-center text-muted p-4 border rounded flex-grow-1" style="border: 2px solid var(--border-color); background: rgba(255,255,255,0.02); min-height: 420px; display: flex; flex-direction: column; justify-content: center;">
                                <i class="${mediaIcon}" style="font-size: 3rem; color: var(--text-muted);"></i>
                                <div class="mt-2" style="color: var(--text-muted);">No poster available</div>
                            </div>`
                        }
                        <div class="mt-3">
                            ${externalLinks}
                        </div>
                    </div>
                </div>
                <div class="col-lg-9 d-flex flex-column">
                    <!-- Title and Status -->
                    <div class="mb-2">
                        <h3 class="mb-2" style="color: var(--text-light); font-weight: 600;">
                            ${this.app.ui.escapeHtml(group.series_title)} 
                            ${group.year ? `<span style="color: var(--text-muted); font-weight: 400;">(${group.year})</span>` : ''}
                        </h3>
                        <div class="d-flex align-items-center gap-3">
                            <span class="badge bg-secondary fs-6 px-3 py-2">
                                <i class="bi bi-collection me-1"></i> Season ${group.season_number}
                            </span>
                            <small style="color: var(--text-muted);">
                                <i class="bi bi-film me-1"></i>
                                ${group.notifications.length} Episode${group.notifications.length !== 1 ? 's' : ''}
                            </small>
                            <small style="color: var(--text-muted);">
                                <i class="bi bi-clock me-1"></i>
                                Latest: ${this.app.ui.getTimeAgo(group.created_at)}
                            </small>
                        </div>
                    </div>

                    <!-- Basic Information -->
                    <div class="detail-section">
                        <h6><i class="bi bi-info-circle me-2"></i>Basic Information</h6>
                        <table class="table table-sm">
                            <tr>
                                <td>Season:</td>
                                <td><strong>${group.season_number}</strong></td>
                            </tr>
                            <tr>
                                <td>Total Size:</td>
                                <td><strong>${sizeFormatted}</strong></td>
                            </tr>
                            <tr>
                                <td>Requested by:</td>
                                <td><span style="color: var(--text-light); font-weight: 600;">${this.app.ui.escapeHtml(group.requested_by || 'Unknown')}</span></td>
                            </tr>
                            <tr>
                                <td>Languages:</td>
                                <td>${this.app.ui.escapeHtml(languages)}</td>
                            </tr>
                            <tr>
                                <td>Subtitles:</td>
                                <td>${this.app.ui.escapeHtml(subtitles)}</td>
                            </tr>
                        </table>
                    </div>
                </div>
            </div>

            <!-- Episodes Section -->
            <div class="row g-3">
                <div class="col-12">
                    <div class="detail-section">
                        <h6><i class="bi bi-collection me-2"></i>Episodes</h6>
                        ${episodeAccordionHtml}
                    </div>
                </div>
            </div>
        `;
        
        const bootstrapModal = new bootstrap.Modal(modal);
        bootstrapModal.show();
    }
    
    createEpisodeAccordion(notifications, mediaType, groupKey) {
        const accordionId = `episodeAccordion-${groupKey}`;
        
        let html = `<div class="accordion" id="${accordionId}">`;
        
        notifications.forEach((notification, index) => {
            const collapseId = `collapse-${groupKey}-${index}`;
            const statusClass = this.getStatusClass(notification.status);
            const statusIcon = this.getStatusIcon(notification.status);
            
            // Extract episode information
            const episodes = notification.episodes || [];
            const episodeFiles = notification.episode_files || [];
            const episodeNum = episodes[0]?.episodeNumber || 0;
            const seasonNum = episodes[0]?.seasonNumber || notification.season_number || 0;
            const episodeTitle = episodes[0]?.title || 'Unknown Episode';
            const episodeCode = `S${String(seasonNum).padStart(2, '0')}E${String(episodeNum).padStart(2, '0')}`;
            
            // Get quality
            let qualityLabel = '';
            if (episodeFiles.length > 0) {
                const q = episodeFiles[0].quality;
                if (typeof q === 'string') {
                    qualityLabel = q;
                } else if (q && typeof q === 'object') {
                    if (q.quality && typeof q.quality === 'object' && q.quality.name) {
                        qualityLabel = q.quality.name;
                    } else if (typeof q.quality === 'string') {
                        qualityLabel = q.quality;
                    } else if (q.name) {
                        qualityLabel = q.name;
                    }
                }
            }
            
            const sizeFormatted = this.app.ui.humanReadableBytes(notification.release_size || 0);
            const firstFilePath = episodeFiles.length > 0 ? (episodeFiles[0].path || episodeFiles[0].relativePath || '') : '';
            
            html += `
                <div class="accordion-item">
                    <h2 class="accordion-header">
                        <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#${collapseId}">
                            <div class="d-flex align-items-center justify-content-between w-100 pe-3">
                                <div class="d-flex align-items-center gap-3">
                                    <strong>${episodeCode}</strong>
                                    <span>${this.app.ui.escapeHtml(episodeTitle)}</span>
                                </div>
                                <span class="badge ${statusClass}">
                                    <i class="${statusIcon}"></i> ${notification.status.toUpperCase()}
                                </span>
                            </div>
                        </button>
                    </h2>
                    <div id="${collapseId}" class="accordion-collapse collapse" data-bs-parent="#${accordionId}">
                        <div class="accordion-body">
                            <!-- Release Information -->
                            <div class="mb-3">
                                <h6 class="mb-2"><i class="bi bi-download me-2"></i>Release Information</h6>
                                <div class="d-flex flex-wrap align-items-center gap-2 mb-2">
                                    <span class="badge bg-secondary">
                                        <i class="bi bi-database-fill me-1"></i>${sizeFormatted}
                                    </span>
                                    ${qualityLabel ? `<span class="badge bg-primary">
                                        <i class="bi bi-badge-hd me-1"></i>${this.app.ui.escapeHtml(qualityLabel)}
                                    </span>` : ''}
                                    ${notification.release_indexer ? `<span class="badge bg-info text-dark">
                                        <i class="bi bi-globe2 me-1"></i>${this.app.ui.escapeHtml(notification.release_indexer)}
                                    </span>` : ''}
                                </div>
                                <div class="p-2 rounded" style="background: rgba(0,0,0,0.3); border: 1px solid var(--border-color);">
                                    <div class="small text-muted mb-1">Release Title</div>
                                    <code class="d-block small" style="white-space: normal; word-break: break-all;">
                                        ${this.app.ui.escapeHtml(notification.release_title || 'Unknown')}
                                    </code>
                                </div>
                            </div>
                            
                            <!-- Episode Details -->
                            ${episodes.length > 0 ? `
                            <div class="mb-3">
                                <h6 class="mb-2"><i class="bi bi-info-circle me-2"></i>Episode Details</h6>
                                <table class="table table-sm table-dark">
                                    <tr>
                                        <td>Episode:</td>
                                        <td><strong>${episodeCode}</strong></td>
                                    </tr>
                                    <tr>
                                        <td>Title:</td>
                                        <td>${this.app.ui.escapeHtml(episodeTitle)}</td>
                                    </tr>
                                    <tr>
                                        <td>Air Date:</td>
                                        <td>${episodes[0].airDate || 'Unknown'}</td>
                                    </tr>
                                </table>
                            </div>` : ''}
                            
                            <!-- Path Information -->
                            ${(notification.season_path || firstFilePath) ? `
                            <div class="mb-3">
                                <h6 class="mb-2"><i class="bi bi-folder me-2"></i>Path Information</h6>
                                <div class="row g-2">
                                    <div class="col-md-6">
                                        <label class="small mb-1 d-block text-muted">Season Path:</label>
                                        <div class="p-2 rounded small" style="background: rgba(0,0,0,0.3); border: 1px solid var(--border-color); font-family: 'Courier New', monospace; word-break: break-all;">
                                            ${this.app.ui.escapeHtml(notification.season_path || 'Unknown')}
                                        </div>
                                    </div>
                                    <div class="col-md-6">
                                        <label class="small mb-1 d-block text-muted">File Path:</label>
                                        <div class="p-2 rounded small" style="background: rgba(0,0,0,0.3); border: 1px solid var(--border-color); font-family: 'Courier New', monospace; word-break: break-all;">
                                            ${this.app.ui.escapeHtml(firstFilePath || 'Unknown')}
                                        </div>
                                    </div>
                                </div>
                            </div>` : ''}
                            
                            <!-- Actions -->
                            <div class="d-flex gap-2 justify-content-end">
                                ${notification.status === 'pending' ? `
                                    <button class="btn btn-primary btn-sm" onclick="dragonCP.webhook.syncNotification('${notification.notification_id}', '${mediaType}')">
                                        <i class="bi bi-play-fill me-1"></i> Sync
                                    </button>
                                ` : ''}
                                ${notification.status === 'failed' ? `
                                    <button class="btn btn-warning btn-sm" onclick="dragonCP.webhook.syncNotification('${notification.notification_id}', '${mediaType}')">
                                        <i class="bi bi-arrow-clockwise me-1"></i> Retry
                                    </button>
                                ` : ''}
                                <button class="btn btn-outline-info btn-sm" onclick="dragonCP.webhook.viewWebhookJson('${notification.notification_id}')">
                                    <i class="bi bi-code-square me-1"></i> View JSON
                                </button>
                                ${notification.status !== 'completed' ? `
                                    <button class="btn btn-success btn-sm" onclick="dragonCP.webhook.markNotificationComplete('${notification.notification_id}', '${mediaType}')">
                                        <i class="bi bi-check-circle me-1"></i> Mark as Complete
                                    </button>
                                ` : ''}
                                ${notification.status !== 'syncing' ? `
                                    <button class="btn btn-outline-danger btn-sm" onclick="dragonCP.webhook.deleteNotification('${notification.notification_id}', '${mediaType}')">
                                        <i class="bi bi-trash me-1"></i> Delete
                                    </button>
                                ` : ''}
                            </div>
                            
                            ${notification.error_message ? `
                            <div class="alert alert-danger mt-3 mb-0" style="background: rgba(220, 53, 69, 0.1); border: 1px solid rgba(220, 53, 69, 0.3);">
                                <strong>Error:</strong> ${this.app.ui.escapeHtml(notification.error_message)}
                            </div>` : ''}
                        </div>
                    </div>
                </div>
            `;
        });
        
        html += '</div>';
        return html;
    }
    
    renderSeriesDetailsModal(notification, mediaType) {
        // Create or update dedicated series/anime modal
        let modal = document.getElementById('seriesDetailsModal');
        if (!modal) {
            modal = document.createElement('div');
            modal.className = 'modal fade';
            modal.id = 'seriesDetailsModal';
            modal.innerHTML = `
                <div class="modal-dialog modal-xl">
                    <div class="modal-content">
                        <div class="modal-header gradient-accent">
                            <h5 class="modal-title">
                                <i class="bi bi-tv me-2"></i>
                                Series Details
                            </h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body" id="seriesDetailsContent">
                        </div>
                        <div class="modal-footer" id="seriesDetailsFooter">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                        </div>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);
        }

        // Update modal title for media type (Anime or Series)
        const modalTitle = modal.querySelector('.modal-title');
        const mediaIcon = mediaType === 'anime' ? 'bi bi-collection-play' : 'bi bi-tv';
        const displayTitle = this.getDisplayModalTitle(mediaType);
        modalTitle.innerHTML = `
            <i class="${mediaIcon} me-2"></i>
            ${displayTitle}
        `;

        const content = document.getElementById('seriesDetailsContent');
        const sizeFormatted = this.app.ui.humanReadableBytes(notification.release_size || 0);
        const episodeCount = notification.episode_count || 1;
        const episodes = notification.episodes || [];
        const episodeFiles = notification.episode_files || [];
        
        // Format languages (for series it's from episode files)
        let languages = 'Not specified';
        if (episodeFiles.length > 0 && episodeFiles[0].languages) {
            const langNames = episodeFiles[0].languages.map(lang => lang.name || lang).filter(Boolean);
            languages = langNames.length > 0 ? langNames.join(', ') : 'Not specified';
        }
        
        // Format subtitles (from episode files)
        let subtitles = 'None';
        if (episodeFiles.length > 0 && episodeFiles[0].mediaInfo && episodeFiles[0].mediaInfo.subtitles) {
            subtitles = episodeFiles[0].mediaInfo.subtitles.join(', ') || 'None';
        }
        
        // Extract quality from episode files for display in Release Information
        let qualityLabel = '';
        if (episodeFiles.length > 0) {
            const q = episodeFiles[0].quality;
            if (typeof q === 'string') {
                qualityLabel = q;
            } else if (q && typeof q === 'object') {
                if (q.quality && typeof q.quality === 'object' && q.quality.name) {
                    qualityLabel = q.quality.name;
                } else if (typeof q.quality === 'string') {
                    qualityLabel = q.quality;
                } else if (q.name) {
                    qualityLabel = q.name;
                }
            }
        }
        
        // Extract first file path from episode files (if available)
        const firstFilePath = episodeFiles.length > 0 ? (episodeFiles[0].path || episodeFiles[0].relativePath || '') : '';
        
        // Download client info (for badges)
        const downloadClient = notification.download_client || '';
        
        // Create external links if available
        let externalLinks = '';
        if (notification.tmdb_id || notification.imdb_id || notification.tvdb_id) {
            externalLinks = '<div class="external-links mb-3">';
            if (notification.tmdb_id) {
                externalLinks += `
                    <a href="https://www.themoviedb.org/tv/${notification.tmdb_id}" target="_blank" class="btn btn-sm btn-outline-info me-2">
                        <i class="bi bi-box-arrow-up-right me-1"></i> TMDB
                    </a>
                `;
            }
            if (notification.imdb_id) {
                externalLinks += `
                    <a href="https://www.imdb.com/title/${notification.imdb_id}" target="_blank" class="btn btn-sm btn-outline-warning me-2">
                        <i class="bi bi-box-arrow-up-right me-1"></i> IMDB
                    </a>
                `;
            }
            if (notification.tvdb_id) {
                externalLinks += `
                    <a href="https://thetvdb.com/?tab=series&id=${notification.tvdb_id}" target="_blank" class="btn btn-sm btn-outline-success me-2">
                        <i class="bi bi-box-arrow-up-right me-1"></i> TVDB
                    </a>
                `;
            }
            externalLinks += '</div>';
        }
        
        // Use the same layout philosophy as movie modal for consistency
        content.innerHTML = `
            <!-- Top Row: Poster, Title, Status, and Basic Information -->
            <div class="row g-3 mb-2 align-items-stretch">
                <div class="col-lg-3 d-flex">
                    <div class="w-100 text-center d-flex flex-column">
                        ${notification.poster_url ? 
                            `<img src="${this.app.ui.escapeHtml(notification.poster_url)}" 
                                alt="${this.app.ui.escapeHtml(notification.series_title || notification.display_title)}" 
                                class="img-fluid rounded shadow-lg"
                                style="max-height: 420px; width: 100%; object-fit: cover; border: 2px solid var(--border-color);">` : 
                            `<div class="text-center text-muted p-4 border rounded flex-grow-1" style="border: 2px solid var(--border-color); background: rgba(255,255,255,0.02); min-height: 420px; display: flex; flex-direction: column; justify-content: center;">
                                <i class="${mediaIcon}" style="font-size: 3rem; color: var(--text-muted);"></i>
                                <div class="mt-2" style="color: var(--text-muted);">No poster available</div>
                            </div>`
                        }
                        <div class="mt-3">
                            ${externalLinks}
                        </div>
                    </div>
                </div>
                <div class="col-lg-9 d-flex flex-column">
                    <!-- Title and Status -->
                    <div class="mb-2">
                        <h3 class="mb-2" style="color: var(--text-light); font-weight: 600;">
                            ${this.app.ui.escapeHtml(notification.series_title || notification.display_title)} 
                            ${notification.year ? `<span style="color: var(--text-muted); font-weight: 400;">(${notification.year})</span>` : ''}
                        </h3>
                        <div class="d-flex align-items-center gap-3">
                            <span class="badge ${this.getStatusClass(notification.status)} fs-6 px-3 py-2">
                                <i class="${this.getStatusIcon(notification.status)} me-1"></i> ${notification.status.toUpperCase()}
                            </span>
                            <small style="color: var(--text-muted);">
                                <i class="bi bi-clock me-1"></i>
                                Received ${this.app.ui.getTimeAgo(notification.created_at)}
                            </small>
                        </div>
                    </div>

                    <!-- Basic Information -->
                    <div class="detail-section">
                        <h6><i class="bi bi-info-circle me-2"></i>Basic Information</h6>
                        <table class="table table-sm">
                            <tr>
                                <td>Season:</td>
                                <td><strong>${notification.season_number || 'Unknown'}</strong></td>
                            </tr>
                            <tr>
                                <td>Release Size:</td>
                                <td><strong>${sizeFormatted}</strong></td>
                            </tr>
                            <tr>
                                <td>Requested by:</td>
                                <td><span style="color: var(--text-light); font-weight: 600;">${this.app.ui.escapeHtml(notification.requested_by || 'Unknown')}</span></td>
                            </tr>
                            <tr>
                                <td>Languages:</td>
                                <td>${this.app.ui.escapeHtml(languages)}</td>
                            </tr>
                            <tr>
                                <td>Subtitles:</td>
                                <td>${this.app.ui.escapeHtml(subtitles)}</td>
                            </tr>
                            ${Array.isArray(notification.tags) && notification.tags.length > 0 ? `
                            <tr>
                                <td>Tags:</td>
                                <td>
                                    ${notification.tags.map(t => `<span class=\"badge bg-secondary me-1\">${this.app.ui.escapeHtml(String(t))}</span>`).join(' ')}
                                </td>
                            </tr>` : ''}
                            ${notification.synced_at ? `<tr><td>Synced at:</td><td>${this.app.ui.getTimeAgo(notification.synced_at)}</td></tr>` : ''}
                        </table>
                    </div>
                </div>
            </div>

            <!-- Release Information Row -->
            <div class="row g-3 mb-2">
                <div class="col-12">
                    <div class="detail-section">
                        <h6><i class="bi bi-download me-2"></i>Release Information</h6>
                        <div class="d-flex flex-wrap align-items-center gap-2 mb-3">
                            <span class="badge bg-secondary">
                                <i class="bi bi-database-fill me-1"></i>
                                ${this.app.ui.humanReadableBytes(notification.release_size || 0)}
                            </span>
                            ${qualityLabel ? `<span class="badge bg-primary">
                                <i class=\"bi bi-badge-hd me-1\"></i>${this.app.ui.escapeHtml(qualityLabel)}
                            </span>` : ''}
                            ${downloadClient ? `<span class="badge bg-dark">
                                <i class=\"bi bi-download me-1\"></i>${this.app.ui.escapeHtml(downloadClient)}
                            </span>` : ''}
                            ${notification.release_indexer ? `<span class="badge bg-info text-dark">
                                <i class=\"bi bi-globe2 me-1\"></i>${this.app.ui.escapeHtml(notification.release_indexer)}
                            </span>` : ''}
                        </div>
                        <div class="p-3 rounded" style="background: rgba(0,0,0,0.35); border: 1px solid var(--border-color);">
                            <div class="small text-muted mb-1">Release Title</div>
                            <code class="d-block" style="white-space: normal; word-break: break-all; font-family: 'Courier New', monospace;">
                                ${this.app.ui.escapeHtml(notification.release_title || 'Unknown')}
                            </code>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Episode Details -->
            ${episodes.length > 0 ? `
            <div class=\"row g-3 mb-2\">
                <div class=\"col-12\">
                    <div class=\"detail-section\">
                        <h6><i class=\"bi bi-collection me-2\"></i>Episode Details</h6>
                        <div class=\"table-responsive\">
                            <table class=\"table table-sm\">
                                <thead class=\"table-dark\">
                                    <tr>
                                        <th>Episode</th>
                                        <th>Title</th>
                                        <th>Air Date</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${episodes.map(ep => `
                                        <tr>
                                            <td>S${String(ep.seasonNumber || 0).padStart(2, '0')}E${String(ep.episodeNumber || 0).padStart(2, '0')}</td>
                                            <td style=\"color: var(--text-light);\">${this.app.ui.escapeHtml(ep.title || 'Unknown')}</td>
                                            <td>${ep.airDate || 'Unknown'}</td>
                                        </tr>
                                    `).join('')}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>` : ''}

            <!-- Paths Row -->
            ${(notification.season_path || firstFilePath) ? `
            <div class=\"row g-3\">
                <div class=\"col-12\">
                    <div class=\"detail-section\">
                        <h6><i class=\"bi bi-folder me-2\"></i>Path Information</h6>
                        <div class=\"row g-3\">
                            <div class=\"col-md-6\">
                                <label class=\"small mb-2 d-block\" style=\"color: var(--text-muted); font-weight: 500;\">
                                    <i class=\"bi bi-folder2-open me-1\"></i> Season Path:\n                                </label>
                                <div class=\"p-3 rounded\" style=\"background: rgba(0,0,0,0.3); border: 1px solid var(--border-color); font-family: 'Courier New', monospace; font-size: 0.85rem; color: var(--text-light); word-break: break-all; min-height: 80px;\">
                                    ${this.app.ui.escapeHtml(notification.season_path || 'Unknown')}\n                                </div>
                            </div>
                            <div class=\"col-md-6\">
                                <label class=\"small mb-2 d-block\" style=\"color: var(--text-muted); font-weight: 500;\">
                                    <i class=\"bi bi-file-earmark me-1\"></i> File Path:\n                                </label>
                                <div class=\"p-3 rounded\" style=\"background: rgba(0,0,0,0.3); border: 1px solid var(--border-color); font-family: 'Courier New', monospace; font-size: 0.85rem; color: var(--text-light); word-break: break-all; min-height: 80px;\">
                                    ${this.app.ui.escapeHtml(firstFilePath || 'Unknown')}\n                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>` : ''}
            
            ${notification.error_message ? `
            <div class=\"row g-3 mt-2\">
                <div class=\"col-12\">
                    <div class=\"detail-section\">
                        <h6><i class=\"bi bi-exclamation-triangle me-2\"></i>Error Details</h6>
                        <div class=\"alert alert-danger border-0\" style=\"background: rgba(220, 53, 69, 0.1); color: #ff6b6b; border: 1px solid rgba(220, 53, 69, 0.3) !important;\">
                            <div style=\"font-size: 0.9rem;\">${this.app.ui.escapeHtml(notification.error_message)}</div>
                        </div>
                    </div>
                </div>
            </div>` : ''}
            
            ${this.renderDryRunResults(notification)}
        `;
        
        // Update modal footer with action buttons
        const footer = document.getElementById('seriesDetailsFooter');
        if (footer) {
            const isCompleted = notification.status === 'completed';
            footer.innerHTML = `
                <button type="button" class="btn btn-outline-info" onclick="dragonCP.webhook.viewWebhookJson('${notification.notification_id}')">
                    <i class="bi bi-code-square me-1"></i> View JSON
                </button>
                ${!isCompleted ? `
                    <button type="button" class="btn btn-success" onclick="dragonCP.webhook.markNotificationComplete('${notification.notification_id}', '${mediaType}')">
                        <i class="bi bi-check-circle me-1"></i> Mark as Complete
                    </button>
                ` : ''}
                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
            `;
        }
        
        const bootstrapModal = new bootstrap.Modal(modal);
        bootstrapModal.show();
    }
    
    renderDryRunResults(notification) {
        // Check if dry-run result exists
        if (!notification.dry_run_result) {
            return '';
        }
        
        try {
            const dryRunResult = typeof notification.dry_run_result === 'string' 
                ? JSON.parse(notification.dry_run_result) 
                : notification.dry_run_result;
            
            const safeToSync = dryRunResult.safe_to_sync;
            const reason = dryRunResult.reason || 'No reason provided';
            const deletedCount = dryRunResult.deleted_count || 0;
            const incomingCount = dryRunResult.incoming_count || 0;
            const serverFileCount = dryRunResult.server_file_count || 0;
            const localFileCount = dryRunResult.local_file_count || 0;
            const deletedFiles = dryRunResult.deleted_files || [];
            const incomingFiles = dryRunResult.incoming_files || [];
            
            // Determine alert color based on safety
            const alertClass = safeToSync ? 'alert-success' : 'alert-warning';
            const alertBg = safeToSync ? 'rgba(40, 167, 69, 0.1)' : 'rgba(255, 193, 7, 0.1)';
            const alertBorder = safeToSync ? 'rgba(40, 167, 69, 0.3)' : 'rgba(255, 193, 7, 0.3)';
            const alertColor = safeToSync ? '#4ecdc4' : '#f39c12';
            const icon = safeToSync ? 'bi bi-check-circle' : 'bi bi-exclamation-triangle';
            
            let html = `
            <div class="row g-3 mt-2">
                <div class="col-12">
                    <div class="detail-section">
                        <h6><i class="bi bi-shield-check me-2"></i>Auto-Sync Validation Results</h6>
                        <div class="alert ${alertClass} border-0 mb-3" style="background: ${alertBg}; color: ${alertColor}; border: 1px solid ${alertBorder} !important;">
                            <div class="d-flex align-items-center mb-2">
                                <i class="${icon} me-2" style="font-size: 1.2rem;"></i>
                                <strong>${safeToSync ? 'Safe to Auto-Sync' : 'Manual Sync Required'}</strong>
                            </div>
                            <div style="font-size: 0.9rem;">${this.app.ui.escapeHtml(reason)}</div>
                        </div>
                        
                        <div class="row g-3">
                            <div class="col-md-6">
                                <div class="p-3 rounded" style="background: rgba(0,0,0,0.3); border: 1px solid var(--border-color);">
                                    <h6 class="mb-3 text-light"><i class="bi bi-server me-2"></i>File Count Analysis</h6>
                                    <table class="table table-sm table-dark mb-0">
                                        <tr>
                                            <td>Server Media Files:</td>
                                            <td class="text-end"><strong>${serverFileCount}</strong></td>
                                        </tr>
                                        <tr>
                                            <td>Local Media Files:</td>
                                            <td class="text-end"><strong>${localFileCount}</strong></td>
                                        </tr>
                                        <tr class="border-top">
                                            <td>Would Delete:</td>
                                            <td class="text-end ${deletedCount > 0 ? 'text-danger' : ''}"><strong>${deletedCount}</strong></td>
                                        </tr>
                                        <tr>
                                            <td>Would Add/Update:</td>
                                            <td class="text-end ${incomingCount > 0 ? 'text-success' : ''}"><strong>${incomingCount}</strong></td>
                                        </tr>
                                    </table>
                                </div>
                            </div>
                            
                            <div class="col-md-6">
                                <div class="p-3 rounded" style="background: rgba(0,0,0,0.3); border: 1px solid var(--border-color); max-height: 250px; overflow-y: auto;">
                                    <h6 class="mb-3 text-light"><i class="bi bi-info-circle me-2"></i>File Details</h6>
            `;
            
            if (deletedFiles.length > 0) {
                html += `
                    <div class="mb-3">
                        <strong class="text-danger d-block mb-2"><i class="bi bi-trash me-1"></i>Files to Delete (${deletedCount}):</strong>
                        <ul class="list-unstyled mb-0" style="font-size: 0.85rem;">
                `;
                deletedFiles.slice(0, 10).forEach(file => {
                    html += `<li class="text-muted mb-1">• ${this.app.ui.escapeHtml(file)}</li>`;
                });
                if (deletedCount > 10) {
                    html += `<li class="text-muted">... and ${deletedCount - 10} more</li>`;
                }
                html += `</ul></div>`;
            }
            
            if (incomingFiles.length > 0) {
                html += `
                    <div class="mb-3">
                        <strong class="text-success d-block mb-2"><i class="bi bi-plus-circle me-1"></i>Files to Add/Update (${incomingCount}):</strong>
                        <ul class="list-unstyled mb-0" style="font-size: 0.85rem;">
                `;
                incomingFiles.slice(0, 10).forEach(file => {
                    html += `<li class="text-muted mb-1">• ${this.app.ui.escapeHtml(file)}</li>`;
                });
                if (incomingCount > 10) {
                    html += `<li class="text-muted">... and ${incomingCount - 10} more</li>`;
                }
                html += `</ul></div>`;
            }
            
            if (deletedFiles.length === 0 && incomingFiles.length === 0) {
                html += `<p class="text-muted mb-0">No file changes detected.</p>`;
            }
            
            html += `
                                </div>
                            </div>
                        </div>
                        
                        ${notification.dry_run_performed_at ? `
                        <div class="mt-2">
                            <small class="text-muted">
                                <i class="bi bi-clock me-1"></i>
                                Validation performed: ${this.app.ui.getTimeAgo(notification.dry_run_performed_at)}
                            </small>
                        </div>` : ''}
                    </div>
                </div>
            </div>
            `;
            
            return html;
        } catch (error) {
            console.error('Error parsing dry-run results:', error);
            return '';
        }
    }

    // Initialize the webhook manager
    initialize() {
        this.loadNotifications();
        
        // Auto-refresh notifications every 30 seconds
        setInterval(() => {
            this.loadNotifications();
        }, 30000);
    }
}
