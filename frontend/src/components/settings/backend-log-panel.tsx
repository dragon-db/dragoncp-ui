import { useState } from "react";
import { toast } from "sonner";
import { useBackendLogs, useDownloadBackendLogs, type BackendLogLevel } from "@/hooks/useConfig";
import { Button } from "@/components/ui/button";
import { SectionCard } from "@/components/layout/section-card";
import { TAP_SM } from "./settings-model";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import { IconDownload, IconRefresh, IconSearch } from "@tabler/icons-react";

const LEVELS: BackendLogLevel[] = ["ERROR", "WARNING", "INFO", "DEBUG", "ALL"];

/** The page's status vocabulary: rose broken, amber attention, quiet otherwise. */
const levelTone: Record<string, string> = {
  CRITICAL: "text-rose-300",
  ERROR: "text-rose-300",
  WARNING: "text-amber-300",
  INFO: "text-muted-foreground",
  DEBUG: "text-muted-foreground/80",
};

/** What each choice shows, as the server filters it (`routes/logs.py`). */
const LEVEL_LABEL: Record<BackendLogLevel, string> = {
  ERROR: "Errors",
  WARNING: "Warnings and errors",
  INFO: "Info only",
  DEBUG: "Debug only",
  ALL: "Everything",
};

export function BackendLogPanel() {
  const [level, setLevel] = useState<BackendLogLevel>("ERROR");
  const [search, setSearch] = useState("");
  const [autoRefresh, setAutoRefresh] = useState(true);
  const logsQuery = useBackendLogs({ level, search: search.trim(), autoRefresh });
  const download = useDownloadBackendLogs();

  const runDownload = async () => {
    try {
      const filename = await download.mutateAsync();
      toast.success(`Downloaded ${filename}`);
    } catch {
      toast.error("Could not download the backend log");
    }
  };

  return (
    <SectionCard
      label="Backend log"
      description="Recent records from the application log. Download it for the whole file."
      actions={
        <>
          <Button
            variant="outline"
            size="sm"
            className={TAP_SM}
            onClick={() => logsQuery.refetch()}
            disabled={logsQuery.isFetching}
          >
            <IconRefresh className={cn("size-4", logsQuery.isFetching && "animate-spin")} />
            Refresh
          </Button>
          <Button
            variant="outline"
            size="sm"
            className={TAP_SM}
            onClick={runDownload}
            disabled={download.isPending}
          >
            <IconDownload className="size-4" />
            Download
          </Button>
        </>
      }
      toolbar={
        <>
          <Select
            items={LEVELS.map((item) => ({ value: item, label: LEVEL_LABEL[item] }))}
            value={level}
            onValueChange={(value) => setLevel(value as BackendLogLevel)}
          >
            <SelectTrigger className={cn("w-40", TAP_SM)} aria-label="Which records">
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="start">
              {LEVELS.map((item) => (
                <SelectItem key={item} value={item}>
                  {LEVEL_LABEL[item]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="relative order-last w-full sm:order-none sm:w-auto sm:min-w-56 sm:flex-1">
            <IconSearch className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search the log"
              aria-label="Search the log"
              className="pl-9 max-sm:h-11"
            />
          </div>
          <label className="flex min-h-11 items-center gap-2 text-[12.5px] text-muted-foreground sm:min-h-9">
            <Switch checked={autoRefresh} onCheckedChange={setAutoRefresh} />
            Keep refreshing
          </label>
        </>
      }
    >
      <p className="flex flex-wrap gap-x-2 px-4 pt-2.5 text-[11.5px] text-muted-foreground">
        <span className="font-mono">{logsQuery.data?.log_file ?? "Backend log"}</span>
        <span>
          {logsQuery.data?.line_count ?? 0} record{logsQuery.data?.line_count === 1 ? "" : "s"}
        </span>
        {logsQuery.data?.last_modified && (
          <span>updated {new Date(logsQuery.data.last_modified).toLocaleString()}</span>
        )}
      </p>
      <ScrollArea className="m-3 mt-2 h-[360px] rounded-lg border border-border bg-black/30">
        <div className="space-y-2 p-3 font-mono text-[11.5px] leading-relaxed">
          {logsQuery.isError ? (
            <p className="text-rose-300">
              Could not read the backend log. Press Refresh to try again.
            </p>
          ) : logsQuery.isLoading ? (
            <p className="text-muted-foreground">Reading the backend log…</p>
          ) : logsQuery.data?.lines.length ? (
            logsQuery.data.lines.map((entry, index) => (
              <div key={`${index}-${entry.text.slice(0, 24)}`} className="flex items-start gap-2">
                <span
                  className={cn(
                    "mt-px w-[4.5rem] shrink-0 text-[10px] font-semibold",
                    levelTone[entry.level] ?? "text-muted-foreground"
                  )}
                >
                  {entry.level}
                </span>
                <pre className="min-w-0 flex-1 whitespace-pre-wrap text-foreground/85">
                  {entry.text}
                </pre>
              </div>
            ))
          ) : (
            <p className="text-muted-foreground">
              {logsQuery.data?.message ??
                (search.trim()
                  ? "Nothing in the log matches that search."
                  : "No records at this level. Pick a wider one to see more.")}
            </p>
          )}
        </div>
      </ScrollArea>
    </SectionCard>
  );
}
