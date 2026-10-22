import { useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { SectionCard, SectionEmpty } from "@/components/layout/section-card";
import { MentionPicker } from "@/components/integrations/mention-picker";
import { errorText } from "@/lib/api-error";
import {
  useAddTarget,
  useDeleteTarget,
  useTestTarget,
  useUpdateTarget,
  type Connector,
  type ConnectorTarget,
} from "@/hooks/useConnectors";
import {
  IconAlertTriangle,
  IconInbox,
  IconPlus,
  IconSend,
  IconStar,
  IconTrash,
} from "@tabler/icons-react";

/**
 * The destinations a connector can send to.
 *
 * The label is the point: it is an identifier the operator chose, and it is
 * what the routing table offers by name. Which is why one webhook is always
 * the default — a connector with destinations but no default cannot deliver
 * anything, and arriving there by adding one webhook would be a trap.
 */
export function TargetsPanel({ connector }: { connector: Connector }) {
  const noun = connector.target_noun ?? "destination";
  const targets = connector.targets ?? [];

  const addTarget = useAddTarget(connector.id);
  const [label, setLabel] = useState("");
  const [credential, setCredential] = useState("");

  const onAdd = async () => {
    try {
      await addTarget.mutateAsync({ label: label.trim(), credential: credential.trim() });
      setLabel("");
      setCredential("");
      toast.success(`Added “${label.trim()}”`);
    } catch (error) {
      toast.error(errorText(error, `Could not add the ${noun}`));
    }
  };

  return (
    <div className="space-y-4">
      <SectionCard
        label={`${noun}s`}
        description={`Where ${connector.display_name} messages can be sent. Give each one a name you will recognise in the notification list.`}
        contentClassName="divide-y divide-border/70"
      >
        {targets.length === 0 ? (
          <SectionEmpty
            icon={IconInbox}
            title={`No ${noun}s yet`}
            hint={`Add one below and DragonCP can start announcing things. Nothing is sent until there is somewhere to send it.`}
          />
        ) : (
          targets.map((target) => (
            <TargetRow key={target.target_id} connector={connector} target={target} />
          ))
        )}
      </SectionCard>

      <SectionCard label={`Add a ${noun}`} contentClassName="p-4">
        <div className="grid gap-3 sm:max-w-xl">
          <div className="grid gap-1.5">
            <Label htmlFor="new-target-label">Name</Label>
            <Input
              id="new-target-label"
              placeholder="alerts"
              value={label}
              onChange={(event) => setLabel(event.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Yours to choose. This is what you will pick from when deciding where each notification
              goes.
            </p>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="new-target-url">Webhook URL</Label>
            <Input
              id="new-target-url"
              type="password"
              placeholder="https://discord.com/api/webhooks/…"
              value={credential}
              onChange={(event) => setCredential(event.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              In Discord: channel settings → Integrations → Webhooks → Copy Webhook URL. It is
              stored on the server and never shown again.
            </p>
          </div>
          <div>
            <Button
              className="w-full sm:w-auto"
              onClick={onAdd}
              disabled={addTarget.isPending || !label.trim() || !credential.trim()}
            >
              <IconPlus className="mr-2 h-4 w-4" />
              {addTarget.isPending ? "Adding…" : `Add ${noun}`}
            </Button>
          </div>
        </div>
      </SectionCard>
    </div>
  );
}

function TargetRow({ connector, target }: { connector: Connector; target: ConnectorTarget }) {
  const updateTarget = useUpdateTarget(connector.id);
  const deleteTarget = useDeleteTarget(connector.id);
  const testTarget = useTestTarget(connector.id);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  const noun = connector.target_noun ?? "destination";

  const run = async (promise: Promise<unknown>, success: string, failure: string) => {
    try {
      await promise;
      toast.success(success);
    } catch (error) {
      toast.error(errorText(error, failure));
    }
  };

  return (
    /*
      Stacked on a phone, a row from `sm`. As a single row the action cluster
      would not shrink, so the name it belongs to was crushed to one character
      and an ellipsis — a destination you cannot read is one you cannot pick
      from the notification list either.
    */
    <div className="flex flex-col gap-3 px-4 py-3.5 sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-3 sm:gap-y-2 sm:py-3">
      <div className="min-w-0 sm:flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="truncate text-sm font-semibold text-foreground">{target.label}</span>
          {target.is_default && (
            <Badge variant="secondary" className="gap-1">
              <IconStar className="h-3 w-3" />
              Default
            </Badge>
          )}
          {!target.enabled && (
            <Badge variant="outline" className="gap-1 text-muted-foreground">
              <IconAlertTriangle className="h-3 w-3" />
              Out of service
            </Badge>
          )}
        </div>
        <div className="mt-0.5 text-xs text-muted-foreground">
          {target.last_send_at ? (
            target.last_send_ok ? (
              <>Last message delivered {new Date(target.last_send_at + "Z").toLocaleString()}</>
            ) : (
              <span className="text-destructive">
                Last message failed: {target.last_send_error}
              </span>
            )
          ) : (
            <>Nothing sent here yet</>
          )}
        </div>
        {connector.supports_mentions && (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-foreground">Pings</span>
            {(connector.mentions ?? []).length > 0 ? (
              <MentionPicker
                mentions={connector.mentions ?? []}
                value={target.mention_ids}
                onChange={(next) =>
                  run(
                    updateTarget.mutateAsync({
                      targetId: target.target_id,
                      mention_ids: next ?? [],
                    }),
                    `Saved who “${target.label}” pings`,
                    "Could not change who it pings"
                  )
                }
                className="h-8 w-56 max-w-full"
                ariaLabel={`Who messages to “${target.label}” ping`}
              />
            ) : (
              <span className="text-xs text-muted-foreground">
                nobody yet — add a role or person on the Mentions tab
              </span>
            )}
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2 sm:flex-nowrap">
        <div
          className="flex items-center gap-1.5"
          title="Messages routed here are held, not sent elsewhere"
        >
          <Switch
            checked={target.enabled}
            onCheckedChange={(checked) =>
              run(
                updateTarget.mutateAsync({ targetId: target.target_id, enabled: checked }),
                checked
                  ? `“${target.label}” is back in service`
                  : `“${target.label}” is out of service`,
                "Could not change it"
              )
            }
            aria-label={`Keep “${target.label}” in service`}
          />
          <span className="text-xs whitespace-nowrap text-muted-foreground">In service</span>
        </div>

        {/* Pushes the buttons to the far edge on a wide row; collapses to
            nothing once the cluster wraps onto its own line. */}
        <span className="ml-auto" />

        {!target.is_default && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() =>
              run(
                updateTarget.mutateAsync({ targetId: target.target_id, make_default: true }),
                `“${target.label}” is now the default`,
                "Could not change the default"
              )
            }
          >
            <IconStar className="mr-1.5 h-4 w-4" />
            <span className="hidden sm:inline">Make default</span>
            <span className="sm:hidden">Default</span>
          </Button>
        )}

        <Button
          variant="outline"
          size="sm"
          disabled={testTarget.isPending}
          onClick={async () => {
            try {
              const result = await testTarget.mutateAsync(target.target_id);
              toast.success(result?.message ?? `Test message sent to “${target.label}”`);
            } catch (error) {
              toast.error(errorText(error, "The test message was not accepted"));
            }
          }}
        >
          <IconSend className="mr-1.5 h-4 w-4" />
          Test
        </Button>

        {confirmingDelete ? (
          <div className="flex items-center gap-1.5">
            <span className="text-xs whitespace-nowrap text-muted-foreground">Remove it?</span>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => {
                setConfirmingDelete(false);
                run(
                  deleteTarget.mutateAsync(target.target_id),
                  `Removed “${target.label}”`,
                  `Could not remove the ${noun}`
                );
              }}
            >
              Remove
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setConfirmingDelete(false)}>
              Keep
            </Button>
          </div>
        ) : (
          <Button
            variant="ghost"
            size="icon"
            className="text-muted-foreground hover:text-destructive"
            onClick={() => setConfirmingDelete(true)}
            title={`Remove this ${noun}`}
            aria-label={`Remove “${target.label}”`}
          >
            <IconTrash className="h-4 w-4" />
          </Button>
        )}
      </div>
    </div>
  );
}
