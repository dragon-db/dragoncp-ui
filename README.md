# DragonCP Web UI

A modern, mobile-friendly web interface for the DragonCP media transfer script. This web UI provides the same functionality as the dragoncp.sh bash script but with an intuitive graphical interface that works on desktop and mobile devices.

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
   ./start.sh
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

## Configuration

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

### Security Features
- SSH key and password authentication support
- Secure WebSocket connections with configurable timeouts
- Input validation and sanitization
- Session management with automatic timeout protection
- Isolated Python environment
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
