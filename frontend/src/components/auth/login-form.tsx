import { useState } from 'react';
import { useLogin, useAuthStatus } from '@/hooks/useAuth';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { IconLoader2, IconAlertTriangle, IconLock, IconUser } from '@tabler/icons-react';

export function LoginForm() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');

  const loginMutation = useLogin();
  const { data: authStatus, isLoading: isCheckingAuth } = useAuthStatus();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (username && password) {
      loginMutation.mutate({ username, password });
    }
  };

  if (isCheckingAuth) {
    return (
      <div className="flex items-center justify-center p-12">
        <div className="relative">
          <div className="w-10 h-10 rounded-full border-2 border-transparent border-t-[#6a00fd] border-r-[#fe00fc] animate-spin" />
        </div>
      </div>
    );
  }

  if (authStatus && !authStatus.auth_configured) {
    return (
      <div className="p-8 text-center">
        <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-amber-500/10 mb-4">
          <IconAlertTriangle className="w-6 h-6 text-amber-500" />
        </div>
        <h3 className="text-lg font-semibold text-white mb-2">Configuration Required</h3>
        <p className="text-sm text-neutral-400 leading-relaxed">
          Set <code className="px-1.5 py-0.5 rounded bg-neutral-800 text-[#fe00fc] font-mono text-xs">DRAGONCP_PASSWORD</code> in your environment to enable authentication.
        </p>
      </div>
    );
  }

  return (
    <div className="p-8">
      <form onSubmit={handleSubmit} className="space-y-5">
        {loginMutation.isError && (
          <div className="p-4 rounded-xl bg-red-500/5 border border-red-500/20 flex items-start gap-3">
            <IconAlertTriangle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-red-300">Authentication Failed</p>
              <p className="text-xs text-red-400/80 mt-0.5">
                {loginMutation.error instanceof Error
                  ? loginMutation.error.message
                  : 'Please check your credentials and try again.'}
              </p>
            </div>
          </div>
        )}

        <div className="space-y-2">
          <Label htmlFor="username" className="text-neutral-300 text-sm font-medium">
            Username
          </Label>
          <div className="relative">
            <div className="absolute left-3.5 top-1/2 -translate-y-1/2 text-neutral-500">
              <IconUser className="w-4 h-4" />
            </div>
            <Input
              id="username"
              type="text"
              placeholder="Enter your username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={loginMutation.isPending}
              autoComplete="username"
              className="h-12 pl-10 bg-black/40 border-neutral-800 text-white placeholder:text-neutral-600 focus:border-[#6a00fd] focus:ring-2 focus:ring-[#6a00fd]/20 transition-all rounded-xl"
            />
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="password" className="text-neutral-300 text-sm font-medium">
            Password
          </Label>
          <div className="relative">
            <div className="absolute left-3.5 top-1/2 -translate-y-1/2 text-neutral-500">
              <IconLock className="w-4 h-4" />
            </div>
            <Input
              id="password"
              type="password"
              placeholder="Enter your password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={loginMutation.isPending}
              autoComplete="current-password"
              className="h-12 pl-10 bg-black/40 border-neutral-800 text-white placeholder:text-neutral-600 focus:border-[#6a00fd] focus:ring-2 focus:ring-[#6a00fd]/20 transition-all rounded-xl"
            />
          </div>
        </div>

        <div className="pt-2">
          <Button
            type="submit"
            className="w-full h-12 rounded-xl bg-gradient-to-r from-[#6a00fd] to-[#fe00fc] text-white font-semibold shadow-lg shadow-purple-500/20 hover:shadow-purple-500/30 hover:scale-[1.02] active:scale-[0.98] transition-all duration-200 border-0"
            disabled={loginMutation.isPending || !username || !password}
          >
            {loginMutation.isPending ? (
              <>
                <IconLoader2 className="mr-2 h-5 w-5 animate-spin" />
                Authenticating...
              </>
            ) : (
              'Sign In'
            )}
          </Button>
        </div>
      </form>
    </div>
  );
}
