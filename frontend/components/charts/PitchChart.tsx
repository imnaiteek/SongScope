"use client";

import { useMemo } from "react";

import { lastIndexLE, midiToNote } from "@/lib/format";
import type { Pitch } from "@/types/analysis";

import { TimeCanvas, TooltipRow } from "./TimeCanvas";

const LINE = "#3987e5";

export function PitchChart({ pitch }: { pitch: Pitch }) {
  const { times, midi, hz } = pitch.contour;
  const [lo, hi] = useMemo(() => {
    const vals = midi.filter((m): m is number => m != null);
    if (!vals.length) return [48, 84];
    const sorted = [...vals].sort((a, b) => a - b);
    const p = (q: number) => sorted[Math.floor(q * (sorted.length - 1))];
    return [Math.floor(p(0.01)) - 2, Math.ceil(p(0.99)) + 2];
  }, [midi]);

  return (
    <TimeCanvas
      height={220}
      ariaLabel={`Pitch contour from ${pitch.lowest_note ?? "?"} to ${pitch.highest_note ?? "?"}. Click to seek.`}
      deps={[pitch, lo, hi]}
      draw={({ ctx, plotLeft, plotRight, plotTop, plotBottom, x, t0, t1 }) => {
        const y = (m: number) => plotBottom - ((m - lo) / (hi - lo)) * (plotBottom - plotTop);
        // note grid: every C labelled, other semitones faint when zoomed vertically
        ctx.restore();
        ctx.save();
        ctx.font = "10px ui-monospace, monospace";
        ctx.textAlign = "right";
        for (let m = Math.ceil(lo); m <= hi; m++) {
          const isC = m % 12 === 0;
          if (!isC && hi - lo > 30) continue;
          ctx.strokeStyle = isC ? "#2c2c33" : "#1c1c21";
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(plotLeft, y(m) + 0.5);
          ctx.lineTo(plotRight, y(m) + 0.5);
          ctx.stroke();
          if (isC || hi - lo <= 14) {
            ctx.fillStyle = "#8a8993";
            ctx.fillText(midiToNote(m), plotLeft - 6, y(m) + 3);
          }
        }
        ctx.beginPath();
        ctx.rect(plotLeft, 0, plotRight - plotLeft, plotBottom);
        ctx.clip();
        ctx.strokeStyle = LINE;
        ctx.lineWidth = 2;
        ctx.lineJoin = "round";
        ctx.beginPath();
        let pen = false;
        let prev: number | null = null;
        const startIdx = Math.max(0, lastIndexLE(times, t0) - 1);
        for (let i = startIdx; i < times.length && times[i] <= t1 + 1; i++) {
          const m = midi[i];
          if (m == null || (prev != null && Math.abs(m - prev) > 7)) {
            pen = false;
            prev = m;
            if (m == null) continue;
          }
          const px = x(times[i]);
          const py = y(m);
          if (!pen) {
            ctx.moveTo(px, py);
            pen = true;
          } else ctx.lineTo(px, py);
          prev = m;
        }
        ctx.stroke();
      }}
      tooltip={(t) => {
        const i = lastIndexLE(times, t);
        if (i < 0) return null;
        const m = midi[i];
        const f = hz[i];
        if (m == null || f == null) return <TooltipRow label="Pitch" value="unvoiced" />;
        const cents = Math.round((m - Math.round(m)) * 100);
        return (
          <>
            <TooltipRow color={LINE} label="Note" value={`${midiToNote(m)}${cents ? ` ${cents > 0 ? "+" : ""}${cents}¢` : ""}`} />
            <TooltipRow label="Frequency" value={`${f.toFixed(1)} Hz`} />
          </>
        );
      }}
    />
  );
}
