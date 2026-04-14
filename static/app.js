/**
 * DragonCP Web UI - Main Application Controller
 * Coordinates between feature modules and manages application state
 */

import { AuthManager } from 'auth-manager';
import { ApiClient } from 'api-client';
import { WebSocketManager } from 'websocket-manager';
import { ConfigManager } from 'config-manager';
import { UIComponents } from 'ui-components';
import { DiskMonitor } from 'disk-monitor';
import { MediaBrowser } from 'media-browser';
import { TransferManager } from 'transfer-manager';
import { BackupManager } from 'backup-manager';
import { WebhookManager } from 'webhook-manager';
import { LogViewer } from 'log-viewer';

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

        this.modulesInitialized = false;
        this.isBootstrapping = false;
        this.handlingSessionExpiry = false;
        this.hasAttemptedAutoConnect = false;

        // Core modules
        this.ui = new UIComponents(this);
        this.auth = new AuthManager(this);
        this.api = new ApiClient(this, this.auth);

        this.initializeAuthEventListeners();
        this.initializeLoginFormListeners();
        this.updateAuthUI(false);
        this.bootstrap();
    }

    initializeModules() {
        if (this.modulesInitialized) return;

        this.websocket = new WebSocketManager(this);
        this.socket = this.websocket.socket;
        this.config = new ConfigManager(this);
        this.disk = new DiskMonitor(this);
        this.media = new MediaBrowser(this);
        this.transfers = new TransferManager(this);
        this.backups = new BackupManager(this);
        this.webhook = new WebhookManager(this);
        this.logs = new LogViewer(this);

        this.initializeEventListeners();
        this.webhook.initialize();
        this.logs.setup();
        this.modulesInitialized = true;
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

            if (this.websocket?.isWebSocketConnected) {
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
                if (fullscreenModal && fullscreenModal.classList.contains('show') && this.transfers) {
                    this.transfers.hideFullscreenLog();
                }
            }
            
            // Ctrl/Cmd + L to toggle auto-scroll
            if ((e.ctrlKey || e.metaKey) && e.key === 'l' && this.transfers) {
                e.preventDefault();
                this.transfers.toggleAutoScroll();
            }
            
            // Ctrl/Cmd + K to clear logs
            if ((e.ctrlKey || e.metaKey) && e.key === 'k' && this.transfers) {
                e.preventDefault();
                this.transfers.clearTransferLog();
            }
        });
    }

    initializeAuthEventListeners() {
        document.addEventListener('auth:logout', (event) => {
            this.handleAuthLogout(event.detail?.reason || 'logout');
        });
    }

    initializeLoginFormListeners() {
        const form = document.getElementById('loginForm');
        const logoutBtn = document.getElementById('logoutBtn');

        if (form) {
            form.addEventListener('submit', async (event) => {
                event.preventDefault();
                await this.submitLogin();
            });
        }

        if (logoutBtn) {
            logoutBtn.addEventListener('click', async () => {
                await this.auth.logout({ notifyServer: true, reason: 'manual_logout' });
            });
        }
    }

    async bootstrap() {
        if (this.isBootstrapping) return;
        this.isBootstrapping = true;
        try {
            this.ui.updateStatus('Checking authentication...', 'connecting');
            const initResult = await this.auth.init();

            if (!initResult.authConfigured) {
                this.showLoginGate('Authentication is not configured on server.');
                this.ui.updateStatus('Authentication not configured', 'disconnected');
                return;
            }

            if (!initResult.authenticated) {
                this.showLoginGate();
                this.ui.updateStatus('Please sign in to continue', 'disconnected');
                return;
            }

            await this.handleAuthenticatedSession();
        } catch (error) {
            console.error('Bootstrap failed:', error);
            this.showLoginGate('Failed to initialize authentication.');
            this.ui.updateStatus('Initialization failed', 'disconnected');
        } finally {
            this.isBootstrapping = false;
        }
    }

    async submitLogin() {
        const usernameInput = document.getElementById('loginUsername');
        const passwordInput = document.getElementById('loginPassword');
        const submitBtn = document.getElementById('loginSubmitBtn');
        const loginError = document.getElementById('loginError');

        const username = (usernameInput?.value || '').trim();
        const password = passwordInput?.value || '';

        if (!username || !password) {
            this.setLoginError('Username and password are required');
            return;
        }

        if (loginError) loginError.style.display = 'none';
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Signing in...';
        }

        try {
            await this.auth.login(username, password);
            if (passwordInput) passwordInput.value = '';
            await this.handleAuthenticatedSession();
        } catch (error) {
            this.setLoginError(error.message || 'Login failed');
        } finally {
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<i class="bi bi-box-arrow-in-right"></i> Sign In';
            }
        }
    }

    setLoginError(message) {
        const loginError = document.getElementById('loginError');
        if (!loginError) return;
        loginError.textContent = message;
        loginError.style.display = 'block';
    }

    showLoginGate(message = '') {
        this.updateAuthUI(false);
        const appContainer = document.getElementById('appContainer');
        if (appContainer) appContainer.style.display = 'none';
        const loginGate = document.getElementById('loginGate');
        if (loginGate) loginGate.style.display = 'block';
        const loginError = document.getElementById('loginError');
        if (loginError) {
            if (message) {
                loginError.textContent = message;
                loginError.style.display = 'block';
            } else {
                loginError.style.display = 'none';
            }
        }
    }

    hideLoginGate() {
        const loginGate = document.getElementById('loginGate');
        if (loginGate) loginGate.style.display = 'none';
        const appContainer = document.getElementById('appContainer');
        if (appContainer) appContainer.style.display = 'block';
    }

    updateAuthUI(isAuthenticated) {
        const configBtn = document.getElementById('configBtn');
        const logoutBtn = document.getElementById('logoutBtn');
        const userBadge = document.getElementById('authenticatedUser');
        const userLabel = document.getElementById('authenticatedUsername');

        if (configBtn) configBtn.style.display = isAuthenticated ? 'inline-block' : 'none';
        if (logoutBtn) logoutBtn.style.display = isAuthenticated ? 'inline-block' : 'none';
        if (userBadge) userBadge.style.display = isAuthenticated ? 'inline-block' : 'none';
        if (userLabel) userLabel.textContent = this.auth.getUser() || 'Unknown';
    }

    async handleAuthenticatedSession() {
        this.updateAuthUI(true);
        this.hideLoginGate();
        this.initializeModules();
        if (this.logs) {
            this.logs.syncPanelState();
        }
        this.websocket.connect();
        await this.initializeConnection();
    }

    handleAuthLogout(reason) {
        this.currentState.connected = false;
        this.hasAttemptedAutoConnect = false;
        this.updateAuthUI(false);

        if (this.websocket) {
            this.websocket.disconnectWebSocket();
            this.websocket.wasAutoDisconnected = false;
        }
        if (this.ui && this.modulesInitialized) {
            this.ui.hideMediaInterface();
        }
        if (this.logs) {
            this.logs.deactivate();
        }

        this.showLoginGate(reason === 'manual_logout' ? '' : 'Session expired. Please sign in again.');
        this.ui.updateStatus('Disconnected', 'disconnected');
    }

    async handleSessionExpired(reason = 'session_expired') {
        if (this.handlingSessionExpiry) return;
        this.handlingSessionExpiry = true;
        try {
            await this.auth.logout({ notifyServer: false, reason });
            this.ui.showAlert('Session expired. Please sign in again.', 'warning');
        } finally {
            this.handlingSessionExpiry = false;
        }
    }

    async initializeConnection() {
        try {
            this.ui.updateStatus('Initializing application...', 'connecting');

            // Load configuration first
            await this.config.loadConfiguration();

            // Attempt SSH auto-connect on first load, independent of WebSocket state.
            // Previously this was gated on !this.websocket.hasEverConnected, which
            // caused a race condition: if Socket.IO connected before this point,
            // hasEverConnected was already true, so auto-connect was skipped entirely
            // and Browse Media would stay hidden (issue #50).
            if (!this.hasAttemptedAutoConnect) {
                this.hasAttemptedAutoConnect = true;
                if (!this.websocket.isWebSocketConnected) {
                    this.websocket.connect();
                }
                const autoConnectResponse = await this.api.fetch('/api/auto-connect');
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
            
            const response = await this.api.fetch('/api/auto-connect');
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
            const response = await this.api.post('/api/disconnect');
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
