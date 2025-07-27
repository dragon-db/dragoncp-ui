# DragonCP Web UI - Setup & Development Guide

This document contains detailed setup instructions, troubleshooting, and development information for the DragonCP Web UI.

## Manual Setup (Alternative)

If you prefer to set up the virtual environment manually instead of using the automated startup script:

### 1. Create Virtual Environment
```bash
python3 -m venv venv
```

### 2. Activate Virtual Environment
```bash
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the Application
```bash
python app.py
```

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

# Activate
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Deactivate when done
deactivate
```

### Activating an Existing Virtual Environment

If you already have a virtual environment set up:

```bash
# Activate the virtual environment
source venv/bin/activate

# Verify activation (you should see (venv) in your prompt)
which python
# Should show: /path/to/your/project/venv/bin/python

# Run the application
python app.py
```

### Deactivating Virtual Environment

When you're done working with the project:

```bash
deactivate
```

### Installing New Requirements

If new dependencies are added to `requirements.txt`:

1. **Activate your virtual environment**:
   ```bash
   source venv/bin/activate
   ```

2. **Install the new requirements**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Or install a specific package**:
   ```bash
   pip install package_name
   ```

4. **Update requirements.txt** (if you added packages manually):
   ```bash
   pip freeze > requirements.txt
   ```

## Configuration

### Changing the Port

By default, the application runs on port 5000. To change this:

#### Method 1: Environment Variable
Add to your `dragoncp_env.env` file:
```env
FLASK_PORT=8080
```

#### Method 2: Command Line
Run the application with a custom port:
```bash
# Activate virtual environment first
source venv/bin/activate

# Run with custom port
python app.py --port 8080
```

#### Method 3: Modify app.py
Edit the `app.py` file and change the port in the `if __name__ == '__main__':` section:
```python
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=8080, debug=True)
```

### Environment File Setup

1. **Copy the sample environment file**:
   ```bash
   cp dragoncp_env_sample.env dragoncp_env.env
   ```

2. **Edit the configuration**:
   ```bash
   nano dragoncp_env.env
   ```

3. **Required variables**:
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

   # Optional: Custom port (default is 5000)
   FLASK_PORT=5000
   ```

## Troubleshooting

### Common Issues

#### 1. Connection Failed
- **Verify server IP and credentials**
- **Check SSH service is running on server**: `sudo systemctl status ssh`
- **Ensure firewall allows SSH connections**: `sudo ufw allow ssh`
- **Test SSH connection manually**: `ssh username@server-ip`

#### 2. Transfer Fails
- **Verify rsync is installed**: `rsync --version`
- **Install rsync if missing**: `sudo apt-get install rsync`
- **Check file permissions on source and destination**
- **Ensure sufficient disk space**: `df -h`
- **Check rsync logs in the web interface**

#### 3. WebSocket Connection Issues
- **Check if port is accessible**: `netstat -tlnp | grep :5000`
- **Verify firewall settings**: `sudo ufw status`
- **Try accessing via localhost first**: `http://localhost:5000`
- **Check browser console for WebSocket errors**

#### 4. Virtual Environment Issues
- **Ensure Python 3.12+ is installed**: `python3 --version`
- **Check if venv module is available**: `python3 -m venv --help`
- **Recreate virtual environment if corrupted**:
  ```bash
  rm -rf venv
  python3 -m venv venv
  source venv/bin/activate
  pip install -r requirements.txt
  ```

#### 5. Permission Issues
- **Fix start.sh permissions**: `chmod u+x start.sh`
- **Check file ownership**: `ls -la start.sh`
- **Run with proper user permissions**

#### 6. Port Already in Use
- **Find process using port**: `lsof -i :5000`
- **Kill the process**: `kill -9 <PID>`
- **Or change the port** (see Configuration section above)

### Logs and Debugging

#### Browser Console
- Open Developer Tools (F12)
- Check Console tab for JavaScript errors
- Check Network tab for failed requests

#### Python Console Output
- Monitor the terminal where you ran the application
- Look for Python errors and stack traces
- Check for import errors or missing dependencies

#### Transfer Logs
- Transfer logs are displayed in real-time in the web interface
- Check the "Transfer Log" section during file transfers
- Look for rsync error messages

#### System Logs
- Check system logs for SSH issues: `journalctl -u ssh`
- Check firewall logs: `sudo ufw status verbose`

## Development

### Project Structure
```
dragoncp_ui/
├── app.py                    # Main Flask application
├── database.py               # Database operations
├── dragoncp_env.env          # Environment configuration (create from sample)
├── dragoncp_env_sample.env   # Sample environment file
├── start.py                  # Smart startup script with venv support
├── start.sh                  # Linux launcher
├── templates/
│   └── index.html           # Main HTML template
├── static/
│   ├── app.js               # Frontend JavaScript
│   └── style.css            # CSS styles
├── requirements.txt         # Python dependencies
├── README.md               # Main documentation
└── SETUP.md               # This file
```

### Development Setup

1. **Clone the repository** (if not already done):
   ```bash
   git clone <repository-url>
   cd dragoncp-ui
   ```

2. **Set up development environment**:
   ```bash
   # Create virtual environment
   python3 -m venv venv
   source venv/bin/activate
   
   # Install dependencies
   pip install -r requirements.txt
   
   # Install development dependencies (if any)
   pip install -e .
   ```

3. **Configure environment**:
   ```bash
   cp dragoncp_env_sample.env dragoncp_env.env
   # Edit dragoncp_env.env with your test configuration
   ```

4. **Run in development mode**:
   ```bash
   python app.py
   ```

### Code Style and Standards

- **Python**: Follow PEP 8 style guidelines
- **JavaScript**: Use consistent indentation and naming conventions
- **HTML/CSS**: Follow semantic HTML and modern CSS practices
- **Comments**: Add meaningful comments for complex logic

### Testing

- **Manual Testing**: Test all features through the web interface
- **SSH Connection**: Test with different authentication methods
- **File Transfers**: Test with various file sizes and types
- **Error Handling**: Test error conditions and edge cases

### Contributing

1. **Fork the repository**
2. **Create a feature branch**: `git checkout -b feature-name`
3. **Make your changes**
4. **Test thoroughly**
5. **Commit with descriptive messages**: `git commit -m "Add feature description"`
6. **Push to your fork**: `git push origin feature-name`
7. **Create a pull request**

### Performance Optimization

- **Large File Transfers**: Monitor memory usage during large transfers
- **Concurrent Transfers**: Test with multiple simultaneous transfers
- **Network Performance**: Optimize rsync settings for your network
- **UI Responsiveness**: Ensure interface remains responsive during transfers

### Security Considerations

- **SSH Keys**: Use SSH keys instead of passwords when possible
- **File Permissions**: Ensure proper file permissions on sensitive files
- **Network Security**: Use HTTPS in production environments
- **Input Validation**: Validate all user inputs to prevent injection attacks

## Advanced Configuration

### Custom rsync Options

You can modify rsync options in `app.py` for specific use cases:

```python
# Example: Add bandwidth limiting
rsync_cmd = f"rsync -avz --bwlimit=1000 {source} {destination}"
```

### Database Configuration

If using the database features, configure database settings in your environment file:

```env
DATABASE_URL="sqlite:///dragoncp.db"
```

### Logging Configuration

Configure logging levels and output in `app.py`:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Support

For additional support:
- Check the main README.md for basic usage
- Review this SETUP.md for detailed configuration
- Check the main DragonCP project documentation
- Review the troubleshooting section above
