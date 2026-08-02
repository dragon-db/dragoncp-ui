# Mobile App Strategy

**Status:** decided, not built. Tracked as TASK-013.

The question: should the React UI become an installable mobile app, and by which
route — a PWA, a native wrapper, or a React Native rewrite?

**Answer: PWA.** The reasoning, and what the other two would actually cost, is
below.

## Decision

**2026-08-01 — PWA, agreed by the operator.** Capacitor and React Native are
both off the table for now; revisit only under the conditions in §6, step 5.

Two things were noted at the same time:

- The README's scope and network sections are known to be stale. They are not
  being corrected piecemeal — README and docs get one pass together once the
  React app is the production UI with every feature integrated.
- This work is sequenced *after* the backups and rename-webhook rework, which is
  what the next branch covers. TASK-013 is planned, not in progress.

---

## 1. What the frontend is today

| | |
|---|---|
| Framework | React 19 + Vite 7 + TypeScript 5.9 |
| Routing | TanStack Router (file-based) |
| Server state | TanStack Query |
| Client state | Zustand (`auth`, `runtime`), `persist` to localStorage |
| UI primitives | Base UI (`@base-ui/react`) — 25 wrappers in `components/ui/` |
| Styling | Tailwind CSS v4, one 347-line `index.css` of tokens |
| Realtime | `socket.io-client` |
| HTTP | axios, relative `/api` baseURL |

106 TypeScript files, ~20,300 lines. The split that decides everything below:

| Layer | Lines | Portable off the DOM? |
|---|---|---|
| `lib/`, `hooks/`, `stores/`, `services/` | 4,625 | Mostly yes |
| `components/` + `routes/` | 14,981 | No |
| `index.css` | 347 | No |

1,411 `className=` occurrences. 51 files containing raw DOM tags. 15 `<table>`
structures. The view layer is DOM-and-Tailwind all the way down.

## 2. What the app actually does on a phone

Every expensive thing — rsync, SSH, the queue, the database, path planning —
happens on the Python server. The client sends JSON, receives Socket.IO events,
and renders tables and progress bars.

It needs **no native device capability**. No camera, no filesystem, no offline
authoring, no background execution. The one thing worth wanting from a native
app is a notification when a transfer finishes or a webhook lands while the app
is closed — and that is available to a PWA on Android.

This is the single most important fact in the assessment. A remote control for a
server has almost nothing to gain from being native.

## 3. Mobile work already done

The UI is not a desktop app awaiting a mobile retrofit:

- Explore had three separate mobile passes — one pane at a time, inspector in a
  sheet, progressive columns, a floating selection bar below `xl`, breadcrumbs
  that scroll rather than truncate (TASK-010).
- `MobileNav` — bottom tab bar with badges, `pb-[env(safe-area-inset-bottom)]`,
  hidden from `md` up.
- Sidebar collapses to a sheet below `md`; `use-mobile` / `use-media-query`
  hooks exist.
- Checked on a 390px viewport, on a real phone, not by reading CSS.

The reload-on-app-switch complaint was diagnosed and closed (TASK-012): it was
the Vite dev client, not the app. Built files are already served two ways —
`npm run serve:prod` on 5181, and an nginx container on 5002 via
`./deploy-frontend.sh` that already proxies `/api` and `/socket.io` to the
backend.

So: the phone UI exists, works, and has a production-shaped host. What is
missing is only the *installed* part.

## 4. The one real blocker: secure context

Service workers and PWA install require HTTPS. The deployment today is plain
HTTP over Tailscale — a `100.x` address or a MagicDNS short name. Neither is a
secure context, so no service worker can register.

This is a configuration gap, not a code gap:

1. Tailscale is already running on the host, and the phone is already on the
   tailnet.
2. `tailscale cert` is available but `CertDomains` is currently empty — HTTPS
   Certificates has not been enabled in the tailnet admin console. That is one
   toggle (Admin console → DNS → HTTPS Certificates).
3. Then `tailscale serve --bg --https=443 http://localhost:5002` puts a real
   Let's Encrypt certificate for `<machine>.<tailnet>.ts.net` in front of the
   existing nginx container.

No port forwarding, no public exposure, no reverse proxy on the box, no change
to the network model in the README. And because nginx already fronts `/`,
`/api` and `/socket.io` together, everything stays same-origin behind that one
certificate — exactly the shape `AGENTS.md` asks for.

## 5. The three options

### A. PWA — recommended

Add `vite-plugin-pwa`, a web app manifest, an icon set, and a service worker.

Specifics this codebase needs:

- **Exclude the API from navigation fallback.**
  `navigateFallbackDenylist: [/^\/api/, /^\/socket\.io/]`, or the service worker
  answers API 404s with `index.html`.
- **Do not runtime-cache `/api`.** This is a control panel; a stale queue state
  is worse than no state. Precache the app shell, `NetworkOnly` for the API.
