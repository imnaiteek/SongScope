"use client";

import { AlertTriangle, CheckCircle2, CircleHelp, Info } from "lucide-react";
import { useState } from "react";

import { LEVEL_LABEL, pct } from "@/lib/format";
import type { Certainty, ConfidenceLevel } from "@/types/analysis";

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
        <defs>
          <linearGradient id="ss-g" x1="0" x2="1" y1="0" y2="1">
            <stop offset="0" stopColor="#8b7bff" />
            <stop offset="1" stopColor="#3ad3e0" />
          </linearGradient>
        </defs>
        <circle cx="16" cy="16" r="14.5" fill="none" stroke="url(#ss-g)" strokeWidth="2" />
        {[7, 11, 15, 19, 23].map((x, i) => (
          <rect key={x} x={x - 1} y={16 - [4, 8, 11, 7, 3][i]} width="2" height={[8, 16, 22, 14, 6][i]} rx="1" fill="url(#ss-g)" />
        ))}
      </svg>
      <span className="font-display text-[1.15rem] font-bold tracking-tight">SongScope</span>
    </span>
  );
}

const CERTAINTY_HELP: Record<Certainty, string> = {
  detected: "Detected — a direct measurement of the signal.",
  estimated: "Estimated — a statistical estimate from the audio.",
  inferred: "Inferred — derived from other estimates using musical heuristics.",
  uncertain: "Uncertain — confidence is too low to rely on. Verify by ear.",
};

export function ConfidenceBadge({
  confidence,
  level,
  status,
  compact = false,
}: {
  confidence?: number | null;
  level?: ConfidenceLevel | null;
  status?: Certainty | null;
  compact?: boolean;
}) {
  const lv: ConfidenceLevel = level ?? "low";
  if (status === "detected") {
    return (
      <span
        className="inline-flex items-center gap-1 rounded-full border border-line px-2 py-0.5 text-[11px] font-medium text-ink-2"
        title={CERTAINTY_HELP.detected}
      >
        <CheckCircle2 size={12} aria-hidden className="text-ink-3" /> Measured
      </span>
    );
  }
  const color = lv === "high" ? "var(--good)" : lv === "medium" ? "var(--warning)" : "var(--critical)";
  const Icon = lv === "high" ? CheckCircle2 : lv === "medium" ? Info : AlertTriangle;
  const label = compact ? lv[0].toUpperCase() + lv.slice(1) : LEVEL_LABEL[lv];
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium text-ink"
      style={{ borderColor: `color-mix(in oklab, ${color} 55%, transparent)`, background: `color-mix(in oklab, ${color} 12%, transparent)` }}
      title={status ? CERTAINTY_HELP[status] : undefined}
    >
      <Icon size={12} aria-hidden style={{ color }} />
      <span>{label}</span>
      {confidence != null && <span className="tabular text-ink-2">{pct(confidence)}</span>}
    </span>
  );
}

export function CertaintyTag({ status }: { status?: Certainty | null }) {
  if (!status) return null;
  return (
    <span className="rounded-md bg-card-2 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-ink-3" title={CERTAINTY_HELP[status]}>
      {status}
    </span>
  );
}

export function LowConfidenceNote({ level, message }: { level?: ConfidenceLevel; message?: string | null }) {
  if (!message && level !== "low") return null;
  const low = level === "low";
  return (
    <p
      className="mt-3 flex items-start gap-2 rounded-lg border px-3 py-2 text-[13px] leading-snug text-ink-2"
      style={{ borderColor: low ? "color-mix(in oklab, var(--critical) 45%, transparent)" : "var(--line)" }}
    >
      {low ? <AlertTriangle size={15} className="mt-0.5 shrink-0" style={{ color: "var(--critical)" }} aria-hidden /> : <Info size={15} className="mt-0.5 shrink-0 text-ink-3" aria-hidden />}
      <span>{message ?? "Low confidence — verify manually."}</span>
    </p>
  );
}

export function AnalysisSection({
  id,
  title,
  eyebrow,
  actions,
  children,
  className = "",
}: {
  id?: string;
  title: string;
  eyebrow?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section id={id} aria-labelledby={id ? `${id}-title` : undefined} className={`scroll-mt-24 rounded-2xl border border-line bg-card p-5 md:p-6 ${className}`}>
      <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2.5">
          <h2 id={id ? `${id}-title` : undefined} className="font-display text-lg font-semibold tracking-tight">
            {title}
          </h2>
          {eyebrow}
        </div>
        {actions}
      </header>
      {children}
    </section>
  );
}

export function Stat({
  label,
  value,
  unit,
  hint,
  badge,
  large = false,
}: {
  label: string;
  value: React.ReactNode;
  unit?: string;
  hint?: React.ReactNode;
  badge?: React.ReactNode;
  large?: boolean;
}) {
  return (
    <div className="rounded-xl border border-line bg-bg-elev/60 p-3.5">
      <div className="text-[11px] font-medium uppercase tracking-[0.1em] text-ink-3">{label}</div>
      <div className={`mt-1 flex items-baseline gap-1.5 ${large ? "text-3xl" : "text-xl"} font-semibold tabular`}>
        <span>{value}</span>
        {unit && <span className="text-sm font-medium text-ink-3">{unit}</span>}
      </div>
      {hint && <div className="mt-1 text-[12px] leading-snug text-ink-3">{hint}</div>}
      {badge && <div className="mt-2">{badge}</div>}
    </div>
  );
}

export function InfoTip({ text }: { text: string }) {
  return (
    <span className="inline-flex cursor-help text-ink-3" title={text} aria-label={text} role="img">
      <CircleHelp size={14} />
    </span>
  );
}

export function CopyButton({ text, label, className = "" }: { text: string; label: string; className?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setDone(true);
          setTimeout(() => setDone(false), 1600);
        } catch {
          /* clipboard unavailable */
        }
      }}
      className={`rounded-lg border border-line px-2.5 py-1.5 text-xs font-medium text-ink-2 transition hover:border-line-strong hover:text-ink ${className}`}
    >
      <span aria-live="polite">{done ? "Copied" : label}</span>
    </button>
  );
}

export function DataTable({ caption, headers, rows }: { caption: string; headers: string[]; rows: (string | number)[][] }) {
  return (
    <details className="mt-3 text-sm">
      <summary className="cursor-pointer select-none text-xs font-medium text-ink-3 hover:text-ink-2">View data table</summary>
      <div className="scrollbar-thin mt-2 max-h-64 overflow-auto rounded-lg border border-line">
        <table className="w-full text-left text-xs tabular">
          <caption className="sr-only">{caption}</caption>
          <thead className="sticky top-0 bg-card-2 text-ink-3">
            <tr>{headers.map((h) => <th key={h} scope="col" className="px-3 py-1.5 font-medium">{h}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-t border-line">
                {r.map((c, j) => <td key={j} className="px-3 py-1 text-ink-2">{c}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
