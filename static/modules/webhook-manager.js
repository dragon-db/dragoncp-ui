/**
 * Webhook Manager Module
 * Handles movie, series, and anime webhook notifications, auto-sync settings, and sync operations
 */
export class WebhookManager {
    constructor(app) {
        this.app = app;
        this.notifications = [];
        this.autoSyncEnabled = false;
        
        this.initializeEventListeners();
        this.loadWebhookSettings();
    }

    initializeEventListeners() {
        // Main sync buttons
        document.getElementById('refreshSyncBtn').addEventListener('click', () => {
            this.loadNotifications();
        });

        document.getElementById('autoSyncToggleBtn').addEventListener('click', () => {
            this.toggleAutoSync();
        });
    }

    async loadWebhookSettings() {
        try {
            const response = await fetch('/api/webhook/settings');
            const result = await response.json();
            
            if (result.status === 'success') {
                this.autoSyncEnabled = result.settings.auto_sync_movies;
                this.updateAutoSyncButton();
            }
        } catch (error) {
            console.error('Failed to load webhook settings:', error);
        }
    }

    async toggleAutoSync() {
        try {
            const newState = !this.autoSyncEnabled;
            
            const response = await fetch('/api/webhook/settings', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    auto_sync_movies: newState
                })
            });
            
            const result = await response.json();
            
            if (result.status === 'success') {
                this.autoSyncEnabled = newState;
                this.updateAutoSyncButton();
                
                const message = newState ? 
                    'Auto-sync enabled. New movies will sync automatically.' : 
                    'Auto-sync disabled. Movies require manual sync.';
                this.app.ui.showAlert(message, 'info');
            } else {
                this.app.ui.showAlert('Failed to update auto-sync setting', 'danger');
            }
        } catch (error) {
            console.error('Failed to toggle auto-sync:', error);
            this.app.ui.showAlert('Failed to update auto-sync setting', 'danger');
        }
    }

    updateAutoSyncButton() {
        const button = document.getElementById('autoSyncToggleBtn');
        const icon = button.querySelector('i');
        
        if (this.autoSyncEnabled) {
            icon.className = 'bi bi-toggle-on text-success';
            button.innerHTML = '<i class="bi bi-toggle-on text-success"></i> Auto-Sync: ON';
            button.title = 'Disable auto-sync';
        } else {
            icon.className = 'bi bi-toggle-off';
            button.innerHTML = '<i class="bi bi-toggle-off"></i> Auto-Sync: OFF';
            button.title = 'Enable auto-sync';
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
        
        this.notifications.forEach(notification => {
            const notificationCard = this.createNotificationCard(notification);
            container.appendChild(notificationCard);
        });
    }

    createNotificationCard(notification) {
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

    getStatusClass(status) {
        switch (status) {
            case 'pending': return 'bg-warning text-dark';
            case 'syncing': return 'bg-info';
            case 'completed': return 'bg-success';
            case 'failed': return 'bg-danger';
            default: return 'bg-secondary';
        }
    }

    getStatusIcon(status) {
        switch (status) {
            case 'pending': return 'bi bi-clock';
            case 'syncing': return 'bi bi-arrow-clockwise spinning';
            case 'completed': return 'bi bi-check-circle';
            case 'failed': return 'bi bi-x-circle';
            default: return 'bi bi-question-circle';
        }
    }

    updateNotificationCount() {
        const countElement = document.getElementById('syncNotificationCount');
        const pendingCount = this.notifications.filter(n => n.status === 'pending').length;
        const syncingCount = this.notifications.filter(n => n.status === 'syncing').length;
        
        let text = '';
        if (syncingCount > 0) {
            text = `${syncingCount} syncing`;
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
                        <div class="modal-footer">
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
                        <div class="modal-footer">
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
        `;
        
        const bootstrapModal = new bootstrap.Modal(modal);
        bootstrapModal.show();
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
