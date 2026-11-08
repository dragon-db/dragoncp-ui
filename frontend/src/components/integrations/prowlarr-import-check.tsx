import type { ReactNode } from "react";
import {
  IconAlertTriangle,
  IconCircleCheck,
  IconFolder,
  IconInfoCircle,
  IconLoader2,
} from "@tabler/icons-react";
import { cn } from "@/lib/utils";
import { useReleaseRoute } from "@/hooks/useProwlarr";
import type {
  ArrApp,
  ArrReading,
  ArrTracking,
  ProwlarrRelease,
  RouteClient,
} from "@/lib/prowlarr-types";

type Tone = "ok" | "warn" | "muted" | "wait";

const TONE: Record<Tone, { icon: typeof IconFolder; className: string }> = {
  ok: { icon: IconCircleCheck, className: "text-emerald-400" },
  warn: { icon: IconAlertTriangle, className: "text-amber-400" },
  muted: { icon: IconInfoCircle, className: "text-muted-foreground" },
  wait: { icon: IconLoader2, className: "animate-spin text-muted-foreground" },
};

const THING: Record<ArrApp, string> = { sonarr: "show", radarr: "film" };

/**
 * Before a send: which category the release lands in on the chosen download
 * client, whether Sonarr or Radarr picks up that category, and what they make
 * of the name. After it: where the release is in their queue, until imported.
 * Everything here is read from Prowlarr, Sonarr and Radarr; nothing changes.
 */
export function ImportCheck({
  searchId,
  release,
  clientId,
}: {
  searchId: string;
  release: ProwlarrRelease;
  clientId: number | null;
}) {
  const route = useReleaseRoute(searchId, release.id, release.grabbed);
  const data = route.data;

  if (route.isLoading) {
    return (
      <Rows>
        <Row tone="wait">Checking where it lands and who imports it…</Row>
      </Rows>
    );
  }
  if (route.isError || !data) {
    return (
      <Rows>
        <Row tone="muted">Could not check where this release lands.</Row>
      </Rows>
    );
  }

  const chosen = release.grabbed ? (data.sent?.client_id ?? null) : clientId;
  const client = data.clients.find((c) => c.id === chosen) ?? data.clients[0];
  if (!client) return null;

  const apps = [
    ...new Set([...client.watchers.map((w) => w.app), ...(data.family ? [data.family] : [])]),
  ];
  const readings = apps
    .map((app) => data.readings.find((r) => r.app === app))
    .filter((r): r is ArrReading => r != null && r.state !== "off");

  return (
    <Rows>
      <Landing client={client} />
      <Watchers client={client} connected={data.connected.length > 0} family={data.family} />
      {readings.map((reading) => (
        <Reading key={reading.app} reading={reading} />
      ))}
      {release.grabbed &&
        data.tracking.map((tracking) => (
          <Tracking key={tracking.app} tracking={tracking} clientName={client.name} />
        ))}
    </Rows>
  );
}

function Rows({ children }: { children: ReactNode }) {
  return (
    <ul
      aria-label="Where it lands"
      className="divide-y divide-border/60 rounded-xl border border-border/70 bg-card/40"
    >
      {children}
    </ul>
  );
}

function Row({
  tone,
  icon,
  children,
}: {
  tone: Tone;
  icon?: typeof IconFolder;
  children: ReactNode;
}) {
  const Glyph = icon ?? TONE[tone].icon;
  return (
    <li className="flex items-start gap-2.5 px-3 py-2.5 text-[12.5px] leading-snug text-foreground-2">
      <Glyph className={cn("mt-px size-4 shrink-0", TONE[tone].className)} />
      <div className="min-w-0 [overflow-wrap:anywhere]">{children}</div>
    </li>
  );
}

function Strong({ children }: { children: ReactNode }) {
  return <span className="font-semibold text-foreground">{children}</span>;
}

