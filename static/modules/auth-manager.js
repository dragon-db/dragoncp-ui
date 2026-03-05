/**
 * Auth Manager Module
 * Handles auth lifecycle, persistence, verification, refresh, and logout.
 */
export class AuthManager {
    constructor(app) {
        this.app = app;
        this.storageKey = 'dragoncp_auth_v1';
        this.session = null;
        this.authConfigured = true;
        this.refreshPromise = null;
    }

    async init() {
        await this.checkAuthStatus();
        if (!this.authConfigured) {
            this.clearSession(false);
            return { authenticated: false, authConfigured: false };
        }

        this.loadSessionFromStorage();
        if (!this.isAuthenticated()) {
            return { authenticated: false, authConfigured: true };
        }

        const verified = await this.verifyToken();
        if (verified) {
            return { authenticated: true, authConfigured: true };
        }

        const refreshed = await this.tryRefreshToken(true);
        if (!refreshed) {
            this.clearSession(true, 'session_expired');
            return { authenticated: false, authConfigured: true };
        }

        return { authenticated: true, authConfigured: true };
    }

    async checkAuthStatus() {
        try {
            const response = await fetch('/api/auth/status');
            const result = await response.json();
            this.authConfigured = Boolean(result && result.auth_configured);
        } catch (error) {
            console.error('Failed to check auth status:', error);
            this.authConfigured = true;
        }
    }

    async login(username, password) {
        const response = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });

        const result = await response.json();
        if (!response.ok || result.status !== 'success') {
            const message = result?.message || 'Login failed';
            throw new Error(message);
        }

        this.setSession({
            token: result.token,
            refresh_token: result.refresh_token,
            expires_at: result.expires_at,
            refresh_expires_at: result.refresh_expires_at,
            user: result.user
        });

        this.dispatchAuthEvent('auth:login', { user: result.user });
        return result;
    }

    async logout(options = {}) {
        const { notifyServer = true, reason = 'manual_logout' } = options;

        if (notifyServer && this.isAuthenticated()) {
            try {
                await fetch('/api/auth/logout', {
                    method: 'POST',
                    headers: {
                        Authorization: `Bearer ${this.getAccessToken()}`
                    }
                });
            } catch (error) {
                console.warn('Logout request failed:', error);
            }
        }

        this.clearSession(true, reason);
    }

    async verifyToken() {
        const token = this.getAccessToken();
        if (!token) return false;

        try {
            const response = await fetch('/api/auth/verify', {
                headers: { Authorization: `Bearer ${token}` }
            });
            const result = await response.json();
            return Boolean(result && result.valid);
        } catch (error) {
            console.warn('Token verification failed:', error);
            return false;
        }
    }

    async ensureValidToken() {
        if (!this.isAuthenticated()) {
            return false;
        }

        if (!this.shouldRefreshToken()) {
            return true;
        }

        return this.tryRefreshToken(false);
    }

    shouldRefreshToken() {
        if (!this.session?.expires_at) return false;
        const expiry = new Date(this.session.expires_at).getTime();
        if (!Number.isFinite(expiry)) return true;
        const now = Date.now();
        const refreshWindowMs = 30 * 60 * 1000;
        return (expiry - now) < refreshWindowMs;
    }

    async tryRefreshToken(force = false) {
        if (!this.session?.refresh_token) {
            return false;
        }

        if (!force && !this.shouldRefreshToken()) {
            return true;
        }

        if (this.refreshPromise) {
            return this.refreshPromise;
        }

        this.refreshPromise = this._doRefreshToken();
        try {
            return await this.refreshPromise;
        } finally {
            this.refreshPromise = null;
        }
    }

    async _doRefreshToken() {
        try {
            const response = await fetch('/api/auth/refresh', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ refresh_token: this.session.refresh_token })
            });
            const result = await response.json();

            if (!response.ok || result.status !== 'success' || !result.token) {
                return false;
            }

            this.session.token = result.token;
            this.session.expires_at = result.expires_at;
            this.session.user = result.user || this.session.user;
            this.saveSessionToStorage();

            this.dispatchAuthEvent('auth:token-refreshed', {
                user: this.session.user
            });
            return true;
        } catch (error) {
            console.error('Token refresh failed:', error);
            return false;
        }
    }

    setSession(session) {
        this.session = {
            token: session.token,
            refresh_token: session.refresh_token,
            expires_at: session.expires_at,
            refresh_expires_at: session.refresh_expires_at,
            user: session.user
        };
        this.saveSessionToStorage();
    }

    clearSession(dispatch = true, reason = 'logout') {
        this.session = null;
        localStorage.removeItem(this.storageKey);
        if (dispatch) {
            this.dispatchAuthEvent('auth:logout', { reason });
        }
    }

    loadSessionFromStorage() {
        try {
            const raw = localStorage.getItem(this.storageKey);
            if (!raw) {
                this.session = null;
                return;
            }
            const parsed = JSON.parse(raw);
            if (parsed && parsed.token && parsed.refresh_token) {
                this.session = parsed;
                return;
            }
            this.session = null;
        } catch (error) {
            console.warn('Failed to load auth session from storage:', error);
            this.session = null;
        }
    }

    saveSessionToStorage() {
        if (!this.session) return;
        localStorage.setItem(this.storageKey, JSON.stringify(this.session));
    }

    dispatchAuthEvent(name, detail = {}) {
        document.dispatchEvent(new CustomEvent(name, { detail }));
    }

    isAuthenticated() {
        return Boolean(this.session?.token && this.session?.refresh_token);
    }

    isAuthConfigured() {
        return this.authConfigured;
    }

    getAccessToken() {
        return this.session?.token || null;
    }

    getRefreshToken() {
        return this.session?.refresh_token || null;
    }

    getUser() {
        return this.session?.user || null;
    }
}
