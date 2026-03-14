import { useEffect, useMemo, useState } from 'react';
import { Link } from '@tanstack/react-router';
import { toast } from 'sonner';
import {
  useEpisodes,
  useFolderSyncStatus,
  useFolders,
  useMediaDryRun,
  useSeasons,
  useSyncStatus,
} from '@/hooks/useMedia';
import { useSSHConfig, useSSHAutoConnect, useSSHStatus } from '@/hooks/useConfig';
import { useStartTransfer } from '@/hooks/useTransfers';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import {
  IconArrowLeft,
  IconArrowNarrowRight,
  IconCheck,
  IconChevronRight,
  IconDownload,
  IconFileSearch,
  IconFolder,
  IconPlayerPlay,
  IconRefresh,
  IconSearch,
  IconSettings,
  IconPlugConnected,
} from '@tabler/icons-react';
import type { DryRunResult, FolderMetadata, FolderSyncStatus, SyncStatusType } from '@/lib/api-types';

interface MediaBrowserPageProps {
  mediaType: string;
}

type ViewMode = 'folders' | 'seasons' | 'options' | 'episodes';
type SortMode = 'recent' | 'alphabetical';

const mediaTypeLabels: Record<string, string> = {
  movies: 'Movies',
  tvshows: 'TV Shows',
  anime: 'Anime',
};

const syncStatusPriority: Record<SyncStatusType, number> = {
  LOADING: 0,
  OUT_OF_SYNC: 1,
  NO_INFO: 2,
  SYNCED: 3,
  PARTIAL_SYNC: 2,
};

function toSyncStatus(value?: string): SyncStatusType {
  if (value === 'SYNCED' || value === 'OUT_OF_SYNC' || value === 'NO_INFO' || value === 'LOADING' || value === 'PARTIAL_SYNC') {
    return value;
  }
  return 'NO_INFO';
}

function getSyncBadge(status: SyncStatusType) {
  switch (status) {
    case 'SYNCED':
      return <Badge className="bg-green-500/20 text-green-300 border-green-500/50">Synced</Badge>;
    case 'OUT_OF_SYNC':
      return <Badge className="bg-amber-500/20 text-amber-300 border-amber-500/50">Out of Sync</Badge>;
    case 'LOADING':
      return <Badge className="bg-blue-500/20 text-blue-300 border-blue-500/50">Loading</Badge>;
    case 'PARTIAL_SYNC':
      return <Badge className="bg-indigo-500/20 text-indigo-300 border-indigo-500/50">Partial</Badge>;
    default:
      return <Badge className="bg-neutral-700/40 text-neutral-300 border-neutral-700">No Info</Badge>;
  }
}

function formatRelativeDate(unixSeconds?: number) {
  if (!unixSeconds) return '';
  const now = Date.now();
  const dateMs = unixSeconds * 1000;
  const diffDays = Math.floor((now - dateMs) / 86400000);
  if (diffDays <= 0) return 'Today';
  if (diffDays === 1) return 'Yesterday';
  if (diffDays < 7) return `${diffDays} days ago`;
  if (diffDays < 30) return `${Math.floor(diffDays / 7)} weeks ago`;
  return new Date(dateMs).toLocaleDateString();
}

function getFolderStatus(folderName: string, statuses: Record<string, FolderSyncStatus>, loadingOverride: boolean): SyncStatusType {
  if (loadingOverride) return 'LOADING';
  return toSyncStatus(statuses[folderName]?.status);
}

function getSeasonStatus(seasonName: string, statuses: Record<string, FolderSyncStatus>, loadingOverride: boolean): SyncStatusType {
  if (loadingOverride) return 'LOADING';
  return toSyncStatus(statuses[seasonName]?.status);
}

