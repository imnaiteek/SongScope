"use client";

import { AlertOctagon, ArrowLeft, ExternalLink, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AnalysisProgress } from "@/components/AnalysisProgress";
import { AudioPlayer } from "@/components/AudioPlayer";
import { ChordTimeline } from "@/components/ChordTimeline";
import { ExplainPanel, ExportMenu, StemsPanel, SummaryCard } from "@/components/ExtrasPanels";
import { HarmonySection } from "@/components/HarmonySection";
import { OverviewCards } from "@/components/OverviewCards";
import { RhythmSection } from "@/components/RhythmSection";
import { AdvancedMetrics, LoudnessSection, PitchSection, SpectrumSection } from "@/components/SignalSections";
import { SongStructure } from "@/components/SongStructure";
import { Logo } from "@/components/ui";
import { Waveform } from "@/components/Waveform";
import { PlayerProvider } from "@/hooks/usePlayer";
import { useAnalysis } from "@/hooks/useAnalysis";
import { api } from "@/lib/api";
import { bytes, formatTime } from "@/lib/format";
import type { AnalysisPayload, Health } from "@/types/analysis";

const NAV = [
  ["timeline", "Timeline"],
  ["harmony", "Harmony"],
  ["chords", "Chords"],
  ["rhythm", "Rhythm"],
  ["structure", "Structure"],
  ["pitch", "Pitch"],
  ["loudness", "Loudness"],
  ["spectrum", "Spectrum"],
  ["stems", "Stems"],
  ["explain", "AI"],
  ["advanced", "Advanced"],
] as const;

export default function AnalysisPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { status, data, error, reload } = useAnalysis(id);
  const [cancelling, setCancelling] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => undefined);
  }, []);

  useEffect(() => {
    const title = data?.results?.metadata.title ?? status?.title;
    if (title) document.title = `${title} · SongScope`;
  }, [data, status]);

  const header = (
    <header className="sticky top-0 z-30 border-b border-line bg-bg/85 backdrop-blur-md">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3">
        <div className="flex items-center gap-4">
          <Link href="/" className="rounded-md p-1 text-ink-3 hover:text-ink" aria-label="Back to home">
            <ArrowLeft size={18} />
          </Link>
          <Link href="/" aria-label="SongScope home">
            <Logo size={24} />
          </Link>
        </div>
        {data?.status === "completed" && (
          <div className="flex items-center gap-3">
            <div className="hidden md:block">
              <ExportMenu id={id} />
            </div>
            <button
              type="button"
              onClick={async () => {
                if (!confirm("Delete this analysis and any stored audio? This cannot be undone.")) return;
                await api.remove(id).catch(() => undefined);
                router.push("/");
              }}
              className="rounded-lg border border-line p-1.5 text-ink-3 hover:text-ink"
              aria-label="Delete analysis"
            >
              <Trash2 size={16} />
            </button>
          </div>
        )}
      </div>
    </header>
  );

  if (error) {
    return (
      <>
        {header}
        <CenteredMessage title={error.status === 404 ? "Analysis not found" : "Something went wrong"} text={error.message} />
      </>
    );
  }

  if (!status) {
    return (
      <>
        {header}
        <div className="grid flex-1 place-items-center text-sm text-ink-3" aria-live="polite">Loading…</div>
      </>
    );
  }

  if (status.status === "failed" || status.status === "cancelled") {
    return (
      <>
        {header}
        <CenteredMessage
          title={status.status === "failed" ? "Analysis failed" : "Analysis cancelled"}
          text={status.error?.message ?? status.message ?? "The analysis did not complete."}
          code={status.error?.code}
        />
      </>
    );
  }

  if (status.status !== "completed" || !data?.results) {
    return (
      <>
        {header}
        <main className="flex flex-1 items-start justify-center px-4 py-10 md:py-16">
          <AnalysisProgress
            status={status}
            cancelling={cancelling}
            onCancel={async () => {
              setCancelling(true);
              await api.cancel(id).catch(() => undefined);
            }}
          />
        </main>
      </>
    );
  }

  return <Dashboard data={data} header={header} health={health} reload={reload} />;
}

