import { Card } from "@/components/ui/card";

interface TokenSavingsCardProps {
  cacheSaved: number;
  compressionSaved: number;
}

export function TokenSavingsCard({ cacheSaved, compressionSaved }: TokenSavingsCardProps) {
  const total = cacheSaved + compressionSaved;

  return (
    <Card className="border border-border bg-card p-5 text-card-foreground">
      <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
        Tokens Saved
      </div>
      <div className="mt-3 text-2xl font-semibold">{total.toLocaleString()}</div>
      <div className="mt-2 text-xs text-muted-foreground">
        Cache: {cacheSaved.toLocaleString()} · Compression: {compressionSaved.toLocaleString()}
      </div>
    </Card>
  );
}
