import type { AnalysisPayload, Health, RecentItem, StatusPayload } from "@/types/analysis";

export const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

async function parseError(res: Response): Promise<ApiError> {
  let body: { error?: { code?: string; message?: string } } | undefined;
  try {
    body = await res.json();
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(res.status, body?.error?.code ?? "http_error", body?.error?.message ?? `Request failed (${res.status}).`);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(API_BASE + path, { cache: "no-store", ...init });
  } catch {
    throw new ApiError(0, "network", "Cannot reach the SongScope analysis server. Is the backend running?");
  }
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export interface StartResponse {
  analysis_id: string;
  status: string;
  cached: boolean;
}

export function uploadFile(
  file: File,
  onProgress: (fraction: number) => void,
  signal?: AbortSignal,
  force = false,
): Promise<StartResponse> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const form = new FormData();
    form.append("file", file, file.name);
    if (force) form.append("force", "true");
    xhr.open("POST", `${API_BASE}/api/analyze/upload`);
    xhr.responseType = "json";
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      const body = xhr.response;
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as StartResponse);
      else
        reject(
          new ApiError(xhr.status, body?.error?.code ?? "upload_failed", body?.error?.message ?? `Upload failed (${xhr.status}).`),
        );
    };
    xhr.onerror = () => reject(new ApiError(0, "network", "Upload failed — cannot reach the analysis server."));
    xhr.onabort = () => reject(new ApiError(0, "aborted", "Upload cancelled."));
    signal?.addEventListener("abort", () => xhr.abort());
    xhr.send(form);
  });
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  health: () => request<Health>("/api/health"),
  analyzeYouTube: (url: string, force = false) => request<StartResponse>("/api/analyze/youtube", json({ url, force })),
  status: (id: string) => request<StatusPayload>(`/api/analyze/${encodeURIComponent(id)}/status`),
  get: (id: string) => request<AnalysisPayload>(`/api/analyze/${encodeURIComponent(id)}`),
  cancel: (id: string) => request<{ cancelled: number }>(`/api/analyze/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
  remove: (id: string) => request<void>(`/api/analyze/${encodeURIComponent(id)}`, { method: "DELETE" }),
  startStems: (id: string) => request<{ status: string }>(`/api/analyze/${encodeURIComponent(id)}/stems`, { method: "POST" }),
  explain: (id: string, audience: string, refresh = false) =>
    request<{ audience: string; text: string; cached: boolean; model: string }>(
      `/api/analyze/${encodeURIComponent(id)}/explain`,
      json({ audience, refresh }),
    ),
  recent: (limit = 8) => request<{ items: RecentItem[] }>(`/api/analyses?limit=${limit}`),
  exportUrl: (id: string, format: "json" | "csv" | "txt" | "pdf") =>
    `${API_BASE}/api/analyze/${encodeURIComponent(id)}/export?format=${format}`,
  absolute: (path: string) => (path.startsWith("http") ? path : API_BASE + path),
  stemAudioUrl: (id: string, stem: string) => `${API_BASE}/api/analyze/${encodeURIComponent(id)}/stems/${stem}/audio`,
};

export const SUPPORTED_EXTENSIONS = ["mp3", "wav", "flac", "m4a", "aac", "ogg", "oga", "opus", "aif", "aiff"];

const YT_HOSTS = new Set(["youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtu.be"]);

/** Client-side pre-validation; the server re-validates authoritatively. */
export function validateYouTubeUrl(raw: string): string | null {
  const value = raw.trim();
  if (!value) return "Paste a YouTube link.";
  let url: URL;
  try {
    url = new URL(/^https?:\/\//i.test(value) ? value : `https://${value}`);
  } catch {
    return "That doesn't look like a valid URL.";
  }
  if (!YT_HOSTS.has(url.hostname.toLowerCase())) return "Only YouTube links are supported (youtube.com or youtu.be).";
  let id: string | null = null;
  if (url.hostname.endsWith("youtu.be")) id = url.pathname.slice(1).split("/")[0];
  else if (url.pathname === "/watch") id = url.searchParams.get("v");
  else {
    const m = url.pathname.match(/^\/(shorts|embed|live)\/([^/]+)/);
    if (m) id = m[2];
    else if (url.pathname.startsWith("/playlist")) return "Playlists aren't supported — paste a single video link.";
  }
  if (!id || !/^[A-Za-z0-9_-]{11}$/.test(id)) return "Couldn't find a video ID in this link.";
  return null;
}
