/**
 * DragonCP Web UI - Main Application Controller
 * Coordinates between feature modules and manages application state
 */

import { WebSocketManager } from './modules/websocket-manager.js';
import { ConfigManager } from './modules/config-manager.js';
import { UIComponents } from './modules/ui-components.js';
import { DiskMonitor } from './modules/disk-monitor.js';
import { MediaBrowser } from './modules/media-browser.js';
import { TransferManager } from './modules/transfer-manager.js';
import { BackupManager } from './modules/backup-manager.js';

class DragonCPUI {
    constructor() {
        // Application state
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
        
        // Initialize modules
        this.ui = new UIComponents(this);
        this.websocket = new WebSocketManager(this);
        this.config = new ConfigManager(this);
        this.disk = new DiskMonitor(this);
        this.media = new MediaBrowser(this);
        this.transfers = new TransferManager(this);
        this.backups = new BackupManager(this);
        
        // Initialize the application
        this.initializeEventListeners();
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

        // Status bar click to extend session
        document.getElementById('statusBar').addEventListener('click', (event) => {
            // Only extend session if clicking the status area, not the buttons
            if (event.target.closest('.status-actions')) {
                return; // Don't interfere with button clicks
            }
            
            if (this.websocket.isWebSocketConnected) {
                this.websocket.extendSession();
            }
        });

        // Configuration button (no timer reset)
        document.getElementById('configBtn').addEventListener('click', () => {
            console.log('Config button clicked - timer NOT reset');
            const configModal = new bootstrap.Modal(document.getElementById('configModal'));
            configModal.show();
            
            // Update WebSocket status when modal is shown (read-only, no timer reset)
            setTimeout(() => {
                this.config.updateWebSocketConfigStatusReadOnly();
            }, 100);
        });

        // Configuration modal
        document.getElementById('saveConfig').addEventListener('click', () => {
            console.log('Save config button clicked - timer NOT reset');
            this.config.saveConfiguration();
        });

        document.getElementById('resetConfigBtn').addEventListener('click', () => {
            console.log('Reset config button clicked - timer NOT reset');
            this.config.resetConfiguration();
        });

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            // ESC key to close fullscreen log
            if (e.key === 'Escape') {
                const fullscreenModal = document.getElementById('fullscreenLogModal');
                if (fullscreenModal.classList.contains('show')) {
                    this.transfers.hideFullscreenLog();
                }
            }
            
            // Ctrl/Cmd + L to toggle auto-scroll
            if ((e.ctrlKey || e.metaKey) && e.key === 'l') {
                e.preventDefault();
                this.transfers.toggleAutoScroll();
            }
            
            // Ctrl/Cmd + K to clear logs
            if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
                e.preventDefault();
                this.transfers.clearTransferLog();
            }
        });
    }

    async initializeConnection() {
        try {
            this.ui.updateStatus('Initializing application...', 'connecting');
            
            // Load configuration first
            await this.config.loadConfiguration();
            
            // Only auto-connect on first load
            if (!this.websocket.hasEverConnected) {
                if (!this.websocket.isWebSocketConnected) {
                    this.websocket.connect();
                }
                const autoConnectResponse = await fetch('/api/auto-connect');
                const autoConnectResult = await autoConnectResponse.json();
                
                if (autoConnectResult.status === 'success') {
                    this.currentState.connected = true;
                    this.ui.updateStatus('Connected to server', 'connected');
                    this.ui.showAlert('Auto-connected successfully!', 'success');
                    this.ui.showMediaInterface();
                    this.media.loadMediaTypes();
                    return;
                }
            }
            // If auto-connect fails, check if we have credentials
            if (this.config.hasConnectionCredentials()) {
                this.ui.updateStatus('SSH credentials available. Click Auto Connect to proceed.', 'disconnected');
                this.config.showAutoConnectOption();
            } else {
                this.ui.updateStatus('No SSH credentials configured. Please configure in Settings.', 'disconnected');
            }
        } catch (error) {
            console.error('Failed to initialize connection:', error);
            this.ui.updateStatus('Failed to initialize connection', 'disconnected');
        }
    }

    async autoConnect() {
        try {
            this.ui.updateStatus('Connecting to server...', 'connecting');
            
            // If we have a disconnected WebSocket, reconnect it
            if (!this.websocket.isWebSocketConnected) {
                this.websocket.connect();
            }
            
            const response = await fetch('/api/auto-connect');
            const result = await response.json();
            
            if (result.status === 'success') {
                this.currentState.connected = true;
                
                // Reset auto-disconnect and config-changed flags
                this.websocket.wasAutoDisconnected = false;
                
                // Reload configuration to ensure we have the latest values
                await this.config.loadConfiguration();
                
                // Wait a moment for WebSocket to establish connection before showing timer
                // The WebSocket 'connect' event handler will call updateStatusWithTimer()
                this.ui.updateStatus('Connected to server', 'connected');
                
                // Show WebSocket dependent UI elements
                this.websocket.showWebSocketDependentUI();
                this.ui.showMediaInterface();
                this.media.loadMediaTypes();
                
                this.ui.showAlert('Connected with updated configuration!', 'success');
            } else {
                this.ui.updateStatus('Connection failed: ' + result.message, 'disconnected');
                this.ui.showAlert('Auto-connection failed: ' + result.message, 'danger');
            }
        } catch (error) {
            console.error('Auto-connection failed:', error);
            this.ui.updateStatus('Auto-connection failed', 'disconnected');
            this.ui.showAlert('Auto-connection failed', 'danger');
        }
    }

    async disconnectFromServer() {
        try {
            // Disconnect WebSocket first
            this.websocket.disconnectWebSocket();
            
            // Then disconnect from SSH server
            const response = await fetch('/api/disconnect');
            const result = await response.json();
            
            if (result.status === 'success') {
                this.ui.updateStatus('Disconnected from server', 'disconnected');
                this.currentState.connected = false;
                this.ui.hideMediaInterface();
                this.websocket.wasAutoDisconnected = false;
            }
        } catch (error) {
            console.error('Disconnect failed:', error);
        }
    }

    // Exposed methods for global access (needed by onclick handlers in HTML)
    selectMediaType(mediaType) {
        return this.media.selectMediaType(mediaType);
    }

    selectFolder(folderName, mediaType) {
        return this.media.selectFolder(folderName, mediaType);
    }

    selectSeason(seasonName, mediaType, folderName) {
        return this.media.selectSeason(seasonName, mediaType, folderName);
    }

    executeTransferOption(optionTitle) {
        return this.media.executeTransferOption(optionTitle);
    }

    downloadEpisode(episodeName, mediaType, folderName, seasonName) {
        return this.media.downloadEpisode(episodeName, mediaType, folderName, seasonName);
    }

    showTransferLogs(transferId) {
        return this.transfers.showTransferLogs(transferId);
    }

    cancelTransfer(transferId) {
        return this.transfers.cancelTransfer(transferId);
    }

    restartTransfer(transferId) {
        return this.transfers.restartTransfer(transferId);
    }

    deleteTransfer(transferId) {
        return this.transfers.deleteTransfer(transferId);
    }

    showTransferDetails(transferId) {
        return this.transfers.showTransferDetails(transferId);
    }

    closeTransferTab(transferId) {
        return this.transfers.closeTransferTab(transferId);
    }
}

// Initialize the application when the page loads
let dragonCP;
document.addEventListener('DOMContentLoaded', () => {
    dragonCP = new DragonCPUI();
    
    // Make it globally accessible for onclick handlers
    window.dragonCP = dragonCP;
});
