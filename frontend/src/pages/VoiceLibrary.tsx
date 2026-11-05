import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Mic, Trash2, Wand2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { api, del, fetchBlob, LANGUAGE_NAMES, relativeDate, type Voice } from "../api";
import { PlayButton } from "../components/PlayButton";
import { PageBody } from "../components/Shell";
import { Button, Field, IconButton, Notice, PageHeader, Panel, Spinner, Status, Textarea } from "../components/ui";
import { ProviderNotice } from "./Dashboard";

function hz(v: number | null | undefined) {
  return v ? `${Math.round(v)} Hz` : "–";
}

function VoiceDetail({ v }: { v: Voice }) {
  const qc = useQueryClient();
  const [text, setText] = useState("Here's a quick line to hear how this voice handles my own words.");
  const [tryUrl, setTryUrl] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const tryIt = useMutation({
    mutationFn: async () => {
      const { blob } = await fetchBlob(`/voices/${v.id}/try`, { method: "POST", body: JSON.stringify({ text }) });
      return URL.createObjectURL(blob);
    },
    onSuccess: (url) => {
      if (tryUrl) URL.revokeObjectURL(tryUrl);
      setTryUrl(url);
    },
  });
  const remove = useMutation({
    mutationFn: () => del(`/voices/${v.id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["voices"] }),
  });
  const a = v.analysis;

  return (
    <div className="px-4 pb-5 pt-1 grid lg:grid-cols-[1fr_1fr] gap-6">
      <div className="space-y-4">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-px bg-line rounded-control overflow-hidden border border-line">
          {[
            ["Median pitch", hz(a.pitch?.median_hz)],
            ["Pitch range", a.pitch?.p10_hz ? `${Math.round(a.pitch.p10_hz)}–${Math.round(a.pitch.p90_hz ?? 0)} Hz` : "–"],
            ["Pace", a.pace ? `${a.pace}${a.syllables_per_s ? `, ${a.syllables_per_s} syl/s` : ""}` : "–"],
            ["Reference used", a.reference_seconds_used ? `${a.reference_seconds_used} s` : "–"],
          ].map(([k, val]) => (
            <div key={k} className="bg-well px-3 py-2.5">
              <p className="legend">{k}</p>
              <p className="tnum text-[14px] mt-0.5">{val}</p>
            </div>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {v.sample && <PlayButton id={`sample-${v.sample.id}`} path={`/samples/${v.sample.id}/audio`} label="original sample" size="sm" />}
          <span className="text-[13px] text-ink-soft">Original sample</span>
          {v.has_preview && (
            <>
              <PlayButton id={`voice-${v.id}`} path={`/voices/${v.id}/preview`} label="cloned preview" size="sm" />
              <span className="text-[13px] text-ink-soft">Cloned preview</span>
            </>
          )}
        </div>
        {v.consent && (
          <p className="legend">
            Consent from {v.consent.speaker_name} ({v.consent.relationship === "self" ? "account owner" : "authorized speaker"}), verified{" "}
            {v.consent.verified_at ? relativeDate(v.consent.verified_at) : "–"}.
          </p>
        )}
        <div>
          {confirm ? (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[13px]">Delete this voice, its recordings and its consent recording?</span>
              <Button variant="danger" busy={remove.isPending} onClick={() => remove.mutate()}>
                Delete voice
              </Button>
              <Button variant="ghost" onClick={() => setConfirm(false)}>
                Keep it
              </Button>
            </div>
          ) : (
            <Button variant="ghost" icon={<Trash2 className="size-4" />} onClick={() => setConfirm(true)}>
              Delete voice
            </Button>
          )}
        </div>
      </div>

      <div className="space-y-3">
        <Field label="Try a line">
          <Textarea rows={3} maxLength={400} value={text} onChange={(e) => setText(e.target.value)} />
        </Field>
        <div className="flex items-center gap-3">
          <Button icon={<Wand2 className="size-4" />} busy={tryIt.isPending} disabled={v.status !== "ready" || !text.trim()} onClick={() => tryIt.mutate()}>
            Generate line
          </Button>
          {tryUrl && <audio src={tryUrl} controls autoPlay className="h-9 flex-1 min-w-0" />}
        </div>
        {tryIt.error && <Notice tone="error">{(tryIt.error as Error).message}</Notice>}
      </div>
    </div>
  );
}

function VoiceRow({ v, open, onToggle }: { v: Voice; open: boolean; onToggle: () => void }) {
  return (
    <li className={open ? "bg-raised/40" : ""}>
      <div className="flex items-center gap-3 px-4 py-3">
        <PlayButton id={`voice-${v.id}`} path={`/voices/${v.id}/preview`} label={`${v.name} preview`} disabled={!v.has_preview} />
        <button onClick={onToggle} className="min-w-0 flex-1 text-left" aria-expanded={open}>
          <p className="truncate">{v.name}</p>
          <p className="legend truncate">
            {LANGUAGE_NAMES[v.language] ?? v.language}
            {v.accent ? `, ${v.accent}` : ""}
            {v.description ? `. ${v.description}` : ""}
          </p>
        </button>
        <span className="legend hidden sm:block w-24 text-right">{relativeDate(v.created_at)}</span>
        <span className="w-28 flex justify-end">
          <Status status={v.status} />
        </span>
        <IconButton label={open ? "Hide details" : "Show details"} onClick={onToggle}>
          <span className={`transition-transform ${open ? "rotate-90" : ""}`}>›</span>
        </IconButton>
      </div>
      {v.status === "failed" && v.error && (
        <div className="px-4 pb-3">
          <Notice tone="error">{v.error}</Notice>
        </div>
      )}
      {open && v.status !== "failed" && <VoiceDetail v={v} />}
    </li>
  );
}

export function VoiceLibrary() {
  const nav = useNavigate();
  const [open, setOpen] = useState<string | null>(null);
  const { data, isLoading } = useQuery({
    queryKey: ["voices"],
    queryFn: () => api<Voice[]>("/voices"),
    refetchInterval: (q) => (q.state.data?.some((v) => v.status === "pending" || v.status === "processing") ? 1500 : false),
  });

  return (
    <PageBody>
      <PageHeader title="Voice library" sub="Every voice here was cloned with the speaker's recorded consent. Deleting a voice removes all of its audio.">
        <Button variant="primary" icon={<Mic className="size-4" />} onClick={() => nav("/voices/new")}>
          Clone a voice
        </Button>
      </PageHeader>
      <div className="mb-6">
        <ProviderNotice />
      </div>
      <Panel>
        {isLoading ? (
          <div className="p-5">
            <Spinner />
          </div>
        ) : !data?.length ? (
          <div className="p-8 text-center">
            <p className="condensed text-[22px]">No voices yet</p>
            <p className="text-ink-soft mt-1">Record or upload 10–30 seconds of clear speech to make your first one.</p>
            <Button className="mt-5" variant="primary" icon={<Mic className="size-4" />} onClick={() => nav("/voices/new")}>
              Clone a voice
            </Button>
          </div>
        ) : (
          <ul className="divide-y divide-line">
            {data.map((v) => (
              <VoiceRow key={v.id} v={v} open={open === v.id} onToggle={() => setOpen(open === v.id ? null : v.id)} />
            ))}
          </ul>
        )}
      </Panel>
    </PageBody>
  );
}
