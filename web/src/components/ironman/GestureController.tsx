"use client";

import * as React from "react";
import type { GestureKey, IronManSettings } from "@/lib/ironman-settings";

interface GestureControllerProps {
  enabled: boolean;
  cameraStream: MediaStream | null;
  settings: IronManSettings;
  onAction: (action: IronManSettings["gestureMap"][GestureKey], gesture: GestureKey) => void;
}

type HandLandmarks = Array<{ x: number; y: number; z?: number }>;

declare global {
  interface Window {
    Hands?: new (config: { locateFile: (file: string) => string }) => {
      setOptions: (opts: Record<string, unknown>) => void;
      onResults: (cb: (results: { multiHandLandmarks?: HandLandmarks[] }) => void) => void;
      send: (payload: { image: HTMLVideoElement }) => Promise<void>;
    };
  }
}

const labels: Record<GestureKey, string> = {
  thumbs_up: "👍 thumbs_up",
  fist: "✊ fist",
  open_hand: "🖐 open_hand",
  peace: "✌️ peace",
  point_up: "☝️ point_up",
};

const tips = { thumb: 4, index: 8, middle: 12, ring: 16, pinky: 20 };
const pips = { thumb: 3, index: 6, middle: 10, ring: 14, pinky: 18 };

function up(landmarks: HandLandmarks, tip: number, pip: number) {
  return landmarks[tip].y < landmarks[pip].y;
}

function detectGesture(landmarks: HandLandmarks, sensitivity: number): GestureKey | null {
  if (landmarks.length < 21) return null;

  const threshold = Math.max(0.45, Math.min(0.95, sensitivity));
  const thumbUp = up(landmarks, tips.thumb, pips.thumb);
  const indexUp = up(landmarks, tips.index, pips.index);
  const middleUp = up(landmarks, tips.middle, pips.middle);
  const ringUp = up(landmarks, tips.ring, pips.ring);
  const pinkyUp = up(landmarks, tips.pinky, pips.pinky);

  const foldedCount = [indexUp, middleUp, ringUp, pinkyUp].filter((v) => !v).length;
  const openCount = [thumbUp, indexUp, middleUp, ringUp, pinkyUp].filter(Boolean).length;

  const spread = Math.abs(landmarks[tips.index].x - landmarks[tips.pinky].x);
  const wideOpen = spread > (0.18 * threshold);

  if (thumbUp && !indexUp && !middleUp && !ringUp && !pinkyUp) return "thumbs_up";
  if (!thumbUp && !indexUp && !middleUp && !ringUp && !pinkyUp) return "fist";
  if (indexUp && middleUp && !ringUp && !pinkyUp) return "peace";
  if (indexUp && !middleUp && !ringUp && !pinkyUp) return "point_up";
  if (openCount >= 4 && wideOpen && foldedCount <= 1) return "open_hand";

  return null;
}

async function loadHandsScripts() {
  const sources = [
    "https://cdn.jsdelivr.net/npm/@mediapipe/hands/hands.js",
  ];

  for (const src of sources) {
    const exists = document.querySelector(`script[src=\"${src}\"]`);
    if (exists) continue;
    await new Promise<void>((resolve, reject) => {
      const script = document.createElement("script");
      script.src = src;
      script.async = true;
      script.onload = () => resolve();
      script.onerror = () => reject(new Error("load failed"));
      document.head.appendChild(script);
    });
  }
}

export function GestureController({ enabled, cameraStream, settings, onAction }: GestureControllerProps) {
  const [lastGesture, setLastGesture] = React.useState<GestureKey | null>(null);
  const [supported, setSupported] = React.useState(true);
  const [hudGlow, setHudGlow] = React.useState(false);
  const lastTriggerRef = React.useRef<number>(0);
  const rafRef = React.useRef<number | null>(null);
  const videoRef = React.useRef<HTMLVideoElement | null>(null);

  React.useEffect(() => {
    if (!enabled || !cameraStream) return;

    let mounted = true;
    let handsInstance: InstanceType<NonNullable<typeof window.Hands>> | null = null;

    const run = async () => {
      try {
        await loadHandsScripts();
        if (!window.Hands) {
          setSupported(false);
          return;
        }

        if (!videoRef.current) return;
        videoRef.current.srcObject = cameraStream;
        await videoRef.current.play().catch(() => null);

        handsInstance = new window.Hands({
          locateFile: (file) => `https://cdn.jsdelivr.net/npm/@mediapipe/hands/${file}`,
        });

        handsInstance.setOptions({
          maxNumHands: 1,
          modelComplexity: 0,
          minDetectionConfidence: 0.4 + settings.gestureSensitivity * 0.4,
          minTrackingConfidence: 0.4 + settings.gestureSensitivity * 0.4,
        });

        handsInstance.onResults((results) => {
          const landmarks = results.multiHandLandmarks?.[0];
          if (!landmarks) return;
          const gesture = detectGesture(landmarks, settings.gestureSensitivity);
          if (!gesture) return;

          setLastGesture(gesture);
          window.dispatchEvent(new CustomEvent("ironman:gesture-detected", { detail: gesture }));

          const now = Date.now();
          if (now - lastTriggerRef.current < 800) return;
          if (!settings.enabledGestures[gesture]) return;

          const action = settings.gestureMap[gesture];
          if (!action || action === "none") return;

          lastTriggerRef.current = now;
          setHudGlow(true);
          window.setTimeout(() => setHudGlow(false), 280);
          onAction(action, gesture);
        });

        const loop = async () => {
          if (!mounted || !handsInstance || !videoRef.current) return;
          await handsInstance.send({ image: videoRef.current }).catch(() => null);
          rafRef.current = window.requestAnimationFrame(loop);
        };

        rafRef.current = window.requestAnimationFrame(loop);
      } catch {
        setSupported(false);
      }
    };

    run();

    return () => {
      mounted = false;
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, [enabled, cameraStream, onAction, settings]);

  if (!enabled) return null;

  return (
    <>
      <video ref={videoRef} className="hidden" muted playsInline />
      <div className={`fixed left-4 bottom-28 z-40 rounded-lg border border-border bg-card/90 px-3 py-2 text-xs text-foreground shadow-sm backdrop-blur ${hudGlow ? "ring-2 ring-primary/60" : ""}`}>
        {supported ? (lastGesture ? labels[lastGesture] : "Gesture HUD: waiting...") : "Gesture not supported"}
      </div>
    </>
  );
}
