import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { api, del, duration, post, relativeDate, type Project, type Voice } from "../api";
import { PageBody } from "../components/Shell";
import { Button, Field, IconButton, Input, Notice, PageHeader, Panel, Select, Spinner, Textarea } from "../components/ui";

function NewProject({ onClose }: { onClose: () => void }) {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const { data: voices } = useQuery({ queryKey: ["voices"], queryFn: () => api<Voice[]>("/voices") });
  const ready = voices?.filter((v) => v.status === "ready") ?? [];
  const [title, setTitle] = useState("");
  const [voice, setVoice] = useState(params.get("voice") ?? "");
  const [content, setContent] = useState("");
  const create = useMutation({
    mutationFn: () => post<Project>("/projects", { title: title.trim() || "Untitled voiceover", voice_profile_id: voice || ready[0]?.id || null, content }),
    onSuccess: (p) => nav(`/studio/${p.id}`),
  });
  return (
    <Panel title="New voiceover" className="mb-6">
      <div className="p-4 grid lg:grid-cols-[1fr_1.4fr] gap-5">
        <div className="space-y-4">
          <Field label="Title">
            <Input autoFocus value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Product launch narration" />
          </Field>
          <Field label="Voice" hint={ready.length ? undefined : "No ready voices yet. You can pick one later in the studio."}>
            <Select value={voice || ready[0]?.id || ""} onChange={(e) => setVoice(e.target.value)} disabled={!ready.length}>
              {ready.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <Field label="Script (you can also paste it in the studio)">
          <Textarea rows={6} value={content} onChange={(e) => setContent(e.target.value)} placeholder="Paste or type your script. Blank lines start new paragraphs." />
        </Field>
      </div>
      {create.error && (
        <div className="px-4 pb-3">
          <Notice tone="error">{(create.error as Error).message}</Notice>
        </div>
      )}
      <div className="flex justify-end gap-2 px-4 pb-4">
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="primary" busy={create.isPending} onClick={() => create.mutate()}>
          Create and open studio
        </Button>
      </div>
    </Panel>
  );
}

export function Projects() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const creating = params.get("new") === "1";
  const [confirm, setConfirm] = useState<string | null>(null);
  const { data, isLoading } = useQuery({ queryKey: ["projects"], queryFn: () => api<Project[]>("/projects") });
  const remove = useMutation({
    mutationFn: (id: string) => del(`/projects/${id}`),
    onSuccess: () => {
      setConfirm(null);
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  return (
    <PageBody>
      <PageHeader title="Projects">
        {!creating && (
          <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setParams({ new: "1" })}>
            New voiceover
          </Button>
        )}
      </PageHeader>
      {creating && <NewProject onClose={() => setParams({})} />}
      <Panel>
        {isLoading ? (
          <div className="p-5">
            <Spinner />
          </div>
        ) : !data?.length ? (
          <p className="p-6 text-ink-soft">No projects yet. Create one to start writing a voiceover.</p>
        ) : (
          <table className="w-full text-left">
            <thead className="legend border-b border-line">
              <tr>
                <th className="font-normal px-4 py-2.5">Title</th>
                <th className="font-normal px-4 py-2.5 hidden md:table-cell">Voice</th>
                <th className="font-normal px-4 py-2.5 hidden sm:table-cell">Progress</th>
                <th className="font-normal px-4 py-2.5 text-right">Length</th>
                <th className="font-normal px-4 py-2.5 text-right hidden sm:table-cell">Edited</th>
                <th className="w-12" />
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {data.map((p) => {
                const ready = p.segment_counts.ready ?? 0;
                return (
                  <tr key={p.id} className="hover:bg-raised/40">
                    <td className="px-4 py-3">
                      <Link to={`/studio/${p.id}`} className="hover:text-signal">
                        {p.title}
                      </Link>
                      <p className="legend">{p.script.word_count} words</p>
                    </td>
                    <td className="px-4 py-3 hidden md:table-cell text-ink-soft">{p.voice_name ?? "–"}</td>
                    <td className="px-4 py-3 hidden sm:table-cell">
                      <span className="tnum text-[13px] text-ink-soft">
                        {ready} of {p.segment_total} lines generated
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right tnum text-ink-soft">{duration(p.duration_s || null)}</td>
                    <td className="px-4 py-3 text-right legend hidden sm:table-cell">{relativeDate(p.updated_at)}</td>
                    <td className="px-2">
                      {confirm === p.id ? (
                        <Button variant="danger" busy={remove.isPending} onClick={() => remove.mutate(p.id)}>
                          Delete
                        </Button>
                      ) : (
                        <IconButton label={`Delete ${p.title}`} onClick={() => setConfirm(p.id)}>
                          <Trash2 className="size-4" />
                        </IconButton>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Panel>
    </PageBody>
  );
}
