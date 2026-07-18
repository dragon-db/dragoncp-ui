import { useState } from "react";
import { useLogin, useAuthStatus } from "@/hooks/useAuth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { IconLoader2, IconAlertTriangle, IconLock, IconUser } from "@tabler/icons-react";

export function LoginForm() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

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
          <div className="h-10 w-10 animate-spin rounded-full border-2 border-transparent border-t-[#6a00fd] border-r-[#fe00fc]" />
        </div>
      </div>
    );
  }

  if (authStatus && !authStatus.auth_configured) {
    return (
      <div className="p-8 text-center">
        <div className="mb-4 inline-flex h-12 w-12 items-center justify-center rounded-xl bg-amber-500/10">
          <IconAlertTriangle className="h-6 w-6 text-amber-500" />
        </div>
        <h3 className="mb-2 text-lg font-semibold text-white">Configuration Required</h3>
        <p className="text-sm leading-relaxed text-neutral-400">
          Set{" "}
          <code className="rounded bg-neutral-800 px-1.5 py-0.5 font-mono text-xs text-[#fe00fc]">
            DRAGONCP_PASSWORD
          </code>{" "}
          in your environment to enable authentication.
        </p>
      </div>
    );
  }

  return (
    <div className="p-8">
      <form onSubmit={handleSubmit} className="space-y-5">
        {loginMutation.isError && (
          <div className="flex items-start gap-3 rounded-xl border border-red-500/20 bg-red-500/5 p-4">
            <IconAlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-red-400" />
            <div>
              <p className="text-sm font-medium text-red-300">Authentication Failed</p>
              <p className="mt-0.5 text-xs text-red-400/80">
                {loginMutation.error instanceof Error
                  ? loginMutation.error.message
                  : "Please check your credentials and try again."}
              </p>
            </div>
          </div>
        )}

        <div className="space-y-2">
          <Label htmlFor="username" className="text-sm font-medium text-neutral-300">
            Username
          </Label>
          <div className="relative">
            <div className="absolute top-1/2 left-3.5 -translate-y-1/2 text-neutral-500">
              <IconUser className="h-4 w-4" />
            </div>
            <Input
              id="username"
              type="text"
              placeholder="Enter your username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={loginMutation.isPending}
              autoComplete="username"
              className="h-12 rounded-xl border-neutral-800 bg-black/40 pl-10 text-white transition-all placeholder:text-neutral-600 focus:border-[#6a00fd] focus:ring-2 focus:ring-[#6a00fd]/20"
            />
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="password" className="text-sm font-medium text-neutral-300">
            Password
          </Label>
          <div className="relative">
            <div className="absolute top-1/2 left-3.5 -translate-y-1/2 text-neutral-500">
              <IconLock className="h-4 w-4" />
            </div>
            <Input
              id="password"
              type="password"
              placeholder="Enter your password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={loginMutation.isPending}
              autoComplete="current-password"
              className="h-12 rounded-xl border-neutral-800 bg-black/40 pl-10 text-white transition-all placeholder:text-neutral-600 focus:border-[#6a00fd] focus:ring-2 focus:ring-[#6a00fd]/20"
            />
          </div>
        </div>

        <div className="pt-2">
          <Button
            type="submit"
            className="h-12 w-full rounded-xl border-0 bg-gradient-to-r from-[#6a00fd] to-[#fe00fc] font-semibold text-white shadow-lg shadow-purple-500/20 transition-all duration-200 hover:scale-[1.02] hover:shadow-purple-500/30 active:scale-[0.98]"
            disabled={loginMutation.isPending || !username || !password}
          >
            {loginMutation.isPending ? (
              <>
                <IconLoader2 className="mr-2 h-5 w-5 animate-spin" />
                Authenticating...
              </>
            ) : (
              "Sign In"
            )}
          </Button>
        </div>
      </form>
    </div>
  );
}
