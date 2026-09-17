"use client";

import { useMemo } from "react";

import { useCurrentTime, usePlayer } from "@/hooks/usePlayer";
import { formatTime, lastIndexLE, num, pct, seqColor } from "@/lib/format";
import type { AnalysisResults, Drums } from "@/types/analysis";

import { TempoCurve } from "./charts/TempoCurve";
import { AnalysisSection, ConfidenceBadge, InfoTip, LowConfidenceNote, Stat } from "./ui";

export function RhythmSection({ r }: { r: AnalysisResults }) {
  const { tempo, rhythm, meter, drums } = r;
  return (
    <AnalysisSection id="rhythm" title="Rhythm" eyebrow={<ConfidenceBadge confidence={tempo.confidence} level={tempo.confidence_level} status={tempo.status} />}>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Tempo" value={tempo.bpm ?? "—"} unit="BPM" hint={tempo.category ?? undefined} />
        <Stat
          label="Meter"
          value={meter.reliable && meter.signature ? meter.signature : "Uncertain"}
          hint={meter.reliable ? `${meter.bars} bars · ${meter.subdivision} subdivision` : "Meter could not be determined reliably."}
          badge={<ConfidenceBadge confidence={meter.confidence} level={meter.confidence_level} status={meter.status} compact />}
        />
        <Stat label="Tempo stability" value={pct(tempo.stability)} hint={tempo.timing_jitter_ms != null ? `±${tempo.timing_jitter_ms} ms beat jitter` : undefined} />
        <Stat label="Beat interval" value={rhythm.beat_interval_s != null ? (rhythm.beat_interval_s * 1000).toFixed(0) : "—"} unit="ms" hint={`${rhythm.beat_count} beats`} />
        <Stat label="Onset density" value={num(rhythm.onset_density, 1)} unit="/ s" />
        <Stat label="Rhythm density" value={num(rhythm.rhythm_density, 2)} unit="onsets / beat" />
        <Stat label="Syncopation" value={pct(rhythm.syncopation)} hint="Onset energy off the beat" />
        <Stat
          label="Alternative tempo"
          value={tempo.alternative_bpm ?? "—"}
          unit={tempo.alternative_bpm ? "BPM" : undefined}
          hint={tempo.alternative_relation ? `${tempo.alternative_relation}${tempo.octave_ambiguous ? " · similarly plausible" : ""}` : undefined}
        />
      </div>

      {tempo.has_tempo_changes && (
        <div className="mt-4 rounded-xl border border-line bg-bg-elev/60 p-3 text-sm">
          <span className="font-semibold">Tempo changes detected: </span>
          {tempo.sections.map((s, i) => (
            <span key={i} className="mr-3 tabular text-ink-2">
              {formatTime(s.start)} → {s.bpm} BPM
            </span>
          ))}
        </div>
      )}

      <div className="mt-5 grid gap-5 xl:grid-cols-2">
        <div>
          <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
            Beat grid <InfoTip text="Detected beats grouped into bars from the downbeat estimate. Click any beat to jump there." />
          </h3>
          <BeatGrid r={r} />
        </div>
        <div>
          <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
            Local tempo <InfoTip text="Least-squares tempo over sliding 16-beat windows." />
          </h3>
          <TempoCurve tempo={tempo} />
          <details className="mt-3 text-xs text-ink-3">
            <summary className="cursor-pointer hover:text-ink-2">Tempo estimators (compared, not trusted individually)</summary>
            <ul className="mt-2 grid grid-cols-2 gap-1 tabular">
              {Object.entries(tempo.estimates ?? {}).map(([k, v]) => (
                <li key={k}>
                  {k.replaceAll("_", " ")}: <span className="text-ink-2">{v ?? "—"}</span>
                </li>
              ))}
            </ul>
          </details>
        </div>
      </div>

      <DrumPattern drums={drums} />
      <LowConfidenceNote level={tempo.confidence_level} message={tempo.message} />
      {!meter.reliable && <LowConfidenceNote level="low" message={meter.message ?? "Meter could not be determined reliably."} />}
    </AnalysisSection>
  );
}

