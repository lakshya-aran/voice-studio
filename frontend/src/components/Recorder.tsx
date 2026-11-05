import { Mic, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { timecode } from "../api";

/** Microphone recorder with a live level meter. Produces a webm/ogg Blob. */
export function Recorder({ onRecorded, maxSeconds = 120, hint }: { onRecorded: (blob: Blob, ext: string) => void; maxSeconds?: number; hint?: string }) {
  const [state, setState] = useState<"idle" | "recording">("idle");
  const [elapsed, setElapsed] = useState(0);
  const [level, setLevel] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const rec = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const raf = useRef<number>(0);
  const ctx = useRef<AudioContext | null>(null);

  const cleanup = () => {
    cancelAnimationFrame(raf.current);
    stream.current?.getTracks().forEach((t) => t.stop());
    ctx.current?.close().catch(() => undefined);
    stream.current = null;
    ctx.current = null;
    setLevel(0);
  };
  useEffect(() => cleanup, []);

  const start = async () => {
    setError(null);
    try {
      const s = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false, channelCount: 1 },
      });
      stream.current = s;
      const mime = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"].find((m) => MediaRecorder.isTypeSupported(m)) ?? "";
      const r = new MediaRecorder(s, mime ? { mimeType: mime, audioBitsPerSecond: 192000 } : undefined);
      const chunks: Blob[] = [];
      r.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      r.onstop = () => {
        const type = r.mimeType || "audio/webm";
        const ext = type.includes("ogg") ? ".ogg" : type.includes("mp4") ? ".m4a" : ".webm";
        onRecorded(new Blob(chunks, { type }), ext);
        cleanup();
        setState("idle");
      };
      rec.current = r;
      r.start(250);
      setState("recording");

      // level meter + timer
      const ac = new AudioContext();
      ctx.current = ac;
      const analyser = ac.createAnalyser();
      analyser.fftSize = 1024;
      ac.createMediaStreamSource(s).connect(analyser);
      const buf = new Float32Array(analyser.fftSize);
      const t0 = performance.now();
      const tick = () => {
        analyser.getFloatTimeDomainData(buf);
        let peak = 0;
        for (const v of buf) peak = Math.max(peak, Math.abs(v));
        setLevel((l) => Math.max(peak, l * 0.9));
        const el = (performance.now() - t0) / 1000;
        setElapsed(el);
        if (el >= maxSeconds) r.state === "recording" && r.stop();
        else raf.current = requestAnimationFrame(tick);
      };
      tick();
    } catch (e) {
      cleanup();
      setError(
        e instanceof DOMException && e.name === "NotAllowedError"
          ? "Microphone access was blocked. Allow it in the browser's site settings and try again."
          : "No microphone was found. Connect one, or upload a file instead.",
      );
    }
  };

  const stop = () => rec.current?.state === "recording" && rec.current.stop();
  const db = level > 0 ? 20 * Math.log10(level) : -60;
  const meter = Math.max(0, Math.min(1, (db + 60) / 60));

  return (
    <div className="rounded-panel border border-line bg-well p-4">
      <div className="flex items-center gap-4">
        <button
          type="button"
          onClick={state === "recording" ? stop : start}
          className={`inline-grid place-items-center size-12 rounded-full border-2 transition-colors ${
            state === "recording" ? "border-rec bg-rec/15 text-rec" : "border-line-strong text-ink hover:border-rec hover:text-rec"
          }`}
          aria-label={state === "recording" ? "Stop recording" : "Start recording"}
        >
          {state === "recording" ? <Square className="size-4 fill-current" /> : <Mic className="size-5" />}
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline justify-between">
            <span className="condensed tnum text-[22px] leading-none">{timecode(elapsed)}</span>
            <span className="legend">{state === "recording" ? "Recording" : `Up to ${Math.round(maxSeconds / 60)} min`}</span>
          </div>
          {/* segmented level meter, like a hardware VU ladder */}
          <div className="mt-2 flex gap-[2px]" aria-hidden>
            {Array.from({ length: 32 }, (_, i) => {
              const on = i / 32 < meter;
              const hot = i >= 28;
              const warm = i >= 22;
              return (
                <span
                  key={i}
                  className={`h-2 flex-1 rounded-[1px] ${on ? (hot ? "bg-rec" : warm ? "bg-signal" : "bg-ok") : "bg-line"}`}
                />
              );
            })}
          </div>
        </div>
      </div>
      {hint && <p className="legend mt-3">{hint}</p>}
      {error && <p className="text-[13px] text-rec mt-3">{error}</p>}
    </div>
  );
}
