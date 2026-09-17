"use client";

import { seqColor } from "@/lib/format";
import type { Harmony } from "@/types/analysis";

import { TimeCanvas, TooltipRow } from "./TimeCanvas";

export function Chromagram({ harmony }: { harmony: Harmony }) {
  const { values, seconds_per_frame: spf, pitch_classes: pcs } = harmony.chromagram;
  return (
    <div>
      <TimeCanvas
        height={200}
        ariaLabel="Chromagram: energy of each pitch class over time. Brighter means stronger."
        padding={{ left: 36, right: 8, top: 4, bottom: 22 }}
        deps={[harmony]}
        draw={({ ctx, plotLeft, plotTop, plotBottom, x, t0, t1 }) => {
          const rowH = (plotBottom - plotTop) / 12;
          const f0 = Math.max(0, Math.floor(t0 / spf));
          const f1 = Math.min(values.length, Math.ceil(t1 / spf) + 1);
          for (let f = f0; f < f1; f++) {
            const col = values[f];
            const xa = x(f * spf);
            const w = Math.max(1, x((f + 1) * spf) - xa + 0.5);
            for (let p = 0; p < 12; p++) {
              const v = col[p] / 99;
              ctx.fillStyle = seqColor(v * v); // squared for contrast: only dominant pitch classes read bright
              ctx.fillRect(xa, plotBottom - (p + 1) * rowH, w, rowH + 0.5);
            }
          }
          ctx.restore();
          ctx.save();
          ctx.font = "10px ui-monospace, monospace";
          ctx.textAlign = "right";
          ctx.fillStyle = "#8a8993";
          for (let p = 0; p < 12; p++) ctx.fillText(pcs[p], plotLeft - 6, plotBottom - p * rowH - rowH / 2 + 3);
        }}
        tooltip={(t, yPos, dc) => {
          const f = Math.floor(t / spf);
          const col = values[f];
          if (!col) return null;
          const rowH = (dc.plotBottom - dc.plotTop) / 12;
          const p = Math.min(11, Math.max(0, Math.floor((dc.plotBottom - yPos) / rowH)));
          const top = col.indexOf(Math.max(...col));
          return (
            <>
              <TooltipRow label={`Pitch class ${pcs[p]}`} value={`${col[p]}%`} />
              <TooltipRow label="Strongest" value={pcs[top]} />
            </>
          );
        }}
      />
      <div className="mt-2 flex items-center gap-2 text-[11px] text-ink-3" aria-hidden>
        <span>weak</span>
        <span className="h-2 w-28 rounded-sm" style={{ background: `linear-gradient(90deg, ${seqColor(0)}, ${seqColor(0.5)}, ${seqColor(1)})` }} />
        <span>strong (relative within each moment)</span>
      </div>
    </div>
  );
}
