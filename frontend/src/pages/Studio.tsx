import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Download, GripVertical, Pause, Play, Plus, RefreshCw, SkipBack, Trash2, Wand2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router";
import {
  api,
  bytes,
  download,
  duration,
  LANGUAGE_NAMES,
  patch,
  post,
  put,
  relativeDate,
  timecode,
  type Export,
  type ExportSettings,
  type Project,
  type ProjectSettings,
  type Pronunciation,
  type Segment,
  type Voice,
} from "../api";
import { PlayButton } from "../components/PlayButton";
import { Button, Field, IconButton, Input, Notice, Progress, Select, Slider, Spinner, Status, Textarea } from "../components/ui";
import { Waveform, type WaveformHandle } from "../components/Waveform";
import { useAudioBlob, useJob, useProviders } from "../hooks";

type TimelineEntry = { segment_id: string; start: number; end: number; pause_after_ms: number };

function useDebounced<T>(value: T, ms: number) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

// ====================================================================== left: voice & settings
function VoicePanel({ project, onSettings, onVoice }: { project: Project; onSettings: (s: Partial<ProjectSettings>) => void; onVoice: (id: string) => void }) {
  const { data: voices } = useQuery({ queryKey: ["voices"], queryFn: () => api<Voice[]>("/voices") });
  const { data: providers } = useProviders();
  const voice = voices?.find((v) => v.id === project.voice_profile_id);
  const provider = providers?.find((p) => p.id === voice?.provider) ?? providers?.[0];
  const caps = provider?.capabilities;
  const s = project.settings;
  const [draft, setDraft] = useState(s);
  useEffect(() => setDraft(project.settings), [project.settings]);
  const set = (patchS: Partial<ProjectSettings>) => {
    setDraft((d) => ({ ...d, ...patchS }));
    onSettings(patchS);
  };
  const [term, setTerm] = useState("");
  const [say, setSay] = useState("");
  const addRule = () => {
    if (!term.trim() || !say.trim()) return;
    set({ pronunciations: [...(draft.pronunciations ?? []), { term: term.trim(), say: say.trim() }] });
    setTerm("");
    setSay("");
  };

  return (
    <div className="space-y-6">
      <section>
        <h2 className="condensed text-[16px] font-semibold mb-3">Voice</h2>
        <div className="flex gap-2 items-center">
          <Select value={project.voice_profile_id ?? ""} onChange={(e) => onVoice(e.target.value)} aria-label="Voice">
            <option value="" disabled>
              Choose a voice
            </option>
            {voices
              ?.filter((v) => v.status === "ready")
              .map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name}
                </option>
              ))}
          </Select>
          {voice && <PlayButton id={`voice-${voice.id}`} path={`/voices/${voice.id}/preview`} label={`${voice.name} preview`} />}
        </div>
        {voice?.sample && (
          <div className="flex items-center gap-2 mt-2.5">
            <PlayButton id={`sample-${voice.sample.id}`} path={`/samples/${voice.sample.id}/audio`} label="original sample" size="sm" />
            <span className="legend">Original sample, for comparison</span>
          </div>
        )}
        {!voices?.some((v) => v.status === "ready") && (
          <p className="legend mt-2">
            No voices yet. <Link className="text-signal" to="/voices/new">Clone one</Link>.
          </p>
        )}
      </section>

      <section className="space-y-4">
        <h2 className="condensed text-[16px] font-semibold">Delivery</h2>
        <Field label="Language">
          <Select value={draft.language ?? voice?.language ?? "en"} onChange={(e) => set({ language: e.target.value })}>
            {Object.entries(caps?.languages ?? LANGUAGE_NAMES).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </Select>
        </Field>
        <Slider label="Speed" value={draft.speed} min={0.5} max={2} step={0.05} format={(v) => `${v.toFixed(2)}×`} onChange={(v) => set({ speed: v })}
          note={caps && !caps.native_speed ? "Applied as a time-stretch after generation" : undefined} />
        <Slider label="Pitch" value={draft.pitch_semitones} min={-6} max={6} step={0.5} format={(v) => `${v > 0 ? "+" : ""}${v} st`} onChange={(v) => set({ pitch_semitones: v })}
          note={caps && !caps.native_pitch ? "Applied after generation; large shifts sound less natural" : undefined} />
        {caps?.expressiveness && (
          <Slider label="Expressiveness" value={draft.temperature ?? 0.3} min={0.1} max={1} step={0.05} format={(v) => v.toFixed(2)} onChange={(v) => set({ temperature: v })}
            note="Higher values vary intonation more between lines" />
        )}
        <div>
          <span className="text-[13px] text-ink-soft">Emotion</span>
          {caps && caps.emotions.length > 0 ? (
            <Select className="mt-1">{caps.emotions.map((e) => <option key={e}>{e}</option>)}</Select>
          ) : (
            <p className="legend mt-1">
              {provider?.name ?? "This model"} has no emotion control. The voice keeps the tone of its reference recording; clone a sample read in the mood you want.
            </p>
          )}
        </div>
      </section>

      <section className="space-y-4">
        <h2 className="condensed text-[16px] font-semibold">Pauses</h2>
        <Slider label="Between sentences" value={draft.pause_ms} min={0} max={2000} step={50} format={(v) => `${v} ms`} onChange={(v) => set({ pause_ms: v })} />
        <Slider label="Between paragraphs" value={draft.paragraph_pause_ms} min={0} max={4000} step={100} format={(v) => `${v} ms`} onChange={(v) => set({ paragraph_pause_ms: v })} />
      </section>

      <section>
        <h2 className="condensed text-[16px] font-semibold mb-1">Pronunciation</h2>
        <p className="legend mb-3">Replace a word with how it should be said before it is spoken.</p>
        <ul className="space-y-1.5 mb-3">
          {(draft.pronunciations ?? []).map((r: Pronunciation, i: number) => (
            <li key={i} className="flex items-center gap-2 text-[14px]">
              <span className="truncate">{r.term}</span>
              <span className="text-muted">says</span>
              <span className="truncate text-signal flex-1">{r.say}</span>
              <IconButton label={`Remove ${r.term}`} onClick={() => set({ pronunciations: draft.pronunciations.filter((_, j) => j !== i) })}>
                <X className="size-3.5" />
              </IconButton>
            </li>
          ))}
        </ul>
        <div className="grid grid-cols-[1fr_1fr_auto] gap-1.5">
          <Input placeholder="Word" value={term} onChange={(e) => setTerm(e.target.value)} aria-label="Word" />
          <Input placeholder="Say as" value={say} onChange={(e) => setSay(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addRule()} aria-label="Say as" />
          <IconButton label="Add pronunciation" onClick={addRule}>
            <Plus className="size-4" />
          </IconButton>
        </div>
      </section>
    </div>
  );
}

