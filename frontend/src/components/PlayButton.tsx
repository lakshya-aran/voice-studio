import { Loader2, Pause, Play } from "lucide-react";
import { useState } from "react";
import { playClip, usePlayingClip } from "../hooks";

export function PlayButton({ id, path, label, size = "md", disabled }: { id: string; path: string; label: string; size?: "sm" | "md"; disabled?: boolean }) {
  const playing = usePlayingClip() === id;
  const [loading, setLoading] = useState(false);
  const dim = size === "sm" ? "size-7" : "size-9";
  return (
    <button
      type="button"
      disabled={disabled || loading}
      onClick={async () => {
        setLoading(true);
        try {
          await playClip(id, path);
        } finally {
          setLoading(false);
        }
      }}
      aria-label={playing ? `Pause ${label}` : `Play ${label}`}
      className={`inline-grid place-items-center ${dim} shrink-0 rounded-full border transition-colors disabled:opacity-40 ${
        playing ? "border-signal bg-signal text-console" : "border-line-strong text-ink hover:border-signal"
      }`}
    >
      {loading ? <Loader2 className="size-3.5 animate-spin" /> : playing ? <Pause className="size-3.5" /> : <Play className="size-3.5 translate-x-px" />}
    </button>
  );
}
