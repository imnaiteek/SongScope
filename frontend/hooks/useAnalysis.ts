"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "@/lib/api";
import type { AnalysisPayload, StatusPayload } from "@/types/analysis";

/** Polls job status until it reaches a terminal state, then loads the full analysis. */
export function useAnalysis(id: string) {
  const [status, setStatus] = useState<StatusPayload | null>(null);
  const [data, setData] = useState<AnalysisPayload | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadFull = useCallback(async () => {
    try {
      const full = await api.get(id);
      setData(full);
      setStatus(full);
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, "unknown", "Failed to load analysis."));
    }
  }, [id]);

  useEffect(() => {
    let cancelled = false;
    let failures = 0;
    const poll = async () => {
      try {
        const s = await api.status(id);
        if (cancelled) return;
        failures = 0;
        setStatus(s);
        setError(null);
        if (s.status === "completed") {
          await loadFull();
          return;
        }
        if (s.status === "failed" || s.status === "cancelled") return;
        timer.current = setTimeout(poll, s.status === "queued" ? 1500 : 900);
      } catch (e) {
        if (cancelled) return;
        const err = e instanceof ApiError ? e : new ApiError(0, "unknown", "Failed to load status.");
        if (err.status === 404) {
          setError(err);
          return;
        }
        failures += 1;
        if (failures >= 5) setError(err);
        timer.current = setTimeout(poll, Math.min(10000, 1000 * 2 ** failures));
      }
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [id, loadFull]);

  return { status, data, error, reload: loadFull };
}
