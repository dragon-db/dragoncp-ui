import { createFileRoute, redirect } from "@tanstack/react-router";
import { useAuthStore } from "@/stores/auth";
import { LoginForm } from "@/components/auth/login-form";

export const Route = createFileRoute("/login")({
  beforeLoad: () => {
    const { isAuthenticated } = useAuthStore.getState();
    if (isAuthenticated) {
      throw redirect({ to: "/dashboard" });
    }
  },
  component: LoginPage,
});

function LoginPage() {
  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-background p-4">
      {/* Full-page ambient gradient */}
      <div className="pointer-events-none fixed inset-0">
        <div className="absolute top-0 left-0 h-full w-full bg-[radial-gradient(ellipse_80%_50%_at_20%_20%,rgba(131,19,235,0.15),transparent)]" />
        <div className="absolute top-0 left-0 h-full w-full bg-[radial-gradient(ellipse_60%_80%_at_80%_80%,rgba(249,2,251,0.12),transparent)]" />
      </div>

      <div className="relative z-10 w-full max-w-[420px]">
        {/* Logo & Branding */}
        <div className="mb-10 text-center">
          <img
            src="/dragoncp-logo.png"
            alt="DragonCP Logo"
            className="mb-4 inline-block h-16 w-16 object-contain drop-shadow-[0_8px_24px_rgba(166,14,239,0.45)]"
          />
          <h1 className="mb-1 text-3xl font-bold tracking-tight text-foreground">
            Dragon
            <span className="text-brand-gradient">CP</span>
          </h1>
          <p className="text-sm text-muted-foreground">Secure Control Panel Access</p>
        </div>

        {/* Login Card */}
        <div className="rounded-2xl border border-border bg-card">
          <LoginForm />
        </div>

        {/* Footer */}
        <div className="mt-8 text-center">
          <p className="text-xs text-muted-foreground/70">
            &copy; 2025 DragonCP Systems &middot; All rights reserved
          </p>
        </div>
      </div>
    </div>
  );
}