function Landing({ client }: { client: RouteClient }) {
  if (client.how === "none" || !client.category) {
    return (
      <Row tone="muted" icon={IconFolder}>
        Lands in <Strong>{client.name}</Strong> with no category.
      </Row>
    );
  }
  return (
    <Row tone="muted" icon={IconFolder}>
      Lands in <Strong>{client.name}</Strong> as <Strong>{client.category}</Strong>
      {client.how === "default" && (
        <span className="text-muted-foreground">
          {" "}
          (Prowlarr's catch-all: none of its category mappings covers this release)
        </span>
      )}
      .
    </Row>
  );
}

function Watchers({
  client,
  connected,
  family,
}: {
  client: RouteClient;
  connected: boolean;
  family: ArrApp | null;
}) {
  if (!connected) {
    return (
      <Row tone="muted">Connect Sonarr or Radarr in DragonCP to see whether they import it.</Row>
    );
  }
  if (client.watchers.length === 0) {
    return (
      <Row tone="warn">
        Neither Sonarr nor Radarr watches{" "}
        {client.category ? <Strong>{client.category}</Strong> : "uncategorised downloads"} in{" "}
        {client.name}, so it downloads and stays there. Add a category mapping for this release's
        category in Prowlarr (Settings → Download Clients → {client.name}).
      </Row>
    );
  }
  const wrongApp = family != null && !client.watchers.some((w) => w.app === family);
  return (
    <>
      {client.watchers.map((watcher) =>
        watcher.imports ? (
          <Row key={watcher.app} tone="ok">
            <Strong>{watcher.label}</Strong>{" "}
            {watcher.everything
              ? `watches everything in ${client.name}`
              : `watches ${client.category}`}{" "}
            and imports finished downloads.
          </Row>
        ) : (
          <Row key={watcher.app} tone="warn">
            <Strong>{watcher.label}</Strong> watches it, but its automatic import of finished
            downloads is off (Settings → Download Clients → Completed Download Handling).
          </Row>
        )
      )}
      {wrongApp && (
        <Row tone="warn">
          The indexer files this as {family === "sonarr" ? "TV" : "a film"}, but it lands where{" "}
          {client.watchers.map((w) => w.label).join(" and ")} looks.
        </Row>
      )}
    </>
  );
}

function pad(n: number) {
  return String(n).padStart(2, "0");
}

function episodeText(r: ArrReading): string {
  if (r.multi_season) return "several seasons";
  if (r.full_season && r.season != null) return `season ${r.season} (whole season)`;
  if (r.season != null && r.episodes?.length)
    return `S${pad(r.season)}${r.episodes.map((e) => `E${pad(e)}`).join("")}`;
  if (r.absolute?.length) return `episode ${r.absolute.join(", ")}`;
  if (r.season != null) return `season ${r.season}`;
  return "";
}

function Reading({ reading: r }: { reading: ArrReading }) {
  if (r.state === "error") return <Row tone="muted">{r.label} did not answer.</Row>;
  if (r.state === "unreadable") {
    return (
      <Row tone="warn">
        {r.label} can't read a {r.app === "sonarr" ? "show and episode" : "film"} from this name, so
        it will need a manual import.
      </Row>
    );
  }
  if (r.state === "unmatched") {
    const read = r.app === "radarr" && r.year ? `${r.read_as} (${r.year})` : r.read_as;
    return (
      <Row tone="warn">
        {r.label} reads the {THING[r.app]} as <Strong>{read || "something"}</Strong>, which is not
        in your {r.label} library. Add it to {r.label} first, or it will need a manual import.
      </Row>
    );
  }

  const episodes = r.app === "sonarr" ? episodeText(r) : "";
  const found = r.found ?? 0;
  const have = r.have ?? 0;
  return (
    <>
      <Row tone="ok">
        {r.label} reads it as <Strong>{r.title}</Strong>
        {r.year ? ` (${r.year})` : ""}
        {episodes ? (
          <>
            , <Strong>{episodes}</Strong>
          </>
        ) : null}
        .
      </Row>
      {r.other_title && (
        <Row tone="warn">
          The indexer tags this release as a different {THING[r.app]} from the one {r.label}{" "}
          matched. Check the name before sending.
        </Row>
      )}
      {r.app === "sonarr" && found === 0 && (
        <Row tone="warn">
          {r.label} has no episode in this show for that name, so it can't import it.
          {r.absolute?.length && !r.anime
            ? " The name counts episodes from the first one; Sonarr reads that only when the show's type is Anime."
            : ""}
        </Row>
      )}
      {have > 0 && (
        <Row tone="muted">
          {r.app === "radarr" || have === found
            ? `Already in your library: ${r.label} imports it only if it is an upgrade.`
            : `${have} of ${found} episodes already in your library: those import only as upgrades.`}
        </Row>
      )}
    </>
  );
}

function Tracking({ tracking: t, clientName }: { tracking: ArrTracking; clientName: string }) {
  if (t.state === "imported") {
    return (
      <Row tone="ok">
        Imported by <Strong>{t.label}</Strong>.
      </Row>
    );
  }
  if (t.state === "error") return <Row tone="muted">{t.label} did not answer.</Row>;
  if (t.state === "not_seen") {
    return (
      <Row tone="wait">
        Waiting for {t.label} to see it in {clientName}. It looks about once a minute.
      </Row>
    );
  }
  if (t.state !== "queued") return null;
  if (!t.known) {
    return (
      <Row tone="warn">
        {t.label} has it, but can't tell which {THING[t.app]} it is. Import it by hand in {t.label}{" "}
        when it finishes.
      </Row>
    );
  }
  if (t.stuck) {
    return (
      <Row tone="warn">
        {t.label}: {t.message || t.why}
      </Row>
    );
  }
  if (t.verdict === "imported") {
    return (
      <Row tone="ok">
        Imported by <Strong>{t.label}</Strong>.
      </Row>
    );
  }
  if (t.verdict === "downloading") {
    const pct = t.progress != null ? ` ${Math.round(t.progress * 100)}%` : "";
    return (
      <Row tone="wait">
        In {t.label}'s queue: downloading{pct}.
      </Row>
    );
  }
  if (t.verdict === "importpending" || t.verdict === "importing") {
    return <Row tone="wait">Downloaded. {t.label} is importing it.</Row>;
  }
  return (
    <Row tone="muted">
      In {t.label}'s queue: {t.why || t.verdict}.
    </Row>
  );
}
