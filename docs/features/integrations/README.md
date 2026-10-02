# Integrations — the outside services DragonCP talks to

DragonCP can link to other applications. Each link is a **connector**: a named,
configurable, testable connection to one outside service, with its own page
under Integrations in the sidebar. Discord is the one that does something
today — it posts a message when a sync finishes, when one fails, when a rename
completes, when the retention rule deletes old backups, and when an automatic
sync refuses to run. Sonarr, Radarr and Jellyfin can be connected and tested,
but nothing reads them yet.

Last updated: 2026-08-17
Primary files: `services/connectors/`, `models/connector.py`, `routes/connectors.py`,
`frontend/src/components/pages/integrations.tsx`

## Where it lives

| Concern | File |
| --- | --- |
| What a connector is | `services/connectors/base.py` |
| The one outbound HTTP call | `services/connectors/transport.py` |
| What the app can announce | `services/connectors/events.py` |
| Which destination an announcement goes to | `services/connectors/routing.py` |
| Delivering without blocking the caller | `services/connectors/dispatch.py` |
| The facade everything else uses | `services/connectors/service.py` |
| Discord: embeds, colours, webhook validation | `services/connectors/adapters/discord.py` |
| Sonarr and Radarr | `services/connectors/adapters/_arr.py`, `sonarr.py`, `radarr.py` |
| Jellyfin | `services/connectors/adapters/jellyfin.py` |
| Storage | `models/connector.py`, tables `connector`, `connector_secret`, `connector_target`, `notification_route`, `connector_delivery` |
| API | `routes/connectors.py` |
| UI | `frontend/src/components/pages/integrations.tsx`, `frontend/src/components/integrations/`, `frontend/src/hooks/useConnectors.ts` |

## What an operator sees

**Integrations → Discord** has four tabs, in the order you are likely to need
them:

- **Webhooks** — the list of destinations, and where the page opens. Each has a
  name you chose, and one of them is the default. Add takes a name and a
  Discord webhook URL; the URL is stored on the server and never shown again.
  Each row has a Test button that sends a real message, and an "in service"
  switch.
- **Notifications** — every announcement the app can make, one per row, each
  with a destination dropdown and an on/off switch. A row set to "Use default"
  goes wherever the default webhook points.
- **Activity** — the last hundred messages this connector handled, including
  the ones it held back and why.
- **Appearance** — the app URL a message links back to, the icon shown beside
  it, and the default thumbnail used for transfers started by hand. Set once
  and rarely touched, which is why it is last.

The settings tab is named by the adapter, not by the page. Discord calls its
tab **Appearance** because nothing on it reaches Discord — a webhook URL
carries its own credential, so connecting happens on the Webhooks tab. Sonarr,
Radarr and Jellyfin are reached with an address and an API key, so theirs is
called **Connection** and carries a Test connection button that genuinely
reaches the service.

Discord has no such button. A connector declares `supports_check = False` when
it has no endpoint to reach at that level, and the UI then offers nothing: a
test that cannot fail is worse than no test, because it leaves a green badge on
something nothing verified.

**Integrations → Sonarr / Radarr / Jellyfin** each have one page: an address,
an API key, and a Test connection button. The page says plainly that nothing
reads them yet.

## How it works

### Announcing something

Anything in the application that wants to announce something writes this, and
nothing else:

```python
from services.connectors import notify
from services.connectors.events import Event, Field

notify(Event(
    key='transfer.failed',
    severity='failure',
    title=parsed_title,
    fields=(Field('Error Details', error_text, monospace=True),),
))
```

No enabled check, no URL, no embed, no colour, no `try`/`except`. `notify()`
resolves which connectors want the event and which destination each uses, hands
the work to a background thread, and returns. It never raises and it never
blocks.

The caller describes *what happened*. The adapter decides how its service shows
it — which is why the colours, the 1024-character field cap and the timestamp
format exist once in `adapters/discord.py` instead of in four call sites.

### The catalogue

`services/connectors/events.py` holds the list of things that can be announced.
Adding one is a row there; the routing UI renders the catalogue, so an
announcement that cannot be seen cannot be turned off.

| Key | Fires when |
| --- | --- |
| `transfer.completed` | A transfer finished successfully |
| `transfer.failed` | A transfer stopped without finishing |
| `rename.finished` | A rename run finished — whole, partial or failed |
| `backup.retention_deleted` | The retention rule deleted stored versions |
| `autosync.blocked` | An automatic sync looked unsafe and stopped |

`connector.test` exists as a key but is deliberately outside the catalogue: a
test send ignores routing by design, so offering a destination choice for it
would be offering a choice that does nothing.

### Routing

One rule decides everything: **a missing route means the default, not
silence.** An announcement added in a later version is delivered the day it is
written, without anyone remembering to configure it.

