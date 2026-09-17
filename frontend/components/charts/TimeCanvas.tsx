"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useCurrentTime, usePlayer, useTimelineView } from "@/hooks/usePlayer";
import { formatTime } from "@/lib/format";

export interface DrawContext {
  ctx: CanvasRenderingContext2D;
  width: number;
  height: number;
  plotLeft: number;
  plotRight: number;
  plotTop: number;
  plotBottom: number;
  t0: number;
  t1: number;
  x: (t: number) => number;
}

interface Props {
  height: number;
  ariaLabel: string;
  draw: (dc: DrawContext) => void;
  /** Returns tooltip rows for a hovered time/y, or null. */
  tooltip?: (t: number, y: number, dc: DrawContext) => React.ReactNode | null;
  padding?: { left: number; right: number; top: number; bottom: number };
  deps: unknown[];
}

/** Canvas bound to the shared timeline view; hover tooltip, click-to-seek and a live playhead. */
export function TimeCanvas({ height, ariaLabel, draw, tooltip, padding = { left: 44, right: 8, top: 8, bottom: 22 }, deps }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const dcRef = useRef<DrawContext | null>(null);
  const [width, setWidth] = useState(0);
  const [hover, setHover] = useState<{ px: number; py: number; t: number; tip: React.ReactNode | null } | null>(null);
  const view = useTimelineView(200);
  const { seek } = usePlayer();

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || width === 0) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const plotLeft = padding.left;
    const plotRight = width - padding.right;
    const t0 = view.start;
    const t1 = Math.max(view.end, t0 + 0.01);
    const dc: DrawContext = {
      ctx, width, height, plotLeft, plotRight, plotTop: padding.top, plotBottom: height - padding.bottom, t0, t1,
      x: (t) => plotLeft + ((t - t0) / (t1 - t0)) * (plotRight - plotLeft),
    };
    dcRef.current = dc;
    // time axis
    ctx.fillStyle = "#8a8993";
    ctx.font = "10px ui-monospace, SFMono-Regular, Menlo, monospace";
    ctx.textAlign = "center";
    const span = t1 - t0;
    const step = [1, 2, 5, 10, 15, 30, 60, 120, 300].find((s) => span / s <= Math.max(3, (plotRight - plotLeft) / 90)) ?? 600;
    for (let t = Math.ceil(t0 / step) * step; t <= t1; t += step) {
      ctx.fillText(formatTime(t), dc.x(t), height - 6);
    }
    ctx.save();
    ctx.beginPath();
    ctx.rect(plotLeft, 0, plotRight - plotLeft, height);
    ctx.clip();
    draw(dc);
    ctx.restore();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [width, height, view.start, view.end, ...deps]);

  const toTime = useCallback(
    (clientX: number) => {
      const dc = dcRef.current;
      const el = wrapRef.current;
      if (!dc || !el) return null;
      const px = clientX - el.getBoundingClientRect().left;
      if (px < dc.plotLeft || px > dc.plotRight) return null;
      return { px, t: dc.t0 + ((px - dc.plotLeft) / (dc.plotRight - dc.plotLeft)) * (dc.t1 - dc.t0) };
    },
    [],
  );

  return (
    <div
      ref={wrapRef}
      className="relative w-full cursor-crosshair select-none"
      style={{ height }}
      onMouseMove={(e) => {
        const r = toTime(e.clientX);
        const el = wrapRef.current;
        if (!r || !el) return setHover(null);
        const py = e.clientY - el.getBoundingClientRect().top;
        setHover({ px: r.px, py, t: r.t, tip: tooltip && dcRef.current ? tooltip(r.t, py, dcRef.current) : null });
      }}
      onMouseLeave={() => setHover(null)}
      onClick={(e) => {
        const r = toTime(e.clientX);
        if (r) seek(r.t);
      }}
    >
      <canvas ref={canvasRef} role="img" aria-label={ariaLabel} style={{ width: "100%", height }} />
      <Playhead padding={padding} t0={view.start} t1={view.end} width={width} height={height} />
      {hover && (
        <>
          <div className="pointer-events-none absolute top-0 w-px bg-ink/40" style={{ left: hover.px, height: height - padding.bottom }} />
          {hover.tip && (
            <div
              className="pointer-events-none absolute z-20 min-w-32 rounded-lg border border-line-strong bg-bg-elev/95 px-2.5 py-2 text-xs shadow-xl"
              style={{
                left: Math.min(hover.px + 12, width - 170),
                top: Math.max(0, Math.min(hover.py - 10, height - 80)),
              }}
            >
              <div className="mb-1 font-mono text-[11px] text-ink-3">{formatTime(hover.t, true)}</div>
              {hover.tip}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Playhead({ padding, t0, t1, width, height }: { padding: Props["padding"] & object; t0: number; t1: number; width: number; height: number }) {
  const t = useCurrentTime();
  if (width === 0 || t < t0 || t > t1) return null;
  const left = padding.left + ((t - t0) / Math.max(0.01, t1 - t0)) * (width - padding.left - padding.right);
  return <div className="pointer-events-none absolute top-0 w-[2px] rounded bg-ink" style={{ left: left - 1, height: height - padding.bottom }} aria-hidden />;
}

export function TooltipRow({ color, label, value }: { color?: string; label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 py-0.5">
      <span className="flex items-center gap-1.5 text-ink-2">
        {color && <span className="size-2 rounded-full" style={{ background: color }} aria-hidden />}
        {label}
      </span>
      <span className="font-medium text-ink tabular">{value}</span>
    </div>
  );
}
