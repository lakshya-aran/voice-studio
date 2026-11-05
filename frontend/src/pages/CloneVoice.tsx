import { useQueryClient } from "@tanstack/react-query";
import { Check, FileAudio, Upload } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router";
import { ApiError, LANGUAGE_NAMES, post, type Consent, type Quality, type Sample, type Voice } from "../api";
import { PlayButton } from "../components/PlayButton";
import { Recorder } from "../components/Recorder";
import { PageBody } from "../components/Shell";
import { Button, Field, Input, Notice, PageHeader, Progress, Select, Textarea } from "../components/ui";
import { Waveform } from "../components/Waveform";
import { useAudioBlob, useJob, useProviders } from "../hooks";

const STEPS = ["Voice sample", "Speaker consent", "Create and preview"];

function Stepper({ step }: { step: number }) {
  return (
    <ol className="flex flex-wrap gap-x-8 gap-y-2 mb-8 border-b border-line pb-4" aria-label="Progress">
      {STEPS.map((s, i) => (
        <li key={s} className={`flex items-center gap-2.5 ${i === step ? "text-ink" : i < step ? "text-ink-soft" : "text-muted"}`} aria-current={i === step ? "step" : undefined}>
          <span
            className={`grid place-items-center size-6 rounded-full text-[12px] tnum border ${
              i < step ? "bg-ok/15 border-ok/60 text-ok" : i === step ? "border-signal text-signal" : "border-line-strong"
            }`}
          >
            {i < step ? <Check className="size-3.5" /> : i + 1}
          </span>
          <span className="condensed text-[16px]">{s}</span>
        </li>
      ))}
    </ol>
  );
}

