# DragonCP Frontend Reference

Last updated: 2026-10-05
Primary files: `frontend/src/`, `frontend/package.json`, `frontend/components.json`, `frontend/vite.config.ts`, `frontend_serving.py`, `app.py`, `start.py`

## Purpose

A map of the browser app: what is built with, where things live, which hooks
talk to the backend, and which state is held outside React Query. Everything
below was read from the files it names.

For the visual conventions the app follows, see
[design-system.md](./design-system.md). For the endpoints these hooks call, see
[api.md](./api.md). For how the app fits with the Python backend, see
[system-overview.md](../architecture/system-overview.md).

## Tech Stack

Versions are the ranges declared in `frontend/package.json`.

| Category | Package | Range |
|---|---|---|
| Framework | `react` / `react-dom` | ^19.2.0 |
| Build tool | `vite` | ^7.2.4 |
| Language | `typescript` | ~5.9.3 |
| Styling | `tailwindcss` + `@tailwindcss/vite` | ^4.1.17 |
| Component primitives | `@base-ui/react` | ^1.0.0 |
| Component CLI | `shadcn` | ^3.6.2 |
| Routing | `@tanstack/react-router` | ^1.144.0 |
| Client state | `zustand` | ^5.0.9 |
| Server state | `@tanstack/react-query` | ^5.90.16 |
| HTTP client | `axios` | ^1.13.2 |
| WebSocket | `socket.io-client` | ^4.8.3 |
| Icons | `@tabler/icons-react` | ^3.36.0 |
| Toasts | `sonner` | ^2.0.7 |
| Fonts | `@fontsource-variable/` nunito-sans, space-grotesk, jetbrains-mono | ^5.x |
| Animation utilities | `tw-animate-css` | ^1.4.0 |

The app is dark-only. `frontend/index.html` pins `<html lang="en" class="dark">`
and there is no theme switcher. `next-themes` is still listed as a dependency
but nothing in `src/` imports it; `components/ui/sonner.tsx` hard-codes
`theme="dark"` with a comment saying it does so because the app pins the class.

### Dev server

`npm run dev` sets `DRAGONCP_BACKEND=dev` and serves on port 5173.
`vite.config.ts` proxies `/api` and `/socket.io` (with `ws: true`) to a named
backend: `dev` is `http://localhost:5050`, `prod` is `http://localhost:5000`
(the live gunicorn service — writes hit real data). `DRAGONCP_BACKEND_URL`
overrides both. The chosen target is printed at startup. `npm run dev:prod`
picks `prod` and pins port 5181.

### Production serving

`npm run build` writes the production application to `frontend/dist/`. Flask
serves that directory same-origin with `/api` and `/socket.io`; extensionless
client routes fall back to `index.html`, while API paths and missing assets
retain real HTTP errors. Hashed `/assets/*` files are immutable for one year and
the shell is not cached. `./start.sh` rebuilds when the output is absent or
older than the source; the example systemd unit requires a build before start.
See [Legacy UI retirement](../operations/legacy-ui-retirement.md) for the
cutover, validation and rollback contract.

## Base UI, not Radix

The shadcn components in this project wrap `@base-ui/react` primitives. The two
libraries differ in how a component hands its rendering to a child element:
Radix uses an `asChild` prop, Base UI uses a `render` prop.

Three triggers accept `asChild` as a compatibility shim and convert it to Base
UI's `render` internally — `DialogTrigger` (`components/ui/dialog.tsx`),
`AlertDialogTrigger` (`alert-dialog.tsx`) and `DropdownMenuTrigger`
(`dropdown-menu.tsx`). Nothing else in `components/ui/` accepts `asChild`;
everywhere else, including router links inside sidebar buttons, uses `render`
directly (`render={<Link to={...} />}`).

## Project Structure

```
frontend/
├── src/
│   ├── components/
│   │   ├── activity/       # person-versus-automation badge
│   │   ├── auth/           # login, password change and forced-change gate
│   │   ├── backups/        # version list, history, housekeeping, restore and
│   │   │                   #   delete dialogs
│   │   ├── dashboard/      # system-ticker, storage-strip, transfers-panel,
│   │   │                   #   webhook-rail, disk-utils
│   │   ├── dry-run/        # dry-run-report (view, summary, dialog)
│   │   ├── explore/        # library-tree, contents-table, explore-bits, plan
│   │   │                   #   and repair dialogs
│   │   ├── integrations/   # connector form and icon, destinations, routing,
│   │   │                   #   delivery log, library/queue/history panels,
│   │   │                   #   scanner-status
│   │   ├── layout/         # app-layout, app-navbar, app-sidebar, mobile-nav,
│   │   │                   #   page-header, page-tabs, section-card,
│   │   │                   #   stat-tiles, list-controls, realtime-status,
│   │   │                   #   backend-unavailable-overlay
│   │   ├── pages/          # dashboard, transfers, webhooks, pipeline,
│   │   │                   #   pipeline-run, notifications, explore, backups,
│   │   │                   #   activity, integrations, settings
│   │   ├── pipeline/       # pipeline-bits, stage-flow, stage-detail, run-stages, sync-row, sync-sheet, alert-card
│   │   ├── settings/       # generated settings, account and backend logs
│   │   ├── transfers/      # transfer-bits, transfer-detail, transfer-logs,
│   │   │                   #   simulation-panel, confirm-dialog
│   │   ├── webhooks/       # webhook-bits, episode-details, auto-sync-panel,
│   │   │                   #   filename-diff, rename-verify-report
│   │   └── ui/             # shadcn components over Base UI primitives
│   ├── hooks/              # data hooks + runtime controller
│   ├── lib/                # api client, api types, formatting, grouping, utils
│   ├── routes/             # TanStack Router file-based routes
│   ├── services/           # socket.ts (Socket.IO client)
│   ├── stores/             # auth.ts, runtime.ts (Zustand)
│   ├── index.css           # brand tokens, theme variables, toast styling
│   └── main.tsx            # app entry point
├── components.json         # shadcn configuration
├── index.html              # pins class="dark"
├── package.json
└── vite.config.ts
```

