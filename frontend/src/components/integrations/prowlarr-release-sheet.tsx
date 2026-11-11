import { useState } from "react";
import { toast } from "sonner";
import {
  IconCheck,
  IconCopy,
  IconDownload,
  IconExternalLink,
  IconLink,
  IconLock,
  IconMagnet,
  IconSend,
} from "@tabler/icons-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { ConfirmDialog } from "@/components/transfers/confirm-dialog";
import { formatSize, libraryError, stampText } from "@/components/integrations/library-vocab";
import { ageText, flagLabel, qualityTokens } from "@/components/integrations/prowlarr-vocab";
import { QualityChips, ProtocolMark } from "@/components/integrations/prowlarr-bits";
import { ImportCheck } from "@/components/integrations/prowlarr-import-check";
import { copyMagnet, copyText, downloadReleaseFile, useGrabRelease } from "@/hooks/useProwlarr";
import type { ProwlarrClient, ProwlarrRelease } from "@/lib/prowlarr-types";

/**
 * One release, from below on a phone: its whole name, the facts, and what can
 * be done with it — send it to a download client, copy or open its magnet
 * link, or save its file.
 */
export function ReleaseSheet({
  release,
  searchId,
  clients,
  canGrab,
  whyNot,
  onClose,
}: {
  release: ProwlarrRelease | null;
  searchId: string | null;
  clients: ProwlarrClient[];
  canGrab: boolean;
  whyNot: string;
  onClose: () => void;
}) {
  return (
    <Sheet open={release != null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent
        side="bottom"
        className="max-h-[88dvh] gap-0 overflow-y-auto rounded-t-2xl pb-[max(1rem,env(safe-area-inset-bottom))] sm:mx-auto sm:max-w-2xl sm:rounded-2xl sm:border sm:pb-4 data-[side=bottom]:sm:bottom-4"
      >
        {release && searchId && (
          <ReleaseBody
            key={`${searchId}:${release.id}`}
            release={release}
            searchId={searchId}
            clients={clients}
            canGrab={canGrab}
            whyNot={whyNot}
          />
        )}
      </SheetContent>
    </Sheet>
  );
}

function ReleaseBody({
  release,
  searchId,
  clients,
  canGrab,
  whyNot,
}: {
  release: ProwlarrRelease;
  searchId: string;
  clients: ProwlarrClient[];
  canGrab: boolean;
  whyNot: string;
}) {
  const grab = useGrabRelease();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState<"magnet" | "file" | null>(null);
  // The magnet link, shown to select by hand when the browser refused to copy.
  const [shownMagnet, setShownMagnet] = useState<string | null>(null);
  // Only clients that take this kind of release, enabled, best priority first.
  const usable = clients
    .filter((c) => c.enabled && (c.protocol === release.protocol || c.protocol === "unknown"))
    .sort((a, b) => (a.priority ?? 50) - (b.priority ?? 50));
  const [clientId, setClientId] = useState<number | null>(usable[0]?.id ?? null);
  const client = usable.find((c) => c.id === clientId) ?? usable[0];
  const noClient = usable.length === 0;

  const send = async () => {
    try {
      const result = await grab.mutateAsync({
        searchId,
        releaseId: release.id,
        downloadClientId: client?.id ?? null,
      });
      toast.success(result.message);
      setConfirming(false);
    } catch (failure) {
      toast.error(libraryError(failure, "Prowlarr did not send it."));
    }
  };

  const copy = async () => {
    setBusy("magnet");
    try {
      const { magnet, copied } = await copyMagnet(searchId, release.id);
      if (copied) {
        toast.success("Magnet link copied");
      } else {
        setShownMagnet(magnet);
        toast.message("This browser did not allow copying here. The link is shown below.");
      }
    } catch (failure) {
      toast.error(libraryError(failure, "Could not copy the magnet link."));
    } finally {
      setBusy(null);
    }
  };

  const save = async () => {
    setBusy("file");
    try {
      await downloadReleaseFile(searchId, release.id);
    } catch (failure) {
      toast.error(libraryError(failure, "Could not get the file."));
    } finally {
      setBusy(null);
    }
  };

  const copyTitle = async () => {
    if (await copyText(release.title)) toast.success("Name copied");
    else toast.error("This browser did not allow copying. Press and hold the name to select it.");
  };

  const facts: [string, string][] = [
    ["Size", formatSize(release.size)],
    [
      "Age",
      release.published ? `${ageText(release.published)} · ${stampText(release.published)}` : "—",
    ],
    ...(release.protocol === "torrent"
      ? ([["Peers", `${release.seeders ?? "?"} seeding · ${release.leechers ?? "?"} leeching`]] as [
          string,
          string,
        ][])
      : []),
    ["Grabs", release.grabs != null ? release.grabs.toLocaleString() : "—"],
    ...(release.files ? ([["Files", String(release.files)]] as [string, string][]) : []),
    ["Indexer", release.indexer || "—"],
    ["Category", release.categories.join(", ") || "—"],
  ];
  const ids: { label: string; href: string }[] = [];
  if (release.imdb_id)
    ids.push({
      label: "IMDb",
      href: `https://www.imdb.com/title/tt${String(release.imdb_id).padStart(7, "0")}/`,
    });
  if (release.tmdb_id)
    ids.push({
      label: "TMDB",
      href: `https://www.themoviedb.org/${release.tvdb_id ? "tv" : "movie"}/${release.tmdb_id}`,
    });
  if (release.tvdb_id)
    ids.push({ label: "TVDB", href: `https://thetvdb.com/dereferrer/series/${release.tvdb_id}` });

  return (
    <>
      <SheetHeader className="gap-2 px-4 pt-4 pr-12 pb-3">
        <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
          <ProtocolMark protocol={release.protocol} />
          <span className="font-medium text-foreground-2">{release.indexer}</span>
          {release.flags.map((flag) => (
            <span
              key={flag}
              className="rounded-md border border-emerald-500/30 px-1.5 py-px text-[10px] font-semibold text-emerald-300"
            >
              {flagLabel(flag)}
            </span>
          ))}
        </div>
        <SheetTitle className="text-[15px] leading-snug font-semibold [overflow-wrap:anywhere] select-text">
          {release.title}
        </SheetTitle>
        <SheetDescription render={<div />} className="flex flex-wrap items-center gap-2">
          <QualityChips tokens={qualityTokens(release.title)} />
          <button
            type="button"
            onClick={copyTitle}
            className="inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground"
          >
            <IconCopy className="size-3" />
            Copy name
          </button>
        </SheetDescription>
      </SheetHeader>

      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 border-y border-border/70 px-4 py-3 text-[13px]">
        {facts.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="min-w-0 [overflow-wrap:anywhere] text-foreground-2">{value}</dd>
          </div>
        ))}
      </dl>

      <div className="space-y-3 px-4 pt-3">
        {/* Sending is the main thing to do here, so it leads and fills the width. */}
        {release.grabbed ? (
          <div className="space-y-2">
            <div className="flex h-11 items-center justify-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 text-sm font-semibold text-emerald-300">
              <IconCheck className="size-4" />
              Sent to the download client
            </div>
            <ImportCheck searchId={searchId} release={release} clientId={client?.id ?? null} />
          </div>
        ) : (
          <div className="space-y-2">
            {usable.length > 1 && (
              <div
                className="flex flex-wrap gap-1.5"
                role="radiogroup"
                aria-label="Download client"
              >
                {usable.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    role="radio"
                    aria-checked={c.id === client?.id}
                    onClick={() => setClientId(c.id)}
                    className={
                      c.id === client?.id
                        ? "rounded-md border border-brand/40 bg-brand/15 px-2.5 py-1.5 text-xs font-semibold text-brand-foreground"
                        : "rounded-md border border-border px-2.5 py-1.5 text-xs font-semibold text-muted-foreground"
                    }
                  >
                    {c.name}
                  </button>
                ))}
              </div>
            )}
            {!noClient && (
              <ImportCheck searchId={searchId} release={release} clientId={client?.id ?? null} />
            )}
            <Button
              className="h-11 w-full text-sm"
              disabled={!canGrab || noClient || grab.isPending}
              onClick={() => setConfirming(true)}
            >
              <IconSend className="size-4" />
              {client ? `Send to ${client.name}` : "Send to download client"}
            </Button>
            {!canGrab && whyNot ? (
              <p className="flex items-start gap-1.5 text-[12px] text-muted-foreground">
                <IconLock className="mt-0.5 size-3.5 shrink-0" />
                {whyNot}
              </p>
            ) : noClient ? (
              <p className="text-[12px] text-muted-foreground">
                Prowlarr has no {release.protocol === "usenet" ? "usenet" : "torrent"} download
                client switched on. Add one in Prowlarr: Settings → Download Clients.
              </p>
            ) : null}
          </div>
        )}

        {shownMagnet && (
          <div className="space-y-2 rounded-xl border border-border/70 bg-card/40 p-3">
            <label className="block text-[12px] text-muted-foreground" htmlFor="magnet-link">
              Magnet link: tap it to select, then copy.
            </label>
            <textarea
              id="magnet-link"
              readOnly
              value={shownMagnet}
              onFocus={(event) => event.currentTarget.select()}
              className="h-20 w-full resize-none rounded-lg border border-border bg-background p-2 font-mono text-[11px] [overflow-wrap:anywhere] text-foreground-2"
            />
            <a
              href={shownMagnet}
              className={cn(buttonVariants({ variant: "outline" }), "h-10 w-full")}
            >
              <IconMagnet className="size-4" />
              Open in a torrent app
            </a>
          </div>
        )}

        <div className="grid grid-cols-2 gap-2">
          {release.protocol === "torrent" && release.can_magnet && (
            <Button variant="outline" className="h-10" disabled={busy !== null} onClick={copy}>
              <IconMagnet className="size-4" />
              {busy === "magnet" ? "Getting…" : "Copy magnet"}
            </Button>
          )}
          {release.can_download && (
            <Button variant="outline" className="h-10" disabled={busy !== null} onClick={save}>
              <IconDownload className="size-4" />
              {busy === "file"
                ? "Getting…"
                : release.protocol === "usenet"
                  ? "Save .nzb"
                  : "Save .torrent"}
            </Button>
          )}
          {release.info_url && (
            <a
              href={release.info_url}
              target="_blank"
              rel="noreferrer noopener"
              className={cn(buttonVariants({ variant: "outline" }), "h-10")}
            >
              <IconExternalLink className="size-4" />
              Indexer page
            </a>
          )}
          {ids.map((id) => (
            <a
              key={id.label}
              href={id.href}
              target="_blank"
              rel="noreferrer noopener"
              className={cn(buttonVariants({ variant: "outline" }), "h-10")}
            >
              <IconLink className="size-4" />
              {id.label}
            </a>
          ))}
        </div>
      </div>

      {confirming && (
        <ConfirmDialog
          open
          onOpenChange={(open) => !open && setConfirming(false)}
          title={`Send to ${client?.name ?? "the download client"}?`}
          description={
            <span className="[overflow-wrap:anywhere]">
              Prowlarr hands <span className="font-medium text-foreground">{release.title}</span> to{" "}
              {client?.name ?? "its download client"}, which starts downloading it.
            </span>
          }
          confirmLabel="Send"
          pending={grab.isPending}
          onConfirm={send}
        />
      )}
    </>
  );
}
