import { Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";

const variants: Record<Variant, string> = {
  primary: "bg-signal text-console hover:bg-[#f7c35e] font-semibold",
  secondary: "bg-raised text-ink border border-line hover:border-line-strong",
  ghost: "text-ink-soft hover:text-ink hover:bg-raised",
  danger: "text-rec border border-rec/40 hover:bg-rec/10",
};

export function Button({
  variant = "secondary",
  busy,
  icon,
  className = "",
  children,
  disabled,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; busy?: boolean; icon?: ReactNode }) {
  return (
    <button
      {...props}
      disabled={disabled || busy}
      className={`inline-flex items-center justify-center gap-2 rounded-control px-3.5 h-9 text-[14px] transition-colors disabled:opacity-45 disabled:cursor-not-allowed ${variants[variant]} ${className}`}
    >
      {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
}

export function IconButton({
  label,
  className = "",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      {...props}
      aria-label={label}
      title={label}
      className={`inline-grid place-items-center size-8 rounded-control text-ink-soft hover:text-ink hover:bg-raised transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${className}`}
    >
      {children}
    </button>
  );
}

export function Field({ label, hint, error, children }: { label: string; hint?: ReactNode; error?: string | null; children: ReactNode }) {
  return (
    <label className="block">
      <span className="block text-[13px] text-ink-soft mb-1.5">{label}</span>
      {children}
      {hint && !error && <span className="block legend mt-1.5">{hint}</span>}
      {error && <span className="block text-[12px] text-rec mt-1.5">{error}</span>}
    </label>
  );
}

const control =
  "w-full rounded-control bg-well border border-line px-3 text-[14px] text-ink placeholder:text-muted/70 focus:border-signal/70 focus:outline-none";

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${control} h-9 ${props.className ?? ""}`} />;
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={`${control} py-2.5 leading-relaxed ${props.className ?? ""}`} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={`${control} h-9 ${props.className ?? ""}`} />;
}

export function Slider({
  label,
  value,
  min,
  max,
  step,
  format,
  onChange,
  disabled,
  note,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format: (v: number) => string;
  onChange: (v: number) => void;
  disabled?: boolean;
  note?: string;
}) {
  return (
    <div className={disabled ? "opacity-50" : ""}>
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-[13px] text-ink-soft">{label}</span>
        <span className="tnum text-[13px] text-ink">{format(value)}</span>
      </div>
      <input
        type="range"
        className="w-full"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        aria-label={label}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      {note && <p className="legend mt-0.5">{note}</p>}
    </div>
  );
}

const STATUS_COLORS: Record<string, string> = {
  ready: "bg-ok",
  succeeded: "bg-ok",
  verified: "bg-ok",
  generating: "bg-signal animate-pulse",
  processing: "bg-signal animate-pulse",
  running: "bg-signal animate-pulse",
  queued: "bg-signal/50",
  pending: "bg-muted/60",
  stale: "bg-signal-dim",
  failed: "bg-rec",
  revoked: "bg-rec",
};

const STATUS_LABELS: Record<string, string> = {
  ready: "Ready",
  generating: "Generating",
  processing: "Cloning",
  queued: "Queued",
  pending: "Not generated",
  stale: "Out of date",
  failed: "Failed",
};

export function Status({ status, label }: { status: string; label?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[12px] text-ink-soft">
      <span className={`size-2 rounded-full ${STATUS_COLORS[status] ?? "bg-muted"}`} aria-hidden />
      {label ?? STATUS_LABELS[status] ?? status}
    </span>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "error" | "warn"; children: ReactNode }) {
  const styles = {
    info: "border-line bg-panel text-ink-soft",
    warn: "border-signal/40 bg-signal/8 text-ink",
    error: "border-rec/50 bg-rec/10 text-ink",
  }[tone];
  return (
    <div role={tone === "error" ? "alert" : undefined} className={`rounded-control border px-3.5 py-2.5 text-[14px] ${styles}`}>
      {children}
    </div>
  );
}

export function Progress({ value, label }: { value: number; label?: string | null }) {
  return (
    <div>
      <div className="h-1.5 rounded-full bg-well overflow-hidden" role="progressbar" aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100}>
        <div className="h-full bg-signal transition-[width] duration-300" style={{ width: `${Math.max(3, value * 100)}%` }} />
      </div>
      {label && <p className="legend mt-1.5">{label}</p>}
    </div>
  );
}

export function PageHeader({ title, children, sub }: { title: string; sub?: ReactNode; children?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4 mb-7">
      <div>
        <h1 className="condensed text-[34px] leading-none font-semibold">{title}</h1>
        {sub && <p className="text-ink-soft mt-2 max-w-[62ch]">{sub}</p>}
      </div>
      {children && <div className="flex gap-2">{children}</div>}
    </header>
  );
}

export function Panel({ title, action, children, className = "" }: { title?: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-panel border border-line bg-panel ${className}`}>
      {title && (
        <div className="flex items-center justify-between px-4 h-11 border-b border-line">
          <h2 className="condensed text-[16px] font-semibold">{title}</h2>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

export function Spinner() {
  return <Loader2 className="size-5 animate-spin text-muted" aria-label="Loading" />;
}