Resolution order, in `routing.py`:

1. Connector turned off → nothing happens, nothing recorded. (A fresh install
   has every connector off; logging each skip would bury the entries that mean
   something.)
2. The notification is switched off → skipped, recorded with the reason.
3. A destination was chosen → that one. If it no longer exists, the default.
4. No destination chosen, or no route row at all → the connector's default.
5. No default at all → skipped, recorded, and shown as a warning on the page.
   This is the only state where a message is lost, and it is visible.

A destination taken out of service is **not** quietly redirected to the
default. "Out of service" is a statement about that destination, and sending
somewhere the operator did not choose is worse than not sending.

### Delivering

`dispatch.py` is one daemon thread and one bounded queue. `notify()` puts and
returns.

This is a fix, not only a tidy-up. A rename notification used to be posted to
Discord synchronously inside the HTTP request Sonarr made — `RenameService`
called straight from the webhook route — so **Sonarr waited up to ten seconds
for Discord to answer**, and adding retries would have made it worse.

The queue is bounded at 500. When it fills, the oldest waiting announcement is
dropped and the drop is logged: a Discord outage with an unbounded queue is a
slow leak that looks like nothing at all until it does not.

### The one HTTP call

`transport.py` is the only place the application makes an outbound request.
Two rules hold there and nowhere else needs to know them:

- **Nothing raises.** Every path — timeout, DNS failure, refused connection,
  malformed response — returns a value. Callers are background threads that
  must survive a service being down.
- **Nothing leaks.** A URL is redacted before it reaches any string a caller
  might log, store or render. A Discord webhook URL *is* the credential; there
  is no separate token to hide, and the code this replaced printed it beside
  the response body on every failure.

One retry, on 429 and 5xx only. `Retry-After` is honoured up to ten seconds —
Discord can ask for several minutes on a hard rate limit, and blocking the
shared worker that long would stall every notification behind it.

## Storage and secrets

Connectors are a **list**, not a fixed set of keys, which is why they sit
outside `settings_registry`. That registry is right about what it holds:
singleton values whose existence is known at import time. "The three webhooks
this operator added" is not that.

Credentials live in `connector_secret` under one rule: **no read path reaches a
response body.** Not redacted, not partially shown — there is simply nothing to
call. That is easier to keep true than remembering which keys inside a config
blob need masking. What the API returns instead is `secrets_set`: whether a
value exists.

They are stored unencrypted, the same as the Discord webhook URL was before
this. Anyone who can reach the Integrations page can make the server issue
requests to its own network — already true of this app's threat model of one to
three trusted administrators on a private network, and worth stating rather
than discovering. Discord destinations are restricted to Discord hosts because
a webhook URL has exactly one legitimate shape.

## The upgrade from 2.2.x

Automatic and invisible, in `DatabaseManager._migrate_discord_to_connector`.
On the first start after upgrading:

1. A stored `DISCORD_WEBHOOK_URL` becomes a destination called **Default**,
   marked as the connector's default.
2. `DISCORD_NOTIFICATIONS_ENABLED` becomes the connector's on/off state.
3. The app, icon and thumbnail URLs move into the connector's settings.
4. **No routing rows are written.** Every notification falls through to the
   default, which is exactly what it did before.
5. The five `DISCORD_*` rows are deleted from `app_settings`, so no value has
   two homes.

Guarded on the connector row already existing rather than on a version number,
so it is safe to run on every start and safe to run twice. An install that
never configured Discord gets no connector row, so the page shows it as never
configured rather than configured-and-empty.

## Adding a connector

One file in `services/connectors/adapters/`, plus one import line in that
package's `__init__.py`. Nothing else changes — not the API, not the sidebar,
not the settings form, which are all driven by what the adapter declares.

```python
@register
class ExampleConnector(Connector):
    id = 'example'
    display_name = 'Example'
    capabilities = frozenset({CAP_QUERY})
    config_fields = (
        ConfigField('base_url', 'Address', kind='url', required=True),
        ConfigField('api_key', 'API key', kind='password', secret=True, required=True),
    )

    def check(self) -> CheckResult:
        ...
```

The only frontend change a new connector might want is an icon, in
`frontend/src/components/integrations/connector-icon.tsx`. Without one it gets
a plug.

## What is not here yet

Sonarr and Radarr are connected but unused. Using them to decide *when* a sync
should start — asking whether a season is still downloading instead of waiting
out `SERIES_ANIME_SYNC_WAIT_TIME` — is TASK-020.

## Related

- [Notifications](../notifications/README.md) — what each message contains
- [Webhooks](../webhooks/README.md) — the inbound side, Radarr and Sonarr
  pushing to DragonCP
- [Settings](../settings/README.md) — the app-level settings that stayed there
- [API reference](../../reference/api.md#connectors)
