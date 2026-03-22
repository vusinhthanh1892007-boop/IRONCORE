"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const items = [
  { label: "Overview", href: "/dashboard" },
  { label: "Usage", href: "/dashboard/usage" },
  { label: "Cron", href: "/dashboard/cron" },
  { label: "Nodes", href: "/dashboard/nodes" },
  { label: "Logs", href: "/dashboard/logs" },
  { label: "Config", href: "/dashboard/config" },
  { label: "Alerts", href: "/dashboard/alerts" },
];

export function ControlPlaneNav() {
  const pathname = usePathname();

  return (
    <div className="overflow-x-auto pb-1">
      <div className="flex min-w-max gap-2">
        {items.map((item) => {
          const active = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors",
                active
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-card text-muted-foreground hover:text-foreground"
              )}
            >
              {item.label}
            </Link>
          );
        })}
      </div>
    </div>
  );
}
