import { IconShieldLock, IconUserShield } from "@tabler/icons-react";
import { useAuthStore } from "@/stores/auth";
import { ChangePasswordForm } from "@/components/auth/change-password-form";
import { SectionCard } from "@/components/layout/section-card";
import { EnvNote, EnvValue, SettingList, SettingRow, ToneIcon } from "./settings-bits";
import { useSettingMap } from "./settings-model";

/**
 * The signed-in person's own account, and how signing in is guarded.
 *
 * Everything you can change here is about yourself. Adding, renaming,
 * disabling or resetting an administrator happens on the server, and the tab
 * says so plainly rather than leaving people hunting for a button that does
 * not exist.
 */
export function AccountTab() {
  const user = useAuthStore((state) => state.user);
  const accountId = useAuthStore((state) => state.accountId);
  const isFallbackAccount = useAuthStore((state) => state.isFallbackAccount);
  const { map } = useSettingMap();
  const hours = map.get("JWT_EXPIRY_HOURS")?.value;

  return (
    <div className="space-y-4">
      <SectionCard label="Signed in as">
        <div className="flex items-center gap-3 px-4 py-4">
          {/* An initial, not a picture: there are no profile photos in this app. */}
          <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-brand-gradient font-display text-base font-semibold text-white">
            {user?.charAt(0).toUpperCase() || "?"}
          </div>
          <div className="min-w-0">
            <div className="truncate font-display text-[15px] font-semibold text-foreground">
              {user || "Unknown"}
            </div>
            <div className="text-[12.5px] text-muted-foreground">
              {isFallbackAccount
                ? "Fallback sign-in from the server's environment file"
                : accountId != null
                  ? `Administrator, account #${accountId}`
                  : "Administrator"}
            </div>
          </div>
        </div>
      </SectionCard>

      <SectionCard
        label="Password"
        description="You can change your own password. Nobody can change it for you from here."
        contentClassName="px-4 py-4"
      >
        <div className="max-w-md">
          <ChangePasswordForm />
        </div>
      </SectionCard>

      <SectionCard
        label="Administrators"
        description="Adding and removing people is done on the server, on purpose: being able to reach the server is the permission."
        contentClassName="space-y-3 px-4 py-4 text-[13px] text-muted-foreground"
      >
        <div className="flex items-start gap-3">
          <ToneIcon icon={IconUserShield} tone="muted" />
          <p className="max-w-prose text-pretty">
            Someone with access to the machine runs these from the project folder. Changes apply at
            once, no restart. Accounts are never deleted, because the activity log points back at
            them; a departing administrator is disabled instead, which signs them out at once and
            keeps their history readable.
          </p>
        </div>
        <pre className="overflow-x-auto rounded-lg border border-border bg-black/30 p-3 font-mono text-xs text-foreground/85">
          {`venv/bin/python scripts/manage_admins.py list
venv/bin/python scripts/manage_admins.py add <username>
venv/bin/python scripts/manage_admins.py rename <old> <new>
venv/bin/python scripts/manage_admins.py reset <username>
venv/bin/python scripts/manage_admins.py disable <username>`}
        </pre>
      </SectionCard>

      <SectionCard
        label="Sign-in and access"
        description="How long a sign-in lasts, and who else may talk to DragonCP."
      >
        <SettingList>
          <SettingRow
            label="Sign-in lasts"
            description="How long a login stays valid before it has to be refreshed."
            icon={<ToneIcon icon={IconShieldLock} tone="muted" />}
          >
            <EnvValue value={hours !== undefined && hours !== "" ? `${hours} hours` : ""} />
          </SettingRow>
          <SettingRow
            label="Fallback username"
            description="Used only while no administrator account exists."
          >
            <EnvValue value={map.get("DRAGONCP_USERNAME")?.value} />
          </SettingRow>
          <SettingRow
            stack
            label="Webhook senders"
            description="Webhooks are the one part of DragonCP meant to face the internet. One from these addresses is accepted, as is one signed with the webhook secret. With neither set, every webhook is accepted."
          >
            <EnvValue value={map.get("WEBHOOK_ALLOWED_IPS")?.value} />
          </SettingRow>
          <SettingRow
            stack
            label="Allowed origins"
            description="Which web addresses may call the API from a browser. Read once at start-up."
          >
            <EnvValue value={map.get("CORS_ORIGINS")?.value} />
          </SettingRow>
        </SettingList>
        <EnvNote />
      </SectionCard>
    </div>
  );
}
