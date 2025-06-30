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

## Features

The interface features:
- Connection setup with SSH authentication
- Media type selection (Movies, TV Shows, Anime)
- Folder and season browsing with breadcrumb navigation
- Transfer management with real-time progress
- Configuration panel for path settings

## Installation

### Prerequisites

- Python 3.12 or higher
- rsync (for file transfers)
- SSH access to your media server

### Quick Start (Recommended)

The startup scripts will automatically handle virtual environment setup:

1. **Clone or download the project**:
   ```bash
   cd dragoncp_ui
   ```

2. **Run the startup script**:
   ```bash
   # On Linux/Mac:
   ./start.sh
   
   # On Windows:
   start.bat
   
   # Or use the Python script (works on all platforms):
   python3 start.py
   ```

3. **Follow the prompts**:
   - The script will detect if a virtual environment exists
   - If not found, it will offer to create one
   - Dependencies will be automatically installed
   - Configuration will be set up

4. **Access the web interface**:
   - Open your browser and go to `http://localhost:5000`
   - The interface will be available on all network interfaces

### Manual Setup (Alternative)

If you prefer to set up the virtual environment manually:

1. **Create virtual environment**:
   ```bash
   python3 -m venv venv
   ```

2. **Activate virtual environment**:
   ```bash
   # On Linux/Mac:
   source venv/bin/activate
   
   # On Windows:
   venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the application**:
   ```bash
   python app.py
   ```

### Using the Setup Script

For a guided setup experience:

```bash
python3 setup_venv.py
```

This script will:
- Check for existing virtual environments
- Create a new one if needed
- Install all dependencies
- Verify the installation

## Configuration

### Environment Variables

Create a `dragoncp_env.env` file in the project root directory (same location as `app.py`) with the following variables:

```env
# Server connection details
REMOTE_IP="your-server-ip"
REMOTE_USER="your-username"

# Media paths on the server
MOVIE_PATH="/path/to/movies"
TVSHOW_PATH="/path/to/tvshows"
ANIME_PATH="/path/to/anime"

# Local destination paths
MOVIE_DEST_PATH="/local/path/to/movies"
TVSHOW_DEST_PATH="/local/path/to/tvshows"
ANIME_DEST_PATH="/local/path/to/anime"

# Backup path for rsync
BACKUP_PATH="/path/to/backup"
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

## Virtual Environment Management

### Automatic Detection

The startup scripts automatically detect virtual environments in these locations:
- `venv/` (default)
- `env/`
- `.venv/`
- `.env/`

### Creating a Virtual Environment

The startup scripts will offer to create a virtual environment if none is found. This is the recommended approach as it:

- Isolates dependencies from your system Python
- Prevents conflicts with other projects
- Makes the project more portable
- Follows Python best practices

### Manual Virtual Environment Management

If you need to manage the virtual environment manually:

```bash
# Create virtual environment
python3 -m venv venv

# Activate (Linux/Mac)
source venv/bin/activate

# Activate (Windows)
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Deactivate when done
deactivate
```

## Technical Details

### Architecture
- **Backend**: Flask with Flask-SocketIO for real-time communication
- **Frontend**: Modern HTML5, CSS3, and JavaScript with Bootstrap 5
- **SSH**: Paramiko library for secure server connections
- **File Transfer**: rsync with optimized settings for media files
- **Environment**: Python virtual environment support

### Security Features
- SSH key and password authentication support
- Secure WebSocket connections
- Input validation and sanitization
- Session management
- Isolated Python environment

### Performance Optimizations
- Optimized rsync settings for large media files
- Asynchronous transfer monitoring
- Efficient folder browsing with caching
- Mobile-optimized UI components
- Virtual environment isolation

## Troubleshooting

### Common Issues

1. **Connection Failed**
   - Verify server IP and credentials
   - Check SSH service is running on server
   - Ensure firewall allows SSH connections

2. **Transfer Fails**
   - Verify rsync is installed on both systems
   - Check file permissions on source and destination
   - Ensure sufficient disk space

3. **WebSocket Connection Issues**
   - Check if port 5000 is accessible
   - Verify firewall settings
   - Try accessing via localhost first

4. **Virtual Environment Issues**
   - Ensure Python 3.12+ is installed
   - Try recreating the virtual environment: `python3 setup_venv.py`
   - Check if venv module is available: `python3 -m venv --help`

### Logs
- Check browser console for JavaScript errors
- Monitor Python console output for backend errors
- Transfer logs are displayed in real-time in the web interface

## Development

### Project Structure
```
dragoncp_ui/
├── app.py              # Main Flask application
├── dragoncp_env.env    # Environment configuration (create from sample)
├── dragoncp_env_sample.env # Sample environment file
├── start.py            # Smart startup script with venv support
├── setup_venv.py       # Virtual environment setup script
├── start.sh            # Linux/Mac launcher
├── start.bat           # Windows launcher
├── templates/
│   └── index.html      # Main HTML template
├── static/
│   ├── app.js          # Frontend JavaScript
│   └── style.css       # CSS styles
├── requirements.txt    # Python dependencies
└── README.md          # This file
```

## License

This project is part of the DragonCP media management system.

## Support

For issues and feature requests, please refer to the main DragonCP project documentation. 