function QualityReport({ q }: { q: Quality }) {
  const color = q.grade === "good" ? "text-ok" : q.grade === "fair" ? "text-signal" : "text-rec";
  return (
    <div className="rounded-control border border-line bg-well">
      <div className="flex items-center justify-between px-4 py-3 border-b border-line">
        <p>
          Sample quality <span className={`${color} font-medium capitalize`}>{q.grade}</span>
        </p>
        <span className="condensed tnum text-[22px]">
          {q.score}
          <span className="text-muted text-[14px]">/100</span>
        </span>
      </div>
      <dl className="grid grid-cols-2 sm:grid-cols-4 gap-px bg-line">
        {[
          ["Speech", `${q.speech_seconds.toFixed(1)} s`],
          ["Signal to noise", `${q.snr_db.toFixed(0)} dB`],
          ["Peak level", `${q.peak_dbfs.toFixed(1)} dBFS`],
          ["Clipping", q.clipping_ratio > 0.001 ? `${(q.clipping_ratio * 100).toFixed(2)}%` : "None"],
        ].map(([k, v]) => (
          <div key={k} className="bg-well px-4 py-2.5">
            <dt className="legend">{k}</dt>
            <dd className="tnum text-[14px]">{v}</dd>
          </div>
        ))}
      </dl>
      {q.issues.length > 0 && (
        <ul className="px-4 py-3 space-y-1 text-[14px] text-ink-soft list-disc pl-8">
          {q.issues.map((i) => (
            <li key={i}>{i}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ step 1
function SampleStep({ initial, onDone }: { initial: Sample | null; onDone: (s: Sample) => void }) {
  const [mode, setMode] = useState<"upload" | "record">("upload");
  const [sample, setSample] = useState<Sample | null>(initial);
  const [sel, setSel] = useState<{ start: number; end: number } | null>(
    initial ? { start: initial.trim_start_s ?? 0, end: initial.trim_end_s ?? initial.duration_s } : null,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const { blob } = useAudioBlob(sample ? `/samples/${sample.id}/audio` : null);
  const [dragOver, setDragOver] = useState(false);

  const upload = async (file: Blob, name: string, source: "upload" | "recording") => {
    setBusy(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append("file", file, name);
      fd.append("source", source);
      const s = await post<Sample>("/samples", fd);
      setSample(s);
      setSel({ start: 0, end: s.duration_s });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  };

  const applyTrim = async () => {
    if (!sample || !sel) return sample;
    const full = sel.start < 0.05 && sel.end > sample.duration_s - 0.05;
    if (full && sample.trim_start_s == null) return sample;
    const s = await post<Sample>(`/samples/${sample.id}/trim`, { start_s: sel.start, end_s: sel.end });
    setSample(s);
    return s;
  };

  // debounce re-analysis when the selection changes
  useEffect(() => {
    if (!sample || !sel) return;
    const t = setTimeout(() => {
      applyTrim().catch((e) => setError(e.message));
    }, 600);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sel?.start, sel?.end]);

  const selected = sel ? sel.end - sel.start : 0;

  return (
    <div className="grid lg:grid-cols-[1.4fr_1fr] gap-8">
      <div className="space-y-5">
        <div role="tablist" className="inline-flex rounded-control border border-line p-0.5 bg-well">
          {(["upload", "record"] as const).map((m) => (
            <button
              key={m}
              role="tab"
              aria-selected={mode === m}
              onClick={() => setMode(m)}
              className={`px-4 h-8 rounded-[5px] text-[14px] ${mode === m ? "bg-raised text-ink" : "text-ink-soft"}`}
            >
              {m === "upload" ? "Upload a file" : "Record with microphone"}
            </button>
          ))}
        </div>

        {mode === "upload" ? (
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              const f = e.dataTransfer.files[0];
              if (f) upload(f, f.name, "upload");
            }}
            className={`rounded-panel border border-dashed p-8 text-center transition-colors ${dragOver ? "border-signal bg-signal/5" : "border-line-strong bg-well"}`}
          >
            <FileAudio className="size-7 mx-auto text-muted" aria-hidden />
            <p className="mt-3">Drop an audio file here</p>
            <p className="legend mt-1">WAV, MP3, M4A or FLAC, up to 50 MB</p>
            <input
              ref={fileRef}
              type="file"
              accept=".wav,.mp3,.m4a,.flac,.ogg,.webm,audio/*"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) upload(f, f.name, "upload");
                e.target.value = "";
              }}
            />
            <Button className="mt-4" icon={<Upload className="size-4" />} busy={busy} onClick={() => fileRef.current?.click()}>
              Choose file
            </Button>
          </div>
        ) : (
          <Recorder
            maxSeconds={120}
            onRecorded={(b, ext) => upload(b, `recording${ext}`, "recording")}
            hint="Read naturally, in the tone you want the voice to have. A quiet room and 15–20 cm from the mic works best."
          />
        )}

        {error && <Notice tone="error">{error}</Notice>}

        {sample && (
          <div className="rounded-panel border border-line bg-panel p-4">
            <div className="flex items-baseline justify-between mb-3 gap-4">
              <p className="truncate">{sample.original_filename}</p>
              <p className="legend tnum shrink-0">
                Selected {selected.toFixed(1)} s of {sample.duration_s.toFixed(1)} s
              </p>
            </div>
            <Waveform blob={blob} height={110} selection={sel} onSelectionChange={setSel} label="Voice sample waveform. Drag the highlighted area edges to trim." />
            <p className="legend mt-2">Drag the edges of the highlighted area to keep only clean speech. Up to 30 seconds is used for cloning.</p>
          </div>
        )}
      </div>

      <aside className="space-y-4">
        {sample ? (
          <>
            <QualityReport q={sample.quality} />
            {!sample.quality.usable && <Notice tone="error">This sample can't be cloned. Fix the issues above and record or upload again.</Notice>}
            <Button
              variant="primary"
              className="w-full h-10"
              disabled={!sample.quality.usable || selected < 5}
              onClick={async () => {
                const s = await applyTrim();
                if (s) onDone(s);
              }}
            >
              Continue to consent
            </Button>
            {selected < 5 && <p className="legend">Select at least 5 seconds of speech.</p>}
          </>
        ) : (
          <div className="text-ink-soft space-y-3 text-[14px]">
            <p className="text-ink">What makes a good sample</p>
            <ul className="space-y-2 list-disc pl-5">
              <li>10–30 seconds of one person speaking, with no music or other voices.</li>
              <li>The speaking style you want: the clone copies tone, pace and emotion.</li>
              <li>A clean recording. Room echo and noise are copied too.</li>
            </ul>
          </div>
        )}
      </aside>
    </div>
  );
}

// ------------------------------------------------------------------ step 2
function ConsentStep({ onDone, onBack }: { onDone: (c: Consent) => void; onBack: () => void }) {
  const [form, setForm] = useState({ speaker_name: "", speaker_email: "", relationship: "self" as Consent["relationship"], typed_signature: "" });
  const [checks, setChecks] = useState({ a: false, b: false, c: false });
  const [consent, setConsent] = useState<Consent | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      setConsent(
        await post<Consent>("/consents", {
          ...form,
          speaker_email: form.speaker_email || null,
          confirm_identity_or_authorization: checks.a,
          confirm_no_impersonation: checks.b,
          confirm_disclosure: checks.c,
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save consent");
    } finally {
      setBusy(false);
    }
  };

  const record = async (b: Blob, ext: string) => {
    if (!consent) return;
    setBusy(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append("file", b, `consent${ext}`);
      const c = await post<Consent>(`/consents/${consent.id}/recording`, fd);
      setConsent(c);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  };

  const Check = ({ k, children }: { k: keyof typeof checks; children: ReactNode }) => (
    <label className="flex gap-3 items-start text-[14px] text-ink-soft cursor-pointer">
      <input type="checkbox" className="mt-1 accent-[var(--color-signal)] size-4" checked={checks[k]} onChange={(e) => setChecks({ ...checks, [k]: e.target.checked })} />
      <span>{children}</span>
    </label>
  );

  if (!consent)
    return (
      <div className="grid lg:grid-cols-[1.4fr_1fr] gap-8">
        <div className="space-y-5">
          <div className="grid sm:grid-cols-2 gap-4">
            <Field label="Whose voice is this?">
              <Select value={form.relationship} onChange={(e) => setForm({ ...form, relationship: e.target.value as Consent["relationship"] })}>
                <option value="self">My own voice</option>
                <option value="authorized_third_party">Someone who has authorized me</option>
              </Select>
            </Field>
            <Field label="Speaker's full name">
              <Input value={form.speaker_name} onChange={(e) => setForm({ ...form, speaker_name: e.target.value })} />
            </Field>
            {form.relationship === "authorized_third_party" && (
              <Field label="Speaker's email" hint="Kept with the consent record">
                <Input type="email" value={form.speaker_email} onChange={(e) => setForm({ ...form, speaker_email: e.target.value })} />
              </Field>
            )}
          </div>
          <div className="space-y-3">
            <Check k="a">
              {form.relationship === "self"
                ? "This is my voice, and I am the person in the recording."
                : "The speaker has personally agreed to have their voice cloned, and they will record the consent statement themselves."}
            </Check>
            <Check k="b">The voice will not be used to impersonate anyone, deceive listeners, commit fraud or harass people.</Check>
            <Check k="c">Audio made with this voice will be disclosed as AI-generated where listeners could mistake it for a real recording.</Check>
          </div>
          <Field label="Signature" hint="The speaker types their full name exactly as entered above">
            <Input value={form.typed_signature} onChange={(e) => setForm({ ...form, typed_signature: e.target.value })} className="italic" />
          </Field>
          {error && <Notice tone="error">{error}</Notice>}
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onBack}>
              Back
            </Button>
            <Button
              variant="primary"
              busy={busy}
              disabled={!checks.a || !checks.b || !checks.c || form.speaker_name.trim().length < 2 || !form.typed_signature.trim()}
              onClick={start}
            >
              Sign consent
            </Button>
          </div>
        </div>
        <aside className="text-[14px] text-ink-soft space-y-3">
          <p className="text-ink">Why we ask</p>
          <p>
            A cloned voice can say anything. Only the speaker, or someone they have explicitly authorized, may create one. The signed record and the
            spoken statement are stored encrypted with the voice and deleted along with it.
          </p>
        </aside>
      </div>
    );

  return (
    <div className="grid lg:grid-cols-[1.4fr_1fr] gap-8">
      <div className="space-y-5">
        <p className="text-ink-soft">
          {consent.speaker_name} now reads the statement below aloud, including the code phrase at the end. This recording is kept as evidence of
          consent.
        </p>
        <blockquote className="rounded-panel border border-line bg-well p-5 leading-relaxed">
          <p>{consent.statement_text}</p>
          <p className="mt-4 condensed text-[20px] text-signal">“{consent.consent_phrase}”</p>
        </blockquote>
        {consent.status === "verified" ? (
          <Notice>
            <span className="text-ok">Consent recorded.</span> The statement is stored with this voice.
          </Notice>
        ) : (
          <Recorder maxSeconds={90} onRecorded={record} hint="Press record, read everything above, then stop." />
        )}
        {error && <Notice tone="error">{error}</Notice>}
        <div className="flex gap-2">
          <Button variant="ghost" onClick={() => setConsent(null)} disabled={busy}>
            Back
          </Button>
          <Button variant="primary" disabled={consent.status !== "verified"} busy={busy} onClick={() => onDone(consent)}>
            Continue
          </Button>
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ step 3
function CreateStep({ sample, consent, onBack }: { sample: Sample; consent: Consent; onBack: () => void }) {
  const nav = useNavigate();
  const qc = useQueryClient();
  const { data: providers } = useProviders();
  const caps = providers?.[0]?.capabilities;
  const [form, setForm] = useState({ name: consent.speaker_name, language: "en", accent: "", description: "" });
  const [voice, setVoice] = useState<Voice | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const job = useJob(jobId, [["voices"], ["dashboard"]]);

  const create = async () => {
    setError(null);
    try {
      const r = await post<{ voice: Voice; job_id: string }>("/voices", {
        ...form,
        accent: form.accent || null,
        description: form.description || null,
        sample_id: sample.id,
        consent_id: consent.id,
      });
      setVoice(r.voice);
      setJobId(r.job_id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not start cloning");
    }
  };

  const done = job?.status === "succeeded";
  const failed = job?.status === "failed";

  return (
    <div className="grid lg:grid-cols-[1.4fr_1fr] gap-8">
      <div className="space-y-5">
        <div className="grid sm:grid-cols-2 gap-4">
          <Field label="Voice name">
            <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} disabled={!!jobId} />
          </Field>
          <Field label="Language of the sample" hint="The voice can also speak the other supported languages">
            <Select value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })} disabled={!!jobId}>
              {Object.entries(caps?.languages ?? LANGUAGE_NAMES).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Accent (optional)">
            <Input placeholder="e.g. Scottish, Brazilian" value={form.accent} onChange={(e) => setForm({ ...form, accent: e.target.value })} disabled={!!jobId} />
          </Field>
        </div>
        <Field label="Notes (optional)">
          <Textarea rows={2} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} disabled={!!jobId} />
        </Field>

        {!jobId && (
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onBack}>
              Back
            </Button>
            <Button variant="primary" disabled={!form.name.trim()} onClick={create}>
              Clone voice
            </Button>
          </div>
        )}
        {error && <Notice tone="error">{error}</Notice>}
        {job && !done && !failed && <Progress value={job.progress} label={job.message} />}
        {failed && (
          <Notice tone="error">
            Cloning failed: {job?.error}
            <div className="mt-2">
              <Button onClick={() => nav("/voices")}>Go to voice library</Button>
            </div>
          </Notice>
        )}
        {done && voice && (
          <div className="rounded-panel border border-line bg-panel p-5 space-y-4">
            <p className="condensed text-[22px]">{form.name} is ready</p>
            <p className="text-ink-soft text-[14px]">Compare the original sample with the cloned voice.</p>
            <div className="flex flex-wrap gap-6">
              <span className="flex items-center gap-3">
                <PlayButton id={`sample-${sample.id}`} path={`/samples/${sample.id}/audio`} label="original sample" />
                Original
              </span>
              <span className="flex items-center gap-3">
                <PlayButton id={`voice-${voice.id}`} path={`/voices/${voice.id}/preview`} label="cloned preview" />
                Cloned
              </span>
            </div>
            <div className="flex gap-2 pt-2">
              <Button variant="primary" onClick={() => nav("/projects?new=1&voice=" + voice.id)}>
                Start a voiceover with this voice
              </Button>
              <Button onClick={() => (qc.invalidateQueries({ queryKey: ["voices"] }), nav("/voices"))}>Open voice library</Button>
            </div>
          </div>
        )}
      </div>
      <aside className="text-[14px] text-ink-soft space-y-3">
        <p className="text-ink">What happens</p>
        <p>
          The trimmed sample is analysed for pitch and pace, then {providers?.[0]?.name ?? "the voice model"} builds a reusable voice from it. A short
          preview is rendered so you can compare.
        </p>
        {caps?.notes.map((n) => (
          <p key={n}>{n}</p>
        ))}
      </aside>
    </div>
  );
}

export function CloneVoice() {
  const [step, setStep] = useState(0);
  const [sample, setSample] = useState<Sample | null>(null);
  const [consent, setConsent] = useState<Consent | null>(null);
  return (
    <PageBody>
      <PageHeader title="Clone a voice" />
      <Stepper step={step} />
      {step === 0 && (
        <SampleStep
          initial={sample}
          onDone={(s) => {
            setSample(s);
            setStep(1);
          }}
        />
      )}
      {step === 1 && (
        <ConsentStep
          onBack={() => setStep(0)}
          onDone={(c) => {
            setConsent(c);
            setStep(2);
          }}
        />
      )}
      {step === 2 && sample && consent && <CreateStep sample={sample} consent={consent} onBack={() => setStep(1)} />}
    </PageBody>
  );
}
