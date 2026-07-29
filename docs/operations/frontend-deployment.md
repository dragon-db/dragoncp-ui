# Frontend Deployment

Running the React frontend in its own container, with the backend staying on the
host. Moved here from the repository README.

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

## Related

- [Runtime and deployment](runtime-and-deployment.md) - backend under systemd and gunicorn
- [Frontend reference](../reference/frontend.md) - architecture of the app being built
