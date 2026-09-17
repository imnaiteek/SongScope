"use client";

import { Download, Headphones, Loader2, Sparkles, SplitSquareHorizontal } from "lucide-react";
import { useEffect, useState } from "react";

import { usePlayer } from "@/hooks/usePlayer";
import { api, ApiError } from "@/lib/api";
import { hz, pct } from "@/lib/format";
import type { AnalysisPayload, AnalysisResults, Health } from "@/types/analysis";

import { AnalysisSection, ConfidenceBadge, CopyButton } from "./ui";

export function SummaryCard({ r }: { r: AnalysisResults }) {
  return (
    <section aria-labelledby="summary-title" className="rounded-2xl border border-line bg-gradient-to-br from-card to-[#15131f] p-5 md:p-6">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 id="summary-title" className="font-display text-lg font-semibold">Musical summary</h2>
        <CopyButton text={analysisText(r)} label="Copy song analysis" />
      </div>
      <p className="max-w-4xl text-[15px] leading-relaxed text-ink-2">{r.summary.text}</p>
      <p className="mt-3 text-[11px] text-ink-3">Generated from detected values only — no language model involved.</p>
      {r.warnings.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-1.5">
          {r.warnings.map((w) => (
            <li key={w} className="rounded-md border border-line px-2 py-0.5 text-[11px] text-ink-3">{w}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function analysisText(r: AnalysisResults): string {
  const m = r.metadata;
  const main = r.progression?.main;
  return [
    `${m.title ?? "Untitled"}${m.artist ? ` — ${m.artist}` : ""}`,
    `Tempo: ${r.tempo.bpm ?? "undetermined"} BPM (${r.tempo.confidence_level} confidence)`,
    `Key: ${r.key.key ?? "undetermined"} (${pct(r.key.confidence)})`,
    `Meter: ${r.meter.reliable ? r.meter.signature : "could not be determined reliably"}`,
    main ? `Progression: ${main.chords.join(" → ")}${main.numerals ? ` (${main.numerals.join(" – ")})` : ""}` : null,
    `Structure: ${r.structure.sections.map((s) => s.display_label).join(" → ")}`,
    `Loudness: ${r.loudness.integrated_lufs} LUFS, true peak ${r.loudness.true_peak_dbtp} dBTP`,
    "",
    r.summary.text,
    "",
    "Analysed with SongScope — results are probabilistic estimates.",
  ]
    .filter((x) => x !== null)
    .join("\n");
}

export function ExportMenu({ id }: { id: string }) {
  const formats: { f: "pdf" | "json" | "csv" | "txt"; label: string }[] = [
    { f: "pdf", label: "PDF report" },
    { f: "json", label: "JSON" },
    { f: "csv", label: "CSV" },
    { f: "txt", label: "Text report" },
  ];
  return (
    <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Export analysis">
      <Download size={15} className="text-ink-3" aria-hidden />
      {formats.map(({ f, label }) => (
        <a
          key={f}
          href={api.exportUrl(id, f)}
          download
          className="rounded-lg border border-line px-2.5 py-1.5 text-xs font-medium text-ink-2 transition hover:border-line-strong hover:text-ink"
        >
          {label}
        </a>
      ))}
    </div>
  );
}

const AUDIENCE_LABEL: Record<string, string> = {
  beginner: "Beginner",
  musician: "Musician",
  guitarist: "Guitarist",
  producer: "Producer",
  drummer: "Drummer",
  singer: "Singer",
  educator: "Educator",
};

export function ExplainPanel({ data, health }: { data: AnalysisPayload; health: Health | null }) {
  const [audience, setAudience] = useState("musician");
  const [texts, setTexts] = useState<Record<string, string>>(data.explanations ?? {});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const enabled = !!health?.capabilities.llm;

  async function run(refresh = false) {
    setBusy(true);
    setError(null);
    try {
      const res = await api.explain(data.id, audience, refresh);
      setTexts((t) => ({ ...t, [audience]: res.text }));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Explanation failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AnalysisSection id="explain" title="AI explanation" eyebrow={<Sparkles size={16} className="text-violet" aria-hidden />}>
      <p className="mb-3 text-sm text-ink-3">
        A language model rewrites the <em>already computed</em> analysis for a specific audience. It receives only the structured
        results and is instructed never to invent or change numbers.
      </p>
      <div className="flex flex-wrap items-center gap-2" role="radiogroup" aria-label="Audience">
        {(health?.capabilities.llm_audiences ?? Object.keys(AUDIENCE_LABEL)).map((a) => (
          <button
            key={a}
            type="button"
            role="radio"
            aria-checked={audience === a}
            onClick={() => setAudience(a)}
            className={`rounded-full border px-3 py-1 text-xs font-medium transition ${audience === a ? "border-violet bg-violet/20 text-ink" : "border-line text-ink-2 hover:text-ink"}`}
          >
            {AUDIENCE_LABEL[a] ?? a}
          </button>
        ))}
        <button
          type="button"
          disabled={!enabled || busy}
          onClick={() => run(!!texts[audience])}
          className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-violet-strong px-3 py-1.5 text-xs font-semibold text-white hover:bg-violet disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy && <Loader2 size={13} className="animate-spin" aria-hidden />}
          {texts[audience] ? "Regenerate" : "Explain"}
        </button>
      </div>
      {!enabled && (
        <p className="mt-3 text-xs text-ink-3">Not configured on this server — set ANTHROPIC_API_KEY for the backend to enable explanations.</p>
      )}
      {error && <p role="alert" className="mt-3 text-sm" style={{ color: "#f08a8a" }}>{error}</p>}
      {texts[audience] && (
        <div className="mt-4 space-y-3 rounded-xl border border-line bg-bg-elev/60 p-4 text-[15px] leading-relaxed text-ink-2" aria-live="polite">
          {texts[audience].split(/\n{2,}/).map((para, i) => <p key={i}>{para}</p>)}
        </div>
      )}
    </AnalysisSection>
  );
}

const STEM_ORDER = ["vocals", "drums", "bass", "other"];

export function StemsPanel({ data, health, onRefresh }: { data: AnalysisPayload; health: Health | null; onRefresh: () => void }) {
  const { setSource, state } = usePlayer();
  const [error, setError] = useState<string | null>(null);
  // live status from polling is layered over the loaded payload; results always come from the payload
  const [live, setLive] = useState<Partial<AnalysisPayload["stems"]> | null>(null);
  const stems = { ...data.stems, ...(live ?? {}), results: data.stems.results };
  const available = !!health?.capabilities.stems;
  useEffect(() => {
    if (stems.status !== "queued" && stems.status !== "processing") return;
    const iv = setInterval(async () => {
      try {
        const s = await api.status(data.id);
        if (s.stems) setLive(s.stems);
        if (s.stems && (s.stems.status === "completed" || s.stems.status === "failed")) onRefresh();
      } catch {
        /* retry next tick */
      }
    }, 1500);
    return () => clearInterval(iv);
  }, [stems.status, data.id, onRefresh]);

  async function start() {
    setError(null);
    try {
      await api.startStems(data.id);
      setLive({ status: "queued", progress: 0, message: "Waiting for a worker" });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not start separation.");
    }
  }

  const results = stems.results;
  return (
    <AnalysisSection id="stems" title="Source separation" eyebrow={<SplitSquareHorizontal size={16} className="text-cyan" aria-hidden />}>
      <p className="mb-3 text-sm text-ink-3">
        Optional: split the mix into vocals, drums, bass and other with Demucs, then analyse each stem. This is CPU-intensive
        and can take several minutes, so it is never part of the basic analysis.
      </p>
      {!available && (
        <p className="rounded-lg border border-line bg-bg-elev px-3 py-2 text-sm text-ink-2">
          Stem separation is not installed on this server. {health?.capabilities.stems_reason} Install the optional
          <code className="mx-1 rounded bg-card-2 px-1">stems</code> extra (PyTorch + Demucs) to enable it.
        </p>
      )}
      {available && (stems.status === "none" || stems.status === "failed" || stems.status === "cancelled") && (
        <button
          type="button"
          onClick={start}
          disabled={!data.audio.available}
          className="rounded-lg bg-violet-strong px-4 py-2 text-sm font-semibold text-white hover:bg-violet disabled:opacity-40"
        >
          Separate stems
        </button>
      )}
      {(stems.status === "queued" || stems.status === "processing") && (
        <div aria-live="polite">
          <div className="mb-1 flex justify-between text-xs text-ink-2">
            <span>{stems.message ?? "Separating…"}</span>
            <span className="tabular">{Math.round(stems.progress * 100)}%</span>
          </div>
          <div className="h-1.5 rounded-full bg-line">
            <div className="h-1.5 rounded-full bg-gradient-to-r from-violet to-cyan transition-[width]" style={{ width: `${stems.progress * 100}%` }} />
          </div>
        </div>
      )}
      {stems.status === "failed" && stems.message && <p role="alert" className="mt-3 text-sm" style={{ color: "#f08a8a" }}>{stems.message}</p>}
      {error && <p role="alert" className="mt-3 text-sm" style={{ color: "#f08a8a" }}>{error}</p>}

      {results && (
        <>
          <div className="mb-3 mt-2 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setSource(data.audio.url ? api.absolute(data.audio.url) : null, "Full mix")}
              className={`rounded-full border px-3 py-1 text-xs ${state.sourceLabel === "Full mix" ? "border-violet bg-violet/20" : "border-line text-ink-2"}`}
            >
              Full mix
            </button>
            {STEM_ORDER.filter((s) => results.stems[s]).map((s) => (
              <button
                key={s}
                type="button"
                disabled={!results.audio_available}
                onClick={() => setSource(api.stemAudioUrl(data.id, s), `${s[0].toUpperCase()}${s.slice(1)} stem`)}
                className={`inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs capitalize disabled:opacity-40 ${state.sourceLabel.toLowerCase().startsWith(s) ? "border-violet bg-violet/20" : "border-line text-ink-2"}`}
              >
                <Headphones size={12} aria-hidden /> {s}
              </button>
            ))}
            <ConfidenceBadge confidence={results.confidence} level={results.confidence_level} status={results.status} compact />
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {STEM_ORDER.filter((s) => results.stems[s]).map((s) => {
              const st = results.stems[s];
              return (
                <div key={s} className="rounded-xl border border-line bg-bg-elev/60 p-4 text-sm">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="font-semibold capitalize">{s}</span>
                    <span className="text-xs text-ink-3 tabular">{pct(st.energy_share)} of energy</span>
                  </div>
                  <dl className="space-y-1 text-xs">
                    <Row k="Loudness" v={st.integrated_lufs != null ? `${st.integrated_lufs} LUFS` : "—"} />
                    <Row k="Brightness" v={`${st.brightness} · ${hz(st.spectral_centroid_hz)}`} />
                    {st.tempo && <Row k="Tempo" v={st.tempo.bpm ? `${st.tempo.bpm} BPM (${st.tempo.confidence_level})` : "—"} />}
                    {st.pitch && (
                      <>
                        <Row k="Range" v={st.pitch.lowest_note ? `${st.pitch.lowest_note}–${st.pitch.highest_note}` : "—"} />
                        <Row k="Most frequent" v={st.pitch.most_frequent_note ?? "—"} />
                        <Row k="Pitch confidence" v={st.pitch.confidence_level ?? "—"} />
                      </>
                    )}
                  </dl>
                </div>
              );
            })}
          </div>
          <p className="mt-3 text-xs text-ink-3">{results.message}</p>
        </>
      )}
    </AnalysisSection>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-2">
      <dt className="text-ink-3">{k}</dt>
      <dd className="text-right text-ink-2">{v}</dd>
    </div>
  );
}
