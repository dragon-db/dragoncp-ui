# Using DragonCP

A walkthrough of the main operator flows. Moved here from the repository README.

### 1. Connect to Server
- Enter your server details (IP/hostname, username, password or SSH key path)
- Click "Connect" to establish SSH connection

### 2. Select Media Type
- Choose from Movies, TV Shows, or Anime
- The interface will load available folders from your configured paths

### 3. Browse and Select
The Explore page is a three-pane console: the library on the left, what is
inside the selected item in the middle, and what you can do with it on the
right. On a phone you see one pane at a time and the actions open as a sheet.

- Pick a series to see its seasons; pick a season to see its episodes
- Movies have no season layer — picking one shows its files straight away
- Every episode carries a label from a real comparison of both libraries:
  **In sync**, **Missing**, **Upgraded** (the remote has a different file) or
  **Local only** (the remote no longer has it)
- Tick boxes select seasons or files; ticking is allowed whether or not
  something is already in sync

### 4. Transfer Options

Nothing that can overwrite or remove a local file runs without a review step.
Whichever action you choose, you get a plan first: what would be downloaded,
what would be replaced, what would be moved to backup, and a set of safety
checks. A plan that fails its checks needs you to type the season or series
name before it will run.

#### Sync
- **Sync the whole series** — one plan, grouped by season, removals listed first
- **Sync seasons** — tick several seasons; still one plan and one transfer
- **Sync this season** — download what is missing, replace what changed
- **Download & replace only** — the same, but leaves local files the remote no
  longer has

#### Pick individual files
- Tick episodes and choose **Download** (adds only what is missing, never
  overwrites) or **Replace** (backs up the local copy, then brings the remote one)
- Replacing a file that already matches is how you re-fetch a damaged copy

#### Dry run
- Available for a series, a set of seasons, one season, or ticked files
- Runs the plan's own rsync command with `--dry-run` and reports what rsync
  says, without moving anything — and leaves the plan runnable afterwards

#### Backups
- The actions panel lists what earlier syncs moved aside for whatever you are
  looking at, so you can see a replaced episode is still recoverable
- Read-only here; restoring is done on the Backups page

### 5. Monitor Transfers
- Real-time progress updates via WebSocket
- Transfer logs with detailed rsync output
- Ability to cancel running transfers
- Progress bars and status indicators
- Persistent transfer history in database
- Resume interrupted transfers

## Related

- [Installation](installation.md)
- [Explore](../features/explore/README.md) — browsing, comparing and planning a sync
- [Backups and restore](../features/backups/README.md)
- [Transfers](../features/transfers/README.md)