- **Socket.IO is unaffected.** Service workers do not intercept WebSockets.
- **Add an update prompt.** A cached shell can leave a client on old JS against
  a new API. `registerType: 'prompt'` plus a toast — `sonner` is already wired.
- **`display: "standalone"`** removes browser chrome; the bottom nav's
  safe-area padding already covers the gesture bar.
- The 401 handler (`lib/api.ts:59`) does `window.location.href = "/login"`. It
  works standalone, but drops you at login rather than where you were. Worth
  improving, not blocking.

Push notifications are a separate, optional step: VAPID keys, a `pywebpush`
sender beside the existing socket emits, one subscription table, two endpoints.
Works on installed Android PWAs and on iOS 16.4+ home-screen apps.

**Cost:** roughly half a day for install + offline shell. One to two more days
if push is wanted.

### B. Capacitor — a real binary, the same code

Wraps the identical `dist/` in an Android/iOS shell. Keeps all 20,300 lines.

It sidesteps the certificate problem a different way: the WebView loads from
`https://localhost`, which is already a secure context. But the backend then
becomes cross-origin — the app origin is `https://localhost`, the API is
`http://<tailscale-ip>:5000`. That means:

- Setting `VITE_API_URL` and `VITE_WS_URL` explicitly. Both hooks already exist
  (`lib/api.ts:7`, `services/socket.ts:83`), so this part is free.
- Opening CORS and `cors_allowed_origins` to the app origin.
- An explicit cleartext-traffic exemption in the Android manifest.

That is a real loosening of the posture the README is deliberate about. In
exchange you get native FCM/APNs push without the Web Push work.

**Cost:** one to two days to a working APK, then a permanent Android SDK/Gradle
toolchain, signing keys, and a rebuild-and-sideload for every release — there is
no store for a 1–3 admin tool. That release friction is worse than a PWA's,
where nginx serving new files *is* the update.

### C. Expo / React Native — not worth it

"Export" does not apply here. `expo export` bundles a React Native app; React
Native cannot render this code. Base UI is DOM-only. Tailwind v4 classes do not
apply (NativeWind is a separate, partial reimplementation). `<div>`, `<table>`,
CSS grid, `position: sticky`, `env(safe-area-inset-*)`, `backdrop-blur` — none
survive.

- **Portable:** ~4,600 lines of api/types/socket/hooks/stores/parsers — and even
  those need edits for `window.setInterval`, `document.addEventListener` in the
  activity tracker, `window.location` in the 401 handler, `navigator.clipboard`.
- **Rewritten:** ~15,000 lines of components and routes plus the CSS token
  layer. That includes 25 Base UI wrappers, Explore (1,558 lines, three panes),
  Webhooks (1,071), Transfers (996).
- **Then maintained twice**, or the web UI is abandoned — but the web UI is what
  gets used from a desktop.

**Cost:** weeks, for an app whose distinguishing feature would be a rounder
icon. The one genuine advantage — native list performance — is a problem the
codebase already has a web answer for (`@tanstack/react-virtual`, noted as
pending on Explore).

## 6. Recommendation and sequence

PWA, and it is not close. The client is already a tested phone UI, the server
does all the work, and the only thing between here and an installed app is a
certificate that a tool already running on the host issues for free.

1. Enable HTTPS certificates in the tailnet admin console. Put `tailscale serve`
   in front of the nginx container on 5002. Confirm the phone loads the
   `.ts.net` URL over HTTPS. **No code.**
2. `vite-plugin-pwa` + manifest + icons + API denylist + update-prompt toast.
   Install to the home screen.
3. Use it for a week. "Does it feel like an app?" is answerable then and not
   before.
4. Only if push proves to be the thing actually wanted: VAPID, `pywebpush`,
   subscription storage. This is where the remaining value is — and Capacitor
   and React Native would both need an equivalent backend piece anyway.
5. Revisit Capacitor only if iOS becomes a target and Safari's PWA limits bite,
   or if the app must work off the tailnet. Neither is true today.

## 7. Open items to settle first

- **The React app is not the production UI yet.** `AGENTS.md` records that the
  served UI is still the legacy Flask/static one. An installed PWA is sticky —
  decide the cutover before putting an icon on a home screen.
- **962 KB of unsplit JS** (plus 161 KB CSS) is tolerable over Tailscale on
  first load and cached after, but route-level code splitting through TanStack
  Router would cut both install and update cost. Worth doing alongside.
- **Explore virtualisation** matters more once the app launches instantly and
  therefore gets opened more.

## Related

- [`../operations/runtime-and-deployment.md`](../operations/runtime-and-deployment.md)
- [`../getting-started/running.md`](../getting-started/running.md#do-not-open-the-dev-server-on-a-phone)
- [`../reference/frontend.md`](../reference/frontend.md)
