import { useEffect, useRef } from "react";
import {
  LIQUID_INTENSITY,
  LIQUID_MAX_DPR,
  LIQUID_SPEED,
  LIQUID_STILL_TIME,
  REDUCED_MOTION_QUERY,
} from "@/config";
import { drawLiquid, readPalette } from "@/lib/liquid";

/** Lo sfondo animato della vista iniziale (canvas 2D). Sempre secondario: con `prefers-reduced-motion`
 * resta un solo fotogramma fermo. */
export function LiquidBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const palette = readPalette(getComputedStyle(document.documentElement));
    if (!palette) return;
    const reduced = window.matchMedia(REDUCED_MOTION_QUERY).matches;
    const start = performance.now();
    let frame = 0;

    const paint = (now: number) => {
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      if (width > 0 && height > 0) {
        const dpr = Math.min(window.devicePixelRatio || 1, LIQUID_MAX_DPR);
        const pixelWidth = Math.round(width * dpr);
        const pixelHeight = Math.round(height * dpr);
        if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
          canvas.width = pixelWidth;
          canvas.height = pixelHeight;
        }
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        const t = reduced ? LIQUID_STILL_TIME : ((now - start) / 1000) * LIQUID_SPEED;
        drawLiquid(ctx, width, height, t, LIQUID_INTENSITY, palette);
      }
      if (!reduced) frame = requestAnimationFrame(paint);
    };

    frame = requestAnimationFrame(paint);
    let observer: ResizeObserver | undefined;
    if (reduced && typeof ResizeObserver !== "undefined") {
      observer = new ResizeObserver(() => paint(performance.now()));
      observer.observe(canvas);
    }
    return () => {
      cancelAnimationFrame(frame);
      observer?.disconnect();
    };
  }, []);

  return <canvas ref={canvasRef} className="block size-full" />;
}
