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
    if (!enabled) {
      stopStream();
      return;
    }

    if (!supported) {
      setError("Camera không được hỗ trợ trên browser này.");
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
      .catch(() => {
        setError("Không thể truy cập camera. Kiểm tra quyền trình duyệt.");
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
          Camera feature hỗ trợ tốt nhất trên Chrome/Edge mới.
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
        <Button size="sm" variant="outline" className="w-full text-xs" onClick={() => onEnabledChange(true)}>
          Enable camera preview
        </Button>
      )}
    </div>
  );
}
