import { useAuthStore } from "@/stores/auth";
import { useLogout } from "@/hooks/useAuth";
import { ChangePasswordForm } from "@/components/auth/change-password-form";
import { Button } from "@/components/ui/button";

/**
 * Held in front of the application until a first password is replaced.
 *
 * An account created from the server starts with a password somebody else chose
 * and handed over. Until the person picks their own, the credential is known to
 * two people, and anything recorded against them is not really theirs. This is
 * the screen that closes that gap, and it is not skippable — only signing out
 * leads away from it.
 */
export function PasswordChangeGate() {
  const user = useAuthStore((state) => state.user);
  const logoutMutation = useLogout();

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-background p-4">
      <div className="pointer-events-none fixed inset-0">
        <div className="absolute top-0 left-0 h-full w-full bg-[radial-gradient(ellipse_80%_50%_at_20%_20%,rgba(131,19,235,0.15),transparent)]" />
        <div className="absolute top-0 left-0 h-full w-full bg-[radial-gradient(ellipse_60%_80%_at_80%_80%,rgba(249,2,251,0.12),transparent)]" />
      </div>

      <div className="relative z-10 w-full max-w-[440px]">
        <div className="mb-8 text-center">
          <img
            src="/dragoncp-logo.png"
            alt="DragonCP Logo"
            className="mb-4 inline-block h-14 w-14 object-contain drop-shadow-[0_8px_24px_rgba(166,14,239,0.45)]"
          />
          <h1 className="mb-1 text-2xl font-bold tracking-tight text-foreground">
            Choose your password
          </h1>
          <p className="text-sm leading-relaxed text-muted-foreground">
            {user ? (
              <>
                You are signed in as <span className="font-medium text-foreground">{user}</span>{" "}
                with a password someone else set up.
              </>
            ) : (
              <>You are signed in with a password someone else set up.</>
            )}{" "}
            Pick your own before carrying on.
          </p>
        </div>

        <div className="rounded-2xl border border-border bg-card p-6">
          <ChangePasswordForm forced />
        </div>

        <div className="mt-6 text-center">
          <Button
            variant="ghost"
            size="sm"
            className="text-xs text-muted-foreground hover:text-foreground"
            onClick={() => logoutMutation.mutate()}
            disabled={logoutMutation.isPending}
          >
            Sign out instead
          </Button>
        </div>
      </div>
    </div>
  );
}
