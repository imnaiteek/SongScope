"use client";

import { AlertTriangle } from "lucide-react";

import { usePlayer } from "@/hooks/usePlayer";
import { formatTime, hz, num, pct } from "@/lib/format";
import type { AnalysisResults } from "@/types/analysis";

import { LoudnessChart } from "./charts/LoudnessChart";
import { PitchChart } from "./charts/PitchChart";
import { SpectrumChart } from "./charts/SpectrumChart";
import { AnalysisSection, ConfidenceBadge, DataTable, LowConfidenceNote, Stat } from "./ui";

export function PitchSection({ r }: { r: AnalysisResults }) {
  const p = r.pitch;
  const { seek } = usePlayer();
  const ok = !!p.lowest_note;
  const topNotes = Object.entries(
    p.events.reduce<Record<string, number>>((acc, e) => {
      acc[e.note] = (acc[e.note] ?? 0) + (e.end - e.start);
      return acc;
    }, {}),
  )
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8);
  return (
    <AnalysisSection
      id="pitch"
      title="Pitch & melody"
      eyebrow={
        <>
          <ConfidenceBadge confidence={p.confidence} level={p.confidence_level} status={p.status} />
          <span className="text-xs text-ink-3">Source: {p.source === "mix" ? "full mix (predominant pitch)" : p.source}</span>
        </>
      }
    >
      {ok ? (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <Stat label="Lowest note" value={p.lowest_note} hint={hz(p.lowest_hz)} />
            <Stat label="Highest note" value={p.highest_note} hint={hz(p.highest_hz)} />
            <Stat label="Range" value={p.range_semitones ?? "—"} unit="semitones" hint={p.range_description} />
            <Stat label="Average pitch" value={p.average_note ?? "—"} hint={`median f0 ${hz(p.fundamental_hz_median)}`} />
            <Stat label="Most frequent note" value={p.most_frequent_note ?? "—"} hint={`pitch class ${p.most_frequent_pitch_class ?? "—"}`} />
            <Stat label="Voiced" value={pct(p.voiced_fraction)} hint="of audible frames" />
          </div>
          <div className="mt-5">
            <PitchChart pitch={p} />
          </div>
          {topNotes.length > 0 && (
            <div className="mt-4">
              <div className="mb-2 text-xs font-medium text-ink-3">Most sustained notes (click to jump to first occurrence)</div>
              <div className="flex flex-wrap gap-1.5">
                {topNotes.map(([note, secs]) => {
                  const first = p.events.find((e) => e.note === note);
                  return (
                    <button
                      key={note}
                      type="button"
                      onClick={() => first && seek(first.start)}
                      className="rounded-md border border-line bg-card-2 px-2 py-1 text-xs hover:border-line-strong"
                    >
                      <b>{note}</b> <span className="text-ink-3">{secs.toFixed(1)}s</span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
          <DataTable
            caption="Pitch events"
            headers={["Start", "End", "Note", "Hz"]}
            rows={p.events.slice(0, 400).map((e) => [formatTime(e.start, true), formatTime(e.end, true), e.note, e.hz])}
          />
        </>
      ) : (
        <p className="text-sm text-ink-2">No reliable melodic pitch could be tracked.</p>
      )}
      <LowConfidenceNote level={p.confidence_level} message={p.message} />
    </AnalysisSection>
  );
}

export function LoudnessSection({ r }: { r: AnalysisResults }) {
  const l = r.loudness;
  return (
    <AnalysisSection id="loudness" title="Loudness & dynamics" eyebrow={<ConfidenceBadge status="detected" />}>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Integrated loudness" value={l.integrated_lufs ?? "—"} unit="LUFS" large />
        <Stat label="True peak" value={l.true_peak_dbtp ?? "—"} unit="dBTP" large hint={l.true_peak_dbtp != null && l.true_peak_dbtp > -1 ? "Above −1 dBTP streaming guideline" : undefined} />
        <Stat label="Dynamic range" value={l.dynamic_range_db ?? "—"} unit="dB" large hint="Crest-based DR estimate" />
        <Stat label="Loudness range" value={l.loudness_range_lu ?? "—"} unit="LU" large hint="EBU Tech 3342 LRA" />
        <Stat label="RMS" value={l.rms_dbfs ?? "—"} unit="dBFS" />
        <Stat label="Peak-to-loudness" value={l.plr_db ?? "—"} unit="dB" />
        <Stat label="Max short-term" value={l.max_short_term_lufs ?? "—"} unit="LUFS" />
        <Stat label="Max momentary" value={l.max_momentary_lufs ?? "—"} unit="LUFS" />
      </div>
      <p className="mt-3 text-sm text-ink-2">{l.character}</p>
      <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-ink-3">
        {l.stereo && (
          <span>
            Stereo correlation {l.stereo.correlation} · side/mid {l.stereo.side_to_mid_ratio}
          </span>
        )}
        <span className="inline-flex items-center gap-1">
          {l.clipping_events > 0 && <AlertTriangle size={12} style={{ color: "var(--warning)" }} aria-hidden />}
          {l.clipping_events > 0 ? `${l.clipping_events} possible clipping events` : "No sample clipping detected"}
        </span>
        <span>{l.method}</span>
      </div>
      <div className="mt-5">
        <LoudnessChart loudness={l} />
      </div>
    </AnalysisSection>
  );
}

export function SpectrumSection({ r }: { r: AnalysisResults }) {
  const s = r.spectrum;
  const maxShare = Math.max(...s.bands.map((b) => b.energy_share), 0.001);
  return (
    <AnalysisSection id="spectrum" title="Frequency spectrum" eyebrow={<ConfidenceBadge status="detected" />}>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Tonal balance" value={s.summary.brightness} hint={`centroid ${hz(s.centroid_hz.mean)}`} />
        <Stat label="Texture" value={s.summary.texture} hint={`flatness ${num(s.flatness.mean, 3)}`} />
        <Stat label="Emphasized regions" value={s.summary.emphasized_regions.length ? s.summary.emphasized_regions.join(", ") : "Even"} hint="Relative to a pink-noise balance" />
        <Stat label="Spectral peak" value={hz(s.summary.peak_frequency_hz)} hint={s.summary.peak_frequency_note ?? undefined} />
      </div>
      <div className="mt-5 grid gap-5 xl:grid-cols-[1.6fr_1fr]">
        <SpectrumChart spectrum={s} />
        <div>
          <h3 className="mb-3 text-sm font-semibold">Band energy</h3>
          <ul className="space-y-2.5">
            {s.bands.map((b) => (
              <li key={b.key}>
                <div className="mb-1 flex justify-between text-xs">
                  <span className="text-ink-2">
                    {b.name} <span className="text-ink-3">{hz(b.low_hz)}–{hz(b.high_hz)}</span>
                  </span>
                  <span className="font-medium tabular">{pct(b.energy_share, 1)}</span>
                </div>
                <div className="h-2 rounded-full bg-line">
                  <div className="h-2 rounded-full" style={{ width: `${(b.energy_share / maxShare) * 100}%`, background: "#3987e5" }} />
                </div>
              </li>
            ))}
          </ul>
          <DataTable
            caption="Band energy"
            headers={["Band", "Range", "Energy share", "Tilt-corrected dB"]}
            rows={s.bands.map((b) => [b.name, `${hz(b.low_hz)}–${hz(b.high_hz)}`, pct(b.energy_share, 1), b.tilt_corrected_db ?? "—"])}
          />
        </div>
      </div>
    </AnalysisSection>
  );
}

export function AdvancedMetrics({ r }: { r: AnalysisResults }) {
  const s = r.spectrum;
  const rows: [string, string][] = [
    ["Spectral centroid (mean ± sd)", `${hz(s.centroid_hz.mean)} ± ${hz(s.centroid_hz.std)}`],
    ["Spectral bandwidth", `${hz(s.bandwidth_hz.mean)} ± ${hz(s.bandwidth_hz.std)}`],
    ["Spectral rolloff (85%)", `${hz(s.rolloff_hz.mean)} (p10 ${hz(s.rolloff_hz.p10)}, p90 ${hz(s.rolloff_hz.p90)})`],
    ["Spectral flatness", `${num(s.flatness.mean, 4)} ± ${num(s.flatness.std, 4)}`],
    ["Zero-crossing rate", `${num(s.zero_crossing_rate.mean, 4)} ± ${num(s.zero_crossing_rate.std, 4)}`],
    ["RMS energy (rel. dB)", `${num(s.rms_db.mean, 1)} ± ${num(s.rms_db.std, 1)}`],
    ["Spectral contrast by band (dB)", Object.values(s.contrast_db).map((v) => v.toFixed(1)).join(" · ")],
    ["Crest factor", `${num(r.loudness.crest_factor_db, 1)} dB`],
    ["Sample peak", `${num(r.loudness.sample_peak_dbfs, 1)} dBFS`],
    ["Tempo drift", r.tempo.drift_percent != null ? `${r.tempo.drift_percent}%` : "—"],
    ["Meter candidates", r.meter.candidates.map((c) => `${c.signature} ${c.score}`).join(" · ") || "—"],
    ["Key method votes", Object.entries(r.key.method_votes ?? {}).map(([k, v]) => `${k.replaceAll("_", " ")}: ${v}`).join(" · ")],
    ["Key candidates", r.key.candidates?.map((c) => `${c.key} ${c.score}`).join(" · ") ?? "—"],
    ["Onset positions", Object.entries(r.rhythm.onset_positions ?? {}).map(([k, v]) => `${k.replaceAll("_", " ")} ${pct(v)}`).join(" · ")],
    ["Processing time", Object.entries(r.timings).map(([k, v]) => `${k} ${v.toFixed(1)}s`).join(" · ")],
    ["Engine", `v${r.engine_version} · schema ${r.schema_version}`],
  ];
  return (
    <details id="advanced" className="group scroll-mt-24 rounded-2xl border border-line bg-card p-5 md:p-6">
      <summary className="cursor-pointer select-none font-display text-lg font-semibold">Advanced Audio Metrics</summary>
      <dl className="mt-4 grid gap-x-8 gap-y-2 text-sm md:grid-cols-2">
        {rows.map(([k, v]) => (
          <div key={k} className="border-b border-line pb-2">
            <dt className="text-xs text-ink-3">{k}</dt>
            <dd className="mt-0.5 break-words text-ink-2 tabular">{v}</dd>
          </div>
        ))}
      </dl>
      {r.errors.length > 0 && (
        <div className="mt-4 text-sm">
          <div className="font-semibold">Stage errors</div>
          <ul className="mt-1 list-inside list-disc text-ink-2">
            {r.errors.map((e, i) => <li key={i}>{e.message}</li>)}
          </ul>
        </div>
      )}
    </details>
  );
}
