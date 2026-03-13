/**
 * WebSocket Manager Module
 * Handles WebSocket connections, activity tracking, and session management
 */
export class WebSocketManager {
    constructor(app) {
        this.app = app;
        const initialToken = this.app.auth?.getAccessToken() || null;
        this.socket = io({ 
            autoConnect: false, 
            reconnection: true,
            reconnectionAttempts: Infinity,
            reconnectionDelay: 1000,
            reconnectionDelayMax: 15000,
            randomizationFactor: 0.5,
            timeout: 20000,
            transports: ['polling', 'websocket'],
            upgrade: true,
            rememberUpgrade: false,
            forceNew: false,
            auth: {
                token: initialToken
            }
        });
        this.app.socket = this.socket;
        
        // WebSocket timeout management
        this.websocketTimeout = 30 * 60 * 1000; // 30 minutes in milliseconds
        this.activityTimer = null;
        this.lastActivity = Date.now();
        this.isWebSocketConnected = false;
        this.wasAutoDisconnected = false;
        this.hasEverConnected = false;
        this.lastConnectionError = null;
        this.isIntentionalDisconnect = false;
        this.reconnectAttemptCount = 0;
        this.lastTransport = 'unknown';
        
        this.initializeWebSocket();
        this.initializeActivityTracking();
        this.startTimerDisplayUpdates();

        document.addEventListener('auth:token-refreshed', () => {
            this.reAuthenticateWithCurrentToken();
        });
    }

