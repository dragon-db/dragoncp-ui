# DragonCP React Frontend

Frontend client for DragonCP admin operations.

Documentation for this app lives in the project documentation library:

- [Frontend reference](../docs/reference/frontend.md) — architecture, routes,
  components, hooks and stores
- [Design system](../docs/reference/design-system.md) — visual conventions
- [Frontend deployment](../docs/operations/frontend-deployment.md) — building
  and running it in a container

Start at [docs/README.md](../docs/README.md) for how the library is organised.

## Working on it

```bash
npm install
npm run dev        # dev server, proxies /api to the local backend on :5050
npm run dev:prod   # same, but proxies to the production backend on :5000
npm run build
npm run lint
```
