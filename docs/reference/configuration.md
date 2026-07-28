# Configuration

Settings that control the application. Moved here from the repository README.

> **Known gap.** This page covers the keys shipped in `dragoncp_env_sample.env`.
> The code reads more than these - logging level and rotation, gunicorn worker
> and timeout tuning, the WebSocket idle timeout, and the storage-monitoring
> keys are all read but not yet described here. See the coverage gaps in
> [INDEX.md](../INDEX.md). Treat this page as incomplete rather than
> authoritative until that is closed.

### Authentication Transport Rules

- HTTP API authentication uses `Authorization: Bearer <access-token>`.
- URL query token authentication (`?token=...`) is not supported for normal HTTP endpoints.
- WebSocket authentication remains token-based through Socket.IO auth payload (`auth: { token }`).

These rules apply regardless of whether you access the app via localhost, LAN IP, or Tailscale IP.

### Environment Variables

Create a `dragoncp_env.env` file in the project root directory (same location as `app.py`) with the following variables:

```env
# Flask Application Settings
SECRET_KEY="your-secret-key-here-change-this-in-production"

# Remote Server Connection Details
REMOTE_IP="your-server-ip"
REMOTE_USER="your-username"
REMOTE_PASSWORD="your-password-here"
SSH_KEY_PATH="/path/to/your/private/key"

# Media Source Paths on Remote Server
MOVIE_PATH="/path/to/movies"
TVSHOW_PATH="/path/to/tvshows"
ANIME_PATH="/path/to/anime"

# Local Destination Paths
MOVIE_DEST_PATH="/local/path/to/movies"
TVSHOW_DEST_PATH="/local/path/to/tvshows"
ANIME_DEST_PATH="/local/path/to/anime"

# Backup Path for rsync
BACKUP_PATH="/path/to/backup"

# Disk Usage Monitoring (optional)
DISK_PATH_1="/path/to/monitor"
DISK_PATH_2="/another/path/to/monitor"
DISK_PATH_3="/third/path/to/monitor"

# Remote disk usage API (optional)
DISK_API_ENDPOINT="https://api.example.com/disk-usage"
DISK_API_TOKEN="your_bearer_token_here"
```

**Note**: The environment file must be placed in the project root directory (same folder as `app.py`). The application will only look for `dragoncp_env.env` in this specific location.

### Quick Setup

1. Copy the sample environment file:
   ```bash
   cp dragoncp_env_sample.env dragoncp_env.env
   ```

2. Edit `dragoncp_env.env` with your actual configuration values

3. The application will automatically load the configuration when started

### Legacy UI Authentication

The legacy static UI now requires JWT authentication before any protected API feature is available.

Required environment variables:
```env
DRAGONCP_USERNAME="admin"
DRAGONCP_PASSWORD="your-secure-password"
JWT_SECRET_KEY="change-this-secret"
JWT_EXPIRY_HOURS=24
```

Behavior:
- A login screen is shown on first load when no valid token exists.
- Tokens are stored in browser `localStorage` under `dragoncp_auth_v1`.
- Access tokens auto-refresh before expiry using `/api/auth/refresh`.
- If refresh fails or token is invalid, the UI logs out and returns to login.
- HTTP requests must send bearer token in `Authorization` header.
- WebSocket connections are authenticated and re-authenticated after token refresh.

### SSH Authentication

You can connect using either:
- **Password authentication**: Enter username and password in the web interface
- **SSH key authentication**: Provide the path to your private key file

## Where settings live

Three stores hold configuration and they do not behave the same way:

- **`dragoncp_env.env`** - read once at startup. The authoritative source for
  connection details and paths.
- **Session overrides** - values entered in the Settings screen apply to that
  browser session only. They do not survive a restart and do not affect
  background work.
- **`app_settings` table** - a small set of automation toggles and Discord
  settings, which persist and do affect background work.

Not verified: the precedence rules between these three for every key.

## Related

- [Installation](../getting-started/installation.md)
- [Runtime and deployment](../operations/runtime-and-deployment.md)
- [Notifications](../features/notifications/README.md) - the Discord keys
