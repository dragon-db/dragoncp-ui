import { useState } from "react";
import { IconAlertTriangle, IconLink, IconLinkOff, IconSearch } from "@tabler/icons-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useTmdbSearch } from "@/hooks/useRenames";
import { errorText } from "@/lib/api-error";
import { cn } from "@/lib/utils";

/**
 * Match a series Sonarr does not have to a show on TMDB, once.
 *
 * Opens on a search for the folder's own name and year, which finds most of
 * them; the box is there for the rest. The link is stored, so its episodes get
 * titles from TMDB from then on, always shown for review before a rename.
 */
export function TmdbLinkDialog({
  open,
  onOpenChange,
  mediaType,
  folder,
  linking,
  onLink,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mediaType: string;
  folder: string | null;
  linking: boolean;
  /** `null` removes the link. */
  onLink: (tmdbId: number | null) => void;
}) {
  const [typed, setTyped] = useState("");
  const query = useDebouncedValue(typed.trim(), 400);
  const search = useTmdbSearch(mediaType, folder, query, open);
  const results = search.data?.results ?? [];
  const linked = search.data?.linked ?? null;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setTyped("");
        onOpenChange(next);
      }}
    >
      <DialogContent className="max-h-[85vh] gap-0 overflow-hidden p-0 sm:max-w-xl">
        <DialogHeader className="border-b border-border px-5 py-4">
          <DialogTitle className="text-[15px]">Find titles on TMDB</DialogTitle>
          <DialogDescription className="text-[12.5px]">
            Sonarr does not have <span className="text-foreground">{folder}</span>. Pick the show it
            is, and its episodes still named TBA get titles from TMDB. You see every name before
            anything is renamed.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3 px-5 py-4">
          {linked && (
            <div className="flex items-center gap-2 rounded-md border border-violet-500/35 bg-violet-500/8 px-3 py-2 text-[12px] text-violet-100">
              <IconLink className="size-3.5 flex-none" />
              <span className="min-w-0 flex-1">
                Linked to{" "}
                <span className="font-medium">
                  {linked.tmdb_name}
                  {linked.tmdb_year ? ` (${linked.tmdb_year})` : ""}
                </span>
              </span>
              <Button
                size="sm"
                variant="ghost"
                className="h-6 px-2 text-[11px]"
                disabled={linking}
                onClick={() => onLink(null)}
              >
                <IconLinkOff className="mr-1 size-3.5" />
                Unlink
              </Button>
            </div>
          )}

          <div className="flex items-center gap-2 rounded-[10px] border border-border bg-well px-[11px] py-1.5">
            <IconSearch className="size-3.5 flex-none text-muted-foreground" />
            <input
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
              placeholder={
                search.data?.query ? `Searching for “${search.data.query}”` : "Show name"
              }
              className="w-full min-w-0 bg-transparent text-[12.5px] outline-none placeholder:text-muted-foreground"
            />
          </div>

          <div className="max-h-[46vh] overflow-y-auto">
            {search.isLoading ? (
              <p className="text-[12.5px] text-muted-foreground">Searching TMDB…</p>
            ) : search.isError ? (
              <p className="flex items-start gap-2 rounded-md border border-rose-500/40 bg-rose-500/8 p-2.5 text-[12.5px] text-rose-100">
                <IconAlertTriangle className="mt-px size-4 flex-none" />
                {errorText(search.error, "TMDB could not be searched.")}
              </p>
            ) : results.length === 0 ? (
              <p className="text-[12.5px] text-muted-foreground">
                Nothing on TMDB by that name. Try a shorter or the original name.
              </p>
            ) : (
              <ul className="flex flex-col gap-1.5">
                {results.map((show) => {
                  const current = linked?.tmdb_id === show.tmdb_id;
                  return (
                    <li
                      key={show.tmdb_id}
                      className={cn(
                        "flex items-start gap-3 rounded-md border p-2.5",
                        current ? "border-violet-500/50 bg-violet-500/8" : "border-border/70"
                      )}
                    >
                      <div className="min-w-0 flex-1">
                        <p className="text-[13px] font-medium text-foreground">
                          {show.name}
                          {show.year && (
                            <span className="ml-1.5 font-mono text-[11px] text-foreground-3">
                              {show.year}
                            </span>
                          )}
                        </p>
                        {show.overview && (
                          <p className="mt-0.5 line-clamp-2 text-[11.5px] text-muted-foreground">
                            {show.overview}
                          </p>
                        )}
                      </div>
                      <Button
                        size="sm"
                        variant={current ? "ghost" : "outline"}
                        className="flex-none"
                        disabled={linking || current}
                        onClick={() => onLink(show.tmdb_id)}
                      >
                        {current ? "Linked" : "This one"}
                      </Button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
