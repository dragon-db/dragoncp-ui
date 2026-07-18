import { createFileRoute, redirect } from "@tanstack/react-router";
import { useAuthStore } from "@/stores/auth";
import { LoginForm } from "@/components/auth/login-form";
import { IconShieldLock } from "@tabler/icons-react";

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
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[#0a0a0a] p-4">
      {/* Full-page ambient gradient */}
      <div className="pointer-events-none fixed inset-0">
        <div className="absolute top-0 left-0 h-full w-full bg-[radial-gradient(ellipse_80%_50%_at_20%_20%,rgba(106,0,253,0.15),transparent)]" />
        <div className="absolute top-0 left-0 h-full w-full bg-[radial-gradient(ellipse_60%_80%_at_80%_80%,rgba(254,0,252,0.12),transparent)]" />
      </div>

      <div className="relative z-10 w-full max-w-[420px]">
        {/* Logo & Branding */}
        <div className="mb-10 text-center">
          <div className="mb-4 inline-flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-[#6a00fd] to-[#fe00fc] shadow-lg shadow-purple-500/25">
            <IconShieldLock className="h-7 w-7 text-white" />
          </div>
          <h1 className="mb-1 text-3xl font-bold tracking-tight text-white">
            Dragon
            <span className="bg-gradient-to-r from-[#6a00fd] to-[#fe00fc] bg-clip-text text-transparent">
              CP
            </span>
          </h1>
          <p className="text-sm text-neutral-500">Secure Control Panel Access</p>
        </div>

        {/* Login Card */}
        <div className="rounded-2xl border border-white/5 bg-[#111111]">
          <LoginForm />
        </div>

        {/* Footer */}
        <div className="mt-8 text-center">
          <p className="text-xs text-neutral-600">
            &copy; 2025 DragonCP Systems &middot; All rights reserved
          </p>
        </div>
      </div>
    </div>
  );
}
