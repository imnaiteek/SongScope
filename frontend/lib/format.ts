import type { ConfidenceLevel } from "@/types/analysis";

export function formatTime(sec: number | null | undefined, withTenths = false): string {
  if (sec == null || !Number.isFinite(sec)) return "—";
  const s = Math.max(0, sec);
  const m = Math.floor(s / 60);
  const rest = s - m * 60;
  if (withTenths) return `${m}:${rest.toFixed(1).padStart(4, "0")}`;
  return `${m}:${Math.floor(rest).toString().padStart(2, "0")}`;
}

export function pct(x: number | null | undefined, digits = 0): string {
  if (x == null || !Number.isFinite(x)) return "—";
  return `${(x * 100).toFixed(digits)}%`;
}

export function num(x: number | null | undefined, digits = 1, unit = ""): string {
  if (x == null || !Number.isFinite(x)) return "—";
  return `${x.toFixed(digits)}${unit ? ` ${unit}` : ""}`;
}

export function bytes(n: number | null | undefined): string {
  if (!n) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

export function hz(x: number | null | undefined): string {
  if (x == null || !Number.isFinite(x)) return "—";
  return x >= 1000 ? `${(x / 1000).toFixed(x >= 10000 ? 0 : 1)} kHz` : `${Math.round(x)} Hz`;
}

export const LEVEL_LABEL: Record<ConfidenceLevel, string> = {
  high: "High confidence",
  medium: "Medium confidence",
  low: "Low confidence",
};

const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

export function midiToNote(m: number): string {
  const r = Math.round(m);
  return `${NOTE_NAMES[((r % 12) + 12) % 12]}${Math.floor(r / 12) - 1}`;
}

export function hzToNote(f: number): string | null {
  if (!(f > 0)) return null;
  const midi = 69 + 12 * Math.log2(f / 440);
  const cents = Math.round((midi - Math.round(midi)) * 100);
  return `${midiToNote(midi)}${cents ? ` ${cents > 0 ? "+" : ""}${cents}¢` : ""}`;
}

/** Validated categorical slots (dark mode), assigned by section group letter in fixed order. */
const SERIES = ["--series-1", "--series-2", "--series-3", "--series-4", "--series-5", "--series-6", "--series-7", "--series-8"];
export const SERIES_HEX = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];

export function groupColor(group: string): string {
  const idx = group.charCodeAt(0) - 65;
  return idx >= 0 && idx < SERIES.length ? `var(${SERIES[idx]})` : "var(--series-other)";
}

export function groupHex(group: string): string {
  const idx = group.charCodeAt(0) - 65;
  return idx >= 0 && idx < SERIES_HEX.length ? SERIES_HEX[idx] : "#6b6a66";
}

/** Sequential single-hue ramp (blue) for magnitudes on the dark surface: 0 → near-surface, 1 → bright. */
const SEQ = ["#0d1a2e", "#0d366b", "#104281", "#184f95", "#1c5cab", "#256abf", "#2a78d6", "#3987e5", "#5598e7", "#6da7ec", "#86b6ef", "#b7d3f6"];

export function seqColor(v: number): string {
  const x = Math.min(1, Math.max(0, v));
  return SEQ[Math.min(SEQ.length - 1, Math.floor(x * SEQ.length))];
}

export function clamp(v: number, lo: number, hi: number) {
  return Math.min(hi, Math.max(lo, v));
}

export function findIndexAt<T extends { start: number; end: number }>(items: T[], t: number): number {
  let lo = 0;
  let hi = items.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (t < items[mid].start) hi = mid - 1;
    else if (t >= items[mid].end) lo = mid + 1;
    else return mid;
  }
  return -1;
}

/** Index of the last value <= t in a sorted array (or -1). */
export function lastIndexLE(arr: number[], t: number): number {
  let lo = 0;
  let hi = arr.length - 1;
  let ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (arr[mid] <= t) {
      ans = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return ans;
}
