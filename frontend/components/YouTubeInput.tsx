"use client";

import { ArrowRight, Link2, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useId, useState } from "react";

import { api, ApiError, validateYouTubeUrl } from "@/lib/api";

export function YouTubeInput({ disabled }: { disabled?: boolean }) {
  const router = useRouter();
  const inputId = useId();
  const errId = useId();
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const problem = validateYouTubeUrl(url);
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await api.analyzeYouTube(url.trim());
      router.push(`/analysis/${res.analysis_id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate>
      <label htmlFor={inputId} className="mb-2 block text-sm font-medium text-ink-2">
        Paste YouTube URL
      </label>
      <div
        className={`flex items-center gap-2 rounded-xl border bg-bg-elev p-1.5 pl-3 transition focus-within:border-violet ${
          error ? "border-[color:var(--critical)]" : "border-line-strong"
        }`}
      >
        <Link2 size={18} className="shrink-0 text-ink-3" aria-hidden />
        <input
          id={inputId}
          type="url"
          inputMode="url"
          autoComplete="off"
          spellCheck={false}
          placeholder="https://www.youtube.com/watch?v=…"
          value={url}
          disabled={disabled || busy}
          onChange={(e) => {
            setUrl(e.target.value);
            if (error) setError(null);
          }}
          aria-invalid={!!error}
          aria-describedby={error ? errId : undefined}
          className="min-w-0 flex-1 bg-transparent py-2 text-[15px] text-ink placeholder:text-ink-3 focus:outline-none"
        />
        <button
          type="submit"
          disabled={disabled || busy || !url.trim()}
          className="inline-flex items-center gap-1.5 rounded-lg bg-violet-strong px-4 py-2 text-sm font-semibold text-white transition hover:bg-violet disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? <Loader2 size={16} className="animate-spin" aria-hidden /> : null}
          Analyze
          {!busy && <ArrowRight size={16} aria-hidden />}
        </button>
      </div>
      {error && (
        <p id={errId} role="alert" className="mt-2 text-sm" style={{ color: "#f08a8a" }}>
          {error}
        </p>
      )}
    </form>
  );
}