Two files are left-over scaffolding rather than part of the running app:
`src/App.tsx` and `src/components/component-example.tsx` (which imports
`src/components/example.tsx`). `main.tsx` renders the router directly and never
imports `App.tsx`, and no route references `ComponentExample`.

## Routes

```
routes/
├── __root.tsx              # QueryClientProvider, Toaster, devtools (not on mobile)
├── index.tsx               # redirects to /dashboard or /login
├── login.tsx               # login page, redirects away when authenticated
├── _authenticated.tsx      # auth guard + AppLayout + useRuntimeConnection()
└── _authenticated/
    ├── dashboard.tsx       → components/pages/dashboard.tsx
    ├── transfers.tsx       → components/pages/transfers.tsx
    ├── webhooks.tsx        → components/pages/webhooks.tsx
    ├── notifications.tsx   → components/pages/notifications.tsx
    ├── backups.tsx         → components/pages/backups.tsx
    ├── activity.tsx        → components/pages/activity.tsx
    ├── settings.tsx        → components/pages/settings.tsx
    ├── pipeline/
    │   ├── index.tsx       # redirects to /transfers (the page was retired 2026-10-06)
    │   └── $runId.tsx      # redirects to /transfers?sync=<run id>
    ├── integrations/
    │   ├── index.tsx       # redirects to /integrations/discord
    │   └── $connector.tsx  → components/pages/integrations.tsx
    └── media/
        ├── index.tsx       # redirects to /media/movies
        └── $type.tsx       → components/pages/explore.tsx (movies, tvshows, anime)
```

`pipeline/$runId.tsx` and `integrations/$connector.tsx` key their page on the
parameter, so moving to a related sync starts from that sync's own stages, and
moving to another connector does not carry a half-typed form across.

`_authenticated.tsx` reads the auth store in `beforeLoad` and redirects to
`/login` when there is no token. It is also the single place
`useRuntimeConnection()` is mounted, so the socket lifecycle and backend-health
tracking run once for the whole signed-in app rather than per page.

`routeTree.gen.ts` is generated by `@tanstack/router-vite-plugin`; do not edit
it by hand.

## Custom Hooks

All hooks live in `src/hooks/`. Everything except `use-media-query`,
`use-mobile`, `useDebouncedValue` and the runtime pair wraps TanStack Query
around the Axios client in `lib/api.ts`.

| File | Exported hooks |
|---|---|
| `useActivity.ts` | `useActivity`, `useActivityFilters`, `useActivityForTarget` |
| `useAuth.ts` | `useLogin`, `useLogout`, `useChangePassword`, `useVerifyAuth`, `useAuthStatus` |
| `useBackups.ts` | `useBackupsOverview`, `useBackupTitles`, `useBackupSeasons`, `useBackupSlots`, `useBackupSlot`, `useUnsortedBackups`, `usePlanRestore`, `useRestoreCapture`, `usePinCapture`, `useDeletePreview`, `useDeleteBackups`, `useSaveRetention`, `useRetentionPreview`, `useRetentionApply`, `useRebuildIndex`, `useMigrationPlan`, `useMigrationApply`, `useBackupHistory`, `useUnseenRetention` (plus the `markRetentionSeen` helper) |
| `useConfig.ts` | `useSettings`, `useUpdateSettings`, SSH/runtime/disk diagnostic hooks, `useWebSocketStatus`, `useBackendLogs`, `useDownloadBackendLogs` |
| `useConnectors.ts` | `useConnectors`, `useConnector`, `useSaveConnector`, `useCheckConnector`, `useNotificationCatalogue`, `useSaveRoutes`, `useAddTarget`, `useUpdateTarget`, `useDeleteTarget`, `useTestTarget`, `useDeliveries` |
| `useExplore.ts` | `useExploreTree`, `useExploreRefresh`, `useExploreSeason`, `useExploreHistory`, `useExploreRepairPlan`, `useExploreRepair`, `useExploreBackups`, `useExplorePlan`, `useExploreDryRun`, `useExploreExecute`, `useExploreLibraries` |
| `useMediaLibrary.ts` | `useLibrary`, `useLibraryTitle`, `useLibraryHistory`, `useRefreshLibrary`, `useLibraryQueue`, `useSyncLibraryItem` — the Sonarr and Radarr Library, Queue and History tabs, `useLibraryTitle` for the series pop-up behind a card (`/library/<source>/<external_id>`), and `useLibraryTitleHistory` for its History tab |
| `use-media-query.ts` | `useMediaQuery` — follows any CSS media query, no network |
| `use-mobile.ts` | `useIsMobile` — viewport breakpoint check, no network |
| `useRemoteTransfer.ts` | `useRemoteTransferStatus`, `useRemoteTransferAction`, `useDetectAddress` — the fast-transfers panel |
| `useRuntime.ts` | `useRuntimeController`, `useRuntimeConnection` |
| `useSimulation.ts` | `useSimulationStatus`, `useStartSimulation`, `useStopSimulation`, `useCleanupSimulation` (plus the `busyConflictFrom` helper) |
| `useSync.ts` | `useSyncCatalogue`, `useSyncRuns`, `useSyncRun`, `useSyncRunAction`, `useAlerts`, `useAlertSummary`, `useAlertAction`, `useSchedulerJobs`, `useRunJob` (plus the `isLiveState` helper) — the sync engine, the Notifications page and the scheduler |
| `useTransferPosters.ts` | `useTransferPosters` |
| `useDebouncedValue.ts` | `useDebouncedValue` — holds a value back until typing settles, no network |
| `useTransfers.ts` | `useActiveTransfers`, `useAllTransfers`, `useTransferStatus`, `useTransferLogs`, `useQueueStatus`, `useStartTransfer`, `useCancelTransfer`, `usePauseTransfer`, `useResumeTransfer`, `useRestartTransfer`, `useDeleteTransfer`, `useBulkDeleteTransfers`, `useCleanupTransfers` |
| `useWebhooks.ts` | `useWebhookNotifications`, `useBulkDeleteNotifications`, `useRenameNotifications`, `useRenameNotificationDetails`, `useDeleteRenameNotification`, `useVerifyRenameNotification`, `useWebhookNotificationDetails`, `useWebhookNotificationJson`, `useTriggerWebhookGroupSync`, `useTriggerWebhookSync`, `useMarkWebhookComplete`, `useDeleteWebhookNotification`, `useWebhookDryRun`, `useWebhookSettings`, `useUpdateWebhookSettings`. The Discord hooks left with the Discord endpoints in 2.3.0 |