// ====================================================================== center: lines
function LineRow({
  seg,
  index,
  total,
  current,
  onMove,
  onRegenerate,
  busy,
  defaultPause,
  dragHandlers,
}: {
  seg: Segment;
  index: number;
  total: number;
  current: boolean;
  onMove: (from: number, to: number) => void;
  onRegenerate: (id: string) => void;
  busy: boolean;
  defaultPause: number;
  dragHandlers: React.HTMLAttributes<HTMLLIElement>;
}) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(seg.text);
  useEffect(() => setText(seg.text), [seg.text]);
  const save = useMutation({
    mutationFn: (body: { text?: string; pause_after_ms?: number }) => patch<Segment>(`/segments/${seg.id}`, body),
    onSettled: () => qc.invalidateQueries({ predicate: (q) => q.queryKey[0] === "project" }),
  });

  return (
    <li
      {...dragHandlers}
      className={`group grid grid-cols-[20px_32px_1fr_auto] gap-3 items-start px-3 py-3 ${current ? "bg-signal/[0.07] shadow-[inset_2px_0_0_var(--color-signal)]" : ""}`}
    >
      <span className="pt-1.5 text-muted cursor-grab active:cursor-grabbing" aria-hidden>
        <GripVertical className="size-4" />
      </span>
      <div className="pt-0.5">
        <PlayButton id={`seg-${seg.id}-${seg.take}`} path={`/segments/${seg.id}/audio`} label={`line ${index + 1}`} size="sm" disabled={!seg.duration_s || seg.status === "generating"} />
      </div>
      <div className="min-w-0">
        {editing ? (
          <div className="space-y-2">
            <Textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} autoFocus />
            <div className="flex gap-2">
              <Button
                variant="primary"
                className="h-8"
                busy={save.isPending}
                onClick={() => save.mutate({ text }, { onSuccess: () => setEditing(false) })}
                disabled={!text.trim()}
              >
                Save line
              </Button>
              <Button variant="ghost" className="h-8" onClick={() => (setText(seg.text), setEditing(false))}>
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <button className="text-left leading-relaxed hover:text-ink text-ink-soft group-hover:text-ink w-full" onClick={() => setEditing(true)} title="Edit line">
            {seg.text}
          </button>
        )}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-1.5">
          <Status status={seg.status} />
          {seg.duration_s != null && <span className="legend tnum">{seg.duration_s.toFixed(1)} s</span>}
          {seg.take > 0 && <span className="legend">Take {seg.take + 1}</span>}
          {index < total - 1 && (
            <label className="legend flex items-center gap-1.5">
              Pause after
              <input
                type="number"
                min={0}
                max={10000}
                step={50}
                placeholder={String(defaultPause)}
                defaultValue={seg.pause_after_ms ?? ""}
                key={seg.pause_after_ms ?? "d"}
                onBlur={(e) => {
                  const v = e.target.value === "" ? -1 : Number(e.target.value);
                  if (v !== (seg.pause_after_ms ?? -1)) save.mutate({ pause_after_ms: v });
                }}
                className="w-16 h-6 rounded bg-well border border-line px-1.5 tnum text-ink text-[12px]"
                aria-label={`Pause after line ${index + 1}, milliseconds`}
              />
              ms
            </label>
          )}
          {seg.error && <span className="text-[12px] text-rec">{seg.error}</span>}
        </div>
      </div>
      <div className="flex items-center gap-0.5 opacity-70 group-hover:opacity-100 focus-within:opacity-100">
        <IconButton label="Move up" disabled={index === 0} onClick={() => onMove(index, index - 1)}>
          <ArrowUp className="size-4" />
        </IconButton>
        <IconButton label="Move down" disabled={index === total - 1} onClick={() => onMove(index, index + 1)}>
          <ArrowDown className="size-4" />
        </IconButton>
        <IconButton label={seg.duration_s ? "Regenerate this line" : "Generate this line"} disabled={busy} onClick={() => onRegenerate(seg.id)}>
          <RefreshCw className="size-4" />
        </IconButton>
      </div>
    </li>
  );
}

