"use client";

import { lastIndexLE } from "@/lib/format";
import type { Tempo } from "@/types/analysis";

import { TimeCanvas, TooltipRow } from "./TimeCanvas";

const LINE = "#3987e5";

export function TempoCurve({ tempo }: { tempo: Tempo }) {
  const { times, bpm } = tempo.curve;
  if (times.length < 3 || !tempo.bpm) return <p className="text-sm text-ink-3">Not enough beats to plot local tempo.</p>;
  const center = tempo.bpm;
  const dev = Math.max(4, ...bpm.map((b) => Math.abs(b - center))) * 1.2;
  const lo = center - dev;
  const hi = center + dev;
  return (
    <TimeCanvas
      height={120}
      ariaLabel={`Local tempo over time around ${center} BPM`}
      deps={[tempo]}
      draw={({ ctx, plotLeft, plotRight, plotTop, plotBottom, x }) => {
        const y = (v: number) => plotBottom - ((v - lo) / (hi - lo)) * (plotBottom - plotTop);
        ctx.restore();
        ctx.save();
        ctx.font = "10px ui-monospace, monospace";
        ctx.textAlign = "right";
        for (const v of [lo, center, hi]) {
          ctx.strokeStyle = v === center ? "#34343c" : "#1f1f25";
          ctx.beginPath();
          ctx.moveTo(plotLeft, y(v) + 0.5);
          ctx.lineTo(plotRight, y(v) + 0.5);
          ctx.stroke();
          ctx.fillStyle = "#8a8993";
          ctx.fillText(v.toFixed(0), plotLeft - 6, y(v) + 3);
        }
        ctx.beginPath();
        ctx.rect(plotLeft, 0, plotRight - plotLeft, plotBottom);
        ctx.clip();
        ctx.strokeStyle = LINE;
        ctx.lineWidth = 2;
        ctx.beginPath();
        times.forEach((t, i) => (i ? ctx.lineTo(x(t), y(bpm[i])) : ctx.moveTo(x(t), y(bpm[i]))));
        ctx.stroke();
        ctx.fillStyle = LINE;
        times.forEach((t, i) => {
          ctx.beginPath();
          ctx.arc(x(t), y(bpm[i]), 2.5, 0, Math.PI * 2);
          ctx.fill();
        });
      }}
      tooltip={(t) => {
        const i = Math.max(0, lastIndexLE(times, t));
        return <TooltipRow color={LINE} label="Local tempo" value={`${bpm[i].toFixed(1)} BPM`} />;
      }}
    />
  );
}
