/**
 * API Client Module
 * Centralized authenticated HTTP client for legacy UI modules.
 */
export class ApiClient {
    constructor(app, auth) {
        this.app = app;
        this.auth = auth;
        this.unauthorizedHandledAt = 0;
    }

    async fetch(url, options = {}, meta = {}) {
        const authRequired = meta.authRequired ?? this.isAuthRequired(url);
        const retryOn401 = meta.retryOn401 ?? true;

        if (authRequired) {
            const valid = await this.auth.ensureValidToken();
            if (!valid) {
                this.handleUnauthorized('token_invalid');
                throw new Error('Authentication required');
            }
        }

        const requestOptions = this.buildOptions(options, authRequired);
        let response = await fetch(url, requestOptions);

        if (response.status === 401 && authRequired && retryOn401) {
            const refreshed = await this.auth.tryRefreshToken(true);
            if (refreshed) {
                const retryOptions = this.buildOptions(options, authRequired);
                response = await fetch(url, retryOptions);
            }
        }

        if (response.status === 401 && authRequired) {
            this.handleUnauthorized('unauthorized');
        }

        return response;
    }

    async get(url, meta = {}) {
        return this.fetch(url, { method: 'GET' }, meta);
    }

    async post(url, body = null, meta = {}) {
        const headers = { 'Content-Type': 'application/json' };
        const options = {
            method: 'POST',
            headers,
            body: body !== null ? JSON.stringify(body) : undefined
        };
        return this.fetch(url, options, meta);
    }

    async getJson(url, meta = {}) {
        const response = await this.get(url, meta);
        return response.json();
    }

    buildOptions(options, authRequired) {
        const merged = { ...options };
        const headers = new Headers(options.headers || {});

        if (authRequired) {
            const token = this.auth.getAccessToken();
            if (token) {
                headers.set('Authorization', `Bearer ${token}`);
            }
        }

        merged.headers = headers;
        return merged;
    }

    isAuthRequired(url) {
        if (!url || typeof url !== 'string') return true;
        if (!url.startsWith('/api/')) return false;

        const publicPrefixes = [
            '/api/auth/login',
            '/api/auth/status',
            '/api/auth/verify',
            '/api/auth/refresh',
            '/api/webhook/movies',
            '/api/webhook/series',
            '/api/webhook/anime'
        ];

        return !publicPrefixes.some((prefix) => url.startsWith(prefix));
    }

    handleUnauthorized(reason) {
        const now = Date.now();
        if (now - this.unauthorizedHandledAt < 1500) {
            return;
        }
        this.unauthorizedHandledAt = now;

        if (this.app && typeof this.app.handleSessionExpired === 'function') {
            this.app.handleSessionExpired(reason);
        } else {
            this.auth.clearSession(true, reason || 'unauthorized');
        }
    }
}
