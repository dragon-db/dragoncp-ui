# DragonCP Web UI

A modern, mobile-friendly web interface for the DragonCP media transfer script. This web UI provides the same functionality as the dragoncp.sh bash script but with an intuitive graphical interface that works on desktop and mobile devices.

## Project Scope (Current)

DragonCP is currently an **admin operations dashboard**, not an end-user product.

- Intended operators: small trusted admin team (typically 1-3 admins)
- No end-user account model
- No multi-tenant permission model
- No user-facing self-service workflows

As of March 3, 2026, scope remains admin-only.

## Network Exposure Model (Current)

- Preferred: keep backend (`/api` + Socket.IO) on trusted network only (localhost/LAN/Tailscale/VPN).
- No reverse proxy is required for the normal deployment model.
- If React UI is internet-reachable, admin actions still require secure access to backend API and socket endpoints.
- Intended public ingress endpoints are webhook receivers only:
  - `POST /api/webhook/movies`
  - `POST /api/webhook/series`
  - `POST /api/webhook/anime`
- Do not expose full admin API surface publicly without additional network controls and strict auth hardening.

## Features

- 🎨 **Modern Dark Theme UI** - Beautiful, responsive design with dark theme
- 📱 **Mobile Friendly** - Optimized for both desktop and mobile devices
- 🔌 **SSH Connection Management** - Easy server connection with password or SSH key support
- 🎬 **Media Type Support** - Movies, TV Shows, and Anime
- 📁 **Folder Browsing** - Navigate through media folders and seasons
- 🎯 **Flexible Transfer Options**:
  - Sync entire folders/seasons
  - Manual episode selection and sync
  - Download single episodes
- 📊 **Real-time Transfer Monitoring** - Live progress updates and logs
- ⚙️ **Configuration Management** - Easy setup of paths and settings
- 🔄 **WebSocket Support** - Real-time communication for transfer updates
- 🐍 **Virtual Environment Support** - Automatic venv detection and creation
- 🗄️ **Database Persistence** - Transfer history and progress tracking
- 🔄 **Transfer Management** - Resume, cancel, and restart transfers
- 💾 **Disk Usage Monitoring** - Real-time storage space tracking

## Installation

### Prerequisites

- Python 3.12 or higher
- rsync (for file transfers)
- SSH access to your media server

### Quick Start (Linux)

The startup script will automatically handle virtual environment setup:

1. **Clone or download the project**:
   ```bash
   cd dragoncp_ui
   ```

2. **Give execute permission to the startup script**:
   ```bash
   chmod u+x start.sh
   ```

3. **Run the startup script**:
   ```bash
   TEST_MODE=1 ./start.sh
   ```

4. **Follow the prompts**:
   - The script will detect if a virtual environment exists
   - If not found, it will offer to create one
   - Dependencies will be automatically installed
   - Configuration will be set up

5. **Access the web interface**:
   - Open your browser and go to `http://localhost:5000`
   - The interface will be available on all network interfaces

For detailed setup instructions, manual installation, troubleshooting, and development information, see [SETUP.md](SETUP.md).

## Development and Production Paths

### Development / Test

- Recommended path: `TEST_MODE=1 ./start.sh`
- Direct `python app.py` is acceptable for local debug/test only.
- Test/debug runs can still use Werkzeug when `TEST_MODE=1` or `FLASK_DEBUG=1`.

### Production

- Recommended runtime: `systemd + venv + gunicorn + gthread + 1 worker`
- Recommended command:
  ```bash
  venv/bin/gunicorn --config deploy/gunicorn.conf.py app:app
  ```
- Use the example service file at `deploy/dragoncp-ui.service.example`.
- Keep Gunicorn worker count at `1`. This app currently has process-local Socket.IO state and background coordination threads.
- Keep dependencies inside the project virtual environment.

### Current UI Status

- The currently served production UI is the legacy Flask/static UI from `templates/index.html` and `static/`.
- The React frontend in `frontend/` should stay aligned, but it is not the active production UI yet.

## React Frontend Docker Support

The repository now includes a Docker Compose setup for running the React frontend in its own container while keeping the existing backend on the host.

- Compose file: `docker-compose.yml`
- Frontend image build: `frontend/Dockerfile`
- nginx reverse proxy config: `frontend/nginx.conf`
- Default frontend URL: `http://localhost:5002`

### How it works

- nginx in the frontend container serves the built React app.
- nginx proxies `/api` and `/socket.io` to the backend running on the host at port `5000`.
- Because the browser stays on a single origin, the React app can keep using its default relative API and Socket.IO settings.

### Start the frontend container

```bash
docker compose up -d --build frontend
```

### Deploy the latest frontend changes

If you update the frontend locally or pull new frontend commits, use the deploy script:

```bash
./deploy-frontend.sh
```

The script checks Docker and Docker Compose availability, stops the running frontend container if needed, rebuilds the image with the latest local source, and starts the container again.

### Optional port override

```bash
DRAGONCP_FRONTEND_PORT=3000 docker compose up -d --build frontend
```

### Notes

- This setup is intended for Linux hosts and uses `host.docker.internal` via Docker's `host-gateway` support.
- The backend should remain on its supported production runtime: `systemd + venv + gunicorn + gthread + 1 worker`.

## Configuration

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

