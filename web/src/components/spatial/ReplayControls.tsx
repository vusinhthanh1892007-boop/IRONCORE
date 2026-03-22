"use client";

import * as React from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";

interface ReplayControlsProps {
  paused: boolean;
  speed: number;
  cursor: number;
  maxCursor: number;
  onPausedChange: (paused: boolean) => void;
  onSpeedChange: (speed: number) => void;
  onCursorChange: (cursor: number) => void;
  onLoadSession: (sessionId: string) => void;
  onExportSnapshot: () => void;
}

const SPEEDS = [0.5, 1, 2, 4] as const;

export function ReplayControls({
  paused,
  speed,
  cursor,
  maxCursor,
  onPausedChange,
  onSpeedChange,
  onCursorChange,
  onLoadSession,
  onExportSnapshot,
}: ReplayControlsProps) {
  const [sessionId, setSessionId] = React.useState("");

  return (
    <Card className="border border-border bg-card p-3">
      <div className="grid gap-3 md:grid-cols-[auto_auto_1fr_auto]">
        <Button variant="outline" onClick={() => onPausedChange(!paused)}>
          {paused ? "Play" : "Pause"}
        </Button>

        <div className="flex items-center gap-1">
          {SPEEDS.map((candidate) => (
            <Button
              key={candidate}
              size="sm"
              variant={candidate === speed ? "default" : "outline"}
              onClick={() => onSpeedChange(candidate)}
            >
              {candidate}x
            </Button>
          ))}
        </div>

        <input
          type="range"
          min={0}
          max={Math.max(0, maxCursor)}
          value={Math.min(cursor, Math.max(0, maxCursor))}
          onChange={(event) => onCursorChange(Number(event.target.value))}
          className="w-full"
        />

        <Button variant="outline" onClick={onExportSnapshot}>
          Export JSON
        </Button>
      </div>

      <div className="mt-3 grid gap-2 md:grid-cols-[1fr_auto]">
        <Input
          value={sessionId}
          onChange={(event) => setSessionId(event.target.value)}
          placeholder="Load session replay (session_id)"
        />
        <Button
          variant="outline"
          onClick={() => onLoadSession(sessionId.trim())}
          disabled={!sessionId.trim()}
        >
          Load Session
        </Button>
      </div>
    </Card>
  );
}
