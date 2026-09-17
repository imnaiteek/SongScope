"use client";

import { formatTime } from "@/lib/format";
import type { AnalysisResults } from "@/types/analysis";

import { ConfidenceBadge } from "./ui";

export function OverviewCards({ r }: { r: AnalysisResults }) {
  const { tempo, key, meter, overview } = r;
  const cards = [
    {
      label: "BPM",
      value: tempo.bpm != null ? (Math.abs(tempo.bpm - Math.round(tempo.bpm)) < 0.25 ? Math.round(tempo.bpm) : tempo.bpm.toFixed(1)) : "—",
      sub: tempo.bpm != null ? [tempo.category, tempo.alternative_bpm ? `alt. ${Math.round(tempo.alternative_bpm)} (${tempo.alternative_relation})` : null].filter(Boolean).join(" · ") : "No reliable pulse",
      badge: <ConfidenceBadge confidence={tempo.confidence} level={tempo.confidence_level} status={tempo.status} />,
    },
    {
      label: "Key",
      value: key.key ?? "—",
      sub: key.alternative_key ? `alt. ${key.alternative_key}` : "No reliable key",
      badge: <ConfidenceBadge confidence={key.confidence} level={key.confidence_level} status={key.status} />,
    },
    {
      label: "Meter",
      value: meter.reliable && meter.signature ? meter.signature : "Uncertain",
      sub: meter.reliable ? `${meter.subdivision ?? ""} subdivision` : meter.tendency ? `Weak tendency: ${meter.tendency}` : "Could not be determined reliably",
      badge: <ConfidenceBadge confidence={meter.confidence} level={meter.confidence_level} status={meter.status} />,
    },
    {
      label: "Duration",
      value: formatTime(overview.duration),
      sub: overview.integrated_lufs != null ? `${overview.integrated_lufs} LUFS integrated` : "",
      badge: <ConfidenceBadge status="detected" />,
    },
    {
      label: "Overall confidence",
      value: overview.overall_confidence_level[0].toUpperCase() + overview.overall_confidence_level.slice(1),
      sub: "Mean of tempo, key, meter & chords",
      badge: <ConfidenceBadge confidence={overview.overall_confidence} level={overview.overall_confidence_level} status="estimated" compact />,
    },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
      {cards.map((c) => (
        <div key={c.label} className="flex flex-col justify-between rounded-2xl border border-line bg-card p-4">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-3">{c.label}</div>
            <div className={`mt-1.5 font-display font-bold leading-none tracking-tight tabular ${String(c.value).length > 8 ? "text-2xl" : "text-4xl"}`}>{c.value}</div>
            <div className="mt-2 min-h-4 text-xs text-ink-3">{c.sub}</div>
          </div>
          <div className="mt-3">{c.badge}</div>
        </div>
      ))}
    </div>
  );
}
