"use client";

import { Pause, Play, RotateCcw, RotateCw, Volume2, VolumeX } from "lucide-react";
import { useEffect } from "react";

import { useCurrentTime, usePlayer } from "@/hooks/usePlayer";
import { formatTime } from "@/lib/format";

const RATES = [0.5, 0.75, 1, 1.25, 1.5];

export function AudioPlayer({ duration, expiredNote }: { duration: number; expiredNote?: string | null }) {
  const { state, toggle, skip, seek, setVolume, setMuted, setRate } = usePlayer();
  const t = useCurrentTime(0.1);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.closest("input, textarea, select, [contenteditable=true]") || e.metaKey || e.ctrlKey || e.altKey)) return;
      if (e.code === "Space" && !(el instanceof HTMLButtonElement)) {
        e.preventDefault();
        toggle();
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        skip(-5);
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        skip(5);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggle, skip]);

  const disabled = !state.hasAudio;
  return (
    <div
      className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-bg/90 backdrop-blur-md"
      role="region"
      aria-label="Audio player. Space: play or pause. Left and right arrows: skip 5 seconds."
    >
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 md:flex-nowrap">
        <div className="flex items-center gap-1">
          <button type="button" onClick={() => skip(-5)} className="rounded-full p-2 text-ink-2 hover:bg-card-2 hover:text-ink" aria-label="Back 5 seconds">
            <RotateCcw size={18} />
          </button>
          <button
            type="button"
            onClick={toggle}
            disabled={disabled}
            className="grid size-11 place-items-center rounded-full bg-ink text-bg transition hover:scale-105 disabled:cursor-not-allowed disabled:opacity-40"
            aria-label={state.playing ? "Pause" : "Play"}
          >
            {state.playing ? <Pause size={20} fill="currentColor" /> : <Play size={20} fill="currentColor" className="translate-x-[1px]" />}
          </button>
          <button type="button" onClick={() => skip(5)} className="rounded-full p-2 text-ink-2 hover:bg-card-2 hover:text-ink" aria-label="Forward 5 seconds">
            <RotateCw size={18} />
          </button>
        </div>

        <div className="order-last flex w-full min-w-0 items-center gap-3 md:order-none md:flex-1">
          <span className="w-12 text-right font-mono text-xs tabular text-ink-2">{formatTime(t)}</span>
          <input
            type="range"
            className="slider min-w-0 flex-1"
            min={0}
            max={duration}
            step={0.1}
            value={Math.min(t, duration)}
            onChange={(e) => seek(Number(e.target.value))}
            aria-label="Seek"
            aria-valuetext={`${formatTime(t)} of ${formatTime(duration)}`}
          />
          <span className="w-12 font-mono text-xs tabular text-ink-3">{formatTime(duration)}</span>
        </div>

        <div className="flex items-center gap-3">
          <span className="hidden rounded-md border border-line px-2 py-1 text-[11px] text-ink-2 lg:inline">{state.sourceLabel}</span>
          <label className="flex items-center gap-1.5 text-xs text-ink-3">
            <span className="sr-only">Playback speed</span>
            <select
              value={state.rate}
              onChange={(e) => setRate(Number(e.target.value))}
              className="rounded-md border border-line bg-card px-1.5 py-1 text-xs text-ink"
            >
              {RATES.map((r) => (
                <option key={r} value={r}>
                  {r}×
                </option>
              ))}
            </select>
          </label>
          <button type="button" onClick={() => setMuted(!state.muted)} className="p-1.5 text-ink-2 hover:text-ink" aria-label={state.muted ? "Unmute" : "Mute"}>
            {state.muted || state.volume === 0 ? <VolumeX size={18} /> : <Volume2 size={18} />}
          </button>
          <input
            type="range"
            className="slider w-20"
            min={0}
            max={1}
            step={0.01}
            value={state.muted ? 0 : state.volume}
            onChange={(e) => {
              setVolume(Number(e.target.value));
              if (state.muted) setMuted(false);
            }}
            aria-label="Volume"
          />
        </div>
      </div>
      {(disabled || state.error) && (
        <p className="mx-auto max-w-7xl px-4 pb-2 text-xs text-ink-3">
          {state.error ?? expiredNote ?? "Audio playback is unavailable. The timeline still works for browsing."}
        </p>
      )}
    </div>
  );
}
