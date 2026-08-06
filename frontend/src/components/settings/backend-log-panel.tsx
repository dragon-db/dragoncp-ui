import { useState } from "react";
import { toast } from "sonner";
import { useBackendLogs, useDownloadBackendLogs, type BackendLogLevel } from "@/hooks/useConfig";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
import { IconDownload, IconRefresh, IconSearch, IconTerminal2 } from "@tabler/icons-react";

const LEVELS: BackendLogLevel[] = ["ERROR", "WARNING", "INFO", "DEBUG", "ALL"];

const levelTone: Record<string, string> = {
  CRITICAL: "border-red-500/40 text-red-300",
  ERROR: "border-red-500/40 text-red-300",
  WARNING: "border-amber-500/40 text-amber-300",
  INFO: "border-sky-500/40 text-sky-300",
  DEBUG: "border-neutral-700 text-neutral-400",
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
    <Card className="border-neutral-800 bg-neutral-900/50">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-white">
              <IconTerminal2 className="size-4" />
              Backend logs
            </CardTitle>
            <CardDescription className="text-neutral-400">
              Search recent application records or download the complete log file
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => logsQuery.refetch()}
              disabled={logsQuery.isFetching}
            >
              <IconRefresh className={cn("size-4", logsQuery.isFetching && "animate-spin")} />
              Refresh
            </Button>
            <Button variant="outline" size="sm" onClick={runDownload} disabled={download.isPending}>
              <IconDownload className="size-4" />
              Download
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <Select value={level} onValueChange={(value) => setLevel(value as BackendLogLevel)}>
            <SelectTrigger className="w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="start">
              {LEVELS.map((item) => (
                <SelectItem key={item} value={item}>
                  {item === "ERROR" ? "Error + Critical" : item}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="relative min-w-56 flex-1">
            <IconSearch className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search log records"
              className="pl-9"
            />
          </div>
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <Switch checked={autoRefresh} onCheckedChange={setAutoRefresh} size="sm" />
            Auto-refresh
          </label>
        </div>

        <div className="flex flex-wrap gap-2 text-[11px] text-muted-foreground">
          <span>{logsQuery.data?.log_file ?? "Backend log"}</span>
          <span>·</span>
          <span>{logsQuery.data?.line_count ?? 0} record(s)</span>
          {logsQuery.data?.last_modified && (
            <>
              <span>·</span>
              <span>updated {new Date(logsQuery.data.last_modified).toLocaleString()}</span>
            </>
          )}
        </div>

        <ScrollArea className="h-[360px] rounded-lg border border-neutral-800 bg-neutral-950">
          <div className="space-y-3 p-3 font-mono text-[11px] leading-relaxed">
            {logsQuery.isError ? (
              <p className="text-red-300">Could not load backend logs.</p>
            ) : logsQuery.isLoading ? (
              <p className="text-muted-foreground">Loading backend logs…</p>
            ) : logsQuery.data?.lines.length ? (
              logsQuery.data.lines.map((entry, index) => (
                <div key={`${index}-${entry.text.slice(0, 24)}`} className="flex items-start gap-2">
                  <Badge
                    variant="outline"
                    className={cn("mt-0.5 w-16 justify-center text-[9px]", levelTone[entry.level])}
                  >
                    {entry.level}
                  </Badge>
                  <pre className="min-w-0 flex-1 whitespace-pre-wrap text-neutral-300">
                    {entry.text}
                  </pre>
                </div>
              ))
            ) : (
              <p className="text-muted-foreground">
                {logsQuery.data?.message ?? "No matching log records."}
              </p>
            )}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
