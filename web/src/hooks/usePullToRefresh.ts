"use client";

import * as React from "react";

interface PullToRefreshOptions {
  onRefresh: () => void;
  enabled?: boolean;
  threshold?: number;
  getScrollElement?: () => HTMLElement | null;
}

export function usePullToRefresh({
  onRefresh,
  enabled = true,
  threshold = 80,
  getScrollElement,
}: PullToRefreshOptions) {
  const startY = React.useRef(0);
  const triggered = React.useRef(false);

  React.useEffect(() => {
    if (!enabled) return;

    const resolveScrollElement = () =>
      getScrollElement?.() ??
      (document.scrollingElement as HTMLElement | null) ??
      document.documentElement;

    const handleTouchStart = (event: TouchEvent) => {
      const scrollElement = resolveScrollElement();
      if (!scrollElement || scrollElement.scrollTop > 0) return;
      startY.current = event.touches[0]?.clientY ?? 0;
      triggered.current = false;
    };

    const handleTouchMove = (event: TouchEvent) => {
      const scrollElement = resolveScrollElement();
      if (!scrollElement || scrollElement.scrollTop > 0) return;
      const currentY = event.touches[0]?.clientY ?? 0;
      const delta = currentY - startY.current;
      if (delta > threshold && !triggered.current) {
        triggered.current = true;
        onRefresh();
      }
    };

    const handleTouchEnd = () => {
      triggered.current = false;
    };

    window.addEventListener("touchstart", handleTouchStart, { passive: true });
    window.addEventListener("touchmove", handleTouchMove, { passive: true });
    window.addEventListener("touchend", handleTouchEnd);

    return () => {
      window.removeEventListener("touchstart", handleTouchStart);
      window.removeEventListener("touchmove", handleTouchMove);
      window.removeEventListener("touchend", handleTouchEnd);
    };
  }, [enabled, getScrollElement, onRefresh, threshold]);
}
