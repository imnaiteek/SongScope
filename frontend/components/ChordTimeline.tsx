"use client";

import { memo, useEffect, useMemo, useRef } from "react";

import { useCurrentTime, usePlayer } from "@/hooks/usePlayer";
import { findIndexAt, formatTime, pct } from "@/lib/format";
import type { ChordItem, Chords } from "@/types/analysis";

import { AnalysisSection, ConfidenceBadge, DataTable, LowConfidenceNote } from "./ui";

const PX_PER_SEC = 34;

export function ChordTimeline({ chords }: { chords: Chords }) {
  const { seek, state } = usePlayer();
  const t = useCurrentTime(0.1);
  const scrollRef = useRef<HTMLDivElement>(null);
  const items = useMemo(() => chords.items.filter((c) => c.chord !== "N"), [chords.items]);
  const activeIdx = findIndexAt(items, t);
  const current = items[activeIdx];
  const next = activeIdx >= 0 ? items[activeIdx + 1] : items.find((c) => c.start > t);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !state.playing) return;
    const target = t * PX_PER_SEC - el.clientWidth / 3;
    if (Math.abs(el.scrollLeft - target) > el.clientWidth / 3) el.scrollTo({ left: Math.max(0, target), behavior: "smooth" });
  }, [t, state.playing]);

  const totalWidth = (chords.items.at(-1)?.end ?? 0) * PX_PER_SEC;

  return (
    <AnalysisSection
      id="chords"
      title="Chord timeline"
      eyebrow={<ConfidenceBadge confidence={chords.confidence} level={chords.confidence_level} status={chords.status} />}
    >
      <div className="mb-4 grid gap-3 sm:grid-cols-[auto_auto_1fr]">
        <div className="rounded-xl border border-line bg-bg-elev/60 px-5 py-3">
          <div className="text-[11px] font-medium uppercase tracking-[0.1em] text-ink-3">Now</div>
          <div className="font-display text-4xl font-bold" aria-live="polite">{current?.chord ?? "—"}</div>
          <div className="text-xs text-ink-3">{current ? `${pct(current.confidence)} confidence` : "no chord"}</div>
        </div>
        <div className="rounded-xl border border-line bg-bg-elev/60 px-5 py-3">
          <div className="text-[11px] font-medium uppercase tracking-[0.1em] text-ink-3">Next</div>
          <div className="font-display text-4xl font-bold text-ink-2">{next?.chord ?? "—"}</div>
          <div className="text-xs text-ink-3">{next ? `at ${formatTime(next.start, true)}` : ""}</div>
        </div>
        <div className="grid grid-cols-3 gap-3 rounded-xl border border-line bg-bg-elev/60 px-4 py-3 text-sm">
          <div>
            <div className="text-[11px] uppercase tracking-[0.1em] text-ink-3">Unique</div>
            <div className="text-xl font-semibold tabular">{chords.unique_chords}</div>
          </div>
          <div>
            <div className="text-[11px] uppercase tracking-[0.1em] text-ink-3">Changes/min</div>
            <div className="text-xl font-semibold tabular">{chords.changes_per_minute ?? "—"}</div>
          </div>
          <div>
            <div className="text-[11px] uppercase tracking-[0.1em] text-ink-3">Avg length</div>
            <div className="text-xl font-semibold tabular">{chords.mean_chord_duration_s}s</div>
          </div>
          <div className="col-span-3 flex flex-wrap gap-1.5">
            {chords.most_common.slice(0, 8).map((c) => (
              <span key={c.chord} className="rounded-md border border-line px-1.5 py-0.5 text-xs text-ink-2">
                <b className="text-ink">{c.chord}</b> {pct(c.share)}
              </span>
            ))}
          </div>
        </div>
      </div>

      <div ref={scrollRef} className="scrollbar-thin relative overflow-x-auto pb-2" tabIndex={0} aria-label="Scrollable chord timeline">
        <ol className="relative h-16" style={{ width: Math.max(totalWidth, 300) }}>
          <ChordStrip items={items} activeIdx={activeIdx} seek={seek} />
          <Cursor />
        </ol>
      </div>
      <p className="mt-2 text-xs text-ink-3">
        Dashed chords have low confidence. Vocabulary is deliberately conservative (major, minor, 7, maj7, m7, sus, dim, aug) —
        a plain triad is reported rather than an unsupported extension.
      </p>
      <DataTable
        caption="Chord list"
        headers={["Start", "End", "Chord", "Confidence"]}
        rows={items.map((c) => [formatTime(c.start, true), formatTime(c.end, true), c.chord, pct(c.confidence)])}
      />
      <LowConfidenceNote level={chords.confidence_level} message={chords.message} />
    </AnalysisSection>
  );
}

function Cursor() {
  const t = useCurrentTime(1 / 30);
  return <li aria-hidden className="pointer-events-none absolute top-0 h-full w-[2px] rounded bg-ink" style={{ left: t * PX_PER_SEC }} />;
}

const ChordStrip = memo(function ChordStrip({ items, activeIdx, seek }: { items: ChordItem[]; activeIdx: number; seek: (t: number) => void }) {
  return (
    <>
      {items.map((c, i) => {
        const low = c.confidence < 0.5;
        const active = i === activeIdx;
        return (
          <li key={i} className="absolute top-0 h-full p-[1px]" style={{ left: c.start * PX_PER_SEC, width: (c.end - c.start) * PX_PER_SEC }}>
            <button
              type="button"
              onClick={() => seek(c.start)}
              className={`flex h-full w-full flex-col items-start justify-center overflow-hidden rounded-md border px-2 text-left transition ${
                active ? "border-violet bg-violet/25" : "border-line bg-card-2 hover:border-line-strong"
              } ${low ? "border-dashed" : ""}`}
              aria-label={`${c.chord} at ${formatTime(c.start, true)}, ${pct(c.confidence)} confidence${low ? ", low confidence" : ""}`}
              aria-current={active ? "true" : undefined}
            >
              <span className="text-sm font-bold">
                {c.chord}
                {low && <span className="text-ink-3">?</span>}
              </span>
              <span className="font-mono text-[10px] text-ink-3">{formatTime(c.start)}</span>
            </button>
          </li>
        );
      })}
    </>
  );
});