function BeatGrid({ r }: { r: AnalysisResults }) {
  const { seek } = usePlayer();
  const t = useCurrentTime(0.05);
  const beats = r.rhythm.beats;
  const downbeats = r.rhythm.downbeats;
  const bars = useMemo(() => {
    if (!downbeats.length) {
      const out: number[][] = [];
      for (let i = 0; i < beats.length; i += 4) out.push(beats.slice(i, i + 4));
      return out;
    }
    const out: number[][] = [];
    const pre = beats.filter((b) => b < downbeats[0] - 0.02);
    if (pre.length) out.push(pre);
    downbeats.forEach((d, i) => {
      const end = downbeats[i + 1] ?? Infinity;
      out.push(beats.filter((b) => b >= d - 0.02 && b < end - 0.02));
    });
    return out;
  }, [beats, downbeats]);
  if (!beats.length) return <p className="text-sm text-ink-3">{r.rhythm.message ?? "No beat grid available."}</p>;

  const curBeat = lastIndexLE(beats, t);
  const curBar = bars.findIndex((b) => b.length && t >= b[0] && t < (bars[bars.indexOf(b) + 1]?.[0] ?? Infinity));
  const first = Math.max(0, Math.min(Math.max(0, curBar - 3), bars.length - 12));
  const visible = bars.slice(first, first + 12);
  const maxLen = Math.max(...visible.map((b) => b.length), 1);
  return (
    <div className="rounded-xl border border-line bg-bg-elev/60 p-3">
      <div className="grid gap-1.5" role="grid" aria-label="Beat grid, bars and beats">
        {visible.map((bar, bi) => {
          const barNo = first + bi + 1 - (downbeats.length && beats[0] < downbeats[0] - 0.02 ? 1 : 0);
          return (
            <div key={first + bi} role="row" className="flex items-center gap-1.5">
              <span className={`w-10 shrink-0 text-right font-mono text-[11px] ${first + bi === curBar ? "text-ink" : "text-ink-3"}`}>{barNo > 0 ? barNo : "·"}</span>
              <div className="grid flex-1 gap-1" style={{ gridTemplateColumns: `repeat(${maxLen}, minmax(0, 1fr))` }}>
                {bar.map((b, k) => {
                  const idx = beats.indexOf(b);
                  const active = idx === curBeat;
                  const down = downbeats.includes(b);
                  return (
                    <button
                      key={b}
                      type="button"
                      role="gridcell"
                      onClick={() => seek(b)}
                      aria-label={`Bar ${barNo}, beat ${k + 1} at ${formatTime(b, true)}`}
                      className={`h-7 rounded-md border text-[11px] font-medium tabular transition ${
                        active ? "border-ink bg-ink text-bg" : down ? "border-line-strong bg-card-2 text-ink" : "border-line bg-card text-ink-3 hover:text-ink"
                      }`}
                    >
                      {k + 1}
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
      <p className="mt-2 text-[11px] text-ink-3">Showing 12 bars around the playhead · downbeats outlined brighter.</p>
    </div>
  );
}

const INSTRUMENT_LABEL: Record<string, string> = { kick: "Kick", snare: "Snare", hihat: "Hi-hat" };

function DrumPattern({ drums }: { drums: Drums }) {
  const entries = Object.entries(drums.instruments ?? {});
  return (
    <div className="mt-5">
      <h3 className="mb-2 flex flex-wrap items-center gap-2 text-sm font-semibold">
        Drum pattern
        <span className="rounded-md border border-amber/50 bg-amber/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber">Estimated</span>
        <ConfidenceBadge confidence={drums.confidence} level={drums.confidence_level} status={drums.status} compact />
      </h3>
      {entries.length === 0 ? (
        <p className="text-sm text-ink-3">{drums.message}</p>
      ) : (
        <div className="rounded-xl border border-line bg-bg-elev/60 p-3">
          <div className="scrollbar-thin overflow-x-auto">
            <table className="w-full min-w-[520px] border-separate border-spacing-[3px] text-xs">
              <caption className="sr-only">Estimated hit probability per 16th-note slot across {drums.bars_analyzed} bars</caption>
              <thead>
                <tr>
                  <th scope="col" className="w-20" />
                  {drums.slot_labels?.map((l, i) => (
                    <th key={i} scope="col" className={`font-mono font-normal ${i % 4 === 0 ? "text-ink-2" : "text-ink-3"}`}>{l}</th>
                  ))}
                  <th scope="col" className="pl-3 text-left font-medium text-ink-3">Pattern</th>
                </tr>
              </thead>
              <tbody>
                {entries.map(([name, inst]) => (
                  <tr key={name}>
                    <th scope="row" className="text-left font-medium text-ink-2">{INSTRUMENT_LABEL[name] ?? name}</th>
                    {inst.slot_probabilities.map((p, i) => (
                      <td key={i} className="p-0">
                        <div
                          className="h-6 rounded-[4px]"
                          style={{ background: p < 0.05 ? "#16161b" : seqColor(0.15 + p * 0.85), outline: p >= 0.5 ? "1px solid #86b6ef" : undefined }}
                          title={`${INSTRUMENT_LABEL[name] ?? name} · ${drums.slot_labels?.[i]} · hit in ${pct(p)} of bars`}
                        />
                      </td>
                    ))}
                    <td className="whitespace-nowrap pl-3 font-medium text-ink">{inst.pattern}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[11px] text-ink-3">
            Cell brightness = share of {drums.bars_analyzed} bars with a hit on that 16th-note slot. {drums.message}
          </p>
        </div>
      )}
    </div>
  );
}
