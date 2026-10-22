import { useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuGroup,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { SectionCard, SectionEmpty } from "@/components/layout/section-card";
import { errorText } from "@/lib/api-error";
import {
  useAddMention,
  useDeleteMention,
  useTestMention,
  useUpdateMention,
  type Connector,
  type ConnectorMention,
} from "@/hooks/useConnectors";
import { IconAt, IconCheck, IconPencil, IconPlus, IconSend, IconTrash } from "@tabler/icons-react";

/** What each kind is called on the form, and whether it needs an ID. */
const KINDS: Record<string, { label: string; needsId: boolean; idLabel?: string }> = {
  role: { label: "Role", needsId: true, idLabel: "Role ID" },
  user: { label: "Person", needsId: true, idLabel: "User ID" },
  here: { label: "@here — everyone online in the channel", needsId: false },
  everyone: { label: "@everyone — everyone in the channel", needsId: false },
};

const KIND_BADGE: Record<string, string> = {
  role: "Role",
  user: "Person",
  here: "@here",
  everyone: "@everyone",
};

/**
 * Who a Discord message can ping.
 *
 * Kept as a named list so a webhook and a notification choose "Admins" rather
 * than each holding a Discord ID — a wrong ID is fixed once here, not in every
 * place it was used.
 */
export function MentionsPanel({ connector }: { connector: Connector }) {
  const mentions = connector.mentions ?? [];
  const kinds = (connector.mention_kinds ?? Object.keys(KINDS)).filter((kind) => KINDS[kind]);

  return (
    <div className="space-y-4">
      <SectionCard
        label="Mentions"
        description="Who a message can ping. Choose who each webhook pings on the Webhooks tab, and which notifications ping on the Routing tab."
        contentClassName="divide-y divide-border/70"
      >
        {mentions.length === 0 ? (
          <SectionEmpty
            icon={IconAt}
            title="No one to ping yet"
            hint="Add a Discord role, a person or @here below. Until then, messages arrive without pinging anyone."
          />
        ) : (
          mentions.map((mention) => (
            <MentionRow
              key={mention.mention_id}
              connector={connector}
              mention={mention}
              kinds={kinds}
            />
          ))
        )}
      </SectionCard>

      <AddMention connector={connector} kinds={kinds} />
    </div>
  );
}

function AddMention({ connector, kinds }: { connector: Connector; kinds: string[] }) {
  const addMention = useAddMention(connector.id);
  const [label, setLabel] = useState("");
  const [kind, setKind] = useState("role");
  const [value, setValue] = useState("");
  const needsId = KINDS[kind]?.needsId ?? false;

  const onAdd = async () => {
    try {
      await addMention.mutateAsync({
        label: label.trim(),
        kind,
        value: needsId ? value.trim() : "",
      });
      toast.success(`Added “${label.trim()}”`);
      setLabel("");
      setValue("");
    } catch (error) {
      toast.error(errorText(error, "Could not add it"));
    }
  };

  return (
    <SectionCard label="Add someone to ping" contentClassName="p-4">
      <div className="grid gap-3 sm:max-w-xl">
        <MentionFields
          idPrefix="new-mention"
          kinds={kinds}
          label={label}
          kind={kind}
          value={value}
          onLabel={setLabel}
          onKind={setKind}
          onValue={setValue}
        />
        <div>
          <Button
            className="w-full sm:w-auto"
            onClick={onAdd}
            disabled={addMention.isPending || !label.trim() || (needsId && !value.trim())}
          >
            <IconPlus className="mr-2 h-4 w-4" />
            {addMention.isPending ? "Adding…" : "Add"}
          </Button>
        </div>
      </div>
    </SectionCard>
  );
}

/** Name, kind and ID — shared by the add form and a row being edited. */
function MentionFields({
  idPrefix,
  kinds,
  label,
  kind,
  value,
  onLabel,
  onKind,
  onValue,
}: {
  idPrefix: string;
  kinds: string[];
  label: string;
  kind: string;
  value: string;
  onLabel: (next: string) => void;
  onKind: (next: string) => void;
  onValue: (next: string) => void;
}) {
  const meta = KINDS[kind];
  const items = kinds.map((id) => ({ value: id, label: KINDS[id].label }));
  return (
    <>
      <div className="grid gap-1.5">
        <Label htmlFor={`${idPrefix}-label`}>Name</Label>
        <Input
          id={`${idPrefix}-label`}
          placeholder="Admins"
          value={label}
          onChange={(event) => onLabel(event.target.value)}
        />
        <p className="text-xs text-muted-foreground">
          Yours to choose. This is what you pick from on the Webhooks and Routing tabs.
        </p>
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor={`${idPrefix}-kind`}>Who</Label>
        <Select items={items} value={kind} onValueChange={(next) => onKind(String(next))}>
          <SelectTrigger id={`${idPrefix}-kind`} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {items.map((item) => (
                <SelectItem key={item.value} value={item.value}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>
      {meta?.needsId && (
        <div className="grid gap-1.5">
          <Label htmlFor={`${idPrefix}-value`}>{meta.idLabel}</Label>
          <Input
            id={`${idPrefix}-value`}
            inputMode="numeric"
            placeholder="112233445566778899"
            value={value}
            onChange={(event) => onValue(event.target.value)}
            className="font-mono"
          />
          <p className="text-xs text-pretty text-muted-foreground">
            In Discord, turn on Settings → Advanced → Developer Mode. Then right-click the{" "}
            {kind === "role" ? "role (Server Settings → Roles)" : "person"} and choose Copy{" "}
            {kind === "role" ? "Role" : "User"} ID.
            {kind === "role" &&
              " If the test ping arrives as plain text, turn on “Allow anyone to @mention this role” for that role."}
          </p>
        </div>
      )}
    </>
  );
}

function MentionRow({
  connector,
  mention,
  kinds,
}: {
  connector: Connector;
  mention: ConnectorMention;
  kinds: string[];
}) {
  const updateMention = useUpdateMention(connector.id);
  const deleteMention = useDeleteMention(connector.id);
  const testMention = useTestMention(connector.id);
  const [editing, setEditing] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [label, setLabel] = useState(mention.label);
  const [kind, setKind] = useState(mention.kind);
  const [value, setValue] = useState(mention.value);

  const webhooks = (connector.targets ?? []).filter((target) => target.enabled);
  const usedBy = (connector.targets ?? [])
    .filter((target) => target.mention_ids.includes(mention.mention_id))
    .map((target) => target.label);

  const startEditing = () => {
    setLabel(mention.label);
    setKind(mention.kind);
    setValue(mention.value);
    setEditing(true);
  };

  const onSave = async () => {
    try {
      await updateMention.mutateAsync({
        mentionId: mention.mention_id,
        label: label.trim(),
        kind,
        value: KINDS[kind]?.needsId ? value.trim() : "",
      });
      toast.success(`Saved “${label.trim()}”`);
      setEditing(false);
    } catch (error) {
      toast.error(errorText(error, "Could not save it"));
    }
  };

  const onTest = async (targetId: string) => {
    try {
      const result = await testMention.mutateAsync({ mentionId: mention.mention_id, targetId });
      toast.success(result.message);
    } catch (error) {
      toast.error(errorText(error, "The test ping was not accepted"));
    }
  };

  if (editing) {
    return (
      <div className="grid gap-3 px-4 py-3.5 sm:max-w-xl">
        <MentionFields
          idPrefix={`edit-${mention.mention_id}`}
          kinds={kinds}
          label={label}
          kind={kind}
          value={value}
          onLabel={setLabel}
          onKind={setKind}
          onValue={setValue}
        />
        <div className="flex gap-2">
          <Button size="sm" onClick={onSave} disabled={updateMention.isPending || !label.trim()}>
            <IconCheck className="mr-1.5 h-4 w-4" />
            {updateMention.isPending ? "Saving…" : "Save"}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
            Cancel
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 px-4 py-3.5 sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-3 sm:gap-y-2 sm:py-3">
      <div className="min-w-0 sm:flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="truncate text-sm font-semibold text-foreground">{mention.label}</span>
          <Badge variant="secondary">{KIND_BADGE[mention.kind] ?? mention.kind}</Badge>
          {mention.value && (
            <span className="font-mono text-xs text-muted-foreground">{mention.value}</span>
          )}
        </div>
        <div className="mt-0.5 text-xs text-muted-foreground">
          {usedBy.length
            ? `Pinged by default on ${usedBy.map((name) => `“${name}”`).join(", ")}`
            : "Not a webhook default. Notifications can still pick it on the Routing tab."}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 sm:flex-nowrap">
        <span className="ml-auto" />
        {webhooks.length === 1 ? (
          <Button
            variant="outline"
            size="sm"
            disabled={testMention.isPending}
            onClick={() => onTest(webhooks[0].target_id)}
          >
            <IconSend className="mr-1.5 h-4 w-4" />
            Test ping
          </Button>
        ) : (
          <DropdownMenu>
            <DropdownMenuTrigger
              render={<Button variant="outline" size="sm" />}
              disabled={testMention.isPending || webhooks.length === 0}
            >
              <IconSend className="mr-1.5 h-4 w-4" />
              Test ping
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-52">
              <DropdownMenuGroup>
                <DropdownMenuLabel>Send it to</DropdownMenuLabel>
                {webhooks.map((target) => (
                  <DropdownMenuItem key={target.target_id} onClick={() => onTest(target.target_id)}>
                    {target.label}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
        <Button variant="ghost" size="sm" onClick={startEditing}>
          <IconPencil className="mr-1.5 h-4 w-4" />
          Edit
        </Button>
        {confirmingDelete ? (
          <div className="flex items-center gap-1.5">
            <span className="text-xs whitespace-nowrap text-muted-foreground">Remove it?</span>
            <Button
              variant="destructive"
              size="sm"
              onClick={async () => {
                setConfirmingDelete(false);
                try {
                  await deleteMention.mutateAsync(mention.mention_id);
                  toast.success(`Removed “${mention.label}”`);
                } catch (error) {
                  toast.error(errorText(error, "Could not remove it"));
                }
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
            title="Remove from the list, and from every webhook and notification that pings it"
            aria-label={`Remove “${mention.label}”`}
          >
            <IconTrash className="h-4 w-4" />
          </Button>
        )}
      </div>
    </div>
  );
}