function Dashboard({ data, header, health, reload }: { data: AnalysisPayload; header: React.ReactNode; health: Health | null; reload: () => void }) {
  const r = data.results!;
  const m = r.metadata;
  const audioSrc = data.audio.available && data.audio.url ? api.absolute(data.audio.url) : null;
  const expiredNote = !data.audio.available
    ? "Audio is no longer stored for this analysis (temporary retention). Re-upload the file to listen — the results remain."
    : null;

  return (
    <PlayerProvider src={audioSrc} duration={m.duration}>
      {header}
      <main className="mx-auto w-full max-w-7xl flex-1 space-y-5 px-4 pb-40 pt-6">
        <section className="flex flex-wrap items-end justify-between gap-4">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-ink-3">
              {m.source_type === "youtube" ? "YouTube" : "Uploaded file"}
            </p>
            <h1 className="mt-1 max-w-4xl font-display text-2xl font-bold leading-tight tracking-tight [overflow-wrap:anywhere] sm:text-3xl md:text-4xl">{m.title ?? "Untitled"}</h1>
            <p className="mt-1 text-ink-2">
              {[m.artist, m.album, m.year?.slice(0, 4)].filter(Boolean).join(" · ") || (m.youtube?.channel ?? "Unknown artist")}
              {m.youtube?.url && (
                <a href={m.youtube.url} target="_blank" rel="noopener noreferrer" className="ml-2 inline-flex items-center gap-1 text-sm text-violet hover:underline">
                  Source <ExternalLink size={12} aria-hidden />
                </a>
              )}
            </p>
          </div>
          <dl className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-ink-3">
            <Meta k="Duration" v={formatTime(m.duration)} />
            <Meta k="Sample rate" v={m.sample_rate ? `${(m.sample_rate / 1000).toFixed(1)} kHz` : "—"} />
            <Meta k="Channels" v={m.channels === 2 ? "Stereo" : m.channels === 1 ? "Mono" : String(m.channels ?? "—")} />
            <Meta k="Bit depth" v={m.bit_depth ? `${m.bit_depth}-bit` : "n/a (lossy)"} />
            <Meta k="Format" v={`${m.format ?? "—"}${m.codec ? ` (${m.codec})` : ""}`} />
            <Meta k="Bitrate" v={m.bit_rate ? `${Math.round(m.bit_rate / 1000)} kbps` : "—"} />
            <Meta k="Size" v={bytes(m.file_size)} />
            <Meta k="Loudness" v={r.loudness.integrated_lufs != null ? `${r.loudness.integrated_lufs} LUFS` : "—"} />
          </dl>
        </section>

        <div className="md:hidden">
          <ExportMenu id={data.id} />
        </div>

        <OverviewCards r={r} />
        <SummaryCard r={r} />

        <nav aria-label="Analysis sections" className="scrollbar-thin sticky top-[57px] z-20 -mx-4 overflow-x-auto border-y border-line bg-bg/85 px-4 py-2 backdrop-blur-md">
          <ul className="flex gap-1 text-sm">
            {NAV.map(([hash, label]) => (
              <li key={hash}>
                <a href={`#${hash}`} className="block whitespace-nowrap rounded-md px-2.5 py-1 text-ink-2 hover:bg-card-2 hover:text-ink">
                  {label}
                </a>
              </li>
            ))}
          </ul>
        </nav>

        <section id="timeline" aria-labelledby="timeline-title" className="scroll-mt-28 rounded-2xl border border-line bg-card p-5 md:p-6">
          <h2 id="timeline-title" className="sr-only">Interactive timeline</h2>
          <Waveform results={r} />
        </section>

        <HarmonySection r={r} />
        <ChordTimeline chords={r.chords} />
        <RhythmSection r={r} />
        <SongStructure r={r} />
        <PitchSection r={r} />
        <LoudnessSection r={r} />
        <SpectrumSection r={r} />
        <StemsPanel data={data} health={health} onRefresh={reload} />
        <ExplainPanel data={data} health={health} />
        <AdvancedMetrics r={r} />
      </main>
      <AudioPlayer duration={m.duration} expiredNote={expiredNote} />
    </PlayerProvider>
  );
}

function Meta({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <dt className="inline">{k}: </dt>
      <dd className="inline font-medium text-ink-2">{v}</dd>
    </div>
  );
}

function CenteredMessage({ title, text, code }: { title: string; text: string; code?: string | null }) {
  return (
    <main className="flex flex-1 items-center justify-center px-4 py-16">
      <div className="max-w-lg rounded-2xl border border-line bg-card p-8 text-center" role="alert">
        <AlertOctagon size={28} className="mx-auto" style={{ color: "var(--critical)" }} aria-hidden />
        <h1 className="mt-3 font-display text-2xl font-bold">{title}</h1>
        <p className="mt-2 text-ink-2">{text}</p>
        {code && <p className="mt-2 font-mono text-xs text-ink-3">{code}</p>}
        <Link href="/" className="mt-6 inline-block rounded-lg bg-violet-strong px-4 py-2 text-sm font-semibold text-white hover:bg-violet">
          Analyze another track
        </Link>
      </div>
    </main>
  );
}
