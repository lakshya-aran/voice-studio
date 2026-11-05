import { useQuery } from "@tanstack/react-query";
import { api, relativeDate } from "../api";
import { PageBody } from "../components/Shell";
import { PageHeader, Panel, Spinner } from "../components/ui";

type Entry = { id: number; created_at: string; action: string; target_type: string | null; target_id: string | null; ip_address: string | null; details: Record<string, unknown> };

const LABELS: Record<string, string> = {
  "auth.register": "Account created",
  "auth.login": "Signed in",
  "sample.upload": "Voice sample uploaded",
  "consent.start": "Consent signed",
  "consent.verified": "Consent statement recorded",
  "voice_profile.create": "Voice cloning started",
  "voice_profile.ready": "Voice ready",
  "voice_profile.try": "Voice auditioned",
  "voice_profile.delete": "Voice deleted",
  "generation.start": "Voiceover generated",
  "generation.regenerate": "Line regenerated",
  "export.create": "Audio exported",
  "project.delete": "Project deleted",
};

export function Activity() {
  const { data, isLoading } = useQuery({ queryKey: ["audit"], queryFn: () => api<Entry[]>("/audit?limit=200") });
  return (
    <PageBody>
      <PageHeader title="Activity log" sub="A record of everything done with your account and voices, kept for accountability." />
      <Panel>
        {isLoading ? (
          <div className="p-5">
            <Spinner />
          </div>
        ) : (
          <ul className="divide-y divide-line">
            {data?.map((e) => (
              <li key={e.id} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 px-4 py-2.5">
                <span className="min-w-0 flex-1">{LABELS[e.action] ?? e.action}</span>
                {Object.keys(e.details).length > 0 && (
                  <span className="legend tnum truncate max-w-[40ch]">
                    {Object.entries(e.details)
                      .map(([k, v]) => `${k.replace(/_/g, " ")}: ${String(v)}`)
                      .join(", ")}
                  </span>
                )}
                <span className="legend w-24 text-right" title={new Date(e.created_at).toLocaleString()}>
                  {relativeDate(e.created_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </PageBody>
  );
}