// ====================================================================== right: export
function ExportPanel({ project, readyCount }: { project: Project; readyCount: number }) {
  const qc = useQueryClient();
  const [opts, setOpts] = useState<ExportSettings>(project.export_settings);
  const [scope, setScope] = useState<"full" | "segments">("full");
  const { data: exports } = useQuery({ queryKey: ["exports", project.id], queryFn: () => api<Export[]>(`/exports?project_id=${project.id}&limit=8`) });
  const run = useMutation({
    mutationFn: () => post<Export>(`/projects/${project.id}/export`, { ...opts, scope }),
    onSuccess: (e) => {
      qc.invalidateQueries({ queryKey: ["exports", project.id] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      download(`/exports/${e.id}/download`, e.title);
    },
  });
  const stale = (project.segment_counts.stale ?? 0) + (project.segment_counts.pending ?? 0) + (project.segment_counts.failed ?? 0);

  return (
    <div className="space-y-5">
      <section className="space-y-3">
        <h2 className="condensed text-[16px] font-semibold">Export</h2>
        <div role="radiogroup" aria-label="Export scope" className="grid grid-cols-2 rounded-control border border-line p-0.5 bg-well">
          {(["full", "segments"] as const).map((v) => (
            <button key={v} role="radio" aria-checked={scope === v} onClick={() => setScope(v)} className={`h-8 rounded-[5px] text-[13px] ${scope === v ? "bg-raised text-ink" : "text-ink-soft"}`}>
              {v === "full" ? "Full voiceover" : "Separate lines"}
            </button>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Format">
            <Select value={opts.format} onChange={(e) => setOpts({ ...opts, format: e.target.value as "wav" | "mp3" })}>
              <option value="mp3">MP3</option>
              <option value="wav">WAV</option>
            </Select>
          </Field>
          <Field label="Sample rate">
            <Select value={opts.sample_rate} onChange={(e) => setOpts({ ...opts, sample_rate: Number(e.target.value) })}>
              {[24000, 44100, 48000].map((r) => (
                <option key={r} value={r}>
                  {(r / 1000).toFixed(r % 1000 ? 1 : 0)} kHz
                </option>
              ))}
            </Select>
          </Field>
        </div>
        {opts.format === "mp3" && (
          <Field label="Bitrate">
            <Select value={opts.bitrate_kbps} onChange={(e) => setOpts({ ...opts, bitrate_kbps: Number(e.target.value) })}>
              {[96, 128, 192, 256, 320].map((b) => (
                <option key={b} value={b}>
                  {b} kbps
                </option>
              ))}
            </Select>
          </Field>
        )}
        {stale > 0 && readyCount > 0 && <p className="legend">{stale} line{stale > 1 ? "s are" : " is"} not generated or out of date and will be left out.</p>}
        <Button variant="primary" className="w-full" icon={<Download className="size-4" />} busy={run.isPending} disabled={!readyCount} onClick={() => run.mutate()}>
          Export {scope === "full" ? opts.format.toUpperCase() : "ZIP"}
        </Button>
        {run.error && <Notice tone="error">{(run.error as Error).message}</Notice>}
        <p className="legend">Files are tagged as AI-generated speech in their metadata.</p>
      </section>

      {!!exports?.length && (
        <section>
          <h2 className="condensed text-[16px] font-semibold mb-2">Previous exports</h2>
          <ul className="divide-y divide-line border-y border-line">
            {exports.map((e) => (
              <li key={e.id} className="flex items-center gap-2 py-2">
                <div className="min-w-0 flex-1">
                  <p className="text-[13px] truncate">{e.title}</p>
                  <p className="legend">
                    {bytes(e.size_bytes)}, {relativeDate(e.created_at)}
                  </p>
                </div>
                <IconButton label={`Download ${e.title}`} onClick={() => download(`/exports/${e.id}/download`, e.title)}>
                  <Download className="size-4" />
                </IconButton>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

// ====================================================================== bottom: transport + tape strip
function Transport({ project, segments, currentId, onCurrent }: { project: Project; segments: Segment[]; currentId: string | null; onCurrent: (id: string | null) => void }) {
  const ready = segments.filter((s) => s.status === "ready");
  const version = useMemo(
    () => JSON.stringify([ready.map((s) => [s.id, s.take, s.pause_after_ms, s.updated_at]), project.settings.pause_ms, project.settings.paragraph_pause_ms]),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [segments, project.settings.pause_ms, project.settings.paragraph_pause_ms],
  );
  const debouncedVersion = useDebounced(version, 400);
  const { blob, headers } = useAudioBlob(ready.length ? `/projects/${project.id}/mix` : null, debouncedVersion);
  const timeline: TimelineEntry[] = useMemo(() => {
    try {
      return JSON.parse(headers?.get("X-Timeline") ?? "[]");
    } catch {
      return [];
    }
  }, [headers]);
  const wf = useRef<WaveformHandle>(null);
  const [t, setT] = useState(0);
  const [dur, setDur] = useState(0);
  const [playing, setPlaying] = useState(false);
  const total = dur || (timeline.length ? timeline[timeline.length - 1].end : 0);

  useEffect(() => {
    const cur = timeline.find((e) => t >= e.start && t <= e.end + e.pause_after_ms / 1000);
    onCurrent(playing || t > 0 ? (cur?.segment_id ?? null) : null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [t, timeline, playing]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (e.code === "Space" && !["INPUT", "TEXTAREA", "SELECT", "BUTTON"].includes(tag)) {
        e.preventDefault();
        wf.current?.toggle();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="border-t border-line bg-well">
      <div className="px-4 sm:px-6 py-3 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 items-center">
        <div className="flex items-center gap-2 row-span-2">
          <IconButton label="Back to start" onClick={() => wf.current?.seek(0)} disabled={!blob}>
            <SkipBack className="size-4" />
          </IconButton>
          <button
            onClick={() => wf.current?.toggle()}
            disabled={!blob}
            aria-label={playing ? "Pause" : "Play voiceover"}
            className="grid place-items-center size-12 rounded-full bg-signal text-console disabled:opacity-40 disabled:bg-raised disabled:text-muted"
          >
            {playing ? <Pause className="size-5" /> : <Play className="size-5 translate-x-0.5" />}
          </button>
          <div className="ml-2 hidden sm:block">
            <p className="condensed tnum text-[32px] leading-none font-medium" aria-live="off">
              {timecode(t)}
            </p>
            <p className="legend tnum">of {timecode(total)}</p>
          </div>
        </div>

        {/* tape strip: each generated line is a clip, sized by its duration */}
        <div className="min-w-0">
          {timeline.length ? (
            <div className="relative h-7 flex rounded-[4px] overflow-hidden bg-console" aria-label="Lines on the timeline">
              {timeline.map((e, i) => {
                const seg = segments.find((s) => s.id === e.segment_id);
                const w = ((e.end - e.start) / total) * 100;
                const gap = ((e.pause_after_ms / 1000) / total) * 100;
                const active = currentId === e.segment_id;
                return (
                  <div key={e.segment_id} className="flex h-full" style={{ width: `${w + (i < timeline.length - 1 ? gap : 0)}%` }}>
                    <button
                      onClick={() => wf.current?.seek(e.start + 0.001)}
                      title={seg?.text}
                      aria-label={`Jump to line ${i + 1}`}
                      className={`h-full min-w-[3px] text-left px-1.5 text-[11px] truncate border-r border-console transition-colors ${
                        active ? "bg-signal text-console" : "bg-wave/35 text-ink-soft hover:bg-wave/55"
                      }`}
                      style={{ width: `${(w / (w + (i < timeline.length - 1 ? gap : 0))) * 100}%` }}
                    >
                      {i + 1}
                    </button>
                  </div>
                );
              })}
              <div className="absolute inset-y-0 w-px bg-ink pointer-events-none" style={{ left: `${total ? (t / total) * 100 : 0}%` }} aria-hidden />
            </div>
          ) : (
            <p className="legend">Generate lines to hear the voiceover here.</p>
          )}
        </div>
        <div className="min-w-0">
          <Waveform
            ref={wf}
            blob={blob}
            height={44}
            showControls={false}
            onTime={setT}
            onReady={setDur}
            onPlayState={setPlaying}
            label="Voiceover waveform"
          />
        </div>
      </div>
    </div>
  );
}

// ====================================================================== page
export function Studio() {
  const { projectId } = useParams();
  const qc = useQueryClient();
  const key = ["project", projectId];
  const { data: project, isLoading, error } = useQuery({
    queryKey: key,
    queryFn: () => api<Project>(`/projects/${projectId}`),
    refetchInterval: (q) => (q.state.data?.active_job_id ? 1000 : false),
  });
  const [tab, setTab] = useState<"script" | "lines">("lines");
  const [content, setContent] = useState<string | null>(null);
  const [title, setTitle] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [current, setCurrent] = useState<string | null>(null);
  const [dragFrom, setDragFrom] = useState<number | null>(null);
  const job = useJob(jobId ?? project?.active_job_id, [key, ["dashboard"]]);
  const active = job && (job.status === "queued" || job.status === "running");

  useEffect(() => {
    if (project && content === null) setContent(project.script.content);
    if (project && title === null) setTitle(project.title);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project]);
  useEffect(() => {
    if (project && !project.segments?.length && content === null) setTab("script");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.id]);

  const update = useMutation({
    mutationFn: (body: Record<string, unknown>) => patch<Project>(`/projects/${projectId}`, body),
    onSuccess: (p) => qc.setQueryData(key, p),
  });

  // autosave script + title
  const dContent = useDebounced(content, 800);
  useEffect(() => {
    if (project && dContent !== null && dContent !== project.script.content) update.mutate({ content: dContent });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dContent]);
  const dTitle = useDebounced(title, 800);
  useEffect(() => {
    if (project && dTitle && dTitle.trim() && dTitle !== project.title) update.mutate({ title: dTitle.trim() });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dTitle]);

  // settings are batched and saved shortly after the last change
  const pendingSettings = useRef<Partial<ProjectSettings>>({});
  const settingsTimer = useRef<number>(0);
  const onSettings = (s: Partial<ProjectSettings>) => {
    pendingSettings.current = { ...pendingSettings.current, ...s };
    window.clearTimeout(settingsTimer.current);
    settingsTimer.current = window.setTimeout(() => {
      update.mutate({ settings: pendingSettings.current });
      pendingSettings.current = {};
    }, 450);
  };

  const generate = useMutation({
    mutationFn: (body: { segment_ids?: string[]; new_take?: boolean }) => post<{ job_id: string }>(`/projects/${projectId}/generate`, body),
    onSuccess: (r) => {
      setJobId(r.job_id);
      qc.invalidateQueries({ queryKey: key });
    },
  });
  const regenerate = useMutation({
    mutationFn: (id: string) => post<{ job_id: string }>(`/segments/${id}/regenerate`),
    onSuccess: (r) => {
      setJobId(r.job_id);
      qc.invalidateQueries({ queryKey: key });
    },
  });
  const cancel = useMutation({ mutationFn: (id: string) => post(`/jobs/${id}/cancel`), onSuccess: () => qc.invalidateQueries({ queryKey: key }) });
  const reorder = useMutation({
    mutationFn: (ids: string[]) => put<Project>(`/projects/${projectId}/segments/order`, { segment_ids: ids }),
    onMutate: (ids) => {
      const prev = qc.getQueryData<Project>(key);
      if (prev?.segments) {
        const byId = new Map(prev.segments.map((s) => [s.id, s]));
        qc.setQueryData(key, { ...prev, segments: ids.map((id, i) => ({ ...byId.get(id)!, position: i })) });
      }
    },
    onSuccess: (p) => {
      qc.setQueryData(key, p);
      setContent(p.script.content);
    },
  });

  if (isLoading)
    return (
      <div className="p-10">
        <Spinner />
      </div>
    );
  if (error || !project)
    return (
      <div className="p-10">
        <Notice tone="error">This project could not be loaded. It may have been deleted.</Notice>
      </div>
    );

  const segments = project.segments ?? [];
  const readyCount = project.segment_counts.ready ?? 0;
  const todo = segments.filter((s) => s.status !== "ready").length;
  const move = (from: number, to: number) => {
    if (to < 0 || to >= segments.length || from === to) return;
    const ids = segments.map((s) => s.id);
    const [m] = ids.splice(from, 1);
    ids.splice(to, 0, m);
    reorder.mutate(ids);
  };
  const genError = (generate.error ?? regenerate.error) as Error | null;
  const words = (content ?? "").trim() ? (content ?? "").trim().split(/\s+/).length : 0;
  const paragraphs = (content ?? "").split(/\n\s*\n/).filter((p) => p.trim()).length;

  return (
    <div className="min-h-dvh md:h-dvh flex flex-col">
      {/* header */}
      <header className="flex flex-wrap items-center gap-3 px-4 sm:px-6 h-auto min-h-16 py-2 border-b border-line">
        <input
          value={title ?? ""}
          onChange={(e) => setTitle(e.target.value)}
          aria-label="Project title"
          className="condensed text-[24px] font-semibold bg-transparent border-b border-transparent hover:border-line focus:border-signal focus:outline-none min-w-0 flex-1 max-w-[520px]"
        />
        <span className="legend">{update.isPending ? "Saving…" : "Saved"}</span>
        <div className="ml-auto flex items-center gap-2">
          {active && job ? (
            <>
              <div className="w-48 hidden sm:block">
                <Progress value={job.progress} label={job.message} />
              </div>
              <Button variant="ghost" onClick={() => cancel.mutate(job.id)} busy={cancel.isPending}>
                Stop
              </Button>
            </>
          ) : (
            <Button
              variant="primary"
              icon={<Wand2 className="size-4" />}
              busy={generate.isPending}
              disabled={!project.voice_profile_id || !todo}
              onClick={() => generate.mutate({})}
              title={!project.voice_profile_id ? "Choose a voice first" : undefined}
            >
              {todo === segments.length ? "Generate voiceover" : todo ? `Generate ${todo} line${todo > 1 ? "s" : ""}` : "All lines generated"}
            </Button>
          )}
        </div>
      </header>
      {(genError || job?.status === "failed") && (
        <div className="px-4 sm:px-6 pt-3">
          <Notice tone="error">{genError?.message ?? job?.error}</Notice>
        </div>
      )}

      {/* workspace */}
      <div className="flex-1 min-h-0 grid lg:grid-cols-[280px_1fr_280px]">
        <aside className="border-b lg:border-b-0 lg:border-r border-line p-5 overflow-y-auto" aria-label="Voice and settings">
          <VoicePanel project={project} onSettings={onSettings} onVoice={(id) => update.mutate({ voice_profile_id: id })} />
        </aside>

        <section className="min-w-0 flex flex-col min-h-[50vh]" aria-label="Script">
          <div className="flex items-center gap-4 px-4 sm:px-6 h-12 border-b border-line">
            <div role="tablist" className="inline-flex rounded-control border border-line p-0.5 bg-well">
              {(["lines", "script"] as const).map((v) => (
                <button key={v} role="tab" aria-selected={tab === v} onClick={() => setTab(v)} className={`px-3 h-7 rounded-[5px] text-[13px] ${tab === v ? "bg-raised text-ink" : "text-ink-soft"}`}>
                  {v === "lines" ? `Lines (${segments.length})` : "Full script"}
                </button>
              ))}
            </div>
            <span className="legend tnum ml-auto">
              {words.toLocaleString()} words, {(content ?? "").length.toLocaleString()} characters, {paragraphs} paragraph{paragraphs === 1 ? "" : "s"}
            </span>
          </div>

          {tab === "script" ? (
            <div className="flex-1 min-h-0 p-4 sm:p-6 bg-well">
              <textarea
                value={content ?? ""}
                onChange={(e) => setContent(e.target.value)}
                placeholder={"Paste or write your script.\n\nLeave a blank line between paragraphs. Long scripts are split into sentences automatically, and lines you've already generated are kept when you edit around them."}
                aria-label="Script"
                className="w-full h-full min-h-[320px] resize-none bg-transparent text-[17px] leading-[1.75] text-ink placeholder:text-muted focus:outline-none max-w-[72ch] mx-auto block"
              />
            </div>
          ) : segments.length === 0 ? (
            <div className="p-8 text-center">
              <p className="condensed text-[20px]">No lines yet</p>
              <p className="text-ink-soft mt-1">Write or paste a script, and it will be split into lines you can generate one by one.</p>
              <Button className="mt-4" onClick={() => setTab("script")}>
                Write the script
              </Button>
            </div>
          ) : (
            <ol className="flex-1 overflow-y-auto divide-y divide-line">
              {segments.map((s, i) => (
                <LineRow
                  key={s.id}
                  seg={s}
                  index={i}
                  total={segments.length}
                  current={current === s.id}
                  onMove={move}
                  onRegenerate={(id) => regenerate.mutate(id)}
                  busy={!!active}
                  defaultPause={
                    i < segments.length - 1 && segments[i + 1].paragraph_index !== s.paragraph_index ? project.settings.paragraph_pause_ms : project.settings.pause_ms
                  }
                  dragHandlers={{
                    draggable: true,
                    onDragStart: () => setDragFrom(i),
                    onDragOver: (e) => e.preventDefault(),
                    onDrop: () => {
                      if (dragFrom !== null) move(dragFrom, i);
                      setDragFrom(null);
                    },
                  }}
                />
              ))}
            </ol>
          )}
        </section>

        <aside className="border-t lg:border-t-0 lg:border-l border-line p-5 overflow-y-auto" aria-label="Export and project">
          <ExportPanel project={project} readyCount={readyCount} />
          <section className="mt-6 pt-5 border-t border-line space-y-2 text-[13px]">
            <h2 className="condensed text-[16px] font-semibold">Project</h2>
            <p className="flex justify-between text-ink-soft">
              Generated <span className="tnum text-ink">{readyCount} of {segments.length} lines</span>
            </p>
            <p className="flex justify-between text-ink-soft">
              Length <span className="tnum text-ink">{duration(project.duration_s || null)}</span>
            </p>
            <p className="flex justify-between text-ink-soft">
              Last edited <span className="text-ink">{relativeDate(project.updated_at)}</span>
            </p>
            {readyCount > 0 && (
              <Button variant="ghost" className="w-full mt-2" icon={<RefreshCw className="size-4" />} disabled={!!active} onClick={() => generate.mutate({ segment_ids: segments.map((s) => s.id), new_take: true })}>
                Regenerate every line
              </Button>
            )}
            <Link to="/projects" className="inline-flex items-center gap-1.5 text-ink-soft hover:text-ink pt-2">
              <Trash2 className="size-3.5" /> Manage projects
            </Link>
          </section>
        </aside>
      </div>

      <Transport project={project} segments={segments} currentId={current} onCurrent={setCurrent} />
    </div>
  );
}
