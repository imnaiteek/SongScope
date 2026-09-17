"use client";

import { ArrowRight } from "lucide-react";

import { usePlayer } from "@/hooks/usePlayer";
import { formatTime, pct } from "@/lib/format";
import type { AnalysisResults } from "@/types/analysis";

import { Chromagram } from "./charts/Chromagram";
import { AnalysisSection, CertaintyTag, ConfidenceBadge, CopyButton, DataTable, InfoTip, LowConfidenceNote, Stat } from "./ui";

export function HarmonySection({ r }: { r: AnalysisResults }) {
  const { key, harmony, progression } = r;
  const { seek } = usePlayer();
  const main = progression?.main;
  const dist = harmony?.chroma_distribution ?? [];
  const maxDist = Math.max(...dist.map((d) => d.value), 0.001);

  return (
    <AnalysisSection id="harmony" title="Harmony" eyebrow={<ConfidenceBadge confidence={key.confidence} level={key.confidence_level} status={key.status} />}>
      <div className="grid gap-4 lg:grid-cols-[1.1fr_1fr]">
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Stat label="Detected key" value={key.key ?? "—"} hint={`Scale certainty ${pct(key.scale_confidence)}`} />
            <Stat label="Alternative" value={key.alternative_key ?? "—"} hint={key.alternative_relation ? `${key.alternative_relation} key` : undefined} />
            <Stat label="Tuning" value={`A4 ${key.reference_a4_hz}`} unit="Hz" hint={`${key.tuning_cents > 0 ? "+" : ""}${key.tuning_cents} cents from 440`} />
          </div>

          <div className="rounded-xl border border-line bg-bg-elev/60 p-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.1em] text-ink-3">
                  Tonic (tonal centre) <CertaintyTag status={key.status} />
                </div>
                <div className="mt-1 font-display text-3xl font-bold">{key.tonic ?? "—"}</div>
              </div>
              <div>
                <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.1em] text-ink-3">
                  Most prominent pitch class <CertaintyTag status="detected" />
                </div>
                <div className="mt-1 font-display text-3xl font-bold">{key.most_prominent_pitch_class ?? "—"}</div>
              </div>
            </div>
            <p className="mt-3 text-[13px] leading-snug text-ink-3">
              The most frequently sounding note is not necessarily the tonal centre. The tonic is the note the harmony
              resolves to; a dominant or melody note can sound more often
              {key.tonic && key.most_prominent_pitch_class && key.tonic !== key.most_prominent_pitch_class
                ? ` — here ${key.most_prominent_pitch_class} is most prominent while ${key.tonic} is the detected tonic.`
                : "."}
            </p>
          </div>

          <div className="rounded-xl border border-line bg-bg-elev/60 p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-semibold">Main chord progression</h3>
                {progression.available !== false && <ConfidenceBadge confidence={progression.confidence} level={progression.confidence_level} status={progression.status} compact />}
              </div>
              {main && <CopyButton text={`${main.chords.join(" - ")}${main.numerals ? `  (${main.numerals.join(" - ")})` : ""}`} label="Copy chord progression" />}
            </div>
            {main ? (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  {main.chords.map((c, i) => (
                    <span key={i} className="flex items-center gap-2">
                      <span className="flex min-w-14 flex-col items-center rounded-lg border border-line-strong bg-card px-3 py-2">
                        <span className="text-lg font-bold">{c}</span>
                        {main.numerals && <span className="font-mono text-xs text-ink-3">{main.numerals[i]}</span>}
                      </span>
                      {i < main.chords.length - 1 && <ArrowRight size={14} className="text-ink-3" aria-hidden />}
                    </span>
                  ))}
                </div>
                <p className="mt-3 text-xs text-ink-3">
                  Repeats {main.count}× · covers {pct(main.coverage)} of the chord sequence · first at{" "}
                  <button type="button" className="text-violet hover:underline" onClick={() => seek(main.occurrences[0]?.start ?? 0)}>
                    {formatTime(main.occurrences[0]?.start)}
                  </button>
                </p>
                {progression.others.length > 0 && (
                  <div className="mt-3 border-t border-line pt-3">
                    <div className="mb-1.5 text-xs font-medium text-ink-3">Other recurring progressions</div>
                    <ul className="space-y-1 text-sm">
                      {progression.others.map((p, i) => (
                        <li key={i} className="flex flex-wrap items-baseline gap-x-3">
                          <span className="font-semibold">{p.display}</span>
                          {p.numerals_display && <span className="font-mono text-xs text-ink-3">{p.numerals_display}</span>}
                          <span className="text-xs text-ink-3">×{p.count}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </>
            ) : (
              <p className="text-sm text-ink-3">{progression.message ?? "No clearly repeating progression was found."}</p>
            )}
          </div>
        </div>

        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <Stat label="Harmonic complexity" value={harmony.complexity_label} hint={`${pct(harmony.harmonic_complexity)} · ${harmony.unique_chords} unique chords`} />
            <Stat label="Harmonic stability" value={harmony.stability_label} hint={`${pct(harmony.harmonic_stability)} · ${pct(harmony.non_diatonic_share)} non-diatonic`} />
            <Stat label="Chord changes" value={harmony.chord_changes_per_minute ?? "—"} unit="/ min" />
            <Stat label="Extended chords" value={pct(harmony.extended_chord_share)} hint="7ths, sus, dim, aug" />
          </div>

          <div className="rounded-xl border border-line bg-bg-elev/60 p-4">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
              Pitch-class distribution <InfoTip text="Energy of each pitch class across the whole track (chroma), relative to the strongest." />
            </div>
            <div className="flex h-32 items-end gap-[2px]" role="img" aria-label="Bar chart of pitch-class energy">
              {dist.map((d) => (
                <div key={d.pitch_class} className="group flex h-full flex-1 flex-col items-center justify-end gap-1" title={`${d.pitch_class}: ${pct(d.value)}`}>
                  <div
                    className="w-full rounded-t-[4px]"
                    style={{ height: `${(d.value / maxDist) * 100}%`, background: d.pitch_class === key.tonic ? "#3987e5" : "#2a4f7d" }}
                  />
                  <span className={`text-[10px] ${d.pitch_class === key.tonic ? "font-bold text-ink" : "text-ink-3"}`}>{d.pitch_class}</span>
                </div>
              ))}
            </div>
            <p className="mt-2 text-[11px] text-ink-3">Brighter bar = detected tonic.</p>
            <DataTable caption="Pitch-class distribution" headers={["Pitch class", "Relative energy"]} rows={dist.map((d) => [d.pitch_class, pct(d.value)])} />
          </div>

          {key.changes?.length > 0 && (
            <div className="rounded-xl border border-line bg-bg-elev/60 p-4 text-sm">
              <div className="mb-2 font-semibold">Possible key changes</div>
              <ul className="space-y-1">
                {key.changes.map((c, i) => (
                  <li key={i}>
                    <button type="button" className="text-violet hover:underline" onClick={() => seek(c.start)}>{formatTime(c.start)}</button>{" "}
                    → {c.key} <span className="text-xs text-ink-3">({pct(c.confidence)})</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>

      <div className="mt-5">
        <h3 className="mb-2 text-sm font-semibold">Chromagram</h3>
        <Chromagram harmony={harmony} />
      </div>
      <LowConfidenceNote level={key.confidence_level} message={key.message} />
    </AnalysisSection>
  );
}
