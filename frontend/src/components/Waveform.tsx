import { Pause, Play } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import RegionsPlugin, { type Region } from "wavesurfer.js/dist/plugins/regions.esm.js";
import { timecode } from "../api";

export type WaveformHandle = {
  play: () => void;
  pause: () => void;
  toggle: () => void;
  seek: (seconds: number) => void;
  playRange: (start: number, end: number) => void;
};

type Props = {
  blob: Blob | null;
  height?: number;
  /** enable a draggable selection region (trim) */
  selection?: { start: number; end: number } | null;
  onSelectionChange?: (s: { start: number; end: number }) => void;
  onTime?: (t: number) => void;
  onReady?: (duration: number) => void;
  onPlayState?: (playing: boolean) => void;
  showControls?: boolean;
  label?: string;
  muted?: boolean;
};

const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

export const Waveform = forwardRef<WaveformHandle, Props>(function Waveform(
  { blob, height = 96, selection, onSelectionChange, onTime, onReady, onPlayState, showControls = true, label, muted },
  ref,
) {
  const container = useRef<HTMLDivElement>(null);
  const ws = useRef<WaveSurfer | null>(null);
  const regions = useRef<ReturnType<typeof RegionsPlugin.create> | null>(null);
  const region = useRef<Region | null>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [dur, setDur] = useState(0);
  const cbs = useRef({ onSelectionChange, onTime, onReady, onPlayState });
  cbs.current = { onSelectionChange, onTime, onReady, onPlayState };

  useEffect(() => {
    if (!container.current) return;
    const w = WaveSurfer.create({
      container: container.current,
      height,
      waveColor: css("--color-wave"),
      progressColor: css("--color-signal"),
      cursorColor: css("--color-ink"),
      cursorWidth: 1,
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
      normalize: true,
      dragToSeek: true,
    });
    const r = w.registerPlugin(RegionsPlugin.create());
    ws.current = w;
    regions.current = r;
    w.on("timeupdate", (t) => {
      setTime(t);
      cbs.current.onTime?.(t);
    });
    w.on("play", () => {
      setPlaying(true);
      cbs.current.onPlayState?.(true);
    });
    w.on("pause", () => {
      setPlaying(false);
      cbs.current.onPlayState?.(false);
    });
    w.on("ready", (d) => {
      setDur(d);
      cbs.current.onReady?.(d);
    });
    r.on("region-updated", (reg) => cbs.current.onSelectionChange?.({ start: reg.start, end: reg.end }));
    return () => {
      w.destroy();
      ws.current = null;
      region.current = null;
    };
  }, [height]);

  useEffect(() => {
    if (ws.current && blob) {
      region.current = null;
      regions.current?.clearRegions();
      ws.current.loadBlob(blob).catch(() => undefined);
    }
  }, [blob]);

  useEffect(() => {
    ws.current?.setMuted(!!muted);
  }, [muted]);

  // keep selection region in sync
  useEffect(() => {
    const r = regions.current;
    if (!r || !dur) return;
    if (!selection) {
      r.clearRegions();
      region.current = null;
      return;
    }
    if (!region.current) {
      region.current = r.addRegion({
        start: selection.start,
        end: selection.end,
        color: "rgba(242, 179, 61, 0.14)",
        drag: true,
        resize: true,
      });
    } else if (Math.abs(region.current.start - selection.start) > 0.01 || Math.abs(region.current.end - selection.end) > 0.01) {
      region.current.setOptions({ start: selection.start, end: selection.end });
    }
  }, [selection, dur]);

  useImperativeHandle(ref, () => ({
    play: () => void ws.current?.play(),
    pause: () => ws.current?.pause(),
    toggle: () => void ws.current?.playPause(),
    seek: (s: number) => ws.current?.setTime(s),
    playRange: (s: number, e: number) => void ws.current?.play(s, e),
  }));

  return (
    <div>
      <div ref={container} aria-label={label ?? "Waveform"} className="w-full" />
      {showControls && (
        <div className="flex items-center gap-3 mt-2">
          <button
            type="button"
            onClick={() => (selection && !playing ? ws.current?.play(selection.start, selection.end) : ws.current?.playPause())}
            disabled={!blob}
            className="inline-grid place-items-center size-9 rounded-full bg-raised border border-line hover:border-signal text-ink disabled:opacity-40"
            aria-label={playing ? "Pause" : selection ? "Play selection" : "Play"}
          >
            {playing ? <Pause className="size-4" /> : <Play className="size-4 translate-x-px" />}
          </button>
          <span className="tnum condensed text-[15px]">
            {timecode(time)} <span className="text-muted">/ {timecode(dur)}</span>
          </span>
        </div>
      )}
    </div>
  );
});
