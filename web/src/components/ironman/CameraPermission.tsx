"use client";

import * as React from "react";
import { Button } from "@/components/ui/button";

interface CameraPermissionProps {
  enabled: boolean;
  onEnabledChange: (next: boolean) => void;
  onStreamChange?: (stream: MediaStream | null) => void;
}

export function CameraPermission({ enabled, onEnabledChange, onStreamChange }: CameraPermissionProps) {
  const [supported, setSupported] = React.useState(true);
  const [permissionState, setPermissionState] = React.useState<"granted" | "denied" | "prompt" | "unknown">("unknown");
  const [error, setError] = React.useState<string>("");
  const videoRef = React.useRef<HTMLVideoElement | null>(null);
  const streamRef = React.useRef<MediaStream | null>(null);

  const stopStream = React.useCallback(() => {
    const stream = streamRef.current;
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      if (onStreamChange) onStreamChange(null);
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
  }, [onStreamChange]);

  React.useEffect(() => {
    setSupported(typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia);
  }, []);

  React.useEffect(() => {
    let mounted = true;
    if (typeof navigator === "undefined") return;
    if (!("permissions" in navigator)) return;

    const updatePermission = async () => {
      try {
        const status = await navigator.permissions.query({ name: "camera" as PermissionName });
        if (!mounted) return;
        const state = status.state as "granted" | "denied" | "prompt";
        setPermissionState(state);
        status.onchange = () => {
          setPermissionState(status.state as "granted" | "denied" | "prompt");
        };
      } catch {
        if (mounted) setPermissionState("unknown");
      }
    };

    void updatePermission();
    return () => {
      mounted = false;
    };
  }, []);

  React.useEffect(() => {
    if (!enabled) {
      stopStream();
      return;
    }

    if (!supported) {
      setError("Camera is not supported in this browser.");
      return;
    }

    let mounted = true;

    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: "user" }, audio: false })
      .then((stream) => {
        if (!mounted) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
        }
        if (onStreamChange) onStreamChange(stream);
        setError("");
      })
      .catch((err: unknown) => {
        const errorName = err instanceof DOMException ? err.name : "UnknownError";
        if (errorName === "NotAllowedError") {
          setError("Camera permission denied. Click the lock icon near the URL and allow Camera, then Retry camera.");
        } else if (errorName === "NotFoundError") {
          setError("No camera device found.");
        } else if (errorName === "NotReadableError") {
          setError("Camera is busy in another app. Close that app and Retry camera.");
        } else if (errorName === "SecurityError") {
          setError("Camera is blocked by browser security policy.");
        } else {
          setError("Cannot access camera. Check browser permissions and Retry camera.");
        }
        onEnabledChange(false);
      });

    return () => {
      mounted = false;
      stopStream();
    };
  }, [enabled, supported, stopStream, onEnabledChange, onStreamChange]);

  return (
    <div className="space-y-2">
      {!supported ? (
        <div className="rounded-md border border-yellow-500/30 bg-yellow-500/10 px-2 py-1 text-[11px] text-yellow-600">
          Camera feature works best on modern Chrome/Edge.
        </div>
      ) : null}

      {supported && permissionState === "denied" ? (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[11px] text-amber-600">
          Camera access is currently blocked by browser permission.
        </div>
      ) : null}

      {error ? (
        <div className="rounded-md border border-red-500/30 bg-red-500/10 px-2 py-1 text-[11px] text-red-500">
          {error}
        </div>
      ) : null}

      {enabled ? (
        <div className="overflow-hidden rounded-lg border border-border bg-black">
          <video ref={videoRef} autoPlay muted playsInline className="h-28 w-full object-cover" />
        </div>
      ) : (
        <div className="space-y-2">
          <Button size="sm" variant="outline" className="w-full text-xs" onClick={() => onEnabledChange(true)}>
            Enable camera preview
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="w-full text-xs"
            onClick={() => {
              setError("");
              onEnabledChange(true);
            }}
          >
            Retry camera
          </Button>
        </div>
      )}
    </div>
  );
}