Three of these are worth knowing about before changing anything:

- **`useRuntimeConnection`** is the app's realtime engine, mounted once in
  `_authenticated.tsx`. It mirrors backend reachability and SSH state into the
  runtime store, reads the idle timeout from `WEBSOCKET_TIMEOUT_MINUTES` in app
  config, opens the socket when realtime has been requested, binds the
  transfer, webhook and rename events to a toast and a query invalidation and
  the sync engine's three events to throttled refreshes (see
  [Socket Service](#socket-service)), tracks user activity (click, keydown,
  submit, touchstart, throttled to once per 1.5 s), and every 15 s
  checks the idle clock. On timeout it first asks `/transfers/active`: if
  transfers are running it keeps the session alive and says so, otherwise it
  disconnects and tells the user polling continues.
- **`useRuntimeController`** is the read/act side used by the header status
  popover: current connection state, minutes remaining, and
  `enableRealtime` / `disableRealtime` / `reconnectRealtime` / `extendSession`.
- **`useTransferPosters`** builds a transfer-id → poster-URL map by joining the
  webhook notification list (transfers carry no artwork of their own). It reuses
  the notifications query, so it costs no extra request, but it only sees the 50
  most recent notifications — an older transfer falls back to the placeholder,
  and a hand-started transfer has no artwork anywhere.

Polling intervals set in `useTransfers.ts`: active transfers and queue status
every 5 s, a single transfer's status every 2 s, and a transfer's logs every 2 s
but only when the caller passes `live` (rows poll their own log only while open
and running).

Polling intervals set in `useSync.ts`: one run every 2.5 s while its state can
still change (`held`, `waiting`, `checking`, `queued`, `transferring`, `paused`,
`finishing` — `isLiveState`) and not at all once it has finished; a page of runs
every 4 s while any run on it is live, otherwise every 15 s; the alert lists and
the open-alert summary every 30 s; scheduler jobs every 3 s while one is running,
otherwise every 30 s. The catalogue is fetched once (`staleTime: Infinity`).
A run or alert action invalidates the `sync`, `alerts`, `transfers` and
`webhooks` queries when it settles; running a job invalidates `scheduler`,
`sync` and `alerts`.

## Stores (Zustand)

Two stores, both in `src/stores/`.

| Store | File | Holds |
|---|---|---|
| `useAuthStore` | `stores/auth.ts` | `token`, `refreshToken`, `user`, `isAuthenticated`, `expiresAt`; actions `login`, `logout`, `updateToken` |
| `useRuntimeStore` | `stores/runtime.ts` | backend reachability, SSH state, and the whole realtime/socket session |

`auth.ts` persists through Zustand's `persist` middleware under the localStorage
key `dragoncp-auth`, and all five fields are persisted. It also exports two
helpers used outside React: `isTokenExpired()` (true when under five minutes
remain, or when there is no expiry at all) and `shouldRefreshToken()` (true when
under thirty minutes remain).

`runtime.ts` is not persisted — it is rebuilt each load. It holds
`backendReachable` / `backendError`, `sshConnected`, the socket session
(`realtimeRequested`, `socketConnected`, `socketError`, `lastActivityAt`,
`timeoutMinutes`, `wasAutoDisconnected`, `configChanged`) and the "what just
happened" ticker (`liveActivityType`, `liveActivityMessage`, `liveActivityAt`,
where the type is one of `transfer`, `webhook`, `rename`, `info`).

Its important piece is `connectionState`, a single derived value the UI reads
instead of combining flags itself. Every setter recomputes it, in this order:

| State | When |
|---|---|
| `config-changed` | settings changed since the session started (checked first, even while connected) |
| `connected` | socket is connected |
| `auto-disconnected` | the session was dropped for inactivity |
| `idle` | realtime has never been requested — the app is in polling mode |
| `disconnected` | requested, not connected, and a socket error is recorded |
| `connecting` | requested, not connected, no error yet |

`components/layout/realtime-status.tsx` maps these six states to the label, dot
colour and wording shown in the header pill and its popover.

## Socket Service

`services/socket.ts` owns one lazily created Socket.IO client. It does not
autoconnect; `connectSocket()` refuses to run without an auth token and attaches
the token as `auth`. The URL comes from `VITE_WS_URL` or the page origin.
Transports are `polling` then `websocket` with upgrade enabled, and reconnection
is unlimited with a 1–15 s backoff.

Typed subscription helpers, each returning an unsubscribe function:

| Helper | Socket event |
|---|---|
| `onTransferUpdate` | `transfer_progress` |
| `onTransferComplete` | `transfer_complete` |
| `onTransferQueued` | `transfer_queued` |
| `onTransferPromoted` | `transfer_promoted` |
| `onWebhookReceived` | `test_webhook_received` |
| `onWebhookCaptured` | `webhook_received` |
| `onRenameWebhookReceived` | `rename_webhook_received` |
| `onRenameCompleted` | `rename_completed` |
| `onTransferLogs` | `transfer_logs` (room-scoped; see below) |
| `onSyncRunUpdated` | `sync_run_updated` |
| `onSyncRunEvent` | `sync_run_event` |
| `onAlertsChanged` | `alerts_changed` |

