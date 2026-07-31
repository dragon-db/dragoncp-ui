# DragonCP Frontend Reference

Last updated: 2026-07-28
Primary files: `frontend/src/`, `frontend/package.json`, `frontend/components.json`, `frontend/vite.config.ts`

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
│   │   ├── auth/           # login-form
│   │   ├── dashboard/      # system-ticker, storage-strip, transfers-panel,
│   │   │                   #   webhook-rail, disk-utils
│   │   ├── dry-run/        # dry-run-report (view, summary, dialog)
│   │   ├── layout/         # app-layout, app-navbar, app-sidebar, mobile-nav,
│   │   │                   #   page-header, page-tabs, section-card,
│   │   │                   #   stat-tiles, realtime-status,
│   │   │                   #   backend-unavailable-overlay
│   │   ├── pages/          # dashboard, transfers, webhooks, explore,
│   │   │                   #   backups, settings
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
    ├── backups.tsx         → components/pages/backups.tsx
    ├── settings.tsx        → components/pages/settings.tsx
    └── media/
        ├── index.tsx       # redirects to /media/movies
        └── $type.tsx       → components/pages/explore.tsx (movies, tvshows, anime)
```

`_authenticated.tsx` reads the auth store in `beforeLoad` and redirects to
`/login` when there is no token. It is also the single place
`useRuntimeConnection()` is mounted, so the socket lifecycle and backend-health
tracking run once for the whole signed-in app rather than per page.

`routeTree.gen.ts` is generated by `@tanstack/router-vite-plugin`; do not edit
it by hand.

## Custom Hooks

All hooks live in `src/hooks/`. Everything except `use-mobile` and the runtime
pair wraps TanStack Query around the Axios client in `lib/api.ts`.

| File | Exported hooks |
|---|---|
| `useAuth.ts` | `useLogin`, `useLogout`, `useVerifyAuth`, `useAuthStatus` |
| `useBackups.ts` | `useBackups`, `useBackupDetails`, `useBackupFiles`, `useRestoreBackup`, `useDeleteBackup`, `usePlanRestoreBackup`, `useReindexBackups` |
| `useConfig.ts` | `useAppConfig`, `useUpdateConfig`, `useResetConfig`, `useEnvOnlyConfig`, `useSSHConfig`, `useSSHStatus`, `useRuntimeStatus`, `useSSHConnect`, `useSSHAutoConnect`, `useSSHDisconnect`, `useLocalDiskUsage`, `useRemoteDiskUsage`, `useDebugInfo`, `useWebSocketStatus` |
| `useExplore.ts` | `useExploreTree`, `useExploreRefresh`, `useExploreSeason`, `useExploreHistory`, `useExploreBackups`, `useExplorePlan`, `useExploreDryRun`, `useExploreExecute`, `useExploreLibraries` |
| `use-media-query.ts` | `useMediaQuery` — follows any CSS media query, no network |
| `use-mobile.ts` | `useIsMobile` — viewport breakpoint check, no network |
| `useRuntime.ts` | `useRuntimeController`, `useRuntimeConnection` |
| `useSimulation.ts` | `useSimulationStatus`, `useStartSimulation`, `useStopSimulation`, `useCleanupSimulation` (plus the `busyConflictFrom` helper) |
| `useTransferPosters.ts` | `useTransferPosters` |
| `useDebouncedValue.ts` | `useDebouncedValue` — holds a value back until typing settles, no network |
| `useTransfers.ts` | `useActiveTransfers`, `useAllTransfers`, `useTransferStatus`, `useTransferLogs`, `useQueueStatus`, `useStartTransfer`, `useCancelTransfer`, `usePauseTransfer`, `useResumeTransfer`, `useRestartTransfer`, `useDeleteTransfer`, `useBulkDeleteTransfers`, `useCleanupTransfers` |
| `useWebhooks.ts` | `useWebhookNotifications`, `useBulkDeleteNotifications`, `useRenameNotifications`, `useRenameNotificationDetails`, `useDeleteRenameNotification`, `useVerifyRenameNotification`, `useWebhookNotificationDetails`, `useWebhookNotificationJson`, `useTriggerWebhookSync`, `useMarkWebhookComplete`, `useDeleteWebhookNotification`, `useWebhookDryRun`, `useWebhookSettings`, `useUpdateWebhookSettings`, `useDiscordSettings`, `useUpdateDiscordSettings`, `useTestDiscord` |

Three of these are worth knowing about before changing anything:

- **`useRuntimeConnection`** is the app's realtime engine, mounted once in
  `_authenticated.tsx`. It mirrors backend reachability and SSH state into the
  runtime store, reads the idle timeout from `WEBSOCKET_TIMEOUT_MINUTES` in app
  config, opens the socket when realtime has been requested, binds every socket
  event to a toast and a query invalidation, tracks user activity (click,
  keydown, submit, touchstart, throttled to once per 1.5 s), and every 15 s
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
| `onTransferError` | `transfer_failed` |
| `onTransferQueued` | `transfer_queued` |
| `onTransferPromoted` | `transfer_promoted` |
| `onWebhookReceived` | `test_webhook_received` |
| `onWebhookCaptured` | `webhook_received` |
| `onRenameWebhookReceived` | `rename_webhook_received` |
| `onRenameCompleted` | `rename_completed` |

Also exported: `disconnectSocket`, `destroySocket`, `getSocket`,
`reAuthenticateSocket`, `sendActivityPing` (emits `activity`) and
`isSocketConnected`.

`onTransferError` is defined but not currently bound by `useRuntime.ts`, which
subscribes to the other eight.

## Layout Shell

`components/layout/app-layout.tsx` wraps every signed-in page: a
`SidebarProvider` carrying the ambient background, the sidebar, then an inset
containing the navbar, the scrolling `<main>` (capped at 1920px), and the mobile
bottom nav as a flex sibling rather than a fixed overlay. It also mounts
`BackendUnavailableOverlay`, shown when the runtime-status query errors or the
store says the backend is unreachable, with a retry that refetches.

| Component | What it is |
|---|---|
| `app-sidebar.tsx` | Three groups — Workspace (Dashboard, Transfers, Webhooks), Library (Browse Media → Movies, TV Shows, Anime), System (Backups, Settings) — plus the user footer with a log-out button |
| `app-navbar.tsx` | Breadcrumb from a longest-prefix path table, the live metrics pill (realtime status, Active, Queued), notification and settings links, and a version badge |
| `mobile-nav.tsx` | Bottom bar below `md`: Home, Transfers, Webhooks and a Menu button that opens the sidebar sheet; counts come from active transfers and pending notifications |
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
| Activity | Running, queued and paused copies |
| History | Finished runs — status filters (All, Completed, Failed, Stopped), search, paging and bulk delete |
| Simulate | Scenario launcher for the simulation tool |

Supporting components in `components/transfers/`:

| File | Purpose |
|---|---|
| `transfer-bits.tsx` | `TransferStatusBadge`, `ProgressMeter`, `Chip`, `Fact`, `PathBlock` |
| `transfer-detail.tsx` | `TransferDetailPanel` and its `TransferActions` interface |
| `transfer-logs.tsx` | Live rsync output; only lines that break rsync's repetitive rhythm are tinted |
| `simulation-panel.tsx` | `SimulationPanel` scenario launcher and `SimulationBadge` |
| `confirm-dialog.tsx` | State-driven `AlertDialog` for stop/delete/cleanup/bulk delete |

`lib/transfer-progress.ts` holds the formatting and derivation: `formatBytes`,
`formatSpeed`, `formatEta`, `formatSizePair`, `formatDuration`,
`parseTimestamp`, `transferElapsed`, `parseProgressText`, `transferPercent`,
`isActiveStatus`.

Two things worth knowing when changing this page:

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

## List Controls

`components/layout/list-controls.tsx` holds what both long lists need, so the
Transfers History tab and the Media sync tab are driven identically:

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
vocabulary (`statusInfo`, `groupStatus`, `isSyncable`), sizing
(`fileBytes`, `seasonBytes`, `effectiveSize`, `formatSize`) and labels
(`mediaLabel`, `itemTitle`, `itemDetail`, `formatEpisodeRange`, `timeAgo`).
`lib/rename-diff.ts` holds `diffFilenames` and `episodeTagOf`.

See [webhooks](../features/webhooks/README.md), [renames](../features/renames/README.md)
and [auto-sync](../features/auto-sync/README.md).

## Dashboard

`components/pages/dashboard.tsx` is a thin composition of four pieces from
`components/dashboard/`: `SystemTicker` (status dot, peak disk, queue, queued,
webhook count, refresh stamp), `StorageStrip`, `TransfersPanel` and
`WebhookRail`. `disk-utils.ts` normalises local and remote disk usage into one
`DiskItem` list and defines the severity thresholds used across the dashboard —
`warn` at 78%, `crit` at 92%.

## Page Tab Bar

`components/layout/page-tabs.tsx` — the section switcher used by the transfers
and webhooks pages. It is shadcn's `Tabs` `variant="line"` re-tinted to the
brand, so a page marks its active section the same way the mobile bottom nav
does rather than introducing a second idiom.

`PageTabItem` fields: `value`, `label`, `icon`, `count` (badge, omit when there
is nothing to count), `atEnd` (pushes a segment to the far end from `sm` up,
marking a tool rather than another view).

Sizing notes, since both have bitten before: segments use `flex-none` to beat
the base trigger's `flex-1`, whose `0%` basis would give every segment the same
width regardless of content; and count badges are hidden below `sm` so three
segments fit on a phone without one scrolling out of sight.

## UI Components

`src/components/ui/` — 25 files, all installed through shadcn and wrapping Base
UI where a primitive exists.

| Component | Base UI primitive |
|---|---|
| `accordion` | `@base-ui/react/accordion` |
| `alert-dialog` | `@base-ui/react/alert-dialog` |
| `badge` | `@base-ui/react/use-render` |
| `button` | `@base-ui/react/button` |
| `card` | native elements |
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
| `lib/api-types.ts` | Shared backend shapes: `Transfer`, `QueueStatus`, `WebhookNotification`, `RenameNotification`, `AppConfig`, `SSHConfig`, `DiskUsage`, `DryRunResult`, and the `TransferStatus` / `WebhookStatus` / `SyncStatusType` unions |
| `lib/dry-run.ts` | `parseDryRun` plus `DryRunReport` and friends, and its own `formatBytes` / `formatNumber` / `formatDuration` |
| `lib/query-client.ts` | The shared `queryClient` |
| `lib/rename-diff.ts` | `diffFilenames`, `episodeTagOf`, `isSeparatorToken` |
| `lib/transfer-progress.ts` | Transfer formatting and derivation (listed above) |
| `lib/utils.ts` | `cn()` — clsx + tailwind-merge |
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
`IconLibraryPhoto`, `IconMovie`, `IconDeviceTv`, `IconBrandNetflix`,
`IconArchive`, `IconSettings`, `IconHome`, `IconMenu2`, `IconLogout`,
`IconChevronRight`.

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
