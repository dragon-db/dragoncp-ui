import { useState } from "react";
import { toast } from "sonner";
import { useChangePassword } from "@/hooks/useAuth";
import { useAuthStore } from "@/stores/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { IconAlertTriangle, IconKey, IconLoader2, IconLock } from "@tabler/icons-react";

/** Kept in step with the server's own rule, so the form fails fast and locally. */
const MIN_PASSWORD_LENGTH = 10;

interface ChangePasswordFormProps {
  /**
   * Rendered as a gate the person cannot walk past, because their password was
   * chosen for them by whoever created the account.
   */
  forced?: boolean;
  onChanged?: () => void;
}

export function ChangePasswordForm({ forced = false, onChanged }: ChangePasswordFormProps) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  const isFallbackAccount = useAuthStore((state) => state.isFallbackAccount);
  const changePassword = useChangePassword();

  // The fallback account's password lives in the server's environment file, so
  // there is nothing here to change. Say so rather than failing on submit.
  if (isFallbackAccount) {
    return (
      <div className="flex items-start gap-3 rounded-xl border border-amber-500/20 bg-amber-500/5 p-4">
        <IconAlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-500" />
        <div className="space-y-1">
          <p className="text-sm font-medium text-amber-200">
            This is the fallback sign-in
          </p>
          <p className="text-xs leading-relaxed text-amber-200/70">
            You are signed in with the credentials from the server's environment file,
            which are used only while no real accounts exist. There is no stored
            password to change here. Create proper accounts on the server, then sign in
            as one of those.
          </p>
        </div>
      </div>
    );
  }

  const tooShort = newPassword.length > 0 && newPassword.length < MIN_PASSWORD_LENGTH;
  const mismatch = confirmPassword.length > 0 && newPassword !== confirmPassword;
  const unchanged = newPassword.length > 0 && newPassword === currentPassword;

  const canSubmit =
    currentPassword.length > 0 &&
    newPassword.length >= MIN_PASSWORD_LENGTH &&
    newPassword === confirmPassword &&
    newPassword !== currentPassword &&
    !changePassword.isPending;

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSubmit) return;

    changePassword.mutate(
      { currentPassword, newPassword },
      {
        onSuccess: () => {
          setCurrentPassword("");
          setNewPassword("");
          setConfirmPassword("");
          toast.success("Password changed", {
            description: "Any other sessions for your account have been signed out.",
          });
          onChanged?.();
        },
      }
    );
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {changePassword.isError && (
        <div className="flex items-start gap-3 rounded-xl border border-red-500/20 bg-red-500/5 p-4">
          <IconAlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-red-400" />
          <div>
            <p className="text-sm font-medium text-red-300">Could not change your password</p>
            <p className="mt-0.5 text-xs text-red-400/80">
              {changePassword.error instanceof Error
                ? changePassword.error.message
                : "Please try again."}
            </p>
          </div>
        </div>
      )}

      <div className="space-y-2">
        <Label htmlFor="current-password" className="text-sm font-medium text-foreground/80">
          Current password
        </Label>
        <div className="relative">
          <div className="absolute top-1/2 left-3.5 -translate-y-1/2 text-muted-foreground">
            <IconLock className="h-4 w-4" />
          </div>
          <Input
            id="current-password"
            type="password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
            disabled={changePassword.isPending}
            autoComplete="current-password"
            className="h-11 rounded-xl bg-black/30 pl-10"
          />
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="new-password" className="text-sm font-medium text-foreground/80">
          New password
        </Label>
        <div className="relative">
          <div className="absolute top-1/2 left-3.5 -translate-y-1/2 text-muted-foreground">
            <IconKey className="h-4 w-4" />
          </div>
          <Input
            id="new-password"
            type="password"
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            disabled={changePassword.isPending}
            autoComplete="new-password"
            className="h-11 rounded-xl bg-black/30 pl-10"
          />
        </div>
        <p
          className={`text-xs ${tooShort || unchanged ? "text-red-400/90" : "text-muted-foreground"}`}
        >
          {unchanged
            ? "Choose something different from your current password."
            : `At least ${MIN_PASSWORD_LENGTH} characters.`}
        </p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="confirm-password" className="text-sm font-medium text-foreground/80">
          Repeat new password
        </Label>
        <div className="relative">
          <div className="absolute top-1/2 left-3.5 -translate-y-1/2 text-muted-foreground">
            <IconKey className="h-4 w-4" />
          </div>
          <Input
            id="confirm-password"
            type="password"
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
            disabled={changePassword.isPending}
            autoComplete="new-password"
            className="h-11 rounded-xl bg-black/30 pl-10"
          />
        </div>
        {mismatch && <p className="text-xs text-red-400/90">The two passwords do not match.</p>}
      </div>

      <div className="flex items-center gap-3 pt-1">
        <Button
          type="submit"
          disabled={!canSubmit}
          className={
            forced
              ? "h-11 w-full rounded-xl border-0 bg-gradient-to-r from-brand-deep to-brand-accent font-semibold text-white"
              : "rounded-xl"
          }
        >
          {changePassword.isPending ? (
            <>
              <IconLoader2 className="mr-2 h-4 w-4 animate-spin" />
              Saving...
            </>
          ) : (
            "Change password"
          )}
        </Button>
      </div>

      <p className="text-xs leading-relaxed text-muted-foreground">
        Changing your password signs out every other browser and live connection using
        this account. This one stays signed in.
      </p>
    </form>
  );
}