    initializeWebSocket() {
        this.socket.on('connect', () => {
            this.bindTransportListeners();
            this.lastTransport = this.getCurrentTransport();
            console.log(`WebSocket connected via ${this.lastTransport}`);
            this.isWebSocketConnected = true;
            this.wasAutoDisconnected = false;
            this.hasEverConnected = true;
            this.lastConnectionError = null;
            this.isIntentionalDisconnect = false;
            this.reconnectAttemptCount = 0;
            
            // Start activity tracking now that WebSocket is connected
            this.updateActivity(); // Start activity tracking
            console.log('Activity tracking enabled');
            
            if (this.app.config) {
                this.app.config.updateWebSocketConfigStatus(); // Update config modal status
            }
            
            // Show WebSocket dependent UI elements if server connection exists
            if (this.app.currentState.connected) {
                this.showWebSocketDependentUI();
            }
            
            // Immediately show timer in status
            setTimeout(() => {
                this.updateStatusWithTimer().catch(error => {
                    console.warn('Failed to update status with timer:', error);
                });
            }, 100);
        });

        this.socket.on('transfer_progress', (data) => {
            this.app.transfers.updateTransferProgress(data);
            // Refresh transfer management display for progress bars
            this.app.transfers.scheduleActiveTransferRefresh();
            // Don't count transfer progress as user activity
        });

        this.socket.on('transfer_complete', (data) => {
            this.app.transfers.handleTransferComplete(data);
            // Refresh transfer management display
            this.app.transfers.scheduleActiveTransferRefresh();
            // Don't count transfer completion as user activity
        });

        this.socket.on('test_webhook_received', (data) => {
            console.log('🧪 TEST webhook received:', data.message);
            this.app.ui.showAlert(data.message, 'info');
        });

        // Rename webhook notifications
        this.socket.on('rename_webhook_received', (data) => {
            console.log('📝 Rename webhook received:', data);
            this.app.ui.showAlert(
                `📝 Rename webhook received for "${data.series_title}" (${data.total_files} file${data.total_files > 1 ? 's' : ''})`,
                'info'
            );
        });

        this.socket.on('rename_completed', (data) => {
            console.log('📝 Rename completed:', data);
            const statusIcon = data.status === 'completed' ? '✅' : 
                               data.status === 'partial' ? '⚠️' : '❌';
            const alertType = data.status === 'failed' ? 'danger' : 
                              data.status === 'partial' ? 'warning' : 'success';
            this.app.ui.showAlert(`${statusIcon} ${data.message}`, alertType);
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

            if (reason === 'io server disconnect' && !this.wasAutoDisconnected && !this.isIntentionalDisconnect && this.app.auth?.isAuthenticated()) {
                console.log('WebSocket server disconnected the client - reconnecting');
                if (this.app.currentState.connected) {
                    this.app.ui.updateStatus('Connected to server - Realtime reconnecting...', 'connecting');
                }
                setTimeout(() => {
                    this.connect();
                }, 1000);
                return;
            }
            
            // Handle status based on type of disconnect and SSH connection state
            if (!this.wasAutoDisconnected && reason !== 'io client disconnect') {
                this.hideWebSocketDependentUI();
                
                // Check if there was a recent connection error
                if (this.lastConnectionError && !this.socket.active) {
                    // Don't override connection error status
                    return;
                }
                
                // Update status based on SSH connection state
                if (this.app.currentState.connected) {
                    const statusMessage = this.socket.active
                        ? 'Connected to server - Realtime reconnecting...'
                        : 'Connected to server - Real-time updates unavailable';
                    this.app.ui.updateStatus(statusMessage, this.socket.active ? 'connecting' : 'disconnected');
                } else {
                    this.app.ui.updateStatus(this.socket.active ? 'Realtime connection retrying...' : 'Connection lost unexpectedly', this.socket.active ? 'connecting' : 'disconnected');
                }
            } else if (this.wasAutoDisconnected && this.app.currentState.connected) {
                // Auto-disconnected but SSH still connected
                this.app.ui.updateStatus('Connected to server - Background monitoring active', 'auto-disconnected');
            }
            
            // Update config modal status
            if (this.app.config) {
                this.app.config.updateWebSocketConfigStatus();
            }
            
            // Only show reconnection message if it wasn't an auto-disconnect
            if (!this.wasAutoDisconnected && !this.isIntentionalDisconnect) {
                console.log('WebSocket disconnected unexpectedly');
            }
        });

        // Add error handling for socket connection issues
        this.socket.on('connect_error', async (error) => {
            console.error('WebSocket connection error:', error);
            this.isWebSocketConnected = false;
            this.lastConnectionError = error;

            const message = (error?.message || '').toLowerCase();
            const authError = message.includes('unauthorized') || message.includes('authentication') || message.includes('token');
            if (authError && this.app.auth?.isAuthenticated()) {
                const refreshed = await this.app.auth.tryRefreshToken(true);
                if (refreshed) {
                    this.isIntentionalDisconnect = false;
                    this.updateSocketAuthToken();
                    if (!this.socket.connected) {
                        this.socket.connect();
                    }
                    return;
                }
                this.app.handleSessionExpired('websocket_auth_failed');
                return;
            }

            const retrying = Boolean(this.socket.active);
            if (this.app.currentState.connected) {
                this.app.ui.updateStatus(
                    retrying ? 'Connected to server - Realtime reconnecting...' : 'Connected to server - WebSocket connection failed',
                    retrying ? 'connecting' : 'disconnected'
                );
            } else {
                this.app.ui.updateStatus(
                    retrying ? 'Realtime connection retrying...' : 'WebSocket connection failed',
                    retrying ? 'connecting' : 'disconnected'
                );
            }
        });

        this.socket.io.on('reconnect_attempt', (attempt) => {
            this.reconnectAttemptCount = attempt;
            console.log(`WebSocket reconnect attempt ${attempt}`);
            if (this.app.currentState.connected) {
                this.app.ui.updateStatus(`Connected to server - Realtime reconnecting (attempt ${attempt})...`, 'connecting');
            }
        });

        this.socket.io.on('reconnect', (attempt) => {
            this.reconnectAttemptCount = attempt;
            this.lastConnectionError = null;
            console.log(`WebSocket reconnected after ${attempt} attempt(s)`);
        });

        this.socket.io.on('reconnect_error', (error) => {
            console.warn('WebSocket reconnect error:', error);
        });

        this.socket.io.on('reconnect_failed', () => {
            console.error('WebSocket reconnection failed after exhausting retries');
            if (this.app.currentState.connected) {
                this.app.ui.updateStatus('Connected to server - Real-time updates unavailable', 'disconnected');
            } else {
                this.app.ui.updateStatus('WebSocket connection failed', 'disconnected');
            }
        });

        this.socket.on('error', (error) => {
            // Filter out expected "Invalid frame header" errors during transport cleanup
            const errorString = error.toString();
            if (errorString.includes('Invalid frame header') || 
                errorString.includes('WebSocket connection to') ||
                errorString.includes('failed: Invalid frame header')) {
                console.log('WebSocket transport cleanup (expected during disconnection)');
                return;
            }
            
            // Log other unexpected errors
            console.error('WebSocket error:', error);
        });
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
    }

