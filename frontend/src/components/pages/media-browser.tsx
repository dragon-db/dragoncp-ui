import { PageHeader } from "@/components/layout/page-header";
import { useEffect, useMemo, useState } from "react";
import { Link } from "@tanstack/react-router";
import { toast } from "sonner";
import {
  useEpisodes,
  useFolderSyncStatus,
  useFolders,
  useMediaDryRun,
  useSeasons,
  useSyncStatus,
} from "@/hooks/useMedia";
import { useSSHConfig, useSSHAutoConnect, useSSHStatus } from "@/hooks/useConfig";
import { useStartTransfer } from "@/hooks/useTransfers";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DryRunDialog } from "@/components/dry-run/dry-run-report";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  IconArrowLeft,
  IconArrowNarrowRight,
  IconChevronRight,
  IconDownload,
  IconFileSearch,
  IconFolder,
  IconPlayerPlay,
  IconRefresh,
  IconSearch,
  IconSettings,
  IconPlugConnected,
} from "@tabler/icons-react";
import type {
  DryRunResult,
  FolderMetadata,
  FolderSyncStatus,
  SyncStatusType,
} from "@/lib/api-types";

interface MediaBrowserPageProps {
  mediaType: string;
}

type ViewMode = "folders" | "seasons" | "options" | "episodes";
type SortMode = "recent" | "alphabetical";

const mediaTypeLabels: Record<string, string> = {
  movies: "Movies",
  tvshows: "TV Shows",
  anime: "Anime",
};

const syncStatusPriority: Record<SyncStatusType, number> = {
  LOADING: 0,
  OUT_OF_SYNC: 1,
  NO_INFO: 2,
  SYNCED: 3,
  PARTIAL_SYNC: 2,
};

function toSyncStatus(value?: string): SyncStatusType {
  if (
    value === "SYNCED" ||
    value === "OUT_OF_SYNC" ||
    value === "NO_INFO" ||
    value === "LOADING" ||
    value === "PARTIAL_SYNC"
  ) {
    return value;
  }
  return "NO_INFO";
}

function getSyncBadge(status: SyncStatusType) {
  switch (status) {
    case "SYNCED":
      return <Badge className="border-green-500/50 bg-green-500/20 text-green-300">Synced</Badge>;
    case "OUT_OF_SYNC":
      return (
        <Badge className="border-amber-500/50 bg-amber-500/20 text-amber-300">Out of Sync</Badge>
      );
    case "LOADING":
      return <Badge className="border-blue-500/50 bg-blue-500/20 text-blue-300">Loading</Badge>;
    case "PARTIAL_SYNC":
      return (
        <Badge className="border-indigo-500/50 bg-indigo-500/20 text-indigo-300">Partial</Badge>
      );
    default:
      return (
        <Badge variant="outline" className="text-muted-foreground">
          Not checked
        </Badge>
      );
  }
}

