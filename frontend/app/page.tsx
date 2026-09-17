"use client";

import { Activity, AudioLines, Gauge, Layers, ListMusic, Music2, Radio, Waves } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { AudioUploader } from "@/components/AudioUploader";
import { Logo } from "@/components/ui";
import { YouTubeInput } from "@/components/YouTubeInput";
import { api } from "@/lib/api";
import { formatTime } from "@/lib/format";
import type { Health, RecentItem } from "@/types/analysis";

const FEATURES = [
  { icon: Gauge, title: "Tempo & beat grid", text: "Multiple tempo estimators, half/double-time alternatives, downbeats and stability." },
  { icon: Music2, title: "Key, chords & progressions", text: "Profile-fused key detection, HMM chord recognition and Roman-numeral analysis." },
  { icon: Activity, title: "Meter", text: "Accent-pattern analysis — reported as undetermined when the evidence is weak." },
  { icon: Layers, title: "Song structure", text: "Self-similarity segmentation with inferred Verse / Chorus labels." },
  { icon: AudioLines, title: "Pitch & melody", text: "Predominant pitch contour, range and note names." },
  { icon: Waves, title: "Loudness & spectrum", text: "BS.1770 LUFS, true peak, LRA and a playback-synced spectrum." },
];

export default function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  const [offline, setOffline] = useState(false);
  const [recent, setRecent] = useState<RecentItem[]>([]);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setOffline(true));
    api.recent(6).then((r) => setRecent(r.items.filter((i) => i.status === "completed"))).catch(() => undefined);
  }, []);

  return (
    <div className="flex min-h-screen flex-col">
      <header className="mx-auto flex w-full max-w-6xl items-center justify-between px-5 py-5">
        <Logo />
        <div className="flex items-center gap-2 text-xs text-ink-3" aria-live="polite">
          <span
            className="size-2 rounded-full"
            style={{ background: offline ? "var(--critical)" : health ? "var(--good)" : "var(--line-strong)" }}
            aria-hidden
          />
          {offline ? "Analysis server offline" : health ? `Engine ${health.engine_version}` : "Connecting…"}
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-5">
        <section className="grid grid-cols-[minmax(0,1fr)] items-start gap-10 pb-12 pt-8 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)] lg:gap-14 lg:pt-16">
          <div>
            <p className="mb-5 inline-flex items-center gap-2 rounded-full border border-line bg-card px-3 py-1 text-xs font-medium text-ink-2">
              <Radio size={13} className="text-cyan" aria-hidden /> Technical Music Analysis
            </p>
            <h1 className="font-display text-[2.6rem] font-extrabold leading-[0.95] tracking-tight [overflow-wrap:anywhere] sm:text-6xl lg:text-[3.5rem] xl:text-7xl">
              Understand
              <br />
              <span className="bg-gradient-to-r from-violet via-[#a99bff] to-cyan bg-clip-text text-transparent">Any Song.</span>
            </h1>
            <p className="mt-6 max-w-xl text-lg leading-relaxed text-ink-2">
              Upload a track or paste a YouTube link and uncover its tempo, key, chords, meter, structure and more.
            </p>
            <HeroWave />
            <p className="mt-6 max-w-lg text-sm leading-relaxed text-ink-3">
              Every result is computed from the actual audio and carries a confidence score. When the signal is
              ambiguous, SongScope says so instead of guessing.
            </p>
          </div>

          <div className="rounded-2xl border border-line bg-card/90 p-5 shadow-[0_30px_80px_-40px_rgba(139,123,255,0.35)] backdrop-blur md:p-6">
            {offline && (
              <p role="alert" className="mb-4 rounded-lg border border-line-strong bg-bg-elev px-3 py-2 text-sm text-ink-2">
                Can&apos;t reach the analysis server. Start the backend (see README) and reload.
              </p>
            )}
            {health?.capabilities.youtube !== false && <YouTubeInput disabled={offline} />}
            <div className="my-5 flex items-center gap-3 text-xs font-semibold uppercase tracking-[0.2em] text-ink-3" aria-hidden>
              <span className="h-px flex-1 bg-line" /> or <span className="h-px flex-1 bg-line" />
            </div>
            <AudioUploader maxMb={health?.limits.max_upload_mb ?? 200} disabled={offline} />
            {health && (
              <p className="mt-4 border-t border-line pt-3 text-xs leading-relaxed text-ink-3">
                Max duration {Math.round(health.limits.max_duration_seconds / 60)} min. Audio is kept temporarily
                ({health.limits.audio_retention_minutes} min) for playback and then deleted; analysis results are kept.
                YouTube downloads are subject to YouTube&apos;s terms and applicable copyright.
              </p>
            )}
          </div>
        </section>

        <section aria-label="What SongScope analyses" className="grid gap-3 border-t border-line py-10 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map(({ icon: Icon, title, text }) => (
            <div key={title} className="rounded-xl border border-line bg-card/60 p-4">
              <Icon size={18} className="text-violet" aria-hidden />
              <h3 className="mt-3 text-sm font-semibold">{title}</h3>
              <p className="mt-1 text-sm leading-snug text-ink-3">{text}</p>
            </div>
          ))}
        </section>

        {recent.length > 0 && (
          <section aria-labelledby="recent-title" className="border-t border-line py-10">
            <h2 id="recent-title" className="mb-4 flex items-center gap-2 font-display text-lg font-semibold">
              <ListMusic size={18} className="text-ink-3" aria-hidden /> Recent analyses
            </h2>
            <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {recent.map((r) => (
                <li key={r.id} className="min-w-0">
                  <Link
                    href={`/analysis/${r.id}`}
                    className="block rounded-xl border border-line bg-card p-4 transition hover:border-line-strong hover:bg-card-2"
                  >
                    <div className="truncate text-sm font-semibold">{r.title}</div>
                    <div className="truncate text-xs text-ink-3">{r.artist ?? (r.source_type === "youtube" ? "YouTube" : "Upload")}</div>
                    <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2 tabular">
                      {r.overview?.bpm != null && <span>{Math.round(r.overview.bpm)} BPM</span>}
                      {r.overview?.key && <span>{r.overview.key}</span>}
                      <span>{r.overview?.meter ?? "Meter ?"}</span>
                      {r.overview?.duration != null && <span>{formatTime(r.overview.duration)}</span>}
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}
      </main>

      <footer className="mx-auto w-full max-w-6xl px-5 py-8 text-xs text-ink-3">
        SongScope analysis is probabilistic. Detected, estimated and inferred results are labelled as such.
      </footer>
    </div>
  );
}

function HeroWave() {
  const bars = [0.3, 0.55, 0.8, 0.45, 0.95, 0.6, 0.35, 0.75, 1, 0.5, 0.3, 0.65, 0.85, 0.4, 0.7, 0.55, 0.25, 0.6, 0.9, 0.45, 0.3, 0.5];
  return (
    <div className="mt-8 flex h-14 items-end gap-[5px]" aria-hidden>
      {bars.map((h, i) => (
        <span
          key={i}
          className="eq-bar w-[5px] rounded-full bg-gradient-to-t from-violet-strong to-cyan"
          style={{ height: `${h * 100}%`, animationDelay: `${(i % 7) * 0.12}s`, opacity: 0.5 + h * 0.5 }}
        />
      ))}
    </div>
  );
}
