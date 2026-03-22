"use client";

import * as React from "react";
import { Camera, HandPalm, Microphone, Keyboard, Sparkle } from "@phosphor-icons/react";
import { CameraPermission } from "@/components/ironman/CameraPermission";
import { GestureController } from "@/components/ironman/GestureController";
import {
  getIronManSettings,
  saveIronManSettings,
  IRONMAN_SETTINGS_EVENT,
  type IronManSettings,
  type GestureKey,
} from "@/lib/ironman-settings";

interface IronManPanelProps {
  onGestureAction: (action: IronManSettings["gestureMap"][GestureKey], gesture: GestureKey) => void;
}

export function IronManPanel({ onGestureAction }: IronManPanelProps) {
  const [settings, setSettings] = React.useState<IronManSettings>(() => getIronManSettings());
  const [cameraStream, setCameraStream] = React.useState<MediaStream | null>(null);
  const [gestureFlash, setGestureFlash] = React.useState(false);

  React.useEffect(() => {
    const handler = (event: Event) => {
      const custom = event as CustomEvent<IronManSettings>;
      if (custom.detail) setSettings(custom.detail);
    };

    window.addEventListener(IRONMAN_SETTINGS_EVENT, handler as EventListener);
    return () => window.removeEventListener(IRONMAN_SETTINGS_EVENT, handler as EventListener);
  }, []);

  const patchSettings = (patch: Partial<IronManSettings>) => {
    const next = { ...settings, ...patch };
    setSettings(next);
    saveIronManSettings(next);
  };

  const onAction = (action: IronManSettings["gestureMap"][GestureKey], gesture: GestureKey) => {
    setGestureFlash(true);
    window.setTimeout(() => setGestureFlash(false), 220);
    onGestureAction(action, gesture);
  };

  return (
    <>
      <div className={`fixed right-4 bottom-24 z-40 w-56 rounded-xl border border-border bg-card/90 p-3 shadow-lg backdrop-blur ${gestureFlash ? "ring-2 ring-primary/70" : ""}`}>
        <div className="mb-2 flex items-center justify-between">
          <div className="text-xs font-semibold tracking-wide">Iron Man</div>
          <Sparkle className="h-3.5 w-3.5 text-primary" />
        </div>

        <div className="space-y-2 text-xs">
          <button
            type="button"
            onClick={() => patchSettings({ cameraEnabled: !settings.cameraEnabled })}
            className="flex w-full items-center justify-between rounded-md border border-border px-2 py-1.5"
          >
            <span className="inline-flex items-center gap-2"><Camera className="h-3.5 w-3.5" /> Camera</span>
            <span>{settings.cameraEnabled ? "ON" : "OFF"}</span>
          </button>

          <button
            type="button"
            onClick={() => patchSettings({ gestureEnabled: !settings.gestureEnabled })}
            className="flex w-full items-center justify-between rounded-md border border-border px-2 py-1.5"
          >
            <span className="inline-flex items-center gap-2"><HandPalm className="h-3.5 w-3.5" /> Gesture</span>
            <span>{settings.gestureEnabled ? "ON" : "OFF"}</span>
          </button>

          <button
            type="button"
            onClick={() => patchSettings({ voiceEnabled: !settings.voiceEnabled })}
            className="flex w-full items-center justify-between rounded-md border border-border px-2 py-1.5"
          >
            <span className="inline-flex items-center gap-2"><Microphone className="h-3.5 w-3.5" /> Voice</span>
            <span>{settings.voiceEnabled ? "ON" : "OFF"}</span>
          </button>
        </div>

        <div className="mt-2 rounded-md border border-border bg-muted/40 px-2 py-1.5 text-[11px] text-muted-foreground">
          <div className="inline-flex items-center gap-1"><Keyboard className="h-3 w-3" /> Keyboard fallback</div>
          <div className="mt-1">Ctrl+Shift+1..5 → gesture actions</div>
        </div>

        <div className="mt-2">
          <CameraPermission
            enabled={settings.cameraEnabled}
            onEnabledChange={(next) => patchSettings({ cameraEnabled: next })}
            onStreamChange={setCameraStream}
          />
        </div>
      </div>

      <GestureController
        enabled={settings.cameraEnabled && settings.gestureEnabled}
        cameraStream={cameraStream}
        settings={settings}
        onAction={onAction}
      />
    </>
  );
}
