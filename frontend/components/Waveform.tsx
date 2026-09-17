"use client";

import { Minus, Plus, ScanLine } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import RegionsPlugin from "wavesurfer.js/dist/plugins/regions.esm.js";

import { useCurrentTime, usePlayer, useTimelineView } from "@/hooks/usePlayer";
import { findIndexAt, formatTime, groupColor, groupHex, lastIndexLE } from "@/lib/format";
import type { AnalysisResults, ChordItem, Section } from "@/types/analysis";

const ZOOM_STEPS = [0, 20, 40, 80, 160, 320];

export function Waveform({ results }: { results: AnalysisResults }) {
  const { audio, seek, view, state } = usePlayer();
  const src = state.src;
  const hostRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WaveSurfer | null>(null);
  const [zoomIdx, setZoomIdx] = useState(0);
  const zoomRef = useRef(0);

  const applyZoom = (ws: WaveSurfer) => {
    if (!ws.getDecodedData()) return; // peaks load asynchronously; re-applied on "decode"
    const fit = (ws.getWidth() || 1) / duration;
    const z = ZOOM_STEPS[zoomRef.current];
    ws.zoom(z === 0 ? fit : Math.max(fit, z));
  };
  const [lanes, setLanes] = useState({ beats: true, sections: true, chords: true, key: true });
  const duration = results.metadata.duration;
  const sections = results.structure?.sections ?? [];
  const peaks = results.waveform.peaks;

  useEffect(() => {
    const host = hostRef.current;
    if (!host || !audio) return;
    const regions = RegionsPlugin.create();
    const maxAmp = results.waveform.max_amplitude || 1;
    const ws = WaveSurfer.create({
      container: host,
      height: 112,
      media: audio,
      // Passing the current URL matters: with peaks but no url WaveSurfer calls setSrc(""),
      // which would strip the src from the shared media element.
      url: src ?? undefined,
      peaks: [peaks.map((p) => p / maxAmp)],
      duration,
      waveColor: "#4a4956",
      progressColor: "#8b7bff",
      cursorColor: "#f3f2ee",
      cursorWidth: 2,
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
      normalize: false,
      dragToSeek: true,
      autoScroll: true,
      autoCenter: true,
      hideScrollbar: false,
      plugins: [regions],
    });
    wsRef.current = ws;

    const updateView = () => {
      const width = ws.getWidth();
      const minPx = ws.options.minPxPerSec || 0;
      const pps = Math.max(minPx, width / duration);
      const start = pps > 0 ? ws.getScroll() / pps : 0;
      const end = pps > 0 ? Math.min(duration, start + width / pps) : duration;
      view.set({ start, end });
    };
    ws.on("interaction", (t) => seek(t));
    let pending: { start: number; end: number } | null = null;
    let raf = 0;
    ws.on("scroll", (start, end) => {
      pending = { start, end };
      if (!raf)
        raf = requestAnimationFrame(() => {
          raf = 0;
          if (pending) view.set(pending);
        });
    });
    ws.on("zoom", () => requestAnimationFrame(updateView));
    ws.on("redrawcomplete", updateView);
    ws.on("ready", updateView);
    ws.on("decode", () => applyZoom(ws));

    for (const s of sections) {
      regions.addRegion({
        start: s.start,
        end: s.end,
        color: `${groupHex(s.group)}1f`,
        drag: false,
        resize: false,
      });
    }
    return () => {
      cancelAnimationFrame(raf);
      ws.destroy();
      wsRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [audio, src, peaks, duration]);

  useEffect(() => {
    zoomRef.current = zoomIdx;
    if (wsRef.current) applyZoom(wsRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [zoomIdx, duration]);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <NowReadout results={results} />
        <div className="flex items-center gap-2">
          <fieldset className="flex flex-wrap items-center gap-1.5 text-xs" aria-label="Timeline overlays">
            {(Object.keys(lanes) as (keyof typeof lanes)[]).map((k) => (
              <label key={k} className="flex cursor-pointer items-center gap-1.5 rounded-md border border-line px-2 py-1 text-ink-2 has-[:checked]:border-line-strong has-[:checked]:text-ink">
                <input
                  type="checkbox"
                  className="accent-[#8b7bff]"
                  checked={lanes[k]}
                  onChange={(e) => setLanes((l) => ({ ...l, [k]: e.target.checked }))}
                />
                {k[0].toUpperCase() + k.slice(1)}
              </label>
            ))}
          </fieldset>
          <div className="flex items-center rounded-lg border border-line" role="group" aria-label="Zoom">
            <button type="button" className="p-1.5 text-ink-2 hover:text-ink disabled:opacity-30" onClick={() => setZoomIdx((z) => Math.max(0, z - 1))} disabled={zoomIdx === 0} aria-label="Zoom out">
              <Minus size={15} />
            </button>
            <button type="button" className="border-x border-line p-1.5 text-ink-2 hover:text-ink" onClick={() => setZoomIdx(0)} aria-label="Fit whole track">
              <ScanLine size={15} />
            </button>
            <button type="button" className="p-1.5 text-ink-2 hover:text-ink disabled:opacity-30" onClick={() => setZoomIdx((z) => Math.min(ZOOM_STEPS.length - 1, z + 1))} disabled={zoomIdx === ZOOM_STEPS.length - 1} aria-label="Zoom in">
              <Plus size={15} />
            </button>
          </div>
        </div>
      </div>

      <div className="rounded-xl border border-line bg-bg-elev px-0 pt-2">
        {lanes.beats && <BeatLane beats={results.rhythm?.beats ?? []} downbeats={results.rhythm?.downbeats ?? []} />}
        <div ref={hostRef} className="waveform-host" aria-label="Audio waveform. Click to seek." role="application" />
        {lanes.sections && sections.length > 0 && <SectionLane sections={sections} />}
        {lanes.chords && (results.chords?.items?.length ?? 0) > 0 && <ChordLane chords={results.chords.items} />}
        {lanes.key && results.key?.key && <KeyLane results={results} />}
        <TimeRuler duration={duration} />
      </div>
    </div>
  );
}

function useLanePosition() {
  const v = useTimelineView();
  const span = Math.max(0.001, v.end - v.start);
  return { v, pos: (t: number) => ((t - v.start) / span) * 100 };
}

function BeatLane({ beats, downbeats }: { beats: number[]; downbeats: number[] }) {
  const { v, pos } = useLanePosition();
  const downSet = useMemo(() => new Set(downbeats), [downbeats]);
  const visible = beats.filter((b) => b >= v.start && b <= v.end);
  const dense = visible.length > 260;
  const t = useCurrentTime(0.05);
  const cur = lastIndexLE(beats, t);
  return (
    <div className="relative mb-1 h-4 overflow-hidden" aria-hidden>
      {visible.map((b) => {
        const down = downSet.has(b);
        if (dense && !down) return null;
        const idx = beats.indexOf(b);
        const active = idx === cur;
        return (
          <span
            key={b}
            className="absolute bottom-0 w-px"
            style={{
              left: `${pos(b)}%`,
              height: down ? 14 : 7,
              background: active ? "#f3f2ee" : down ? "#8a8993" : "#4a4956",
              width: active ? 2 : 1,
            }}
          />
        );
      })}
    </div>
  );
}

function SectionLane({ sections }: { sections: Section[] }) {
  const { v, pos } = useLanePosition();
  const { seek } = usePlayer();
  const t = useCurrentTime(0.25);
  const active = findIndexAt(sections, t);
  return (
    <div className="relative mt-1 h-7 overflow-hidden" role="list" aria-label="Song sections">
      {sections.map((s, i) => {
        if (s.end < v.start || s.start > v.end) return null;
        const left = pos(s.start);
        const width = pos(s.end) - left;
        return (
          <button
            key={i}
            type="button"
            role="listitem"
            onClick={() => seek(s.start)}
            title={`${s.display_label} · group ${s.group} · ${formatTime(s.start)}–${formatTime(s.end)} · ${Math.round(s.confidence * 100)}% confidence`}
            className={`absolute top-0 flex h-full items-center overflow-hidden rounded-[5px] border-l-[3px] px-1.5 text-left text-[11px] font-medium transition ${i === active ? "text-ink" : "text-ink-2"}`}
            style={{
              left: `calc(${left}% + 1px)`,
              width: `calc(${width}% - 2px)`,
              borderColor: groupColor(s.group),
              background: i === active ? "rgba(243,242,238,0.12)" : "rgba(243,242,238,0.04)",
            }}
          >
            <span className="truncate">{s.display_label}</span>
          </button>
        );
      })}
    </div>
  );
}

function ChordLane({ chords }: { chords: ChordItem[] }) {
  const { v, pos } = useLanePosition();
  const { seek } = usePlayer();
  const t = useCurrentTime(0.1);
  const active = findIndexAt(chords, t);
  return (
    <div className="relative mt-1 h-7 overflow-hidden" role="list" aria-label="Chord changes">
      {chords.map((c, i) => {
        if (c.chord === "N" || c.end < v.start || c.start > v.end) return null;
        const left = pos(c.start);
        const width = pos(c.end) - left;
        const low = c.confidence < 0.5;
        return (
          <button
            key={i}
            type="button"
            role="listitem"
            onClick={() => seek(c.start)}
            title={`${c.chord} · ${formatTime(c.start, true)} · ${Math.round(c.confidence * 100)}% confidence`}
            className={`absolute top-0 flex h-full items-center justify-center overflow-hidden rounded-[5px] border text-[11px] font-semibold tabular ${
              i === active ? "border-violet bg-violet/25 text-ink" : "border-line bg-card-2 text-ink-2"
            } ${low ? "border-dashed" : ""}`}
            style={{ left: `calc(${left}% + 1px)`, width: `calc(${width}% - 2px)` }}
          >
            {width > 1.2 ? `${c.chord}${low ? "?" : ""}` : ""}
          </button>
        );
      })}
    </div>
  );
}

function KeyLane({ results }: { results: AnalysisResults }) {
  const { pos } = useLanePosition();
  const d = results.metadata.duration;
  const changes = results.key.changes ?? [];
  const segs: { start: number; end: number; key: string; alt: boolean }[] = [];
  let cursor = 0;
  for (const c of changes) {
    if (c.start > cursor) segs.push({ start: cursor, end: c.start, key: results.key.key!, alt: false });
    segs.push({ start: c.start, end: c.end, key: c.key, alt: true });
    cursor = c.end;
  }
  if (cursor < d) segs.push({ start: cursor, end: d, key: results.key.key!, alt: false });
  return (
    <div className="relative mt-1 h-5 overflow-hidden" aria-label="Key regions">
      {segs.map((s, i) => (
        <div
          key={i}
          className={`absolute top-0 flex h-full items-center overflow-hidden px-1.5 text-[10px] font-medium ${s.alt ? "text-amber" : "text-ink-3"}`}
          style={{ left: `${pos(s.start)}%`, width: `${pos(s.end) - pos(s.start)}%`, borderTop: `1px solid ${s.alt ? "var(--amber)" : "var(--line-strong)"}` }}
        >
          <span className="truncate">{s.alt ? `Key change → ${s.key}` : `Key: ${s.key}`}</span>
        </div>
      ))}
    </div>
  );
}

function TimeRuler({ duration }: { duration: number }) {
  const { v, pos } = useLanePosition();
  const span = v.end - v.start;
  const step = [1, 2, 5, 10, 15, 30, 60, 120].find((s) => span / s <= 12) ?? 300;
  const ticks = [];
  for (let t = Math.ceil(v.start / step) * step; t <= Math.min(v.end, duration); t += step) ticks.push(t);
  return (
    <div className="relative h-5 overflow-hidden border-t border-line" aria-hidden>
      {ticks.map((t) => (
        <span key={t} className="absolute top-1 -translate-x-1/2 font-mono text-[10px] text-ink-3" style={{ left: `${pos(t)}%` }}>
          {formatTime(t)}
        </span>
      ))}
    </div>
  );
}

function NowReadout({ results }: { results: AnalysisResults }) {
  const t = useCurrentTime(0.05);
  const sections = results.structure?.sections ?? [];
  const chords = results.chords?.items ?? [];
  const sec = sections[findIndexAt(sections, t)];
  const chord = chords[findIndexAt(chords, t)];
  const beats = results.rhythm?.beats ?? [];
  const downbeats = results.rhythm?.downbeats ?? [];
  const bar = lastIndexLE(downbeats, t);
  const beatIdx = lastIndexLE(beats, t);
  const beatInBar = bar >= 0 && beatIdx >= 0 ? beats.slice(0, beatIdx + 1).filter((b) => b >= downbeats[bar]).length : null;
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-sm" aria-live="off">
      <span className="font-mono text-base tabular text-ink">{formatTime(t, true)}</span>
      <span className="text-ink-3">
        Section <span className="font-medium text-ink">{sec?.display_label ?? "—"}</span>
      </span>
      <span className="text-ink-3">
        Chord <span className="font-semibold text-ink">{chord && chord.chord !== "N" ? chord.chord : "—"}</span>
      </span>
      {results.meter?.reliable && bar >= 0 && (
        <span className="text-ink-3 tabular">
          Bar <span className="font-medium text-ink">{bar + 1}</span>
          {beatInBar ? <span className="text-ink-2"> · beat {beatInBar}</span> : null}
        </span>
      )}
    </div>
  );
}