export function MediaBrowserPage({ mediaType }: MediaBrowserPageProps) {
  const [viewMode, setViewMode] = useState<ViewMode>('folders');
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null);
  const [selectedSeason, setSelectedSeason] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [sortMode, setSortMode] = useState<SortMode>('recent');
  const [manualSyncRefresh, setManualSyncRefresh] = useState(false);
  const [dryRunResult, setDryRunResult] = useState<DryRunResult | null>(null);
  const [autoConnectAttempted, setAutoConnectAttempted] = useState(false);

  const sshStatusQuery = useSSHStatus();
  const sshConfigQuery = useSSHConfig();
  const autoConnect = useSSHAutoConnect();
  const sshConnected = Boolean(sshStatusQuery.data);
  const hasStoredSshCredentials = Boolean(sshConfigQuery.data?.host && sshConfigQuery.data?.username);

  const foldersQuery = useFolders(sshConnected ? mediaType : '');
  const syncStatusQuery = useSyncStatus(sshConnected ? mediaType : '');
  const seasonsQuery = useSeasons(sshConnected ? mediaType : '', selectedFolder ?? '');
  const seasonSyncQuery = useFolderSyncStatus(sshConnected ? mediaType : '', selectedFolder ?? '');
  const episodesQuery = useEpisodes(sshConnected ? mediaType : '', selectedFolder ?? '', selectedSeason ?? '');

  const startTransfer = useStartTransfer();
  const dryRun = useMediaDryRun();

  useEffect(() => {
    setViewMode('folders');
    setSelectedFolder(null);
    setSelectedSeason(null);
    setSearchTerm('');
    setSortMode('recent');
    setAutoConnectAttempted(false);
  }, [mediaType]);

  useEffect(() => {
    if (sshConnected || autoConnectAttempted || autoConnect.isPending) return;
    if (sshStatusQuery.isLoading || sshConfigQuery.isLoading) return;
    if (!hasStoredSshCredentials) return;

    setAutoConnectAttempted(true);

    autoConnect.mutate(undefined, {
      onSuccess: () => {
        sshStatusQuery.refetch();
        toast.success('Remote browse session connected.');
      },
      onError: () => {
        toast.error('Failed to auto-connect remote browse session. Check Settings.');
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
      if (sortMode === 'alphabetical') return a.name.localeCompare(b.name);
      return (b.modification_time ?? 0) - (a.modification_time ?? 0);
    });
  }, [folders, searchTerm, sortMode]);

  const isAnySyncLoading =
    manualSyncRefresh || syncStatusQuery.isFetching || (viewMode !== 'folders' && seasonSyncQuery.isFetching);

  const breadcrumb = useMemo(() => {
    const base = [{ label: mediaTypeLabels[mediaType] ?? mediaType, level: 'folders' as ViewMode }];
    if (!selectedFolder) return base;

    base.push({ label: selectedFolder, level: mediaType === 'movies' ? 'options' : 'seasons' as ViewMode });

    if (selectedSeason) {
      base.push({ label: selectedSeason, level: 'options' as ViewMode });
    }

    if (viewMode === 'episodes') {
      base.push({ label: 'Episodes', level: 'episodes' as ViewMode });
    }

    return base;
  }, [mediaType, selectedFolder, selectedSeason, viewMode]);

  const refreshSyncStatus = async () => {
    if (isAnySyncLoading) return;
    try {
      setManualSyncRefresh(true);
      await syncStatusQuery.refetch();
      if (selectedFolder && mediaType !== 'movies') {
        await seasonSyncQuery.refetch();
      }
      toast.success('Sync status refreshed');
    } catch {
      toast.error('Failed to refresh sync status');
    } finally {
      setManualSyncRefresh(false);
    }
  };

  const onSelectFolder = (folder: FolderMetadata) => {
    setSelectedFolder(folder.name);
    setSelectedSeason(null);
    if (mediaType === 'movies') {
      setViewMode('options');
      return;
    }
    setViewMode('seasons');
  };

  const onSelectSeason = (season: FolderMetadata) => {
    setSelectedSeason(season.name);
    setViewMode('options');
  };

  const runTransfer = async (type: 'folder' | 'file', episodeName?: string) => {
    if (!selectedFolder) return;

    try {
      const response = await startTransfer.mutateAsync({
        type,
        media_type: mediaType as 'movies' | 'tvshows' | 'anime',
        folder_name: selectedFolder,
        season_name: selectedSeason ?? undefined,
        episode_name: episodeName,
      });

      toast.success(response?.message || (type === 'file' ? 'Episode transfer started' : 'Transfer started'));
    } catch {
      toast.error(type === 'file' ? 'Failed to start episode transfer' : 'Failed to start transfer');
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
      toast.info('Dry-run completed');
    } catch {
      toast.error('Dry-run failed');
    }
  };

  const navigateToLevel = (index: number) => {
    const target = breadcrumb[index];
    if (!target) return;

    if (target.level === 'folders') {
      setSelectedFolder(null);
      setSelectedSeason(null);
      setViewMode('folders');
      return;
    }

    if (target.level === 'seasons') {
      setSelectedSeason(null);
      setViewMode('seasons');
      return;
    }

    if (target.level === 'options') {
      setViewMode('options');
      return;
    }

    setViewMode('episodes');
  };

  const title = selectedSeason
    ? `${selectedFolder} / ${selectedSeason}`
    : selectedFolder
      ? selectedFolder
      : mediaTypeLabels[mediaType] ?? mediaType;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold text-white">{title}</h1>
          <p className="text-neutral-400 mt-1">Static-parity media browse and transfer workflow</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => foldersQuery.refetch()} disabled={!sshConnected || foldersQuery.isFetching}>
            <IconRefresh className={`h-4 w-4 mr-2 ${foldersQuery.isFetching ? 'animate-spin' : ''}`} />
            Refresh Folders
          </Button>
          <Button variant="outline" onClick={refreshSyncStatus} disabled={!sshConnected || isAnySyncLoading}>
            <IconRefresh className={`h-4 w-4 mr-2 ${isAnySyncLoading ? 'animate-spin' : ''}`} />
            Refresh Sync Status
          </Button>
        </div>
      </div>

      {!sshConnected && !sshStatusQuery.isLoading && (
        <Card className="border-amber-500/30 bg-amber-500/8">
          <CardContent className="flex flex-wrap items-center justify-between gap-3 pt-6">
            <div>
              <p className="text-sm font-medium text-amber-100">Remote browse session required</p>
              <p className="mt-1 text-sm text-amber-50/80">
                {hasStoredSshCredentials
                  ? 'Media browsing uses the dedicated SSH browse connection. DragonCP can auto-connect with your saved SSH credentials, or you can review them in Settings.'
                  : 'Media browsing uses the dedicated SSH browse connection. Add SSH host and username in Settings before exploring remote folders.'}
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
                      toast.success('Remote browse session connected.');
                    } catch {
                      toast.error('Failed to connect remote browse session.');
                    }
                  }}
                >
                  <IconPlugConnected className={`mr-2 h-4 w-4 ${autoConnect.isPending ? 'animate-pulse' : ''}`} />
                  {autoConnect.isPending ? 'Connecting...' : 'Connect Browse Session'}
                </Button>
              )}
              <Link to="/settings">
                <Button variant="outline" className="border-amber-400/40 bg-background/40 text-amber-100 hover:bg-background/60">
                  <IconSettings className="mr-2 h-4 w-4" />
                  Open Settings
                </Button>
              </Link>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="flex items-center flex-wrap gap-2 text-sm">
        {breadcrumb.map((entry, index) => {
          const isLast = index === breadcrumb.length - 1;
          return (
            <div key={`${entry.label}-${index}`} className="flex items-center gap-2">
              {isLast ? (
                <span className="text-white font-medium">{entry.label}</span>
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

      {viewMode === 'folders' && (
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
                  <IconSearch className="h-4 w-4 text-neutral-500 absolute left-2.5 top-2.5" />
                  <Input
                    value={searchTerm}
                    onChange={(event) => setSearchTerm(event.target.value)}
                    placeholder="Search folders"
                    className="w-56 pl-8 bg-neutral-800 border-neutral-700"
                  />
                </div>
                <Select value={sortMode} onValueChange={(value) => setSortMode((value as SortMode) ?? 'recent')}>
                  <SelectTrigger className="w-44 bg-neutral-800 border-neutral-700">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-neutral-900 border-neutral-700">
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
                        className="w-full rounded-lg border border-neutral-700/50 bg-neutral-800/50 px-4 py-3 text-left hover:bg-neutral-800 transition"
                      >
                        <div className="flex items-center justify-between gap-3">
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2 text-sm text-white font-medium truncate">
                              <IconFolder className="h-4 w-4 text-fuchsia-400 shrink-0" />
                              <span className="truncate">{folder.name}</span>
                            </div>
                            <p className="text-xs text-neutral-500 mt-1">{formatRelativeDate(folder.modification_time)}</p>
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
                <div className="text-center py-12 text-neutral-500">No folders found</div>
              )}
            </ScrollArea>
          </CardContent>
        </Card>
      )}

      {viewMode === 'seasons' && (
        <Card className="border-neutral-800 bg-neutral-900/50">
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <div>
                <CardTitle className="text-white">Seasons</CardTitle>
                <CardDescription className="text-neutral-400">
                  {selectedFolder ? `Select a season from ${selectedFolder}` : 'Select a folder first'}
                </CardDescription>
              </div>
              <Button variant="outline" size="sm" onClick={() => setViewMode('folders')}>
                <IconArrowLeft className="h-4 w-4 mr-1" />
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
                          className="w-full rounded-lg border border-neutral-700/50 bg-neutral-800/50 px-4 py-3 text-left hover:bg-neutral-800 transition"
                        >
                          <div className="flex items-center justify-between gap-3">
                            <div className="flex items-center gap-2 min-w-0">
                              <IconFolder className="h-4 w-4 text-blue-300 shrink-0" />
                              <span className="text-sm text-white truncate">{season.name}</span>
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
                <div className="text-center py-12 text-neutral-500">No seasons found</div>
              )}
            </ScrollArea>
          </CardContent>
        </Card>
      )}

      {viewMode === 'options' && (
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
              onClick={() => runTransfer('folder')}
              className="w-full rounded-lg border border-neutral-700/50 bg-neutral-800/50 p-4 text-left hover:bg-neutral-800 transition"
              disabled={startTransfer.isPending}
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="font-medium text-white">Sync Entire Folder</p>
                  <p className="text-sm text-neutral-400 mt-1">Start full folder sync for the selected path.</p>
                </div>
                <IconPlayerPlay className="h-5 w-5 text-green-300" />
              </div>
            </button>

            <button
              type="button"
              onClick={runDryRun}
              className="w-full rounded-lg border border-neutral-700/50 bg-neutral-800/50 p-4 text-left hover:bg-neutral-800 transition"
              disabled={dryRun.isPending}
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="font-medium text-white">Dry-Run</p>
                  <p className="text-sm text-neutral-400 mt-1">Preview changes and safety checks before syncing.</p>
                </div>
                <IconFileSearch className="h-5 w-5 text-blue-300" />
              </div>
            </button>

            {selectedSeason && (
              <>
                <button
                  type="button"
                  onClick={() => setViewMode('episodes')}
                  className="w-full rounded-lg border border-neutral-700/50 bg-neutral-800/50 p-4 text-left hover:bg-neutral-800 transition"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="font-medium text-white">Manual Episode Sync</p>
                      <p className="text-sm text-neutral-400 mt-1">Select specific episodes to sync.</p>
                    </div>
                    <IconDownload className="h-5 w-5 text-fuchsia-300" />
                  </div>
                </button>

                <button
                  type="button"
                  onClick={() => setViewMode('episodes')}
                  className="w-full rounded-lg border border-neutral-700/50 bg-neutral-800/50 p-4 text-left hover:bg-neutral-800 transition"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="font-medium text-white">Download Single Episode</p>
                      <p className="text-sm text-neutral-400 mt-1">Choose one episode file for file-level transfer.</p>
                    </div>
                    <IconDownload className="h-5 w-5 text-amber-300" />
                  </div>
                </button>
              </>
            )}
          </CardContent>
        </Card>
      )}

      {viewMode === 'episodes' && (
        <Card className="border-neutral-800 bg-neutral-900/50">
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <div>
                <CardTitle className="text-white">Episodes</CardTitle>
                <CardDescription className="text-neutral-400">Download specific episodes as file transfers</CardDescription>
              </div>
              <Button variant="outline" size="sm" onClick={() => setViewMode('options')}>
                <IconArrowLeft className="h-4 w-4 mr-1" />
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
                      className="w-full rounded-lg border border-neutral-700/50 bg-neutral-800/50 px-4 py-3 flex items-center justify-between gap-3"
                    >
                      <div className="min-w-0 text-sm text-white truncate">{episode}</div>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => runTransfer('file', episode)}
                        disabled={startTransfer.isPending}
                      >
                        <IconDownload className="h-4 w-4 mr-1" />
                        Download
                      </Button>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-center py-12 text-neutral-500">No episodes found</div>
              )}
            </ScrollArea>
          </CardContent>
        </Card>
      )}

      <Dialog open={Boolean(dryRunResult)} onOpenChange={(open) => !open && setDryRunResult(null)}>
        <DialogContent className="max-w-3xl bg-neutral-900 border-neutral-800">
          <DialogHeader>
            <DialogTitle className="text-white">Dry-Run Result</DialogTitle>
            <DialogDescription className="text-neutral-400">Validation summary before sync execution</DialogDescription>
          </DialogHeader>
          {dryRunResult && (
            <div className="space-y-4 text-sm">
              <div className="flex items-center gap-2">
                {dryRunResult.safe_to_sync ? (
                  <Badge className="bg-green-500/20 text-green-300 border-green-500/50">
                    <IconCheck className="h-3.5 w-3.5 mr-1" />
                    Safe to Sync
                  </Badge>
                ) : (
                  <Badge className="bg-red-500/20 text-red-300 border-red-500/50">Manual Review Required</Badge>
                )}
                {dryRunResult.reason && <span className="text-neutral-300">{dryRunResult.reason}</span>}
              </div>

              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <div className="rounded border border-neutral-800 bg-neutral-950 p-3">
                  <div className="text-neutral-500">Server Files</div>
                  <div className="text-neutral-200 mt-1">{dryRunResult.server_file_count ?? 0}</div>
                </div>
                <div className="rounded border border-neutral-800 bg-neutral-950 p-3">
                  <div className="text-neutral-500">Local Files</div>
                  <div className="text-neutral-200 mt-1">{dryRunResult.local_file_count ?? 0}</div>
                </div>
                <div className="rounded border border-neutral-800 bg-neutral-950 p-3">
                  <div className="text-neutral-500">Incoming</div>
                  <div className="text-neutral-200 mt-1">{dryRunResult.incoming_count ?? 0}</div>
                </div>
                <div className="rounded border border-neutral-800 bg-neutral-950 p-3">
                  <div className="text-neutral-500">Deleted</div>
                  <div className="text-neutral-200 mt-1">{dryRunResult.deleted_count ?? 0}</div>
                </div>
              </div>

              <div className="rounded border border-neutral-800 bg-neutral-950 p-3 max-h-72 overflow-auto font-mono text-xs text-neutral-300 whitespace-pre-wrap">
                {dryRunResult.raw_output || 'No raw output available'}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
