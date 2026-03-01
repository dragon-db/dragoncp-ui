import { createFileRoute, redirect } from '@tanstack/react-router';
import { useAuthStore } from '@/stores/auth';
import { LoginForm } from '@/components/auth/login-form';
import { IconShieldLock } from '@tabler/icons-react';

export const Route = createFileRoute('/login')({
  beforeLoad: () => {
    const { isAuthenticated } = useAuthStore.getState();
    if (isAuthenticated) {
      throw redirect({ to: '/dashboard' });
    }
  },
  component: LoginPage,
});

function LoginPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-[#0a0a0a] p-4 relative overflow-hidden">
      {/* Full-page ambient gradient */}
      <div className="fixed inset-0 pointer-events-none">
        <div className="absolute top-0 left-0 w-full h-full bg-[radial-gradient(ellipse_80%_50%_at_20%_20%,rgba(106,0,253,0.15),transparent)]" />
        <div className="absolute top-0 left-0 w-full h-full bg-[radial-gradient(ellipse_60%_80%_at_80%_80%,rgba(254,0,252,0.12),transparent)]" />
      </div>

      <div className="w-full max-w-[420px] relative z-10">
        {/* Logo & Branding */}
        <div className="mb-10 text-center">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-gradient-to-br from-[#6a00fd] to-[#fe00fc] mb-4 shadow-lg shadow-purple-500/25">
            <IconShieldLock className="w-7 h-7 text-white" />
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white mb-1">
            Dragon<span className="text-transparent bg-clip-text bg-gradient-to-r from-[#6a00fd] to-[#fe00fc]">CP</span>
          </h1>
          <p className="text-sm text-neutral-500">Secure Control Panel Access</p>
        </div>

        {/* Login Card */}
        <div className="bg-[#111111] rounded-2xl border border-white/5">
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
