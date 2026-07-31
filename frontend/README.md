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
npm run serve:prod # built files on :5181 — use this one on a phone
npm run build
npm run lint
```

Reach for `serve:prod` when you are testing on a phone. A dev server page
reloads itself whenever you switch back to the browser, because the dev client
answers its dropped websocket with `location.reload()`. See
[running.md](../docs/getting-started/running.md#do-not-open-the-dev-server-on-a-phone).
