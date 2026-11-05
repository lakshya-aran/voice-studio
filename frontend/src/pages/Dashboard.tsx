import { useQuery } from "@tanstack/react-query";
import { Download, Mic, Plus } from "lucide-react";
import { Link, useNavigate } from "react-router";
import { api, bytes, download, duration, LANGUAGE_NAMES, relativeDate, type Dashboard as D } from "../api";
import { PlayButton } from "../components/PlayButton";
import { PageBody } from "../components/Shell";
import { Button, IconButton, Notice, Panel, Spinner, Status } from "../components/ui";
import { useProviders } from "../hooks";

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

export function ProviderNotice() {
  const { data } = useProviders();
  const p = data?.[0];
  if (!p || p.status.ready) return null;
  const err = Object.values(p.status.errors ?? {})[0];
  return (
    <Notice tone="warn">
      {err ??
        (p.status.hf_token_configured
          ? "The voice model loads the first time you clone or generate. That first run takes about a minute."
          : "Voice cloning is not set up yet. Accept the model terms at huggingface.co/kyutai/pocket-tts, add HF_TOKEN to backend/.env, and restart the server.")}
    </Notice>
  );
}

export function Dashboard() {
  const nav = useNavigate();
  const { data, isLoading } = useQuery({ queryKey: ["dashboard"], queryFn: () => api<D>("/dashboard") });

  if (isLoading || !data)
    return (
      <PageBody>
        <Spinner />
      </PageBody>
    );
  const { stats } = data;
  const readouts = [
    { value: (stats.audio_seconds / 60).toFixed(1), unit: "min", label: "Audio generated" },
    { value: stats.characters_30d.toLocaleString(), unit: "chars", label: "Characters, last 30 days" },
    { value: String(stats.voices), unit: stats.voices === 1 ? "voice" : "voices", label: "In your library" },
    { value: String(stats.projects), unit: stats.projects === 1 ? "project" : "projects", label: "Saved" },
  ];

  return (
    <PageBody>
      <header className="flex flex-wrap items-end justify-between gap-6 mb-8">
        <div>
          <p className="text-ink-soft">{greeting()},</p>
          <h1 className="condensed text-[44px] leading-none font-semibold mt-1">{data.user.name}</h1>
        </div>
        <div className="flex gap-2">
          <Button icon={<Mic className="size-4" />} onClick={() => nav("/voices/new")}>
            Clone a voice
          </Button>
          <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => nav("/projects?new=1")}>
            New voiceover
          </Button>
        </div>
      </header>

      <div className="mb-6">
        <ProviderNotice />
      </div>

      {/* readout strip: one console row, divided like meter windows */}
      <section aria-label="Usage" className="grid grid-cols-2 lg:grid-cols-4 rounded-panel border border-line bg-well mb-8 divide-line [&>*]:border-line max-lg:[&>*:nth-child(-n+2)]:border-b lg:divide-x max-lg:[&>*:nth-child(odd)]:border-r">
        {readouts.map((r) => (
          <div key={r.label} className="px-5 py-4">
            <p className="condensed tnum text-[30px] leading-none font-medium">
              {r.value}
              <span className="text-[15px] text-muted ml-1.5 font-normal">{r.unit}</span>
            </p>
            <p className="legend mt-2">{r.label}</p>
          </div>
        ))}
      </section>

      <div className="grid lg:grid-cols-[1fr_1.25fr] gap-6">
        <Panel title="Your voices" action={<Link to="/voices" className="text-[13px] text-ink-soft hover:text-ink">Open library</Link>}>
          {data.voices.length === 0 ? (
            <div className="p-5">
              <p className="text-ink-soft">Clone your first voice from a 10–30 second recording. You'll confirm the speaker's consent along the way.</p>
              <Button className="mt-4" icon={<Mic className="size-4" />} onClick={() => nav("/voices/new")}>
                Clone a voice
              </Button>
            </div>
          ) : (
            <ul className="divide-y divide-line">
              {data.voices.map((v) => (
                <li key={v.id} className="flex items-center gap-3 px-4 py-3">
                  <PlayButton id={`voice-${v.id}`} path={`/voices/${v.id}/preview`} label={`${v.name} preview`} disabled={!v.has_preview} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate">{v.name}</p>
                    <p className="legend">
                      {LANGUAGE_NAMES[v.language] ?? v.language}
                      {v.accent ? `, ${v.accent}` : ""}
                    </p>
                  </div>
                  <Status status={v.status} />
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="Recent projects" action={<Link to="/projects" className="text-[13px] text-ink-soft hover:text-ink">All projects</Link>}>
          {data.projects.length === 0 ? (
            <div className="p-5">
              <p className="text-ink-soft">Projects hold a script, a voice and every take you generate.</p>
              <Button className="mt-4" icon={<Plus className="size-4" />} onClick={() => nav("/projects?new=1")}>
                New voiceover
              </Button>
            </div>
          ) : (
            <ul className="divide-y divide-line">
              {data.projects.map((p) => (
                <li key={p.id}>
                  <Link to={`/studio/${p.id}`} className="flex items-center gap-4 px-4 py-3 hover:bg-raised/50">
                    <div className="min-w-0 flex-1">
                      <p className="truncate">{p.title}</p>
                      <p className="legend truncate">
                        {p.voice_name ?? "No voice selected"}, {p.script.word_count} words
                      </p>
                    </div>
                    <span className="tnum text-[13px] text-ink-soft">{duration(p.duration_s || null)}</span>
                    <span className="legend w-20 text-right">{relativeDate(p.updated_at)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <Panel title="Recently exported" className="mt-6">
        {data.exports.length === 0 ? (
          <p className="p-5 text-ink-soft">Exports from the studio appear here for download.</p>
        ) : (
          <ul className="divide-y divide-line">
            {data.exports.map((e) => (
              <li key={e.id} className="flex items-center gap-4 px-4 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="truncate">{e.title}</p>
                  <p className="legend">
                    {e.format.toUpperCase()}
                    {e.bitrate_kbps ? `, ${e.bitrate_kbps} kbps` : ""}, {bytes(e.size_bytes)}
                  </p>
                </div>
                <span className="tnum text-[13px] text-ink-soft">{duration(e.duration_s)}</span>
                <span className="legend w-20 text-right">{relativeDate(e.created_at)}</span>
                <IconButton label={`Download ${e.title}`} onClick={() => download(`/exports/${e.id}/download`, e.title)}>
                  <Download className="size-4" />
                </IconButton>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </PageBody>
  );
}
