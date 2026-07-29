# Using DragonCP

A walkthrough of the main operator flows. Moved here from the repository README.

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

## Related

- [Installation](installation.md)
- [Media browsing](../features/media-browser/README.md)
- [Transfers](../features/transfers/README.md)