function formatRelativeDate(unixSeconds?: number) {
  if (!unixSeconds) return "";
  const now = Date.now();
  const dateMs = unixSeconds * 1000;
  const diffDays = Math.floor((now - dateMs) / 86400000);
  if (diffDays <= 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return diffDays === 1 ? "1 day ago" : `${diffDays} days ago`;
  if (diffDays < 30) {
    const weeks = Math.floor(diffDays / 7);
    return weeks === 1 ? "1 week ago" : `${weeks} weeks ago`;
  }
  return new Date(dateMs).toLocaleDateString();
}

function getFolderStatus(
  folderName: string,
  statuses: Record<string, FolderSyncStatus>,
  loadingOverride: boolean
): SyncStatusType {
  if (loadingOverride) return "LOADING";
  return toSyncStatus(statuses[folderName]?.status);
}

function getSeasonStatus(
  seasonName: string,
  statuses: Record<string, FolderSyncStatus>,
  loadingOverride: boolean
): SyncStatusType {
  if (loadingOverride) return "LOADING";
  return toSyncStatus(statuses[seasonName]?.status);
}

export function MediaBrowserPage({ mediaType }: MediaBrowserPageProps) {
  const [viewMode, setViewMode] = useState<ViewMode>("folders");
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null);
  const [selectedSeason, setSelectedSeason] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState("");
  const [sortMode, setSortMode] = useState<SortMode>("recent");
  const [manualSyncRefresh, setManualSyncRefresh] = useState(false);
  const [dryRunResult, setDryRunResult] = useState<DryRunResult | null>(null);
  const [autoConnectAttempted, setAutoConnectAttempted] = useState(false);

  const sshStatusQuery = useSSHStatus();
  const sshConfigQuery = useSSHConfig();
  const autoConnect = useSSHAutoConnect();
  const sshConnected = Boolean(sshStatusQuery.data);
  const hasStoredSshCredentials = Boolean(
    sshConfigQuery.data?.host && sshConfigQuery.data?.username
  );

  const foldersQuery = useFolders(sshConnected ? mediaType : "");
  const syncStatusQuery = useSyncStatus(sshConnected ? mediaType : "");
  const seasonsQuery = useSeasons(sshConnected ? mediaType : "", selectedFolder ?? "");
  const seasonSyncQuery = useFolderSyncStatus(sshConnected ? mediaType : "", selectedFolder ?? "");
  const episodesQuery = useEpisodes(
    sshConnected ? mediaType : "",
    selectedFolder ?? "",
    selectedSeason ?? ""
  );

  const startTransfer = useStartTransfer();
  const dryRun = useMediaDryRun();

  useEffect(() => {
    setViewMode("folders");
    setSelectedFolder(null);
    setSelectedSeason(null);
    setSearchTerm("");
    setSortMode("recent");
    setAutoConnectAttempted(false);
    // The open report belongs to the library we just left.
    setDryRunResult(null);
  }, [mediaType]);

  useEffect(() => {
    if (sshConnected || autoConnectAttempted || autoConnect.isPending) return;
    if (sshStatusQuery.isLoading || sshConfigQuery.isLoading) return;
    if (!hasStoredSshCredentials) return;

    setAutoConnectAttempted(true);

    autoConnect.mutate(undefined, {
      onSuccess: () => {
        sshStatusQuery.refetch();
        toast.success("Remote browse session connected.");
      },
      onError: () => {
        toast.error("Failed to auto-connect remote browse session. Check Settings.");
      },
    });
  }, [
    autoConnect,
    autoConnectAttempted,
    hasStoredSshCredentials,
    sshConfigQuery.isLoading,
    sshConnected,
    sshStatusQuery,
    sshStatusQuery.isLoading,
  ]);

  const folders = foldersQuery.data?.folders ?? [];
  const seasons = seasonsQuery.data?.seasons ?? [];
  const episodes = episodesQuery.data?.episodes ?? [];

  const folderStatuses = syncStatusQuery.data?.sync_statuses ?? {};
  const seasonStatuses = seasonSyncQuery.data?.seasons_sync_status ?? {};

  const filteredFolders = useMemo(() => {
    const normalized = searchTerm.trim().toLowerCase();
    let list = folders;

    if (normalized) {
      list = folders.filter((folder) => folder.name.toLowerCase().includes(normalized));
    }

    return [...list].sort((a, b) => {
      if (sortMode === "alphabetical") return a.name.localeCompare(b.name);
      return (b.modification_time ?? 0) - (a.modification_time ?? 0);
    });
  }, [folders, searchTerm, sortMode]);

  const isAnySyncLoading =
    manualSyncRefresh ||
    syncStatusQuery.isFetching ||
    (viewMode !== "folders" && seasonSyncQuery.isFetching);

  const breadcrumb = useMemo(() => {
    const base = [{ label: mediaTypeLabels[mediaType] ?? mediaType, level: "folders" as ViewMode }];
    if (!selectedFolder) return base;

    base.push({
      label: selectedFolder,
      level: mediaType === "movies" ? "options" : ("seasons" as ViewMode),
    });

    if (selectedSeason) {
      base.push({ label: selectedSeason, level: "options" as ViewMode });
    }

    if (viewMode === "episodes") {
      base.push({ label: "Episodes", level: "episodes" as ViewMode });
    }

    return base;
  }, [mediaType, selectedFolder, selectedSeason, viewMode]);

  const refreshSyncStatus = async () => {
    if (isAnySyncLoading) return;
    try {
      setManualSyncRefresh(true);
      await syncStatusQuery.refetch();
      if (selectedFolder && mediaType !== "movies") {
        await seasonSyncQuery.refetch();
      }
      toast.success("Sync status refreshed");
    } catch {
      toast.error("Failed to refresh sync status");
    } finally {
      setManualSyncRefresh(false);
    }
  };

  const onSelectFolder = (folder: FolderMetadata) => {
    setSelectedFolder(folder.name);
    setSelectedSeason(null);
    if (mediaType === "movies") {
      setViewMode("options");
      return;
    }
    setViewMode("seasons");
  };

  const onSelectSeason = (season: FolderMetadata) => {
    setSelectedSeason(season.name);
    setViewMode("options");
  };

  const runTransfer = async (type: "folder" | "file", episodeName?: string) => {
    if (!selectedFolder) return;

    try {
      const response = await startTransfer.mutateAsync({
        type,
        media_type: mediaType as "movies" | "tvshows" | "anime",
        folder_name: selectedFolder,
        season_name: selectedSeason ?? undefined,
        episode_name: episodeName,
      });

      toast.success(
        response?.message || (type === "file" ? "Episode transfer started" : "Transfer started")
      );
    } catch {
      toast.error(
        type === "file" ? "Failed to start episode transfer" : "Failed to start transfer"
      );
    }
  };

  const runDryRun = async () => {
    if (!selectedFolder) return;

    try {
      const result = await dryRun.mutateAsync({
        media_type: mediaType,
        folder_name: selectedFolder,
        season_name: selectedSeason ?? undefined,
      });
      setDryRunResult(result.dry_run_result);
      toast.info("Dry-run completed");
    } catch {
      toast.error("Dry-run failed");
    }
  };

  const navigateToLevel = (index: number) => {
    const target = breadcrumb[index];
    if (!target) return;

    if (target.level === "folders") {
      setSelectedFolder(null);
      setSelectedSeason(null);
      setViewMode("folders");
      return;
    }

    if (target.level === "seasons") {
      setSelectedSeason(null);
      setViewMode("seasons");
      return;
    }

    if (target.level === "options") {
      setViewMode("options");
      return;
    }

    setViewMode("episodes");
  };

  const title = selectedSeason
    ? `${selectedFolder} / ${selectedSeason}`
    : selectedFolder
      ? selectedFolder
      : (mediaTypeLabels[mediaType] ?? mediaType);

  return (
    <div className="space-y-6">
      <PageHeader title={title} description="Browse your library and start transfers">
        <Button
          variant="outline"
          onClick={() => foldersQuery.refetch()}
          disabled={!sshConnected || foldersQuery.isFetching}
        >
          <IconRefresh
            className={`mr-2 h-4 w-4 ${foldersQuery.isFetching ? "animate-spin" : ""}`}
          />
          Refresh Folders
        </Button>
        <Button
          variant="outline"
          onClick={refreshSyncStatus}
          disabled={!sshConnected || isAnySyncLoading}
        >
          <IconRefresh className={`mr-2 h-4 w-4 ${isAnySyncLoading ? "animate-spin" : ""}`} />
          Refresh Sync Status
        </Button>
      </PageHeader>

      {!sshConnected && !sshStatusQuery.isLoading && (
        <Card className="border-amber-500/30 bg-amber-500/8">
          <CardContent className="flex flex-wrap items-center justify-between gap-3 pt-6">
            <div>
              <p className="text-sm font-medium text-amber-100">Remote browse session required</p>
              <p className="mt-1 text-sm text-amber-50/80">
                {hasStoredSshCredentials
                  ? "Media browsing uses the dedicated SSH browse connection. DragonCP can auto-connect with your saved SSH credentials, or you can review them in Settings."
                  : "Media browsing uses the dedicated SSH browse connection. Add SSH host and username in Settings before exploring remote folders."}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {hasStoredSshCredentials && (
                <Button
                  variant="outline"
                  className="border-amber-400/40 bg-background/40 text-amber-100 hover:bg-background/60"
                  disabled={autoConnect.isPending}
                  onClick={async () => {
                    try {
                      await autoConnect.mutateAsync();
                      await sshStatusQuery.refetch();
                      toast.success("Remote browse session connected.");
                    } catch {
                      toast.error("Failed to connect remote browse session.");
                    }
                  }}
                >
                  <IconPlugConnected
                    className={`mr-2 h-4 w-4 ${autoConnect.isPending ? "animate-pulse" : ""}`}
                  />
                  {autoConnect.isPending ? "Connecting..." : "Connect Browse Session"}
                </Button>
              )}
              <Link to="/settings">
                <Button
                  variant="outline"
                  className="border-amber-400/40 bg-background/40 text-amber-100 hover:bg-background/60"
                >
                  <IconSettings className="mr-2 h-4 w-4" />
                  Open Settings
                </Button>
              </Link>
            </div>
          </CardContent>
        </Card>
      )}

      {breadcrumb.length > 1 && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          {breadcrumb.map((entry, index) => {
            const isLast = index === breadcrumb.length - 1;
            return (
              <div key={`${entry.label}-${index}`} className="flex items-center gap-2">
                {isLast ? (
                  <span className="font-medium text-white">{entry.label}</span>
                ) : (
                  <button
                    type="button"
                    className="text-neutral-400 hover:text-white"
                    onClick={() => navigateToLevel(index)}
                  >
                    {entry.label}
                  </button>
                )}
                {!isLast && <IconChevronRight className="h-4 w-4 text-neutral-600" />}
              </div>
            );
          })}
        </div>
      )}

      {viewMode === "folders" && (
        <Card className="border-neutral-800 bg-neutral-900/50">
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <CardTitle className="text-white">Folders</CardTitle>
                <CardDescription className="text-neutral-400">
                  {filteredFolders.length === folders.length
                    ? `${folders.length} folders`
                    : `${filteredFolders.length} of ${folders.length} folders`}
                </CardDescription>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <div className="relative">
                  <IconSearch className="absolute top-2.5 left-2.5 h-4 w-4 text-neutral-500" />
                  <Input
                    value={searchTerm}
                    onChange={(event) => setSearchTerm(event.target.value)}
                    placeholder="Search folders"
                    className="w-56 pl-8"
                  />
                </div>
                <Select
                  value={sortMode}
                  onValueChange={(value) => setSortMode((value as SortMode) ?? "recent")}
                  items={{ recent: "Recently Modified", alphabetical: "Alphabetical" }}
                >
                  <SelectTrigger className="w-44">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="recent">Recently Modified</SelectItem>
                    <SelectItem value="alphabetical">Alphabetical</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-[560px] pr-3">
              {foldersQuery.isLoading ? (
                <div className="space-y-2">
                  {[1, 2, 3, 4, 5].map((idx) => (
                    <Skeleton key={idx} className="h-14 w-full" />
                  ))}
                </div>
              ) : filteredFolders.length ? (
                <div className="space-y-2">
                  {filteredFolders.map((folder) => {
                    const status = getFolderStatus(folder.name, folderStatuses, isAnySyncLoading);
                    return (
                      <button
                        key={folder.name}
                        type="button"
                        onClick={() => onSelectFolder(folder)}
                        className="w-full rounded-lg border border-neutral-700/50 bg-neutral-800/50 px-4 py-3 text-left transition hover:bg-neutral-800"
                      >
                        <div className="flex items-center justify-between gap-3">
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2 truncate text-sm font-medium text-white">
                              <IconFolder className="h-4 w-4 shrink-0 text-brand-hover" />
                              <span className="truncate">{folder.name}</span>
                            </div>
                            <p className="mt-1 text-xs text-neutral-500">
                              {formatRelativeDate(folder.modification_time)}
                            </p>
                          </div>
                          <div className="flex items-center gap-2">
                            {getSyncBadge(status)}
                            <IconArrowNarrowRight className="h-4 w-4 text-neutral-500" />
                          </div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              ) : (
                <div className="py-12 text-center text-neutral-500">No folders found</div>
              )}
            </ScrollArea>
          </CardContent>
        </Card>
      )}

      {viewMode === "seasons" && (
        <Card className="border-neutral-800 bg-neutral-900/50">
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <div>
                <CardTitle className="text-white">Seasons</CardTitle>
                <CardDescription className="text-neutral-400">
                  {selectedFolder
                    ? `Select a season from ${selectedFolder}`
                    : "Select a folder first"}
                </CardDescription>
              </div>
              <Button variant="outline" size="sm" onClick={() => setViewMode("folders")}>
                <IconArrowLeft className="mr-1 h-4 w-4" />
                Back
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-[560px] pr-3">
              {seasonsQuery.isLoading ? (
                <div className="space-y-2">
                  {[1, 2, 3].map((idx) => (
                    <Skeleton key={idx} className="h-14 w-full" />
                  ))}
                </div>
              ) : seasons.length ? (
                <div className="space-y-2">
                  {seasons
                    .slice()
                    .sort((a, b) => {
                      const sa = getSeasonStatus(a.name, seasonStatuses, isAnySyncLoading);
                      const sb = getSeasonStatus(b.name, seasonStatuses, isAnySyncLoading);
                      if (sa !== sb) return syncStatusPriority[sb] - syncStatusPriority[sa];
                      return a.name.localeCompare(b.name);
                    })
                    .map((season) => {
                      const status = getSeasonStatus(season.name, seasonStatuses, isAnySyncLoading);
                      return (
                        <button
                          key={season.name}
                          type="button"
                          onClick={() => onSelectSeason(season)}
                          className="w-full rounded-lg border border-neutral-700/50 bg-neutral-800/50 px-4 py-3 text-left transition hover:bg-neutral-800"
                        >
                          <div className="flex items-center justify-between gap-3">
                            <div className="flex min-w-0 items-center gap-2">
                              <IconFolder className="h-4 w-4 shrink-0 text-blue-300" />
                              <span className="truncate text-sm text-white">{season.name}</span>
                            </div>
                            <div className="flex items-center gap-2">
                              {getSyncBadge(status)}
                              <IconArrowNarrowRight className="h-4 w-4 text-neutral-500" />
                            </div>
                          </div>
                        </button>
                      );
                    })}
                </div>
              ) : (
                <div className="py-12 text-center text-neutral-500">No seasons found</div>
              )}
            </ScrollArea>
          </CardContent>
        </Card>
      )}

      {viewMode === "options" && (
        <Card className="border-neutral-800 bg-neutral-900/50">
          <CardHeader>
            <CardTitle className="text-white">Transfer Options</CardTitle>
            <CardDescription className="text-neutral-400">
              {selectedSeason
                ? `${selectedFolder} / ${selectedSeason}`
                : `${selectedFolder} folder`}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <button
              type="button"
              onClick={() => runTransfer("folder")}
              className="w-full rounded-lg border border-neutral-700/50 bg-neutral-800/50 p-4 text-left transition hover:bg-neutral-800"
              disabled={startTransfer.isPending}
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="font-medium text-white">Sync Entire Folder</p>
                  <p className="mt-1 text-sm text-neutral-400">
                    Start full folder sync for the selected path.
                  </p>
                </div>
                <IconPlayerPlay className="h-5 w-5 text-green-300" />
              </div>
            </button>

            <button
              type="button"
              onClick={runDryRun}
              className="w-full rounded-lg border border-neutral-700/50 bg-neutral-800/50 p-4 text-left transition hover:bg-neutral-800"
              disabled={dryRun.isPending}
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="font-medium text-white">Dry-Run</p>
                  <p className="mt-1 text-sm text-neutral-400">
                    Preview changes and safety checks before syncing.
                  </p>
                </div>
                <IconFileSearch className="h-5 w-5 text-blue-300" />
              </div>
            </button>

            {selectedSeason && (
              <>
                <button
                  type="button"
                  onClick={() => setViewMode("episodes")}
                  className="w-full rounded-lg border border-neutral-700/50 bg-neutral-800/50 p-4 text-left transition hover:bg-neutral-800"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="font-medium text-white">Manual Episode Sync</p>
                      <p className="mt-1 text-sm text-neutral-400">
                        Select specific episodes to sync.
                      </p>
                    </div>
                    <IconDownload className="h-5 w-5 text-brand-hover" />
                  </div>
                </button>

                <button
                  type="button"
                  onClick={() => setViewMode("episodes")}
                  className="w-full rounded-lg border border-neutral-700/50 bg-neutral-800/50 p-4 text-left transition hover:bg-neutral-800"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="font-medium text-white">Download Single Episode</p>
                      <p className="mt-1 text-sm text-neutral-400">
                        Choose one episode file for file-level transfer.
                      </p>
                    </div>
                    <IconDownload className="h-5 w-5 text-amber-300" />
                  </div>
                </button>
              </>
            )}
          </CardContent>
        </Card>
      )}

      {viewMode === "episodes" && (
        <Card className="border-neutral-800 bg-neutral-900/50">
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <div>
                <CardTitle className="text-white">Episodes</CardTitle>
                <CardDescription className="text-neutral-400">
                  Download specific episodes as file transfers
                </CardDescription>
              </div>
              <Button variant="outline" size="sm" onClick={() => setViewMode("options")}>
                <IconArrowLeft className="mr-1 h-4 w-4" />
                Back to Options
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-[560px] pr-3">
              {episodesQuery.isLoading ? (
                <div className="space-y-2">
                  {[1, 2, 3, 4].map((idx) => (
                    <Skeleton key={idx} className="h-14 w-full" />
                  ))}
                </div>
              ) : episodes.length ? (
                <div className="space-y-2">
                  {episodes.map((episode) => (
                    <div
                      key={episode}
                      className="flex w-full items-center justify-between gap-3 rounded-lg border border-neutral-700/50 bg-neutral-800/50 px-4 py-3"
                    >
                      <div className="min-w-0 truncate text-sm text-white">{episode}</div>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => runTransfer("file", episode)}
                        disabled={startTransfer.isPending}
                      >
                        <IconDownload className="mr-1 h-4 w-4" />
                        Download
                      </Button>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="py-12 text-center text-neutral-500">No episodes found</div>
              )}
            </ScrollArea>
          </CardContent>
        </Card>
      )}

      <DryRunDialog
        payload={dryRunResult}
        open={Boolean(dryRunResult)}
        onOpenChange={(open) => !open && setDryRunResult(null)}
        subtitle={
          selectedFolder
            ? `${selectedFolder}${selectedSeason ? ` · ${selectedSeason}` : ""} — what this sync would do`
            : undefined
        }
      />
    </div>
  );
}
