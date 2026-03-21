import type { ReactNode } from "react";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-zinc-50 text-zinc-900">
      <div className="mx-auto flex min-h-screen w-full max-w-md items-center justify-center px-6">
        {children}
      </div>
    </div>
  );
}
