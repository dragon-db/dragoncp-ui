import { useState } from "react";
import { IconAlertTriangle, IconCheck } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Notice } from "@/components/integrations/library-bits";
import { libraryError } from "@/components/integrations/library-vocab";
import { freeSpace, titleName } from "@/components/integrations/seerr-vocab";
import { useRequestOptions } from "@/hooks/useSeerr";
import type { RequestChanges, RequestOptions, SeerrRequest } from "@/lib/seerr-types";

/**
 * Approve with changes: the same choices Seerr's own approve dialog offers —
 * which Sonarr or Radarr, which quality, which folder, which seasons.
 *
 * Opening it makes Seerr ask that Sonarr or Radarr (on the remote server) for
 * its profiles and folders, which is why the plain Approve button does not.
 */
export function ApproveDialog({
  request,
  pending,
  onClose,
  onApprove,
}: {
  request: SeerrRequest | null;
  pending: boolean;
  onClose: () => void;
  onApprove: (changes: RequestChanges) => void;
}) {
  return (
    <Dialog open={Boolean(request)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg">
        {request && (
          <ApproveBody
            key={request.id}
            request={request}
            pending={pending}
            onClose={onClose}
            onApprove={onApprove}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function ApproveBody({
  request,
  pending,
  onClose,
  onApprove,
}: {
  request: SeerrRequest;
  pending: boolean;
  onClose: () => void;
  onApprove: (changes: RequestChanges) => void;
}) {
  const [serverId, setServerId] = useState<number | null>(null);
  const options = useRequestOptions(request.id, serverId);
  const service = request.type === "tv" ? "Sonarr" : "Radarr";

  return (
    <>
      <DialogHeader>
        <DialogTitle>Approve {titleName(request.title)}</DialogTitle>
        <DialogDescription>
          Change what Seerr hands to {service}, then approve. Anything left as it is stays as{" "}
          {request.requested_by?.name ?? "they"} asked.
        </DialogDescription>
      </DialogHeader>
      {options.isLoading ? (
        <div className="space-y-3 py-2">
          <p className="text-[12px] text-muted-foreground">Asking {service} through Seerr…</p>
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </div>
      ) : options.isError || !options.data ? (
        <Notice tone="crit" icon={IconAlertTriangle}>
          {libraryError(options.error, `Could not read ${service}'s choices.`)}
        </Notice>
      ) : (
        <ApproveForm
          key={options.data.server_id ?? "none"}
          request={request}
          options={options.data}
          pending={pending}
          onServer={setServerId}
          onClose={onClose}
          onApprove={onApprove}
        />
      )}
    </>
  );
}

function ApproveForm({
  request,
  options,
  pending,
  onServer,
  onClose,
  onApprove,
}: {
  request: SeerrRequest;
  options: RequestOptions;
  pending: boolean;
  onServer: (id: number) => void;
  onClose: () => void;
  onApprove: (changes: RequestChanges) => void;
}) {
  const [profile, setProfile] = useState(
    options.current.profile_id != null ? String(options.current.profile_id) : ""
  );
  const [folder, setFolder] = useState(options.current.root_folder ?? "");
  const [seasons, setSeasons] = useState<number[]>(
    options.seasons.filter((s) => s.requested).map((s) => s.number)
  );
  const isTv = request.type === "tv";

  const submit = () => {
    const changes: RequestChanges = {};
    if (options.server_id != null) changes.server_id = options.server_id;
    if (profile) changes.profile_id = Number(profile);
    if (folder) changes.root_folder = folder;
    if (isTv) changes.seasons = seasons;
    onApprove(changes);
  };

  const serverItems = options.servers.map((s) => ({
    value: String(s.id),
    label: s.is_default ? `${s.name} (default)` : s.name,
  }));
  const profileItems = options.profiles.map((p) => ({ value: String(p.id), label: p.name }));
  const folderItems = options.root_folders.map((f) => ({
    value: f.path,
    label: [f.path, freeSpace(f.free_bytes)].filter(Boolean).join(" · "),
  }));

  return (
    <>
      <div className="space-y-4 py-1">
        {serverItems.length > 1 && (
          <Field label="Server">
            <PickOne
              items={serverItems}
              value={options.server_id != null ? String(options.server_id) : ""}
              label="Server"
              onChange={(value) => onServer(Number(value))}
            />
          </Field>
        )}
        <Field label="Quality">
          <PickOne items={profileItems} value={profile} label="Quality" onChange={setProfile} />
        </Field>
        <Field label="Folder on the remote server">
          <PickOne items={folderItems} value={folder} label="Folder" onChange={setFolder} />
        </Field>
        {isTv && options.seasons.length > 0 && (
          <Field label="Seasons">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {options.seasons
                .filter((s) => s.number > 0 || s.requested)
                .map((season) => {
                  const checked = seasons.includes(season.number);
                  return (
                    <label
                      key={season.number}
                      className="flex items-center gap-2 rounded-md border border-border/70 px-2 py-1.5 text-[12.5px]"
                    >
                      <Checkbox
                        checked={checked}
                        disabled={season.available}
                        onCheckedChange={(next) =>
                          setSeasons((current) =>
                            next
                              ? [...current, season.number]
                              : current.filter((n) => n !== season.number)
                          )
                        }
                      />
                      <span className={season.available ? "text-muted-foreground" : ""}>
                        {season.number === 0 ? "Specials" : `Season ${season.number}`}
                        {season.available
                          ? " · in Jellyfin"
                          : season.episodes
                            ? ` · ${season.episodes} ep`
                            : ""}
                      </span>
                    </label>
                  );
                })}
            </div>
          </Field>
        )}
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={onClose} disabled={pending}>
          Cancel
        </Button>
        <Button onClick={submit} disabled={pending || (isTv && seasons.length === 0)}>
          <IconCheck className="size-3.5" />
          Approve
        </Button>
      </DialogFooter>
    </>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <p className="text-[12px] font-medium text-foreground-2">{label}</p>
      {children}
    </div>
  );
}

function PickOne({
  items,
  value,
  label,
  onChange,
}: {
  items: { value: string; label: string }[];
  value: string;
  label: string;
  onChange: (value: string) => void;
}) {
  return (
    <Select
      items={items}
      value={value || null}
      onValueChange={(next) => next && onChange(String(next))}
    >
      <SelectTrigger className="w-full" aria-label={label}>
        <SelectValue className="truncate">
          {() => items.find((item) => item.value === value)?.label ?? "Choose…"}
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        {items.map((item) => (
          <SelectItem key={item.value} value={item.value}>
            {item.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
