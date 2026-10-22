import { BackendLogPanel } from "./backend-log-panel";
import { LiveConnectionTiles, SessionsCard } from "./websocket-panel";

/**
 * Where to look when something is off: the live connections first, because
 * they fit on one screen, then the backend log, which runs as long as it has to.
 */
export function LogsTab() {
  return (
    <div className="space-y-4">
      <LiveConnectionTiles />
      <SessionsCard />
      <BackendLogPanel />
    </div>
  );
}
