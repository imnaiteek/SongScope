"use client";

import { Check, Loader2, X } from "lucide-react";

import type { StatusPayload } from "@/types/analysis";

export function AnalysisProgress({ status, onCancel, cancelling }: { status: StatusPayload; onCancel: () => void; cancelling: boolean }) {
  const pct = Math.round((status.progress ?? 0) * 100);
  const queued = status.status === "queued";
  return (
    <div className="mx-auto w-full max-w-2xl rounded-2xl border border-line bg-card p-6 md:p-8">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-ink-3">{queued ? "Queued" : "Analyzing"}</p>
          <h1 className="mt-1 font-display text-2xl font-bold [overflow-wrap:anywhere]">{status.title ?? "Your track"}</h1>
          <p className="mt-1 text-sm text-ink-3" aria-live="polite">
            {queued ? "Waiting for an analysis worker…" : status.message ?? status.stage_label ?? "Working…"}
          </p>
        </div>
        <div className="text-right">
          <div className="font-display text-4xl font-bold tabular">{pct}%</div>
        </div>
      </div>

      <div
        className="mt-5 h-2 overflow-hidden rounded-full bg-line"
        role="progressbar"
        aria-label="Analysis progress"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div className="h-full rounded-full bg-gradient-to-r from-violet-strong to-cyan transition-[width] duration-500" style={{ width: `${pct}%` }} />
      </div>

      <ol className="mt-6 grid gap-1.5 sm:grid-cols-2" aria-label="Analysis stages">
        {status.stages.map((s, i) => (
          <li
            key={s.key}
            className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm ${s.state === "active" ? "bg-card-2 text-ink" : s.state === "done" ? "text-ink-2" : "text-ink-3"}`}
            aria-current={s.state === "active" ? "step" : undefined}
          >
            <span
              className={`grid size-6 shrink-0 place-items-center rounded-full border text-[11px] tabular ${
                s.state === "done" ? "border-transparent bg-violet-strong text-white" : s.state === "active" ? "border-violet text-violet" : "border-line-strong"
              }`}
            >
              {s.state === "done" ? <Check size={13} aria-hidden /> : s.state === "active" ? <Loader2 size={13} className="animate-spin" aria-hidden /> : i + 1}
            </span>
            <span>{s.label}</span>
            {s.state === "active" && status.stage_progress > 0 && status.stage_progress < 1 && (
              <span className="ml-auto text-xs text-ink-3 tabular">{Math.round(status.stage_progress * 100)}%</span>
            )}
            <span className="sr-only">{s.state === "done" ? "(complete)" : s.state === "active" ? "(in progress)" : "(pending)"}</span>
          </li>
        ))}
      </ol>

      <div className="mt-6 flex items-center justify-between gap-4 border-t border-line pt-4">
        <p className="text-xs text-ink-3">Progress is reported by the analysis engine as each stage completes.</p>
        <button
          type="button"
          onClick={onCancel}
          disabled={cancelling}
          className="inline-flex items-center gap-1.5 rounded-lg border border-line-strong px-3 py-1.5 text-sm text-ink-2 transition hover:text-ink disabled:opacity-50"
        >
          <X size={14} aria-hidden /> {cancelling ? "Cancelling…" : "Cancel"}
        </button>
      </div>
    </div>
  );
}
