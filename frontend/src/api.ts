// Typed API client. All requests go through /api (proxied to FastAPI in development).

export type Quality = {
  duration_s: number;
  speech_seconds: number;
  peak_dbfs: number;
  rms_dbfs: number;
  snr_db: number;
  silence_ratio: number;
  clipping_ratio: number;
  syllables_per_s: number | null;
  score: number;
  grade: "good" | "fair" | "poor";
  issues: string[];
  usable: boolean;
};

export type Sample = {
  id: string;
  original_filename: string;
  source: "upload" | "recording";
  duration_s: number;
  trim_start_s: number | null;
  trim_end_s: number | null;
  quality: Quality;
  voice_profile_id: string | null;
  created_at: string;
};

export type Consent = {
  id: string;
  speaker_name: string;
  speaker_email: string | null;
  relationship: "self" | "authorized_third_party";
  statement_text: string;
  consent_phrase: string;
  status: "pending" | "verified" | "revoked";
  verification: Record<string, unknown>;
  has_recording: boolean;
  created_at: string;
  verified_at: string | null;
};

export type VoiceAnalysis = {
  pitch?: { median_hz: number | null; p10_hz: number | null; p90_hz: number | null };
  register?: "low" | "mid" | "high" | null;
  pace?: "slow" | "moderate" | "fast" | null;
  syllables_per_s?: number | null;
  snr_db?: number;
  reference_seconds_used?: number;
};

export type Voice = {
  id: string;
  name: string;
  description: string | null;
  language: string;
  accent: string | null;
  provider: string;
  status: "pending" | "processing" | "ready" | "failed";
  error: string | null;
  analysis: VoiceAnalysis;
  preview_text: string | null;
  has_preview: boolean;
  sample: Sample | null;
  consent: { id: string; speaker_name: string; status: string; relationship: string; verified_at: string | null } | null;
  created_at: string;
};

export type Pronunciation = { term: string; say: string; case_sensitive?: boolean };

export type ProjectSettings = {
  speed: number;
  pitch_semitones: number;
  pause_ms: number;
  paragraph_pause_ms: number;
  language: string | null;
  temperature: number | null;
  pronunciations: Pronunciation[];
  seed: number | null;
};

export type ExportSettings = { format: "wav" | "mp3"; bitrate_kbps: number; sample_rate: number };

export type Segment = {
  id: string;
  position: number;
  paragraph_index: number;
  text: string;
  pause_after_ms: number | null;
  status: "pending" | "queued" | "generating" | "ready" | "failed" | "stale";
  error: string | null;
  duration_s: number | null;
  take: number;
  updated_at: string;
};

export type Script = {
  id: string;
  title: string;
  content: string;
  language: string;
  word_count: number;
  char_count: number;
  paragraph_count: number;
};

export type Project = {
  id: string;
  title: string;
  voice_profile_id: string | null;
  voice_name: string | null;
  script: Script;
  settings: ProjectSettings;
  export_settings: ExportSettings;
  segment_counts: Record<string, number>;
  segment_total: number;
  duration_s: number;
  active_job_id: string | null;
  created_at: string;
  updated_at: string;
  segments?: Segment[];
};

export type Job = {
  id: string;
  kind: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  progress: number;
  message: string | null;
  error: string | null;
  result: Record<string, unknown>;
  project_id: string | null;
  voice_profile_id: string | null;
};

export type Export = {
  id: string;
  project_id: string | null;
  kind: "mix" | "segment" | "bundle";
  title: string;
  format: "wav" | "mp3" | "zip";
  bitrate_kbps: number | null;
  sample_rate: number | null;
  duration_s: number | null;
  size_bytes: number;
  created_at: string;
};

export type Provider = {
  id: string;
  name: string;
  capabilities: {
    voice_cloning: boolean;
    languages: Record<string, string>;
    native_speed: boolean;
    native_pitch: boolean;
    emotions: string[];
    expressiveness: boolean;
    max_chars_per_request: number;
    min_sample_seconds: number;
    recommended_sample_seconds: [number, number];
    licence: string;
    notes: string[];
  };
  status: { ready: boolean; hf_token_configured?: boolean; errors?: Record<string, string> };
};

export type User = { id: string; email: string; name: string };

export type Dashboard = {
  user: { name: string; email: string };
  stats: {
    voices: number;
    projects: number;
    segments_generated: number;
    audio_seconds: number;
    characters_30d: number;
    jobs_30d: number;
    export_bytes: number;
  };
  voices: Voice[];
  projects: Project[];
  exports: Export[];
};

// ------------------------------------------------------------------ transport
const TOKEN_KEY = "vs_token";

export const tokenStore = {
  get: () => {
    try {
      return localStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set: (t: string | null) => {
    try {
      if (t) localStorage.setItem(TOKEN_KEY, t);
      else localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* storage unavailable */
    }
  },
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

function errorMessage(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((e) => (e as { msg?: string }).msg ?? String(e)).join("; ");
  }
  return `Request failed (${status})`;
}

async function raw(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = tokenStore.get();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(`/api${path}`, { ...init, headers });
  if (res.status === 401 && token) {
    tokenStore.set(null);
    window.dispatchEvent(new Event("vs:logout"));
  }
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, errorMessage(body, res.status));
  }
  return res;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await raw(path, init);
  return (await res.json()) as T;
}

export const post = <T>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body: body instanceof FormData ? body : JSON.stringify(body ?? {}) });
export const patch = <T>(path: string, body: unknown) => api<T>(path, { method: "PATCH", body: JSON.stringify(body) });
export const put = <T>(path: string, body: unknown) => api<T>(path, { method: "PUT", body: JSON.stringify(body) });
export const del = <T>(path: string) => api<T>(path, { method: "DELETE" });

/** Fetch authenticated binary audio. */
export async function fetchBlob(path: string, init: RequestInit = {}): Promise<{ blob: Blob; headers: Headers }> {
  const res = await raw(path, init);
  return { blob: await res.blob(), headers: res.headers };
}

export async function download(path: string, filename: string) {
  const { blob } = await fetchBlob(path);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

// ------------------------------------------------------------------ formatting
export function timecode(seconds: number, withMs = true): string {
  const s = Math.max(0, seconds);
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  const base = `${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  return withMs ? `${base}.${String(Math.floor((s % 1) * 10))}` : base;
}

export function duration(seconds: number | null | undefined): string {
  if (seconds == null) return "–";
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const m = Math.floor(seconds / 60);
  return `${m} min ${Math.round(seconds % 60)} s`;
}

export function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 ** 2).toFixed(1)} MB`;
}

export function relativeDate(iso: string): string {
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} d ago`;
  return d.toLocaleDateString();
}

export const LANGUAGE_NAMES: Record<string, string> = {
  en: "English",
  fr: "French",
  de: "German",
  es: "Spanish",
  it: "Italian",
  pt: "Portuguese",
  nl: "Dutch",
};
