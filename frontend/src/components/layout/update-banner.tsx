import { useState } from "react";
import { IconRefresh, IconX } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { useUpdateAvailable } from "@/hooks/useConfig";

/**
 * "This tab is running an older release."
 *
 * The one caching problem hashed filenames cannot solve. Asset URLs change with
 * their contents and the shell is never cached, so **a reload always lands on
 * the new build** — which is exactly why nothing on the server can help a tab
 * that does not reload. A window left open across a deploy keeps running the
 * old JavaScript against the new API until someone refreshes it, and the
 * failures that produces look like bugs rather than staleness.
 *
 * So the server's version is compared against the one compiled into this
 * bundle, using the runtime status every page already polls — no extra request.
 *
 * It prompts rather than reloading on its own. Reloading underneath someone
 * halfway through reviewing a sync plan would lose their work to fix a problem
 * they were not having yet.
 */
export function UpdateBanner() {
  const { stale, running, available } = useUpdateAvailable();
  const [dismissed, setDismissed] = useState(false);

  if (!stale || dismissed) return null;

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-brand/35 bg-brand/[0.08] px-4 py-2 sm:px-6">
      <IconRefresh className="size-4 flex-none text-brand-hover" />
      <p className="min-w-0 flex-1 text-[12.5px]">
        <span className="font-medium text-brand-foreground">Version {available} is running</span>
        <span className="text-muted-foreground">
          {" "}
          — this tab still has {running}. Reload to pick it up.
        </span>
      </p>
      <div className="flex flex-none items-center gap-1.5">
        <Button size="sm" className="h-7" onClick={() => window.location.reload()}>
          Reload
        </Button>
        <Button
          size="icon-sm"
          variant="ghost"
          className="size-7"
          aria-label="Dismiss until this tab is reloaded"
          onClick={() => setDismissed(true)}
        >
          <IconX className="size-4" />
        </Button>
      </div>
    </div>
  );
}
