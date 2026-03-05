import { useMemo, useState } from 'react';
import { toast } from 'sonner';
import {
  useBackupDetails,
  useBackupFiles,
  useBackups,
  useDeleteBackup,
  usePlanRestoreBackup,
  useReindexBackups,
  useRestoreBackup,
  type Backup,
} from '@/hooks/useBackups';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import {
  IconArchive,
  IconArrowLeft,
  IconCheck,
  IconEye,
  IconFileDownload,
  IconRefresh,
  IconRestore,
  IconTrash,
} from '@tabler/icons-react';

type Stage = 'list' | 'files' | 'plan' | 'delete';

function humanBytes(value?: number) {
  const bytes = value ?? 0;
  if (bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const idx = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / Math.pow(1024, idx)).toFixed(2)} ${units[idx]}`;
}

function statusBadge(status: string) {
  switch (status) {
    case 'ready':
      return <Badge className="bg-green-500/20 text-green-300 border-green-500/50">Ready</Badge>;
    case 'restored':
      return <Badge className="bg-blue-500/20 text-blue-300 border-blue-500/50">Restored</Badge>;
    case 'deleted':
      return <Badge className="bg-neutral-500/20 text-neutral-300 border-neutral-500/50">Deleted</Badge>;
    default:
      return <Badge variant="outline">{status}</Badge>;
  }
}

export function BackupsPage() {
  const [stage, setStage] = useState<Stage>('list');
  const [selectedBackupId, setSelectedBackupId] = useState<string | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set());
  const [planPayloadFiles, setPlanPayloadFiles] = useState<string[] | undefined>(undefined);
  const [restorePlan, setRestorePlan] = useState<{
    operations?: Array<{
      backup_relative: string;
      context_display?: string;
      target_delete?: string;
      copy_to: string;
    }>;
    restore_targets?: Array<{ source: string; destination: string }>;
  } | null>(null);
  const [deleteRecord, setDeleteRecord] = useState(true);
  const [deleteFiles, setDeleteFiles] = useState(false);

  const backupsQuery = useBackups(200);
  const filesQuery = useBackupFiles(selectedBackupId ?? '');
  const backupDetailsQuery = useBackupDetails(selectedBackupId ?? '');

  const planMutation = usePlanRestoreBackup();
  const restoreMutation = useRestoreBackup();
  const deleteMutation = useDeleteBackup();
  const reindexMutation = useReindexBackups();

  const selectedBackup = useMemo(
    () => backupsQuery.data?.backups.find((backup) => backup.backup_id === selectedBackupId) ?? null,
    [backupsQuery.data?.backups, selectedBackupId],
  );

  const stageLabel = useMemo(() => {
    switch (stage) {
      case 'files':
        return ['Backups', 'Files'];
      case 'plan':
        return ['Backups', 'Files', 'Confirmation'];
      case 'delete':
        return ['Backups', 'Delete Backup'];
      default:
        return [];
    }
  }, [stage]);

  const openFilesStage = (backupId: string) => {
    setSelectedBackupId(backupId);
    setSelectedFiles(new Set());
    setRestorePlan(null);
    setPlanPayloadFiles(undefined);
    setStage('files');
  };

  const openDeleteStage = (backupId: string) => {
    setSelectedBackupId(backupId);
    setDeleteRecord(true);
    setDeleteFiles(false);
    setStage('delete');
  };

  const toggleFile = (relativePath: string, checked: boolean) => {
    setSelectedFiles((previous) => {
      const next = new Set(previous);
      if (checked) next.add(relativePath);
      else next.delete(relativePath);
      return next;
    });
  };

  const toggleAllFiles = (checked: boolean) => {
    if (!checked) {
      setSelectedFiles(new Set());
      return;
    }
    const all = new Set((filesQuery.data?.files ?? []).map((file) => file.relative_path));
    setSelectedFiles(all);
  };

  const planRestore = async (files?: string[]) => {
    if (!selectedBackupId) return;

    try {
      const result = await planMutation.mutateAsync({ backupId: selectedBackupId, files });
      setRestorePlan(result.plan);
      setPlanPayloadFiles(files);
      setStage('plan');
    } catch {
      toast.error('Failed to plan restore');
    }
  };

  const applyRestore = async () => {
    if (!selectedBackupId) return;

    try {
      await restoreMutation.mutateAsync({ backupId: selectedBackupId, files: planPayloadFiles });
      toast.success('Restore completed successfully');
      setStage('list');
      setRestorePlan(null);
      backupsQuery.refetch();
    } catch {
      toast.error('Restore failed');
    }
  };

  const executeDelete = async () => {
    if (!selectedBackupId) return;
    if (!deleteRecord && !deleteFiles) {
      toast.warning('Select at least one delete option');
      return;
    }

    try {
      await deleteMutation.mutateAsync({
        backupId: selectedBackupId,
        deleteRecord,
        deleteFiles,
      });
      toast.success('Backup delete completed');
      setStage('list');
      backupsQuery.refetch();
    } catch {
      toast.error('Delete failed');
    }
  };

  const runReindex = async () => {
    try {
      const result = await reindexMutation.mutateAsync();
      toast.success(result.message || `Imported ${result.imported} backups`);
      backupsQuery.refetch();
    } catch {
      toast.error('Import/reindex failed');
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold text-white">Backups</h1>
          <p className="text-neutral-400 mt-1">Static-parity backup management with staged restore and delete flows</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={runReindex} disabled={reindexMutation.isPending}>
            <IconArchive className={`h-4 w-4 mr-2 ${reindexMutation.isPending ? 'animate-spin' : ''}`} />
            Import/Reindex
          </Button>
          <Button variant="outline" onClick={() => backupsQuery.refetch()} disabled={backupsQuery.isFetching}>
            <IconRefresh className={`h-4 w-4 mr-2 ${backupsQuery.isFetching ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </div>

      {stageLabel.length > 0 && (
        <div className="flex items-center gap-2 text-sm">
          {stageLabel.map((part, index) => {
            const last = index === stageLabel.length - 1;
            return (
              <div key={`${part}-${index}`} className="flex items-center gap-2">
                {last ? (
                  <span className="text-white">{part}</span>
                ) : (
                  <button
                    type="button"
                    className="text-neutral-400 hover:text-white"
                    onClick={() => {
                      if (index === 0) setStage('list');
                      if (index === 1) setStage('files');
                    }}
                  >
                    {part}
                  </button>
                )}
                {!last && <span className="text-neutral-600">/</span>}
              </div>
            );
          })}
        </div>
      )}

      {stage === 'list' && (
        <Card className="border-neutral-800 bg-neutral-900/50">
          <CardHeader>
            <CardTitle className="text-white">Backup History</CardTitle>
            <CardDescription className="text-neutral-400">{backupsQuery.data?.total ?? 0} backups found</CardDescription>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-[560px] pr-3">
              {backupsQuery.isLoading ? (
                <div className="space-y-3">
                  {[1, 2, 3, 4].map((idx) => (
                    <Skeleton key={idx} className="h-24 w-full" />
                  ))}
                </div>
              ) : (backupsQuery.data?.backups.length ?? 0) > 0 ? (
                <div className="space-y-3">
                  {(backupsQuery.data?.backups ?? []).map((backup) => (
                    <BackupRow
                      key={backup.backup_id}
                      backup={backup}
                      onOpenFiles={openFilesStage}
                      onOpenDelete={openDeleteStage}
                      onRestoreAll={(backupId) => {
                        openFilesStage(backupId);
                        setTimeout(() => {
                          planRestore(undefined);
                        }, 0);
                      }}
                    />
                  ))}
                </div>
              ) : (
                <div className="text-center py-14 text-neutral-500">No backups found</div>
              )}
            </ScrollArea>
          </CardContent>
        </Card>
      )}

      {stage === 'files' && (
        <Card className="border-neutral-800 bg-neutral-900/50">
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <div>
                <CardTitle className="text-white">Backup Files</CardTitle>
                <CardDescription className="text-neutral-400">
                  {selectedBackup?.folder_name || selectedBackupId} - {(filesQuery.data?.files.length ?? 0)} file(s)
                </CardDescription>
              </div>
              <Button variant="outline" size="sm" onClick={() => setStage('list')}>
                <IconArrowLeft className="h-4 w-4 mr-1.5" />
                Back
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                onClick={() => planRestore(Array.from(selectedFiles))}
                disabled={selectedFiles.size === 0 || planMutation.isPending}
              >
                <IconRestore className="h-4 w-4 mr-2" />
                Restore Selected ({selectedFiles.size})
              </Button>
              <Button variant="outline" onClick={() => planRestore(undefined)} disabled={planMutation.isPending}>
                <IconFileDownload className="h-4 w-4 mr-2" />
                Restore All
              </Button>
              <Button variant="outline" onClick={() => openDeleteStage(selectedBackupId || '')}>
                <IconTrash className="h-4 w-4 mr-2" />
                Delete Backup
              </Button>
            </div>

            <ScrollArea className="h-[460px] rounded border border-neutral-800">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-neutral-900">
                  <tr className="text-left text-neutral-400 border-b border-neutral-800">
                    <th className="p-3 w-10">
                      <input
                        type="checkbox"
                        checked={(filesQuery.data?.files.length ?? 0) > 0 && selectedFiles.size === (filesQuery.data?.files.length ?? 0)}
                        onChange={(event) => toggleAllFiles(event.target.checked)}
                      />
                    </th>
                    <th className="p-3">Context</th>
                    <th className="p-3">Relative Path</th>
                    <th className="p-3">Size</th>
                  </tr>
                </thead>
                <tbody>
                  {(filesQuery.data?.files ?? []).map((file) => (
                    <tr key={file.relative_path} className="border-b border-neutral-900">
                      <td className="p-3">
                        <input
                          type="checkbox"
                          checked={selectedFiles.has(file.relative_path)}
                          onChange={(event) => toggleFile(file.relative_path, event.target.checked)}
                        />
                      </td>
                      <td className="p-3 text-neutral-300">{file.context_display || '-'}</td>
                      <td className="p-3 text-neutral-200 font-mono break-all">{file.relative_path}</td>
                      <td className="p-3 text-neutral-300">{humanBytes(file.file_size)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ScrollArea>
          </CardContent>
        </Card>
      )}

      {stage === 'plan' && (
        <Card className="border-neutral-800 bg-neutral-900/50">
          <CardHeader>
            <CardTitle className="text-white">Restore Plan Preview</CardTitle>
            <CardDescription className="text-neutral-400">Review planned actions before applying restore</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <ScrollArea className="h-[480px] rounded border border-neutral-800">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-neutral-900">
                  <tr className="text-left text-neutral-400 border-b border-neutral-800">
                    <th className="p-3">Backup File</th>
                    <th className="p-3">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {(restorePlan?.operations ?? []).length > 0 ? (
                    (restorePlan?.operations ?? []).map((operation) => (
                      <tr key={`${operation.backup_relative}-${operation.copy_to}`} className="border-b border-neutral-900">
                        <td className="p-3">
                          <div className="text-neutral-200 font-mono break-all">{operation.backup_relative}</div>
                          <div className="text-xs text-neutral-500 mt-1">{operation.context_display || 'No context detected'}</div>
                        </td>
                        <td className="p-3">
                          {operation.target_delete && operation.target_delete !== operation.copy_to ? (
                            <div className="space-y-1 text-xs">
                              <div className="text-yellow-300">Replace: {operation.target_delete}</div>
                              <div className="text-green-300">Copy To: {operation.copy_to}</div>
                            </div>
                          ) : (
                            <div className="text-green-300 text-xs">Copy To: {operation.copy_to}</div>
                          )}
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={2} className="p-6 text-center text-neutral-500">
                        No operations in restore plan
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </ScrollArea>
            <div className="flex gap-2">
              <Button onClick={applyRestore} disabled={restoreMutation.isPending}>
                <IconCheck className="h-4 w-4 mr-2" />
                Apply Restore
              </Button>
              <Button variant="outline" onClick={() => setStage('files')}>
                <IconArrowLeft className="h-4 w-4 mr-2" />
                Back to Files
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {stage === 'delete' && (
        <Card className="border-neutral-800 bg-neutral-900/50">
          <CardHeader>
            <CardTitle className="text-white">Delete Backup</CardTitle>
            <CardDescription className="text-neutral-400">Choose whether to delete record, files, or both</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-3 rounded border border-neutral-800 bg-neutral-950 p-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-white">Delete backup record</div>
                  <div className="text-xs text-neutral-500">Remove backup metadata from database</div>
                </div>
                <Switch checked={deleteRecord} onCheckedChange={setDeleteRecord} />
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-white">Delete backup files</div>
                  <div className="text-xs text-neutral-500">
                    Remove files from {backupDetailsQuery.data?.backup?.backup_path || 'backup storage'}
                  </div>
                </div>
                <Switch checked={deleteFiles} onCheckedChange={setDeleteFiles} />
              </div>
            </div>

            {deleteFiles && (
              <ScrollArea className="h-[360px] rounded border border-neutral-800">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-neutral-900">
                    <tr className="text-left text-neutral-400 border-b border-neutral-800">
                      <th className="p-3">Backup File</th>
                      <th className="p-3">Size</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(filesQuery.data?.files ?? []).map((file) => (
                      <tr key={file.relative_path} className="border-b border-neutral-900">
                        <td className="p-3 font-mono text-xs break-all text-neutral-200">{file.relative_path}</td>
                        <td className="p-3 text-neutral-300">{humanBytes(file.file_size)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </ScrollArea>
            )}

            <div className="flex gap-2">
              <Button variant="outline" onClick={() => setStage('list')}>
                <IconArrowLeft className="h-4 w-4 mr-2" />
                Cancel
              </Button>
              <Button onClick={executeDelete} disabled={deleteMutation.isPending || (!deleteRecord && !deleteFiles)}>
                <IconTrash className="h-4 w-4 mr-2" />
                Delete Selected
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function BackupRow({
  backup,
  onOpenFiles,
  onRestoreAll,
  onOpenDelete,
}: {
  backup: Backup;
  onOpenFiles: (backupId: string) => void;
  onRestoreAll: (backupId: string) => void;
  onOpenDelete: (backupId: string) => void;
}) {
  return (
    <div className="rounded-lg border border-neutral-700/50 bg-neutral-800/50 p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <p className="text-sm font-medium text-white truncate">
              {backup.folder_name || backup.transfer_id || backup.backup_id}
              {backup.season_name ? ` - ${backup.season_name}` : ''}
            </p>
            {statusBadge(backup.status)}
            {backup.media_type && <Badge variant="outline">{backup.media_type}</Badge>}
          </div>
          <p className="text-xs text-neutral-400 mt-1">
            {backup.file_count} file(s) - {humanBytes(backup.total_size)} - {new Date(backup.created_at).toLocaleString()}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 shrink-0">
          <Button size="sm" variant="outline" onClick={() => onOpenFiles(backup.backup_id)}>
            <IconEye className="h-4 w-4 mr-1.5" />
            Files
          </Button>
          {backup.status === 'ready' && (
            <Button size="sm" variant="outline" onClick={() => onRestoreAll(backup.backup_id)}>
              <IconRestore className="h-4 w-4 mr-1.5" />
              Restore
            </Button>
          )}
          <Button size="sm" variant="outline" onClick={() => onOpenDelete(backup.backup_id)}>
            <IconTrash className="h-4 w-4 mr-1.5" />
            Delete
          </Button>
        </div>
      </div>
    </div>
  );
}