    initializeUIElementTracking() {
        // Track clicks on buttons and interactive elements (but exclude config and modal buttons)
        const trackClicksOn = [
            '.card.h-100:not(.disk-usage-card)', // Media type cards only (exclude disk usage cards)
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
            this.updateStatusWithTimer().catch(error => {
                console.warn('Failed to update status with timer:', error);
            });
        }
    }

    startActivityMonitoring() {
        // Check activity every minute
        setInterval(async () => {
            if (!this.app.auth?.isAuthenticated()) return;
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
                this.app.ui.showAlert('Session timeout prevented - active file transfers are protecting your connection', 'info');
                
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
        if (!this.app.auth?.isAuthenticated()) {
            return false;
        }
        try {
            const response = await this.app.api.fetch('/api/transfers/active');
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
        this.app.ui.showAlert(`Real-time connection will disconnect in ${minutesLeft} minute(s) due to inactivity. Click the status bar to extend your session and maintain full features.`, 'warning');
    }

    showWebSocketTimeoutNotification() {
        this.app.ui.showAlert('App connection lost due to inactivity. Active transfers continue running automatically in the background. Click "Auto Connect" to restore real-time features.', 'info');
        
        // Update status based on SSH connection state
        if (this.app.currentState.connected) {
            this.app.ui.updateStatus('Connected to server - Background monitoring active', 'auto-disconnected');
        } else {
            this.app.ui.updateStatus('Disconnected due to inactivity - background monitoring active', 'auto-disconnected');
        }
        
        // Hide UI elements that depend on WebSocket
        this.hideWebSocketDependentUI();
        
        // Update config modal status
        this.app.config.updateWebSocketConfigStatus();
    }

    hideWebSocketDependentUI() {
        // Hide media interface when WebSocket is disconnected
        const elementsToHide = [
            'browseMediaCard',
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
            this.app.ui.showAlert('Media browsing features temporarily disabled. Active transfers continue in the background. Reconnect to restore full functionality.', 'info');
        }, 1000);
    }

    showWebSocketDependentUI() {
        // Show media interface when WebSocket is connected
        const elementsToShow = [
            'browseMediaCard'
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
        if (this.socket) {
            console.log('Intentionally disconnecting WebSocket');
            this.isIntentionalDisconnect = true;
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

    extendSession() {
        this.app.ui.showAlert('Session extended successfully!', 'success');
        
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

    startTimerDisplayUpdates() {
        // Update timer display every minute
        setInterval(() => {
            if (this.isWebSocketConnected) {
                this.updateStatusWithTimer().catch(error => {
                    console.warn('Failed to update status with timer:', error);
                });
            }
        }, 60000);
        
        // Also update every 15 seconds when time is running low (last 5 minutes)
        setInterval(() => {
            if (this.isWebSocketConnected) {
                const minutesLeft = this.getTimeRemaining();
                if (minutesLeft <= 5) {
                    this.updateStatusWithTimer().catch(error => {
                        console.warn('Failed to update status with timer:', error);
                    });
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

    async updateStatusWithTimer() {
        // Check if SSH server connection exists
        const isServerConnected = this.app.currentState.connected;
        const reconnecting = Boolean(this.socket.active) && !this.isWebSocketConnected;
        
        // Prioritize showing websocket connection errors
        if (this.lastConnectionError && !this.isWebSocketConnected) {
            if (isServerConnected) {
                this.app.ui.updateStatus(reconnecting ? 'Connected to server - Realtime reconnecting...' : 'Connected to server - WebSocket connection failed', reconnecting ? 'connecting' : 'disconnected');
            } else {
                this.app.ui.updateStatus(reconnecting ? 'Realtime connection retrying...' : 'WebSocket connection failed', reconnecting ? 'connecting' : 'disconnected');
            }
            return;
        }
        
        // Only update status if we have an active timer and websocket is connected
        if (this.activityTimer && this.isWebSocketConnected) {
            const timeRemaining = this.getTimeRemaining();
            
            if (timeRemaining > 0 && isServerConnected) {
                this.app.ui.updateStatus(`Connected to server - Session: ${timeRemaining} min remaining`, 'connected');
            } else if (timeRemaining > 0) {
                // WebSocket connected but no SSH server connection
                this.app.ui.updateStatus(`WebSocket connected - ${timeRemaining} min remaining`, 'connecting');
            } else {
                this.app.ui.updateStatus('Session expired - reconnecting...', 'auto-disconnected');
            }
        } else if (!this.isWebSocketConnected && isServerConnected) {
            // SSH connected but websocket disconnected - show appropriate status
            if (this.wasAutoDisconnected) {
                this.app.ui.updateStatus('Connected to server - Background monitoring active', 'auto-disconnected');
            } else {
                this.app.ui.updateStatus(reconnecting ? 'Connected to server - Realtime reconnecting...' : 'Connected to server - Real-time updates unavailable', reconnecting ? 'connecting' : 'disconnected');
            }
        }
    }

    // Public methods for external access
    connect() {
        if (!this.app.auth?.isAuthenticated()) {
            return;
        }
        if (this.isWebSocketConnected || this.socket.active) {
            return;
        }
        // Clear any previous connection errors when manually reconnecting
        this.isIntentionalDisconnect = false;
        this.lastConnectionError = null;
        this.updateSocketAuthToken();
        this.socket.connect();
    }

    disconnect() {
        this.disconnectWebSocket();
    }

    setWebSocketTimeout(timeoutMinutes) {
        this.websocketTimeout = timeoutMinutes * 60 * 1000;
    }
    
    clearConnectionError() {
        this.lastConnectionError = null;
    }

    updateSocketAuthToken() {
        const token = this.app.auth?.getAccessToken();
        this.socket.auth = { token };
    }

    bindTransportListeners() {
        const engine = this.socket?.io?.engine;
        if (!engine || engine.__dragoncpTransportBound) {
            return;
        }

        engine.__dragoncpTransportBound = true;
        this.lastTransport = engine.transport?.name || 'unknown';
        console.log(`Socket transport active: ${this.lastTransport}`);

        engine.on('upgrade', (transport) => {
            this.lastTransport = transport?.name || 'unknown';
            console.log(`Socket transport upgraded to ${this.lastTransport}`);
        });

        engine.on('upgradeError', (error) => {
            console.warn('Socket transport upgrade failed, continuing with fallback transport:', error?.message || error);
        });
    }

    getCurrentTransport() {
        return this.socket?.io?.engine?.transport?.name || this.lastTransport || 'unknown';
    }

    reAuthenticateWithCurrentToken() {
        this.updateSocketAuthToken();
        if (!this.socket || !this.app.auth?.isAuthenticated()) return;

        if (this.socket.connected) {
            this.socket.emit('authenticate', { token: this.app.auth.getAccessToken() }, (response) => {
                if (!response || response.success !== true) {
                    this.isIntentionalDisconnect = false;
                    this.socket.disconnect();
                    this.socket.connect();
                }
            });
            return;
        }

        this.connect();
    }
}
