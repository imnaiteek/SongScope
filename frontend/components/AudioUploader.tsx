"use client";

import { FileAudio, Loader2, UploadCloud, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useId, useRef, useState } from "react";

import { ApiError, SUPPORTED_EXTENSIONS, uploadFile } from "@/lib/api";
import { bytes } from "@/lib/format";

type Phase = "idle" | "uploading" | "validating" | "error";

export function AudioUploader({ maxMb = 200, disabled }: { maxMb?: number; disabled?: boolean }) {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const descId = useId();
  const [dragging, setDragging] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState(0);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);

  const start = useCallback(
    async (f: File) => {
      const ext = f.name.split(".").pop()?.toLowerCase() ?? "";
      if (!SUPPORTED_EXTENSIONS.includes(ext)) {
        setPhase("error");
        setError(`“.${ext || "?"}” files aren't supported. Use MP3, WAV, FLAC, M4A, AAC, OGG or AIFF.`);
        return;
      }
      if (f.size > maxMb * 1024 * 1024) {
        setPhase("error");
        setError(`This file is ${bytes(f.size)}; the limit is ${maxMb} MB.`);
        return;
      }
      if (f.size === 0) {
        setPhase("error");
        setError("This file is empty.");
        return;
      }
      setFile(f);
      setError(null);
      setPhase("uploading");
      setProgress(0);
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      try {
        const res = await uploadFile(
          f,
          (p) => {
            setProgress(p);
            if (p >= 1) setPhase("validating");
          },
          ctrl.signal,
        );
        router.push(`/analysis/${res.analysis_id}`);
      } catch (err) {
        if (err instanceof ApiError && err.code === "aborted") {
          setPhase("idle");
          setFile(null);
          return;
        }
        setPhase("error");
        setError(err instanceof ApiError ? err.message : "Upload failed. Please try again.");
      }
    },
    [maxMb, router],
  );

  const busy = phase === "uploading" || phase === "validating";

  return (
    <div>
      <div
        role="button"
        tabIndex={disabled || busy ? -1 : 0}
        aria-describedby={descId}
        aria-disabled={disabled || busy}
        onClick={() => !busy && !disabled && inputRef.current?.click()}
        onKeyDown={(e) => {
          if ((e.key === "Enter" || e.key === " ") && !busy && !disabled) {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          if (!busy) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const f = e.dataTransfer.files?.[0];
          if (f && !busy && !disabled) void start(f);
        }}
        className={`group relative flex min-h-44 cursor-pointer flex-col items-center justify-center gap-3 overflow-hidden rounded-xl border border-dashed px-6 py-8 text-center transition ${
          dragging ? "border-violet bg-violet/10" : "border-line-strong bg-bg-elev hover:border-ink-3"
        } ${busy ? "cursor-default" : ""}`}
      >
        {busy && file ? (
          <div className="w-full max-w-md" aria-live="polite">
            <div className="mb-3 flex items-center gap-3 text-left">
              <FileAudio size={28} className="shrink-0 text-violet" aria-hidden />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium">{file.name}</div>
                <div className="text-xs text-ink-3 tabular">
                  {phase === "uploading" ? `Uploading · ${Math.round(progress * 100)}% of ${bytes(file.size)}` : "Validating audio…"}
                </div>
              </div>
              {phase === "uploading" ? (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    abortRef.current?.abort();
                  }}
                  className="rounded-md p-1.5 text-ink-3 hover:bg-card-2 hover:text-ink"
                  aria-label="Cancel upload"
                >
                  <X size={16} />
                </button>
              ) : (
                <Loader2 size={18} className="animate-spin text-ink-3" aria-hidden />
              )}
            </div>
            <div
              className="h-1.5 overflow-hidden rounded-full bg-line"
              role="progressbar"
              aria-label="Upload progress"
              aria-valuenow={Math.round(progress * 100)}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <div className="h-full rounded-full bg-gradient-to-r from-violet to-cyan transition-[width]" style={{ width: `${progress * 100}%` }} />
            </div>
          </div>
        ) : (
          <>
            <span className="grid size-12 place-items-center rounded-full border border-line-strong bg-card text-ink-2 transition group-hover:text-ink">
              <UploadCloud size={22} aria-hidden />
            </span>
            <div>
              <div className="text-[15px] font-medium">Drag & drop an audio file</div>
              <div className="mt-1 text-sm text-ink-3">
                or <span className="text-violet underline-offset-2 group-hover:underline">browse your computer</span>
              </div>
            </div>
          </>
        )}
        <input
          ref={inputRef}
          type="file"
          className="sr-only"
          tabIndex={-1}
          aria-label="Choose audio file"
          accept={SUPPORTED_EXTENSIONS.map((e) => `.${e}`).join(",") + ",audio/*"}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void start(f);
            e.target.value = "";
          }}
        />
      </div>
      <p id={descId} className="mt-2 text-xs text-ink-3">
        MP3 · WAV · FLAC · M4A · AAC · OGG · AIFF — up to {maxMb} MB
      </p>
      {phase === "error" && error && (
        <p role="alert" className="mt-2 text-sm" style={{ color: "#f08a8a" }}>
          {error}
        </p>
      )}
    </div>
  );
}
