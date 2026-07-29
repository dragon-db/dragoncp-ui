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

## Documentation

All documentation lives in [`docs/`](docs/). Two entry points:

- **[docs/README.md](docs/README.md)** — how to explore the docs, and the
  standard to follow when adding to them.
- **[docs/INDEX.md](docs/INDEX.md)** — the catalogue: every document, with a
  one-line summary and the known coverage gaps.

Common starting points:

| I want to... | Read |
|---|---|
| Install and run it | [Installation](docs/getting-started/installation.md) |
| Configure it | [Configuration](docs/reference/configuration.md) |
| Understand how a sync works | [System overview](docs/architecture/system-overview.md) |
| Work on transfers | [Transfers](docs/features/transfers/README.md) |
| Call the API | [API reference](docs/reference/api.md) |
| Deploy it | [Runtime and deployment](docs/operations/runtime-and-deployment.md) |
| Fix something broken | [Troubleshooting](docs/operations/troubleshooting.md) |

## Quick Start

See [Installation](docs/getting-started/installation.md) for prerequisites and
the full procedure, and [Usage](docs/getting-started/usage.md) for a walkthrough
of the main flows.

Development and test runs use `TEST_MODE=1 ./start.sh`, which keeps rsync in
dry-run. Production runs under systemd and gunicorn — see
[Runtime and deployment](docs/operations/runtime-and-deployment.md).

## License

This project is part of the DragonCP media management system and is specifically designed to work with the DragonDB management system. This application is optimized for DragonDB's custom setup and directory structure, and may not work correctly with other custom media management configurations. The application is intended for use with DragonDB's specific media organization and transfer workflows.
