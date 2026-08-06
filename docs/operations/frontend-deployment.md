# Frontend deployment

Last updated: 2026-08-06

The normal production deployment serves the built React application from the
same Flask/Gunicorn process as the API and Socket.IO. The nginx container remains
an optional alternative for previewing or placing a frontend proxy in front of
the host backend.

## Normal production path

Build before restarting the service:

```bash
cd frontend
npm ci
npm run build
cd ..
sudo systemctl restart dragoncp-ui
```

Flask serves `frontend/dist/index.html`, static build assets, and client-side
route fallbacks on the backend's existing port. The example systemd unit has an
`ExecStartPre` check for the built index so a missed build fails visibly.

`frontend/dist/` is ignored by Git. Rebuild after every frontend change; an old
directory can otherwise serve an old client against a new backend.

## Optional nginx container

The repository also includes a Docker Compose setup for running the React
frontend in its own container while keeping the backend on the host.

- Compose file: `docker-compose.yml`
- Frontend image build: `frontend/Dockerfile`
- nginx reverse proxy config: `frontend/nginx.conf`
- Default frontend URL: `http://localhost:5002`

### How the container works

- nginx in the frontend container serves the built React app.
- nginx proxies `/api` and `/socket.io` to the backend running on the host at port `5000`.
- Because the browser stays on a single origin, the React app can keep using its default relative API and Socket.IO settings.

### Start the container

```bash
docker compose up -d --build frontend
```

### Deploy container changes

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
- The browser must use the frontend container's port in this topology. Opening
  the backend port serves Flask's own React build instead.

## Related

- [Runtime and deployment](runtime-and-deployment.md) - backend under systemd and gunicorn
- [Legacy UI retirement](legacy-ui-retirement.md) - serving contract, capability audit and rollback
- [Frontend reference](../reference/frontend.md) - architecture of the app being built
