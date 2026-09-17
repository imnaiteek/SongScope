"use client";

import { useEffect, useRef, useState } from "react";

import { useCurrentTime } from "@/hooks/usePlayer";
import { hz, hzToNote } from "@/lib/format";
import type { Spectrum } from "@/types/analysis";

import { TooltipRow } from "./TimeCanvas";

const LTAS = "#3987e5";
const LIVE = "#d95926";
const F_MIN = 20;
const F_MAX = 20000;
const DB_MIN = -90;
const PAD = { left: 40, right: 10, top: 10, bottom: 34 };

/** Long-term average spectrum plus the band spectrum at the playhead (updates during playback). */
export function SpectrumChart({ spectrum }: { spectrum: Spectrum }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(0);
  const [hover, setHover] = useState<{ px: number; py: number; f: number } | null>(null);
  const t = useCurrentTime(spectrum.spectrogram.seconds_per_frame);
  const height = 260;
  const { ltas, spectrogram: sg, bands } = spectrum;
  const frame = sg.db[Math.min(sg.db.length - 1, Math.max(0, Math.floor(t / sg.seconds_per_frame)))] ?? null;

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  const xOf = (f: number) => PAD.left + (Math.log10(f / F_MIN) / Math.log10(F_MAX / F_MIN)) * (width - PAD.left - PAD.right);
  const fOf = (px: number) => F_MIN * 10 ** (((px - PAD.left) / (width - PAD.left - PAD.right)) * Math.log10(F_MAX / F_MIN));
  const yOf = (db: number) => PAD.top + (Math.max(DB_MIN, db) / DB_MIN) * (height - PAD.top - PAD.bottom);

  useEffect(() => {
    const c = canvasRef.current;
    if (!c || width === 0) return;
    const dpr = window.devicePixelRatio || 1;
    c.width = width * dpr;
    c.height = height * dpr;
    const ctx = c.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const bottom = height - PAD.bottom;
    ctx.font = "10px ui-monospace, monospace";
    // band regions
    bands.forEach((b, i) => {
      const xa = xOf(Math.max(F_MIN, b.low_hz));
      const xb = xOf(Math.min(F_MAX, b.high_hz));
      ctx.fillStyle = i % 2 ? "rgba(255,255,255,0.018)" : "rgba(255,255,255,0.0)";
      ctx.fillRect(xa, PAD.top, xb - xa, bottom - PAD.top);
      ctx.strokeStyle = "#24242a";
      ctx.beginPath();
      ctx.moveTo(xa + 0.5, PAD.top);
      ctx.lineTo(xa + 0.5, bottom + 14);
      ctx.stroke();
      ctx.fillStyle = "#8a8993";
      ctx.textAlign = "center";
      if (xb - xa > 44) ctx.fillText(b.name, (xa + xb) / 2, height - 6);
    });
    // grid
    ctx.textAlign = "right";
    for (let db = 0; db >= DB_MIN; db -= 15) {
      ctx.strokeStyle = "#1c1c21";
      ctx.beginPath();
      ctx.moveTo(PAD.left, yOf(db) + 0.5);
      ctx.lineTo(width - PAD.right, yOf(db) + 0.5);
      ctx.stroke();
      ctx.fillStyle = "#8a8993";
      ctx.fillText(`${db}`, PAD.left - 6, yOf(db) + 3);
    }
    ctx.textAlign = "center";
    for (const f of [50, 100, 200, 500, 1000, 2000, 5000, 10000]) {
      ctx.fillStyle = "#6f6e78";
      ctx.fillText(f >= 1000 ? `${f / 1000}k` : `${f}`, xOf(f), bottom + 12);
    }
    // live band spectrum (area)
    if (frame) {
      ctx.beginPath();
      ctx.moveTo(xOf(sg.freqs[0]), bottom);
      sg.freqs.forEach((f, i) => ctx.lineTo(xOf(f), yOf(frame[i])));
      ctx.lineTo(xOf(sg.freqs[sg.freqs.length - 1]), bottom);
      ctx.closePath();
      ctx.fillStyle = "rgba(217, 89, 38, 0.18)";
      ctx.fill();
      ctx.strokeStyle = LIVE;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      sg.freqs.forEach((f, i) => (i ? ctx.lineTo(xOf(f), yOf(frame[i])) : ctx.moveTo(xOf(f), yOf(frame[i]))));
      ctx.stroke();
    }
    // LTAS
    ctx.strokeStyle = LTAS;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ltas.freqs.forEach((f, i) => (i ? ctx.lineTo(xOf(f), yOf(ltas.db[i])) : ctx.moveTo(xOf(f), yOf(ltas.db[i]))));
    ctx.stroke();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [width, spectrum, frame]);

  const hoverRows = (() => {
    if (!hover) return null;
    const nearest = (freqs: number[], f: number) =>
      freqs.reduce((best, x, i) => (Math.abs(Math.log(x / f)) < Math.abs(Math.log(freqs[best] / f)) ? i : best), 0);
    const li = nearest(ltas.freqs, hover.f);
    const si = nearest(sg.freqs, hover.f);
    const band = bands.find((b) => hover.f >= b.low_hz && hover.f < b.high_hz);
    return (
      <>
        <div className="mb-1 font-mono text-[11px] text-ink-3">
          {hz(hover.f)} · {hzToNote(hover.f)}
        </div>
        <TooltipRow color={LTAS} label="Track average" value={`${ltas.db[li].toFixed(1)} dB`} />
        {frame && <TooltipRow color={LIVE} label="At playhead" value={`${frame[si]} dB`} />}
        {band && <TooltipRow label="Band" value={band.name} />}
      </>
    );
  })();

  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-4 text-xs text-ink-2" aria-label="Legend">
        <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 rounded" style={{ background: LTAS }} />Whole-track average</span>
        <span className="flex items-center gap-1.5"><span className="h-2 w-4 rounded-sm" style={{ background: LIVE, opacity: 0.8 }} />At playhead (live)</span>
        <span className="text-ink-3">dB relative to peak · log frequency</span>
      </div>
      <div
        ref={wrapRef}
        className="relative w-full cursor-crosshair"
        style={{ height }}
        onMouseMove={(e) => {
          const r = wrapRef.current!.getBoundingClientRect();
          const px = e.clientX - r.left;
          if (px < PAD.left || px > width - PAD.right) return setHover(null);
          setHover({ px, py: e.clientY - r.top, f: fOf(px) });
        }}
        onMouseLeave={() => setHover(null)}
      >
        <canvas ref={canvasRef} role="img" aria-label="Frequency spectrum: long-term average and the spectrum at the current playback position" style={{ width: "100%", height }} />
        {hover && (
          <>
            <div className="pointer-events-none absolute w-px bg-ink/40" style={{ left: hover.px, top: PAD.top, height: height - PAD.top - PAD.bottom }} />
            <div
              className="pointer-events-none absolute z-20 min-w-40 rounded-lg border border-line-strong bg-bg-elev/95 px-2.5 py-2 text-xs shadow-xl"
              style={{ left: Math.min(hover.px + 12, width - 180), top: Math.min(hover.py, height - 110) }}
            >
              {hoverRows}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
