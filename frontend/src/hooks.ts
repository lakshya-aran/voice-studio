import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api, fetchBlob, type Job, type Provider } from "./api";

/** Poll a background job until it finishes; invalidates the given query keys on completion. */
export function useJob(jobId: string | null | undefined, invalidate: unknown[][] = []) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api<Job>(`/jobs/${jobId}`),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const s = query.state.data?.status;
      return s === "queued" || s === "running" || !s ? 700 : false;
    },
  });
  const status = q.data?.status;
  const last = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (status && status !== last.current) {
      last.current = status;
      invalidate.forEach((key) => qc.invalidateQueries({ queryKey: key }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, q.data?.progress]);
  return q.data ?? null;
}

/** Load an authenticated audio URL as a Blob (for WaveSurfer / <audio>). */
export function useAudioBlob(path: string | null, version: unknown = 0) {
  const [blob, setBlob] = useState<Blob | null>(null);
  const [headers, setHeaders] = useState<Headers | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    setError(null);
    if (!path) {
      setBlob(null);
      return;
    }
    fetchBlob(path)
      .then((r) => {
        if (!cancelled) {
          setBlob(r.blob);
          setHeaders(r.headers);
        }
      })
      .catch((e) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [path, version]);
  return { blob, headers, error };
}

export function useProviders() {
  return useQuery({ queryKey: ["providers"], queryFn: () => api<Provider[]>("/providers"), staleTime: 60_000 });
}

/** Single shared <audio> element so only one clip plays at a time. */
let shared: HTMLAudioElement | null = null;
let sharedUrl: string | null = null;
const listeners = new Set<(id: string | null) => void>();
let playingId: string | null = null;

function setPlaying(id: string | null) {
  playingId = id;
  listeners.forEach((l) => l(id));
}

export async function playClip(id: string, path: string) {
  if (!shared) {
    shared = new Audio();
    shared.addEventListener("ended", () => setPlaying(null));
    shared.addEventListener("pause", () => setPlaying(null));
  }
  if (playingId === id) {
    shared.pause();
    return;
  }
  shared.pause();
  const { blob } = await fetchBlob(path);
  if (sharedUrl) URL.revokeObjectURL(sharedUrl);
  sharedUrl = URL.createObjectURL(blob);
  shared.src = sharedUrl;
  await shared.play();
  setPlaying(id);
}

export function stopClip() {
  shared?.pause();
}

export function usePlayingClip() {
  const [id, setId] = useState<string | null>(playingId);
  useEffect(() => {
    listeners.add(setId);
    return () => {
      listeners.delete(setId);
    };
  }, []);
  return id;
}
