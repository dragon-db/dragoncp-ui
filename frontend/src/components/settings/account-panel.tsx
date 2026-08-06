import { useAuthStore } from "@/stores/auth";
import { ChangePasswordForm } from "@/components/auth/change-password-form";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { IconInfoCircle, IconUserShield } from "@tabler/icons-react";

/**
 * The signed-in person's own account.
 *
 * Everything here is about yourself. Adding, renaming, disabling or resetting an
 * administrator happens on the server, and this panel says so plainly rather
 * than leaving people hunting for a button that does not exist.
 */
export function AccountPanel() {
  const user = useAuthStore((state) => state.user);
  const accountId = useAuthStore((state) => state.accountId);
  const isFallbackAccount = useAuthStore((state) => state.isFallbackAccount);

  return (
    <>
      <Card className="border-neutral-800 bg-neutral-900/50">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-white">
            <IconUserShield className="h-5 w-5 text-brand-accent" />
            Signed in as
          </CardTitle>
          <CardDescription className="text-neutral-400">
            Who this browser is acting as
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-brand-gradient font-display text-base font-semibold text-white">
              {user?.charAt(0).toUpperCase() || "U"}
            </div>
            <div className="min-w-0">
              <div className="truncate text-base font-semibold text-white">{user || "Unknown"}</div>
              <div className="text-xs text-neutral-400">
                {isFallbackAccount
                  ? "Fallback sign-in from the server's environment file"
                  : accountId != null
                    ? `Administrator · account #${accountId}`
                    : "Administrator"}
              </div>
            </div>
            {isFallbackAccount && (
              <Badge variant="outline" className="border-amber-500/40 text-amber-300">
                Fallback
              </Badge>
            )}
          </div>
        </CardContent>
      </Card>

      <Card className="border-neutral-800 bg-neutral-900/50">
        <CardHeader>
          <CardTitle className="text-white">Change your password</CardTitle>
          <CardDescription className="text-neutral-400">
            You can only change your own. Nobody can change it for you from here.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ChangePasswordForm />
        </CardContent>
      </Card>

      <Card className="border-neutral-800 bg-neutral-900/50">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-white">
            <IconInfoCircle className="h-5 w-5 text-neutral-400" />
            Managing administrators
          </CardTitle>
          <CardDescription className="text-neutral-400">
            Adding and removing people is done on the server
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm leading-relaxed text-neutral-300">
          <p>
            There is no screen for creating administrators, on purpose: being able to reach the
            server is the permission, and that is a stronger boundary than one this page could
            enforce. Someone with access to the machine runs these from the project directory:
          </p>
          <pre className="overflow-x-auto rounded-lg border border-neutral-800 bg-black/40 p-3 font-mono text-xs text-neutral-300">
            {`venv/bin/python scripts/manage_admins.py list
venv/bin/python scripts/manage_admins.py add <username>
venv/bin/python scripts/manage_admins.py rename <old> <new>
venv/bin/python scripts/manage_admins.py reset <username>
venv/bin/python scripts/manage_admins.py disable <username>`}
          </pre>
          <p className="text-neutral-400">
            Changes apply straight away — no restart. Accounts are never deleted, because the record
            of what they did points back at them; a departing administrator is disabled instead,
            which signs them out immediately and keeps their history readable.
          </p>
        </CardContent>
      </Card>
    </>
  );
}