## Usage

### 1. Connect to Server
- Enter your server details (IP/hostname, username, password or SSH key path)
- Click "Connect" to establish SSH connection

### 2. Select Media Type
- Choose from Movies, TV Shows, or Anime
- The interface will load available folders from your configured paths

### 3. Browse and Select
- Navigate through folders and seasons using the breadcrumb navigation
- For TV Shows and Anime, you'll see season folders
- For Movies, you'll see movie folders directly

### 4. Transfer Options

#### Sync Entire Folder
- Transfers all content from the selected folder/season
- Uses optimized rsync settings for large media files

#### Manual Episode Sync
- Browse available episodes in a season
- Select specific episodes to download
- Useful for updating individual episodes

#### Download Single Episode
- Direct download of a specific episode
- Creates necessary directories automatically

### 5. Monitor Transfers
- Real-time progress updates via WebSocket
- Transfer logs with detailed rsync output
- Ability to cancel running transfers
- Progress bars and status indicators
- Persistent transfer history in database
- Resume interrupted transfers

## Technical Details

### Architecture
- **Backend**: Flask with Flask-SocketIO for real-time communication
- **Frontend**: Modern HTML5, CSS3, and JavaScript with Bootstrap 5
- **SSH**: Paramiko library for secure server connections
- **File Transfer**: rsync with optimized settings for media files
- **Database**: SQLite with persistent transfer tracking and metadata
- **Environment**: Python virtual environment support
- **Transfer Management**: Enhanced transfer manager with database persistence
- **WebSocket Timeout**: Configurable session management with activity tracking

### Future Reverse Proxy / Tunnel Notes

- If you later expose the app through Traefik, Cloudflared, or another reverse proxy, keep it same-origin when possible.
- Proxy `/`, `/api`, and `/socket.io` together.
- Exposing only the React UI is not sufficient by itself; the browser still needs backend HTTP and Socket.IO access.
- If UI and backend move to different origins, update `CORS_ORIGINS` and explicit frontend API/socket URLs.

### Security Features
- SSH key and password authentication support
- Secure WebSocket connections with configurable timeouts
- Input validation and sanitization
- Session management with automatic timeout protection
- Isolated Python environment
- Admin-only operational scope (trusted operators, no end-user workflows)
- Database-based transfer tracking and audit logs

### Performance Optimizations
- Optimized rsync settings for large media files
- Asynchronous transfer monitoring with database persistence
- Efficient folder browsing with caching
- Mobile-optimized UI components
- Virtual environment isolation
- Transfer resume capability for interrupted operations
- Real-time disk usage monitoring

### Database Features
- **Transfer Persistence**: All transfers are stored in SQLite database
- **Metadata Tracking**: Parsed titles, seasons, and episode information
- **Progress History**: Complete transfer logs and status tracking
- **Resume Capability**: Interrupted transfers can be resumed
- **Transfer Management**: Cancel, restart, and monitor active transfers
- **Audit Trail**: Complete history of all transfer operations
- **v2 Schema**: Improved database structure with better naming conventions (see [Migration Guide](docs/database/MIGRATION_GUIDE.md))

## License

This project is part of the DragonCP media management system and is specifically designed to work with the DragonDB management system. This application is optimized for DragonDB's custom setup and directory structure, and may not work correctly with other custom media management configurations. The application is intended for use with DragonDB's specific media organization and transfer workflows.

## Database Migration (v1 to v2)

If you're upgrading from v1 to v2, you'll need to migrate your database. See the [Migration Guide](docs/database/MIGRATION_GUIDE.md) for detailed instructions.

**Quick Migration:**
```bash
# Basic migration (drops old tables, creates v2 schema)
python scripts/migrate_v1_to_v2.py

# Migration with backup and data preservation
python scripts/migrate_v1_to_v2.py --backup --migrate-data
```

## Support

If you encounter any issues while using this script, please raise a GitHub issue with the following details:

- **Operating System**: Linux distribution and version
- **Python Version**: Output of `python3 --version`
- **Error Messages**: Complete error logs and stack traces
- **Configuration**: Your environment file settings (without sensitive data)
- **Steps to Reproduce**: Detailed steps that led to the issue
- **Expected vs Actual Behavior**: What you expected vs what happened
- **Transfer Logs**: Any relevant transfer logs from the web interface
- **Browser Information**: Browser type and version if UI-related

For detailed setup instructions, manual installation, troubleshooting, and development information, see [SETUP.md](SETUP.md). 

## Troubleshooting (Auth / Session)

- `Session expired. Please sign in again.`:
  - Refresh token is expired/invalid, or JWT secret changed.
  - Sign in again and verify `JWT_SECRET_KEY` consistency across restarts.
- `WebSocket connection failed` immediately after login:
  - Access token might be invalid or stale.
  - Sign out/sign in again and confirm backend `/api/auth/verify` returns `valid: true`.
- Repeated 401/API failures:
  - Confirm `DRAGONCP_PASSWORD`/`DRAGONCP_PASSWORD_HASH` is configured.
  - Confirm server clock is correct (JWT expiry depends on time).
- Login endpoint returns auth not configured:
  - Set `DRAGONCP_PASSWORD` (or `DRAGONCP_PASSWORD_HASH`) in `dragoncp_env.env` and restart.
