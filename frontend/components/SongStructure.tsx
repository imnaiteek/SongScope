"use client";

import { ArrowRight } from "lucide-react";
import { useEffect, useRef } from "react";

import { useCurrentTime, usePlayer } from "@/hooks/usePlayer";
import { findIndexAt, formatTime, groupColor, pct, seqColor } from "@/lib/format";
import type { AnalysisResults } from "@/types/analysis";

import { AnalysisSection, ConfidenceBadge } from "./ui";

export function SongStructure({ r }: { r: AnalysisResults }) {
  const { structure, progression } = r;
  const { seek } = usePlayer();
  const t = useCurrentTime(0.25);
  const sections = structure.sections ?? [];
  const duration = r.metadata.duration;
  const active = findIndexAt(sections, t);
  const bySection = new Map((progression?.by_section ?? []).map((b) => [b.section_index, b]));

  return (
    <AnalysisSection
      id="structure"
      title="Song structure"
      eyebrow={<ConfidenceBadge confidence={structure.confidence} level={structure.confidence_level} status={structure.status} />}
    >
      <div className="mb-3 flex flex-wrap items-center gap-1.5 text-sm" aria-label="Section sequence">
        {sections.map((s, i) => (
          <span key={i} className="flex items-center gap-1.5">
            <span className={i === active ? "font-semibold text-ink" : "text-ink-2"}>{s.display_label}</span>
            {i < sections.length - 1 && <ArrowRight size={12} className="text-ink-3" aria-hidden />}
          </span>
        ))}
      </div>

      <div className="flex h-12 w-full overflow-hidden rounded-xl border border-line" role="list" aria-label="Section map">
        {sections.map((s, i) => (
          <button
            key={i}
            type="button"
            role="listitem"
            onClick={() => seek(s.start)}
            className={`relative flex h-full items-end overflow-hidden border-r-2 border-bg px-1.5 pb-1 text-left text-[11px] font-medium transition hover:brightness-125 ${i === active ? "text-ink" : "text-ink-2"}`}
            style={{
              width: `${((s.end - s.start) / duration) * 100}%`,
              background: `color-mix(in oklab, ${groupColor(s.group)} ${i === active ? 55 : 30}%, #131316)`,
            }}
            aria-label={`${s.display_label}, ${formatTime(s.start)} to ${formatTime(s.end)}, group ${s.group}`}
          >
            <span className="truncate">{s.display_label}</span>
          </button>
        ))}
      </div>

      <div className="scrollbar-thin mt-4 overflow-x-auto">
        <table className="w-full min-w-[560px] text-sm">
          <caption className="sr-only">Sections with times, repetition group and confidence</caption>
          <thead className="text-left text-[11px] uppercase tracking-[0.1em] text-ink-3">
            <tr>
              <th scope="col" className="py-2 font-medium">Time</th>
              <th scope="col" className="font-medium">Section</th>
              <th scope="col" className="font-medium">Group</th>
              <th scope="col" className="font-medium">Chords</th>
              <th scope="col" className="font-medium">Energy</th>
              <th scope="col" className="font-medium">Confidence</th>
            </tr>
          </thead>
          <tbody>
            {sections.map((s, i) => {
              const bs = bySection.get(i);
              return (
                <tr key={i} className={`border-t border-line ${i === active ? "bg-card-2" : ""}`}>
                  <td className="py-2 pr-3">
                    <button type="button" onClick={() => seek(s.start)} className="font-mono text-xs text-violet hover:underline">
                      {formatTime(s.start)}
                    </button>
                  </td>
                  <td className="pr-3 font-medium">{s.display_label}</td>
                  <td className="pr-3">
                    <span className="inline-flex items-center gap-1.5 text-ink-2">
                      <span className="size-2.5 rounded-sm" style={{ background: groupColor(s.group) }} aria-hidden />
                      {s.group}
                    </span>
                  </td>
                  <td className="max-w-64 truncate pr-3 text-xs text-ink-2" title={bs?.chords.join(" ")}>
                    {bs?.chords.length ? bs.chords.join(" · ") : "—"}
                  </td>
                  <td className="pr-3 font-mono text-xs text-ink-2">{s.relative_energy_db != null ? `${s.relative_energy_db > 0 ? "+" : ""}${s.relative_energy_db} dB` : "—"}</td>
                  <td className="text-xs text-ink-2">{pct(s.confidence)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs leading-relaxed text-ink-3">
        Letters (A, B, C…) group acoustically similar sections and are detected from repetition. Names like Verse or Chorus are
        <em> inferred</em> from repetition, energy and position — SongScope does not analyse lyrics. Uncertain names are shown as “Possible …”.
      </p>
      {structure.ssm && <SelfSimilarity ssm={structure.ssm} />}
    </AnalysisSection>
  );
}

function SelfSimilarity({ ssm }: { ssm: NonNullable<AnalysisResults["structure"]["ssm"]> }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const n = ssm.size;
    c.width = n;
    c.height = n;
    const ctx = c.getContext("2d")!;
    for (let i = 0; i < n; i++)
      for (let j = 0; j < n; j++) {
        const v = ssm.values[i][j] / 99;
        ctx.fillStyle = seqColor(Math.max(0, (v - 0.4) / 0.6));
        ctx.fillRect(j, i, 1, 1);
      }
  }, [ssm]);
  return (
    <details className="mt-4">
      <summary className="cursor-pointer text-xs font-medium text-ink-3 hover:text-ink-2">Self-similarity matrix</summary>
      <div className="mt-3 flex flex-wrap items-start gap-4">
        <canvas ref={ref} className="size-64 rounded-lg border border-line [image-rendering:pixelated]" role="img" aria-label="Self-similarity matrix; bright diagonal stripes indicate repeated material" />
        <p className="max-w-sm text-xs leading-relaxed text-ink-3">
          Each pixel compares two moments of the track (time runs down and right, ≈{ssm.seconds_per_cell.toFixed(1)} s per cell).
          Bright off-diagonal stripes are repeated passages; block edges are section boundaries.
        </p>
      </div>
    </details>
  );
}