Also exported: `disconnectSocket`, `destroySocket`, `getSocket`,
`reAuthenticateSocket`, `subscribeTransferLogs` / `unsubscribeTransferLogs`
(join and leave a transfer's log room, replayed on reconnect),
`sendActivityPing` (emits `activity`) and `isSocketConnected`.

`useRuntime.ts` binds eleven of these; `onTransferLogs` and the log-room
subscriptions belong to the Transfers page, which patches an open row's log
from them. There is no `onTransferError`: a failure arrives as
`transfer_complete` with `status: "failed"`.

The sync engine's three events are bound as refresh hints, never as data:

- `sync_run_updated` invalidates the run lists (`["sync", "runs"]`) and that
  run (`["sync", "run", run_id]`); `sync_run_event` invalidates the run. Each of
  those keys refreshes at most once every 1.5 s, because one step of a run emits
  several events; the polling in `useSync.ts` catches anything a skipped event
  carried.
- `alerts_changed` writes its counts straight into the `["alerts", "summary"]`
  cache — the bell and the sidebar update at once — and invalidates the alert
  lists. When the open count rises above what the cache held, it raises a
  warning toast, "Something needs a person — see Notifications.", and stores the
  same sentence as the runtime store's latest live activity.

## Layout Shell

`components/layout/app-layout.tsx` wraps every signed-in page: a
`SidebarProvider` carrying the ambient background, the sidebar, then an inset
containing the navbar, the scrolling `<main>` (capped at 1920px), and the mobile
bottom nav as a flex sibling rather than a fixed overlay. It also mounts
`BackendUnavailableOverlay`, shown when the runtime-status query errors or the
store says the backend is unreachable, with a retry that refetches.

| Component | What it is |
|---|---|
| `app-sidebar.tsx` | Four groups — Workspace (Dashboard, Transfers, Webhooks, Notifications), Library (Browse Media → Movies, TV Shows, Anime), Integrations (one entry per connector the server lists, hidden until that list arrives, with a dot on each one switched on), System (Backups, Activity, Settings) — plus the user footer with a log-out button. Notifications carries an amber count of open alerts (`useAlertSummary`, capped at "99+"). Workspace had a Pipeline entry from 2026-10-05 to 2026-10-06; syncs now live on Transfers |
| `app-navbar.tsx` | Breadcrumb from a prefix path table, the live metrics pill (realtime status, Active, Queued), the bell and settings links, and a version badge. The bell links to Notifications and shows a dot while any alert is open; until 2026-10-05 it linked to Webhooks and lit for pending webhooks |
| `mobile-nav.tsx` | Bottom bar below `md`: Home, Transfers, Webhooks and a Menu button that opens the sidebar sheet, which is where Notifications is on a phone; counts come from active transfers and pending notifications |
| `realtime-status.tsx` | The connection popover — state, session minutes, active WebSocket count, and enable/extend/disable/reconnect |
| `page-header.tsx` | Page title, optional description, optional action buttons |
| `page-tabs.tsx` | `PageTabsList` — the in-page section switcher |
| `section-card.tsx` | `SectionCard` (bordered card with a label row, optional toolbar) and `SectionEmpty` |
| `stat-tiles.tsx` | `StatTiles` — the four-numbers row a page opens with |
| `backend-unavailable-overlay.tsx` | Full-screen "backend is down" state with retry |

## Explore Page

`components/pages/explore.tsx`, served at `/media/$type`. It replaced the old
`media-browser.tsx`, which is gone; the endpoints it used still exist but
nothing in the app calls them.

Unlike every other page it is **full-bleed**: `AppLayout` detects a `/media/`
route and drops the page padding and the max-width cap, because the layout is a
three-pane console that should reach the window edges.

| Pane | Component | Holds |
|---|---|---|
| Library | `explore/library-tree.tsx` | Series with their seasons on a thread line; badges align to the right edge at every depth |
| Contents | `explore/contents-table.tsx` | `SeasonRows` when a series is open, `EpisodeRows` when a season is |
| Actions | `Inspector` (in `explore.tsx`) | What is selected, what can be done to it, History and Backups |

Below `lg` the panes become one at a time; below `xl` the actions pane becomes a
`Sheet`, and a floating bar above the status line carries the current selection
because the pane holding its actions is off screen. `useMediaQuery` is used —
rather than CSS alone — only where behaviour differs, i.e. whether showing
actions means opening the sheet.

Supporting modules:

| File | Purpose |
|---|---|
| `explore/explore-bits.tsx` | `StatusBadge`, `EpisodeLabel`, `CountChips` |
| `explore/plan-dialog.tsx` | The review step, the dry-run card, the typed override |
| `lib/explore-types.ts` | Every shape the endpoints return |
| `lib/explore-format.ts` | `formatBytes`, `formatWhen`, `formatAge` |
| `index.css` | `.explore-*` thread-line geometry for the tree |

The page is keyed on the media type in `routes/_authenticated/media/$type.tsx`,
so switching library discards the open series, season, expanded rows and ticks
rather than carrying a TV series into Anime.

Behaviour and endpoints: [`../features/explore/README.md`](../features/explore/README.md).

## Transfers Page

`components/pages/transfers.tsx`, built on the layout primitives above:
`PageHeader` → `PageTabsList` → `StatTiles` → `SectionCard` with rows that
expand in place. There are no detail dialogs; opening a row is the only way in.

| Tab | Shows |
|---|---|
| Activity | **Waiting to start** — syncs not at the queue yet (held, waiting, checking), when there are any — then running, queued and paused copies |
| History | Finished runs — status filters (All, Completed, Failed, Stopped), search, paging and bulk delete — then **Stopped before copying**: syncs that ended without a transfer, 10 to a page |
| Simulate | Scenario launcher for the simulation tool |

The page also owns the **sync panel**: `?sync=<run id>` (the route's
`validateSearch`) opens `SyncSheet` over it, and closing it clears the
parameter. Rows on both sync lists, a transfer's **Webhooks, alerts and related
syncs**, an alert's **Open the sync**, an episode's **Open its sync** and the
auto-scanner card all link there. See
[syncs on the Transfers page](#syncs-on-the-transfers-page-and-notifications).

Supporting components in `components/transfers/`:

| File | Purpose |
|---|---|
| `transfer-bits.tsx` | `TransferStatusBadge`, `ProgressMeter`, `TransportBadge` (the route badge — **Fast**, **SSH** or **SSH fallback**; nothing while queued or for runs before routes were recorded; also on the dashboard's Active Transfers rows), `Chip`, `Fact`, `PathBlock` — the stage list's Transfer stage reuses several |
| `transfer-detail.tsx` | `TransferDetailPanel` and its `TransferActions` interface. Where a queued / started / completed `Timeline` used to be, **Pipeline** draws the transfer's sync with `RunStages` (Transfer stage facts off — the row already shows them) and any open alert as an `AlertCard`, fetched by `useSyncRun` only while the row is open |
| `transfer-logs.tsx` | `TransferLogConsole` — live rsync output; only lines that break rsync's repetitive rhythm are tinted. Also embedded in the sync panel's Transfer stage |
| `simulation-panel.tsx` | `SimulationPanel` scenario launcher and `SimulationBadge` |
| `confirm-dialog.tsx` | State-driven `AlertDialog` for stop/delete/cleanup/bulk delete |

`lib/transfer-progress.ts` holds the formatting and derivation: `formatBytes`,
`formatSpeed`, `formatEta`, `formatSizePair`, `formatDuration`,
`parseTimestamp`, `transferElapsed`, `parseProgressText`, `transferPercent`,
`isActiveStatus`.

Worth knowing when changing this page:

- **Realtime is opt-in.** The socket only connects when the user enables it, so
  a socket-only log would be frozen for anyone who has not. Open rows poll their
  own log while the transfer runs (`useTransferLogs` with `live`), and socket
  events patch the same query cache when realtime is on.
- **Progress events patch the cache rather than triggering a refetch.** They
  arrive several times a second per transfer; refetching per event meant one API
  round trip per rsync output line.
- **History is filtered, searched and paged on the server.** The tab requests
  `statuses=completed,failed,cancelled` so live rows never reach it, and the
  filter buttons pass a `status` rather than narrowing what arrived. Filtering in
  the browser could only ever find what the fetched slice contained, which is why
  "Failed" showed nothing while failures existed further back.
- **Who started it, the route and the sync come from the listing.** A row's
  "by …" fact, the detail's *Started by* badge, the route badge, the
  detail's *Route* fact and its **Pipeline** read `started_by_kind`,
  `started_by_name`, `transport` and `sync_run_id` from `/transfers/all` and
  `/transfers/active`. Until 2026-10-05 neither listing returned them, so every
  transfer said "not recorded" and the fast route never showed.
- **Restart shows the server's answer.** The toast is the endpoint's own
  message — "Restart requested: the safety check runs first, then the queue."
  — or its refusal, such as a restore's "A restore is run again from the
  Backups page, where its preview shows what it will replace." It used to say
  "Transfer restarted" or "Could not restart the transfer" whatever happened.

## List Controls

`components/layout/list-controls.tsx` holds what the long lists need, so the
Transfers History tab and the Media sync tab are driven identically; the
Pipeline list uses its search, filter chips and pager too, and Notifications
its pager:

| Export | Purpose |
|---|---|
| `ListSearch` | Search box with a clear button; pair with `useDebouncedValue` |
| `FilterChips` | Status filters, each showing its own server-counted total |
| `ListPagination` | Position stated in records ("51–100 of 519"), page sizes 25/50/100, previous/next |
| `SelectionBar` | Appears once rows are picked: select page, select every match, clear, delete |
| `RowCheckbox` | Row tick that does not open the row it sits on |

Two distinctions these encode are worth keeping:

- **Select page and select-all-matching are separate actions.** The first takes
  the rows in view; the second means every record the filter finds, which the
  server re-evaluates at delete time rather than the browser shipping thousands
  of ids. Touching any single row cancels the broader claim.
- **Counts describe the record, not the page.** Filter chips and stat tiles read
  `status_counts` from the listing; tab badges read `unfiltered_total`, which
  ignores the search so a badge does not count down as someone types.

See [transfers](../features/transfers/README.md), [queue](../features/queue/README.md)
and [simulation](../features/simulation/README.md) for the backend side.

## Webhooks Page

`components/pages/webhooks.tsx` has two tabs, `Media sync` and `Renames`, each
with its own stat tiles. The media-sync tab filters by All, Completed, Pending,
Syncing, Manual (`MANUAL_SYNC_REQUIRED`) and Failed, each chip carrying its own
count, and uses the shared [list controls](#list-controls) for search, paging and
bulk delete.

Rows are grouped by season after paging, so a season split across a page
boundary appears on both pages; selecting a season row selects every arrival
inside it.

Supporting components in `components/webhooks/`:

| File | Purpose |
|---|---|
| `webhook-bits.tsx` | `MediaIcon`, `WebhookPoster`, `StatusDot`, `StatusBadge`, `MediaBadge` — shared by the page and the dashboard rail |
| `episode-details.tsx` | `EpisodeDetailPanel`, `EpisodeList` and the `EpisodeActions` interface |
| `auto-sync-panel.tsx` | `AutoSyncControl` |
| `filename-diff.tsx` | Old name over new name with only changed tokens tinted, plus a `−`/`+` gutter so the diff reads without colour |
| `rename-verify-report.tsx` | `RenameVerifyReport` and `RenameVerifyDialog` |

`lib/webhook-grouping.ts` is the shared logic: grouping notifications into
items (`groupNotifications`, `releaseGroups`, `episodeEntries`), status
vocabulary (`statusInfo`, `effectiveStatus`, `groupStatus`, `isSyncable`), sizing
(`fileBytes`, `seasonBytes`, `effectiveSize`, `formatSize`) and labels
(`mediaLabel`, `itemTitle`, `itemDetail`, `formatEpisodeRange`, `timeAgo`).
`lib/rename-diff.ts` holds `diffFilenames` and `episodeTagOf`.

**Manual, not Pending.** The backend never stores `MANUAL_SYNC_REQUIRED`: a
sync the safety check stopped, or a restart interrupted, leaves its
notifications `pending` with `requires_manual_sync` raised.
`effectiveStatus()` turns that pair into `MANUAL_SYNC_REQUIRED`, which
`statusInfo` labels **Manual**. Episode rows use it, and so does `groupStatus`,
so a movie row, a season row and the dashboard's webhook rail read Manual too —
unless another episode in the season is plainly `pending`, which ranks above it.
`EpisodeDetailPanel` opens with "Waiting for a person: <reason>" for such a
notification and with **Open its sync** for any notification carrying a
`sync_run_id`.

See [webhooks](../features/webhooks/README.md), [renames](../features/renames/README.md)
and [auto-sync](../features/auto-sync/README.md).

## Syncs on the Transfers Page, and Notifications

The sync engine's screens, all through `hooks/useSync.ts`. Syncs have no page
of their own: they are read on Transfers (see [Transfers Page](#transfers-page))
— inside a transfer's row, in the two sync lists, and in the sync panel. What
an operator sees is described in
[the sync engine](../features/sync-engine/README.md#screens). A Pipeline page
(`pages/pipeline.tsx`, `pages/pipeline-run.tsx`) existed from 2026-10-05 to
2026-10-06; its routes now redirect.

| Page | File | Route |
|---|---|---|
| Notifications — open and closed alerts | `pages/notifications.tsx` | `/notifications` |

Supporting components in `components/pipeline/`:

| File | Purpose |
|---|---|
| `pipeline-bits.tsx` | `StageNode` (a stage's round marker), `StageStatusBadge`, `StageStrip` (nine segments, each titled with its stage and outcome, the whole labelled for screen readers), `RunStateBadge`, `KindBadge`, `FactLine` |
| `run-stages.tsx` | `RunStages` — `StageFlow` and, under it, the `StagePanel` of the one stage picked; used in a transfer's row and in the sync panel. Until someone picks, the stage that is failed, refused, waiting or running is open (none for a clean run); picking the open stage again closes it |
| `stage-flow.tsx` | `StageFlow` — the nine stage cards, sized by a container query (`@container`: three across, five from `@lg`, nine from `@4xl`) because the same flow sits in a page-wide row and in a 42rem panel. Each card is a toggle (`aria-expanded`, `aria-controls` the panel); the picked one has a brand outline, the live one a tint and a pulsing dot, and from `@4xl` a rule joins each card to the next, green after a passed stage |
| `stage-detail.tsx` | `StagePanel` — one stage: its sentence, time and duration, its kind's note, its facts (Receive the linked webhooks; Identify, Ready check, Safety check and Transfer draw theirs) and its log lines (the last 200). The Transfer stage embeds `TransferLogConsole` from `components/transfers/transfer-logs.tsx`, polled every 2 s while rsync runs; `showTransferFacts={false}` leaves that out inside a transfer's row. Its anchor is `stage-<run id>-<stage>` (`stageAnchor`), since several runs can be open at once. Replaced `stage-list.tsx`, an accordion of all nine, on 2026-10-07 |
| `sync-row.tsx` | `SyncRow` — one run without a transfer row, for **Waiting to start** and **Stopped before copying**: title, kind, state, `StageStrip`, the sentence, facts, and **Sync now** / **Go now** for a held or waiting run |
| `sync-sheet.tsx` | `SyncSheet` — the sync panel: header with the run's actions, the state callout, its alerts, `RunStages`, webhooks linked, its transfer and related runs (each opens in the panel) |
| `alert-card.tsx` | `AlertCard` — one alert with the buttons its `action_buttons` name, a confirm before `sync_anyway`, and **Open the sync**, which opens the sync panel on Transfers (left out inside the panel) |

`lib/pipeline.ts` holds the pipeline vocabulary that is not a component, so
`pipeline-bits.tsx` exports components only, as fast refresh needs: the tone
classes (`TONE_BADGE`, `TONE_TEXT`), the stage-status and run-state maps
(`STAGE_STATUS`, `stageStatusInfo`, `RUN_STATE`, `runStateTone`) and the words
for time (`formatSpan`, `sinceText`, `clockText`). `lib/sync-types.ts` mirrors
what `routes/sync_engine.py` returns (`SyncCatalogue`, `RunSummary`,
`RunDetail`, `StageDetail`, `RunEvent`, `RunWebhook`, `RunTransfer`,
`RelatedRun`, `RunActionResult`, `Alert`, `AlertList`, `AlertSummary`,
`SchedulerJob`). Neither repeats the stage or kind vocabulary: labels,
taglines and each kind's notes come from `GET /api/sync/catalogue`, so the
screen cannot describe a different pipeline from the one that ran.

Worth knowing when changing these pages:

- **A row's sentence depends on the state.** A live run shows
  `current_summary` — what its current stage last wrote — and falls back to
  `outcome_message`; a finished one shows `outcome_message` first. The panel's
  one-line callout does the same, without the fallback for a live run.
- **The open stages follow the run until someone chooses.** Until a stage is
  opened or closed by hand, the open set is recomputed from the run: its current
  stage while it is live, plus every stage `running`, `waiting`, `failed` or
  `refused`. The panel's body is keyed on the run, so a related sync starts
  from its own set.
- **The two sync lists ask for `copied=0`.** Waiting to start is
  `state=held,waiting,checking`, Stopped before copying
  `state=failed,cancelled,refused,interrupted` (fetched only while History is
  showing). A run's `transfer_id` cannot answer "did it copy": a retry carries
  the id of the copy it retries.
- **The Closed tab is one request** (`state=done,wrong,dismissed`).
- **Retry in the panel is the transfer restart** (`useRestartTransfer`); on
  success the panel refreshes the sync queries and switches to the new retry.
  Go now, Sync anyway and Cancel go through `useSyncRunAction`.
- **Only a 404 reads "No such sync".** Any other failed fetch reads "Could not
  load this sync" with the server's reason and a Try again button.

## Integrations Page

`components/pages/integrations.tsx`, at `/integrations/$connector`, draws a
connector's tabs from what it declares rather than from its name: a connector
that can notify (Discord) gets its destinations, **Routing**, Activity and its
settings tab; one that answers queries (Sonarr, Radarr, Jellyfin) gets Library,
Queue, History and its settings tab. **Routing** was named Notifications until
2026-10-05; that name now belongs to the alerts page.

The tabs are `PageTabsList`, the same underlined bar as Transfers and Webhooks
(a segmented pill until 2026-10-07), with an icon each and the settings tab at
the far end. Destinations count their webhooks; Library counts its titles and
Queue its downloads, read through `useLibrary` and `useLibraryQueue` — the same
queries the panels make, so the Library count costs nothing extra. The queue is
only asked for once the library has answered, so a query connector with no
library here (Jellyfin) is not polled for one.

On the Library tab each card is `group/card`, and `TitlePoster` takes
`interactive`: on hover or keyboard focus the picture eases in within its
frame, dims, a brand ring draws round it and an "Episodes" (or "Details") veil
fades in. The card itself does not move; until 2026-10-07 it lifted on hover,
which made the grid jump as the pointer crossed it.

The tab in view and an open title live in the address: the route's
`validateSearch` reads `?tab=` and `?title=` (a TVDB or TMDB id, kept a number
so the address has no quotes), and the tabs are controlled from it. A Library,
Queue or History row calls the page's `onOpenTitle`, which sets `?title=`;
`integrations/title-dialog.tsx` (`TitleDialog`, rendered once by the page)
opens over the list and clears it on close, so the list keeps its filters,
search, page and scroll. The dialog is the whole screen below `sm` and a
`max-w-3xl` panel above, with its own 44px close button. Inside, two tabs:

- **Episodes** reads `useLibraryTitle`, draws its header from the cached library
  list while that loads, and offers **Get** and **Replace** through Explore's
  own plan and execute hooks (`useExplorePlan`, `useExploreExecute`): one plan
  per season with the episode codes, a one-line confirmation built from the
  plan's counts, then the plan ids executed. A 409 "no browse session" from
  the plan is answered by `useSSHAutoConnect` and one retry.
- **History** reads `useLibraryTitleHistory` once the tab is opened. Each
  entry's mark is worked out on screen (`marksFor`): an import from the
  episode comparison already loaded (Not here yet, Different here, Here; only
  an episode's newest import), a failed download of an episode that is here
  anyway as Here anyway, and a failed or stopped sync that a newer finished
  sync of the same season covers as Done later. Everything / Not done is a
  local filter.

`title-sheet.tsx`, the side panel it replaced, and the episode strip and legend
in `library-bits.tsx` were removed on 2026-10-12. `PageTabsList` tabs are 44px
tall below `sm` and never shrink in a flex column (in the dialog, a long
History list squeezed the tab bar to 8px).

On a query connector's settings tab, `integrations/scanner-status.tsx`
(`ScannerStatus`) sits under the form. It looks for the scheduler job named
`<connector>_auto_scanner` in `useSchedulerJobs()` and renders nothing when
there is none — so Jellyfin has no card — otherwise the schedule, the last
scan's summary, up to eight of that scan's decisions (a started sync opens in
the sync panel on Transfers) and **Scan now** (`useRunJob`) while the job is enabled.
Behaviour: [integrations](../features/integrations/README.md).

## Dashboard

`components/pages/dashboard.tsx` is a thin composition of four pieces from
`components/dashboard/`: `SystemTicker` (status dot, peak disk, queue, queued,
webhook count, refresh stamp), `StorageStrip`, `TransfersPanel` and
`WebhookRail`. `disk-utils.ts` normalises local and remote disk usage into one
`DiskItem` list and defines the severity thresholds used across the dashboard —
`warn` at 78%, `crit` at 92%.

## Page Tab Bar

`components/layout/page-tabs.tsx` — the section switcher used by the transfers,
webhooks, backups and notifications pages. It is shadcn's `Tabs`
`variant="line"` re-tinted to the brand, so a page marks its active section the
same way the mobile bottom nav does rather than introducing a second idiom.

`PageTabItem` fields: `value`, `label`, `icon`, `count` (badge, omit when there
is nothing to count), `atEnd` (pushes a segment to the far end from `sm` up,
marking a tool rather than another view).

Sizing notes, since both have bitten before: segments use `flex-none` to beat
the base trigger's `flex-1`, whose `0%` basis would give every segment the same
width regardless of content; and count badges are hidden below `sm` so three
segments fit on a phone without one scrolling out of sight.

## UI Components

`src/components/ui/` — 26 files, all installed through shadcn and wrapping Base
UI where a primitive exists.

| Component | Base UI primitive |
|---|---|
| `accordion` | `@base-ui/react/accordion` |
| `alert-dialog` | `@base-ui/react/alert-dialog` |
| `badge` | `@base-ui/react/use-render` |
| `button` | `@base-ui/react/button` |
| `card` | native elements |
| `checkbox` | `@base-ui/react/checkbox` |
| `combobox` | `@base-ui/react` (`Combobox`) |
| `dialog` | `@base-ui/react/dialog` |
| `dropdown-menu` | `@base-ui/react/menu` |
| `field` | native elements |
| `input` | `@base-ui/react/input` |
| `input-group` | native elements |
| `label` | native elements |
| `popover` | `@base-ui/react/popover` |
| `progress` | `@base-ui/react/progress` |
| `scroll-area` | `@base-ui/react/scroll-area` |
| `select` | `@base-ui/react/select` |
| `separator` | `@base-ui/react/separator` |
| `sheet` | `@base-ui/react/dialog` |
| `sidebar` | `@base-ui/react/use-render` |
| `skeleton` | native elements |
| `sonner` | the `sonner` library |
| `switch` | `@base-ui/react/switch` |
| `tabs` | `@base-ui/react/tabs` |
| `textarea` | native elements |
| `tooltip` | `@base-ui/react/tooltip` |

### Sub-exports worth knowing

- **Button** — `Button`, `buttonVariants`. Variants `default`, `outline`,
  `secondary`, `ghost`, `destructive`, `link`; sizes `default`, `xs`, `sm`,
  `lg`, `icon`, `icon-xs`, `icon-sm`, `icon-lg`.
- **Badge** — `Badge`, `badgeVariants`. Variants `default`, `secondary`,
  `destructive`, `outline`, `ghost`, `link`.
- **Card** — `Card`, `CardHeader`, `CardTitle`, `CardDescription`, `CardAction`,
  `CardContent`, `CardFooter`.
- **Dialog** — `Dialog`, `DialogTrigger`, `DialogContent`, `DialogHeader`,
  `DialogTitle`, `DialogDescription`, `DialogFooter`, `DialogClose`,
  `DialogOverlay`, `DialogPortal`.
- **AlertDialog** — `AlertDialog`, `AlertDialogTrigger`, `AlertDialogContent`,
  `AlertDialogHeader`, `AlertDialogTitle`, `AlertDialogDescription`,
  `AlertDialogFooter`, `AlertDialogAction`, `AlertDialogCancel`,
  `AlertDialogMedia`, `AlertDialogOverlay`, `AlertDialogPortal`. There is no
  `AlertDialogClose` — use `AlertDialogCancel`.
- **Tabs** — `Tabs`, `TabsList`, `TabsTrigger`, `TabsContent`, `tabsListVariants`.

## Library Modules

| File | Contents |
|---|---|
| `lib/api.ts` | The Axios instance (default export `api`, also named `api`), `authApi`, and the `ApiResponse` / `LoginResponse` / `VerifyResponse` types |
| `lib/api-error.ts` | `errorText(error, fallback)` — the server's own `message` from a failed request, else the fallback |
| `lib/api-types.ts` | Shared backend shapes: `Transfer`, `QueueStatus`, `WebhookNotification`, `RenameNotification`, `AppConfig`, `SSHConfig`, `DiskUsage`, `DryRunResult`, and the `TransferStatus` / `WebhookStatus` / `SyncStatusType` unions. `Transfer` and `WebhookNotification` carry `sync_run_id`; `WebhookNotification` also `requires_manual_sync` and `manual_sync_reason` |
| `lib/backup-types.ts` | Every shape the Backups endpoints return, plus the history and reason label maps |
| `lib/dry-run.ts` | `parseDryRun` plus `DryRunReport` and friends, and its own `formatBytes` / `formatNumber` / `formatDuration` |
| `lib/explore-types.ts`, `lib/explore-format.ts` | Explore's shapes and formatting (see [Explore Page](#explore-page)) |
| `lib/media-filename.ts` | `parseFilename`, `containerOf`, `EPISODE_CODE` — reading a Sonarr/Radarr-shaped file name |
| `lib/pipeline.ts` | Pipeline tones, stage-status and run-state maps, time words and `stageAnchor` (see [Syncs on the Transfers Page, and Notifications](#syncs-on-the-transfers-page-and-notifications)) |
| `lib/query-client.ts` | The shared `queryClient` |
| `lib/rename-diff.ts` | `diffFilenames`, `episodeTagOf`, `isSeparatorToken` |
| `lib/sync-types.ts` | The sync engine's, alerts' and scheduler's response shapes |
| `lib/transfer-progress.ts` | Transfer formatting and derivation (listed above) |
| `lib/utils.ts` | `cn()` — clsx + tailwind-merge |
| `lib/version.ts` | `isOutdated` — whether this tab's build differs from the server's; an unknown version on either side never counts |
| `lib/webhook-grouping.ts` | Webhook grouping, status and sizing (listed above) |

`lib/dry-run.ts` and `lib/transfer-progress.ts` each export their own
`formatBytes` and `formatDuration` with different signatures. Import from the
one that matches the data you are formatting.

## shadcn Configuration

From `frontend/components.json`:

| Setting | Value |
|---|---|
| Style | `base-nova` |
| RSC | `false` |
| TSX | `true` |
| Base colour | `neutral` |
| CSS variables | `true` |
| Tailwind CSS entry | `src/index.css` |
| Icon library | `tabler` |
| Menu colour / accent | `default` / `subtle` |

Aliases: `@/components`, `@/components/ui`, `@/lib`, `@/lib/utils`, `@/hooks`.
The `@` → `./src` resolution itself is set in `vite.config.ts`.

## Icons

All icons come from `@tabler/icons-react`:

```tsx
import { IconTransfer } from '@tabler/icons-react';
```

Navigation icons in use: `IconLayoutDashboard`, `IconTransfer`, `IconWebhook`,
`IconRoute` (every "Open its sync" link), `IconBell`
(Notifications and the header bell), `IconCategory2` (Browse Media),
`IconMovie`, `IconDeviceTv`, `IconBrandNetflix`, `IconArchive`, `IconHistory`,
`IconSettings`, `IconHome`, `IconMenu2`, `IconLogout`, `IconChevronRight`.

## Toasts

`sonner`, mounted once in `routes/__root.tsx` as `<Toaster position="top-right"
richColors />`. Toast placement and styling are customised in the
`@layer components` block of `index.css` so the toaster clears the 3.5rem
header and, from `lg` up, the sidebar.

```tsx
import { toast } from 'sonner';

toast.success('Message');
toast.error('Error message');
```

## Not verified

- Whether `next-themes` is pulled in transitively by a shadcn component rather
  than being pure leftover. It is only confirmed unused in `src/`.
- Whether the leftover `App.tsx` / `component-example.tsx` files are
  deliberately kept as a component gallery. They are confirmed unreferenced by
  the router.
- The Pipeline, sync, Notifications and Integrations pages as rendered in a
  browser. Everything said about them here was read from the source on
  2026-10-05; none of it was clicked through, and the frontend has no tests.
