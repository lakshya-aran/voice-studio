import { useState, type FormEvent } from "react";
import { useAuth } from "../auth";
import { Logo } from "../components/Shell";
import { Button, Field, Input, Notice } from "../components/ui";

export function Login() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") await login(email, password);
      else await register(name, email, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-dvh grid lg:grid-cols-[1fr_minmax(420px,520px)]">
      <div className="hidden lg:flex flex-col justify-between p-12 bg-well border-r border-line overflow-hidden">
        <Logo />
        <div>
          <p className="condensed text-[64px] leading-[0.95] font-semibold max-w-[12ch]">Your voice, read back to you.</p>
          <p className="text-ink-soft mt-6 max-w-[48ch]">
            Record a short sample, confirm the speaker's consent, and turn any script into a voiceover in that voice. Cloning
            runs locally with Kyutai Pocket TTS.
          </p>
        </div>
        {/* decorative static waveform, drawn as a tape strip */}
        <div className="flex items-center gap-[3px] h-24" aria-hidden>
          {Array.from({ length: 90 }, (_, i) => {
            const h = 10 + Math.abs(Math.sin(i * 0.37) * Math.cos(i * 0.11)) * 80;
            return <span key={i} className={`w-[3px] rounded-full ${i < 38 ? "bg-signal" : "bg-wave/60"}`} style={{ height: `${h}%` }} />;
          })}
        </div>
      </div>

      <div className="flex items-center justify-center p-6 sm:p-12">
        <form onSubmit={submit} className="w-full max-w-[380px] space-y-5">
          <div className="lg:hidden mb-8">
            <Logo />
          </div>
          <div>
            <h1 className="condensed text-[30px] font-semibold leading-tight">{mode === "login" ? "Sign in" : "Create your account"}</h1>
            <p className="text-ink-soft mt-1">{mode === "login" ? "Pick up where you left off." : "Voices and projects are private to your account."}</p>
          </div>
          {error && <Notice tone="error">{error}</Notice>}
          {mode === "register" && (
            <Field label="Name">
              <Input value={name} onChange={(e) => setName(e.target.value)} required autoComplete="name" />
            </Field>
          )}
          <Field label="Email">
            <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
          </Field>
          <Field label="Password" hint={mode === "register" ? "At least 8 characters" : undefined}>
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={mode === "register" ? 8 : undefined}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
            />
          </Field>
          <Button type="submit" variant="primary" busy={busy} className="w-full h-10">
            {mode === "login" ? "Sign in" : "Create account"}
          </Button>
          <p className="text-[14px] text-ink-soft text-center">
            {mode === "login" ? "New here? " : "Already have an account? "}
            <button type="button" className="text-signal hover:underline" onClick={() => setMode(mode === "login" ? "register" : "login")}>
              {mode === "login" ? "Create an account" : "Sign in"}
            </button>
          </p>
        </form>
      </div>
    </div>
  );
}
