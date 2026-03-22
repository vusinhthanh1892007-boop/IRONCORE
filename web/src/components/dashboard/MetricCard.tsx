import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { Icon as PhosphorIcon } from "@phosphor-icons/react";

interface MetricCardProps {
  title: string;
  value: string | number;
  unit?: string;
  trend?: number;
  trendLabel?: string;
  icon: PhosphorIcon;
  loading?: boolean;
}

export function MetricCard({
  title,
  value,
  unit,
  trend,
  trendLabel,
  icon: Icon,
  loading,
}: MetricCardProps) {
  return (
    <Card className="border border-border bg-card p-5 text-card-foreground">
      <div className="flex items-center justify-between">
        <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
          {title}
        </div>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </div>
      <div className="mt-3 flex items-end gap-2">
        <div className="text-2xl font-semibold">
          {loading ? "--" : value}
        </div>
        {unit ? <div className="text-xs text-muted-foreground">{unit}</div> : null}
      </div>
      <div className="mt-2 text-xs text-muted-foreground">
        {trend !== undefined ? (
          <span
            className={cn(
              "font-medium",
              trend >= 0 ? "text-emerald-500" : "text-red-500"
            )}
          >
            {trend >= 0 ? "+" : ""}
            {trend}%
          </span>
        ) : null}
        {trendLabel ? <span className="ml-2">{trendLabel}</span> : null}
      </div>
    </Card>
  );
}
