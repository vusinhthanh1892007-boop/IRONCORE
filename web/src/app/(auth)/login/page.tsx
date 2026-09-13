"use client";

import * as React from "react";
import { signIn } from "next-auth/react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";

export default function LoginPage() {
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [showPassword, setShowPassword] = React.useState(false);
  const [remember, setRemember] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setLoading(true);

    const res = await signIn("credentials", {
      redirect: false,
      email,
      password,
      remember: remember ? "true" : "false",
      callbackUrl: "/chat",
    });

    if (res?.error) {
      setError("Invalid credentials or server error.");
      setLoading(false);
    } else if (res?.ok) {
      window.location.href = res.url ?? "/chat";
    }
    setLoading(false);
  };

  return (
    <div className="w-full rounded-2xl border border-zinc-200 bg-white p-8 shadow-sm">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-zinc-900 text-sm font-semibold text-white">
          IC
        </div>
        <div>
          <div className="text-lg font-semibold">IronCore</div>
          <div className="text-xs text-zinc-500">Secure operator console</div>
        </div>
      </div>

      <h1 className="mt-6 text-2xl font-semibold">Sign in</h1>
      <p className="mt-1 text-sm text-zinc-500">
        Access your IronCore workspace.
      </p>

      <form onSubmit={handleSubmit} className="mt-6 space-y-4">
        <div className="space-y-1">
          <label className="text-xs font-medium text-zinc-600">Email</label>
          <Input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="you@company.com"
            autoComplete="email"
            required
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs font-medium text-zinc-600">Password</label>
          <div className="relative">
            <Input
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              required
            />
            <button
              type="button"
              onClick={() => setShowPassword((value) => !value)}
              className="absolute right-3 top-2.5 text-xs text-zinc-500"
            >
              {showPassword ? "Hide" : "Show"}
            </button>
          </div>
        </div>

        <div className="flex items-center justify-between text-xs text-zinc-500">
          <label className="flex items-center gap-2">
            <Checkbox checked={remember} onCheckedChange={(v) => setRemember(Boolean(v))} />
            Remember me
          </label>
          <Link href="/register" className="text-zinc-700">
            Create account
          </Link>
        </div>

        {error ? (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">
            {error}
          </div>
        ) : null}

        <Button type="submit" className="w-full" disabled={loading}>
          {loading ? "Signing in..." : "Sign in"}
        </Button>
      </form>

      <div className="mt-4 text-xs text-zinc-500">
        Need an API key? Configure it in Settings after signing in.
      </div>
    </div>
  );
}
