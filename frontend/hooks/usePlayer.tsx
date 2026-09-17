"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

type Listener = () => void;

class Store<T> {
  private listeners = new Set<Listener>();
  constructor(private value: T) {}
  get = () => this.value;
  set = (v: T) => {
    if (Object.is(v, this.value)) return;
    this.value = v;
    this.listeners.forEach((l) => l());
  };
  subscribe = (l: Listener) => {
    this.listeners.add(l);
    return () => this.listeners.delete(l);
  };
}

export interface TimelineView {
  start: number;
  end: number;
}

export interface PlayerState {
  playing: boolean;
  duration: number;
  volume: number;
  muted: boolean;
  rate: number;
  hasAudio: boolean;
  sourceLabel: string;
  /** URL currently loaded into the shared media element (null when audio is unavailable). */
  src: string | null;
  error: string | null;
}

interface PlayerApi {
  audio: HTMLAudioElement | null;
  time: Store<number>;
  view: Store<TimelineView>;
  state: PlayerState;
  seek: (t: number) => void;
  toggle: () => void;
  play: () => void;
  pause: () => void;
  skip: (delta: number) => void;
  setVolume: (v: number) => void;
  setMuted: (m: boolean) => void;
  setRate: (r: number) => void;
  setSource: (url: string | null, label: string) => void;
}

const Ctx = createContext<PlayerApi | null>(null);

export function PlayerProvider({ src, duration, children }: { src: string | null; duration: number; children: React.ReactNode }) {
  // The dashboard only mounts client-side after data loads, but guard for SSR anyway.
  const [audioEl] = useState<HTMLAudioElement | null>(() => {
    if (typeof window === "undefined") return null;
    const a = new Audio();
    a.preload = "metadata";
    a.volume = 0.9;
    if (src) a.src = src;
    return a;
  });
  const audioRef = useRef<HTMLAudioElement | null>(audioEl);
  const time = useMemo(() => new Store(0), []);
  const view = useMemo(() => new Store<TimelineView>({ start: 0, end: duration }), [duration]);
  const [state, setState] = useState<PlayerState>({
    playing: false, duration, volume: 0.9, muted: false, rate: 1, hasAudio: !!src, sourceLabel: "Full mix", src, error: null,
  });

  useEffect(() => {
    const a = audioEl;
    if (!a) return;
    let raf = 0;
    const tick = () => {
      time.set(a.currentTime);
      raf = requestAnimationFrame(tick);
    };
    const onPlay = () => {
      setState((s) => ({ ...s, playing: true }));
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(tick);
    };
    const onPause = () => {
      setState((s) => ({ ...s, playing: false }));
      cancelAnimationFrame(raf);
      time.set(a.currentTime);
    };
    const onSeeked = () => time.set(a.currentTime);
    const onError = () =>
      setState((s) => ({ ...s, playing: false, error: "Audio could not be loaded (it may have expired on the server)." }));
    const onVolume = () => setState((s) => ({ ...s, volume: a.volume, muted: a.muted }));
    const onRate = () => setState((s) => ({ ...s, rate: a.playbackRate }));
    a.addEventListener("play", onPlay);
    a.addEventListener("pause", onPause);
    a.addEventListener("ended", onPause);
    a.addEventListener("seeked", onSeeked);
    a.addEventListener("error", onError);
    a.addEventListener("volumechange", onVolume);
    a.addEventListener("ratechange", onRate);
    return () => {
      cancelAnimationFrame(raf);
      a.pause();
      a.removeAttribute("src");
      a.load();
      a.removeEventListener("play", onPlay);
      a.removeEventListener("pause", onPause);
      a.removeEventListener("ended", onPause);
      a.removeEventListener("seeked", onSeeked);
      a.removeEventListener("error", onError);
      a.removeEventListener("volumechange", onVolume);
      a.removeEventListener("ratechange", onRate);
    };
  }, [audioEl, time]);

  const setSource = useCallback(
    (url: string | null, label: string) => {
      const a = audioRef.current;
      if (!a) return;
      const t = a.currentTime;
      const wasPlaying = !a.paused;
      if (url && a.src === url) {
        setState((s) => ({ ...s, hasAudio: true, sourceLabel: label, src: url, error: null }));
        return;
      }
      if (url) {
        a.src = url;
        a.currentTime = t;
        if (wasPlaying) void a.play().catch(() => undefined);
      } else {
        a.pause();
        a.removeAttribute("src");
      }
      setState((s) => ({ ...s, hasAudio: !!url, sourceLabel: label, src: url, error: null }));
    },
    [],
  );

  useEffect(() => {
    if (audioEl) setSource(src, "Full mix");
  }, [audioEl, src, setSource]);

  const api = useMemo<PlayerApi>(() => {
    const clampT = (t: number) => Math.max(0, Math.min(duration, t));
    return {
      audio: audioEl,
      time,
      view,
      state,
      seek: (t) => {
        const v = clampT(t);
        const a = audioRef.current;
        if (a && state.hasAudio) a.currentTime = v;
        time.set(v);
      },
      play: () => void audioRef.current?.play().catch(() => undefined),
      pause: () => audioRef.current?.pause(),
      toggle: () => {
        const a = audioRef.current;
        if (!a || !state.hasAudio) return;
        if (a.paused) void a.play().catch(() => undefined);
        else a.pause();
      },
      skip: (d) => {
        const a = audioRef.current;
        const v = clampT((a && state.hasAudio ? a.currentTime : time.get()) + d);
        if (a && state.hasAudio) a.currentTime = v;
        time.set(v);
      },
      setVolume: (v) => {
        if (audioRef.current) audioRef.current.volume = v;
      },
      setMuted: (m) => {
        if (audioRef.current) audioRef.current.muted = m;
      },
      setRate: (r) => {
        if (audioRef.current) {
          audioRef.current.playbackRate = r;
          audioRef.current.preservesPitch = true;
        }
      },
      setSource,
    };
  }, [audioEl, duration, setSource, state, time, view]);

  return <Ctx.Provider value={api}>{children}</Ctx.Provider>;
}

export function usePlayer(): PlayerApi {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("usePlayer must be used inside PlayerProvider");
  return ctx;
}

/** Current playhead time; re-renders subscribers at animation-frame rate. */
export function useCurrentTime(quantum = 0): number {
  const { time } = usePlayer();
  const getSnapshot = useCallback(() => (quantum > 0 ? Math.floor(time.get() / quantum) * quantum : time.get()), [time, quantum]);
  return useSyncExternalStore(time.subscribe, getSnapshot, getSnapshot);
}

/**
 * Visible timeline window. Pass `throttleMs` for expensive consumers (canvas charts): during
 * auto-scrolling playback the view changes every frame, and charts only need a few redraws per second.
 */
export function useTimelineView(throttleMs = 0): TimelineView {
  const { view } = usePlayer();
  const subscribe = useCallback(
    (notify: () => void) => {
      if (throttleMs <= 0) return view.subscribe(notify);
      let last = 0;
      let timer: ReturnType<typeof setTimeout> | null = null;
      const unsub = view.subscribe(() => {
        const now = performance.now();
        if (now - last >= throttleMs) {
          last = now;
          notify();
        } else if (!timer) {
          timer = setTimeout(() => {
            timer = null;
            last = performance.now();
            notify();
          }, throttleMs - (now - last));
        }
      });
      return () => {
        unsub();
        if (timer) clearTimeout(timer);
      };
    },
    [view, throttleMs],
  );
  return useSyncExternalStore(subscribe, view.get, view.get);
}
