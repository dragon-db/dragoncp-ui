/**
 * UI Components Module
 * Handles common UI components, alerts, status updates, and utility functions
 */
export class UIComponents {
    constructor(app) {
        this.app = app;
        this.collapsedCards = new Set();
        this.initializeCollapsibleCards();
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

    // Utility functions
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

    truncateText(text, maxLength) {
        if (text.length <= maxLength) return text;
        return text.substring(0, maxLength - 3) + '...';
    }

    humanReadableBytes(bytes) {
        const thresh = 1024;
        if (Math.abs(bytes) < thresh) {
            return bytes + ' B';
        }
        const units = ['KB','MB','GB','TB','PB','EB','ZB','YB'];
        let u = -1;
        do {
            bytes /= thresh;
            ++u;
        } while (Math.abs(bytes) >= thresh && u < units.length - 1);
        return bytes.toFixed(1) + ' ' + units[u];
    }

    timeAgo(isoString) {
        if (!isoString) return '';
        
        // Handle both UTC (with Z) and local timestamps
        let ts;
        if (isoString.endsWith('Z')) {
            // UTC timestamp
            ts = new Date(isoString);
        } else {
            // Assume local timestamp or SQLite CURRENT_TIMESTAMP format
            ts = new Date(isoString + 'Z'); // Treat as UTC for consistency
        }
        
        const now = new Date();
        const diffMs = now - ts;
        const mins = Math.floor(diffMs / 60000);
        const hrs = Math.floor(mins / 60);
        const days = Math.floor(hrs / 24);
        
        // Debug logging for timestamp issues
        if (console && typeof console.debug === 'function') {
            console.debug('TimeAgo Debug:', {
                input: isoString,
                parsed: ts,
                now: now,
                diffMs: diffMs,
                hours: hrs
            });
        }
        
        if (diffMs < 0) return 'In the future'; // Handle negative time differences
        if (mins < 1) return 'Just now';
        if (mins < 60) return `${mins} min ago`;
        if (hrs < 24) return `${hrs} hour${hrs > 1 ? 's' : ''} ago`;
        return `${days} day${days > 1 ? 's' : ''} ago`;
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

    // Media interface visibility
    hideMediaInterface() {
        document.getElementById('diskUsageCard').style.display = 'none';
        document.getElementById('transferManagementCard').style.display = 'none';
        document.getElementById('browseMediaCard').style.display = 'none';
        document.getElementById('transferCard').style.display = 'none';
        document.getElementById('logCard').style.display = 'none';
        this.app.media.resetBrowseMediaState();
    }

    showMediaInterface() {
        document.getElementById('diskUsageCard').style.display = 'block';
        document.getElementById('transferManagementCard').style.display = 'block';
        document.getElementById('browseMediaCard').style.display = 'block';
        document.getElementById('transferCard').style.display = 'none';
        document.getElementById('logCard').style.display = 'none';
        this.app.media.showMediaTypeView();
        
        // Only load media types if we don't already have them
        const mediaTypesContainer = document.getElementById('mediaTypes');
        if (!mediaTypesContainer || mediaTypesContainer.children.length === 0) {
            this.app.media.loadMediaTypes();
        }
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

    // Custom confirmation dialog for better UX
    async showCustomConfirm(message, title = 'Confirmation', yesText = 'Yes', noText = 'No') {
        return new Promise((resolve) => {
            // Create modal-like overlay
            const overlay = document.createElement('div');
            overlay.className = 'custom-confirm-overlay';
            overlay.style.cssText = `
                position: fixed; top: 0; left: 0; right: 0; bottom: 0; 
                background: rgba(0,0,0,0.6); z-index: 9999; 
                display: flex; align-items: center; justify-content: center;
            `;
            
            const dialog = document.createElement('div');
            dialog.className = 'custom-confirm-dialog card';
            dialog.style.cssText = `
                width: 400px; max-width: 90vw; margin: 20px; 
                background: var(--bs-dark); border: 1px solid var(--bs-border-color);
                border-radius: 0.375rem; box-shadow: 0 0.5rem 1rem rgba(0,0,0,0.15);
            `;
            
            dialog.innerHTML = `
                <div class="card-header gradient-accent">
                    <h6 class="mb-0">${this.escapeHtml(title)}</h6>
                </div>
                <div class="card-body">
                    <p class="mb-3">${this.escapeHtml(message)}</p>
                    <div class="d-flex justify-content-end gap-2">
                        <button class="btn btn-outline-secondary custom-confirm-no">${this.escapeHtml(noText)}</button>
                        <button class="btn btn-primary custom-confirm-yes">${this.escapeHtml(yesText)}</button>
                    </div>
                </div>
            `;
            
            overlay.appendChild(dialog);
            document.body.appendChild(overlay);
            
            const cleanup = () => {
                document.body.removeChild(overlay);
            };
            
            dialog.querySelector('.custom-confirm-yes').onclick = () => {
                cleanup();
                resolve(true);
            };
            
            dialog.querySelector('.custom-confirm-no').onclick = () => {
                cleanup();
                resolve(false);
            };
            
            // Close on overlay click
            overlay.onclick = (e) => {
                if (e.target === overlay) {
                    cleanup();
                    resolve(false);
                }
            };
            
            // Focus first button
            setTimeout(() => dialog.querySelector('.custom-confirm-no').focus(), 100);
        });
    }
}
