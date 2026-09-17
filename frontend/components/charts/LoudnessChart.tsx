"use client";

import { useMemo } from "react";

import { lastIndexLE } from "@/lib/format";
import type { Loudness } from "@/types/analysis";

import { TimeCanvas, TooltipRow } from "./TimeCanvas";

const SHORT = "#3987e5";
const MOMENTARY = "#d95926";

export function LoudnessChart({ loudness }: { loudness: Loudness }) {
  const { short_term: st, momentary: mo } = loudness;
  const [lo, hi] = useMemo(() => {
    const vals = [...st.lufs, ...mo.lufs].filter((v): v is number => v != null);
    if (!vals.length) return [-40, 0];
    const max = Math.max(...vals);
    const sorted = [...vals].sort((a, b) => a - b);
    const low = sorted[Math.floor(sorted.length * 0.02)];
    return [Math.floor((low - 3) / 6) * 6, Math.min(0, Math.ceil((max + 1) / 3) * 3)];
  }, [st, mo]);

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-4 text-xs text-ink-2" aria-label="Legend">
        <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 rounded" style={{ background: SHORT }} />Short-term (3 s)</span>
        <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 rounded" style={{ background: MOMENTARY }} />Momentary (400 ms)</span>
        {loudness.integrated_lufs != null && (
          <span className="flex items-center gap-1.5"><span className="h-0 w-4 border-t border-dashed border-ink-2" />Integrated {loudness.integrated_lufs} LUFS</span>
        )}
      </div>
      <TimeCanvas
        height={200}
        ariaLabel={`Loudness over time. Integrated ${loudness.integrated_lufs} LUFS, max short-term ${loudness.max_short_term_lufs} LUFS.`}
        deps={[loudness, lo, hi]}
        draw={({ ctx, plotLeft, plotRight, plotTop, plotBottom, x, t0, t1 }) => {
          const y = (v: number) => plotBottom - ((v - lo) / (hi - lo)) * (plotBottom - plotTop);
          ctx.restore();
          ctx.save();
          ctx.font = "10px ui-monospace, monospace";
          ctx.textAlign = "right";
          const step = hi - lo > 30 ? 12 : 6;
          for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
            ctx.strokeStyle = "#1f1f25";
            ctx.beginPath();
            ctx.moveTo(plotLeft, y(v) + 0.5);
            ctx.lineTo(plotRight, y(v) + 0.5);
            ctx.stroke();
            ctx.fillStyle = "#8a8993";
            ctx.fillText(`${v}`, plotLeft - 6, y(v) + 3);
          }
          ctx.beginPath();
          ctx.rect(plotLeft, 0, plotRight - plotLeft, plotBottom);
          ctx.clip();
          const line = (s: { times: number[]; lufs: (number | null)[] }, color: string, width: number) => {
            ctx.strokeStyle = color;
            ctx.lineWidth = width;
            ctx.lineJoin = "round";
            ctx.beginPath();
            let pen = false;
            const i0 = Math.max(0, lastIndexLE(s.times, t0) - 1);
            for (let i = i0; i < s.times.length && s.times[i] <= t1 + 3; i++) {
              const v = s.lufs[i];
              if (v == null) {
                pen = false;
                continue;
              }
              const px = x(s.times[i]);
              const py = y(Math.max(lo, v));
              if (pen) ctx.lineTo(px, py);
              else {
                ctx.moveTo(px, py);
                pen = true;
              }
            }
            ctx.stroke();
          };
          line(mo, MOMENTARY, 1.25);
          line(st, SHORT, 2);
          if (loudness.integrated_lufs != null) {
            ctx.setLineDash([4, 4]);
            ctx.strokeStyle = "#b9b8c0";
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(plotLeft, y(loudness.integrated_lufs) + 0.5);
            ctx.lineTo(plotRight, y(loudness.integrated_lufs) + 0.5);
            ctx.stroke();
            ctx.setLineDash([]);
          }
        }}
        tooltip={(t) => {
          const i = lastIndexLE(st.times, t);
          const j = lastIndexLE(mo.times, t);
          return (
            <>
              <TooltipRow color={SHORT} label="Short-term" value={i >= 0 && st.lufs[i] != null ? `${st.lufs[i]} LUFS` : "—"} />
              <TooltipRow color={MOMENTARY} label="Momentary" value={j >= 0 && mo.lufs[j] != null ? `${mo.lufs[j]} LUFS` : "—"} />
            </>
          );
        }}
      />
    </div>
  );
}
