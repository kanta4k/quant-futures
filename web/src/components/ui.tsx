import type { ReactNode } from "react";

export function Card({ title, children, actions }: { title?: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-4">
      {(title || actions) && (
        <div className="mb-3 flex items-center justify-between gap-2">
          {title && <h2 className="text-sm font-semibold text-zinc-300">{title}</h2>}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: "pos" | "neg" }) {
  const color = tone === "pos" ? "text-emerald-400" : tone === "neg" ? "text-rose-400" : "text-zinc-100";
  return (
    <div className="rounded-md bg-zinc-950/60 px-3 py-2">
      <div className="text-xs text-zinc-500">{label}</div>
      <div className={`mt-0.5 font-mono text-lg ${color}`}>{value}</div>
    </div>
  );
}

export function Button({
  variant = "default",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "default" | "primary" | "danger" }) {
  const styles = {
    default: "border-zinc-700 bg-zinc-800 hover:bg-zinc-700",
    primary: "border-sky-600 bg-sky-600 hover:bg-sky-500 text-white",
    danger: "border-rose-700 bg-rose-900/60 hover:bg-rose-800",
  }[variant];
  return (
    <button
      {...props}
      className={`rounded-md border px-3 py-1.5 text-sm disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${props.className ?? ""}`}
    />
  );
}

export const inputCls =
  "w-full rounded-md border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-sm font-mono focus:border-sky-500 focus:outline-none";

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs text-zinc-400">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-zinc-500">{hint}</span>}
    </label>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "error" | "ok"; children: ReactNode }) {
  const styles = {
    info: "border-zinc-700 bg-zinc-900 text-zinc-300",
    error: "border-rose-800 bg-rose-950/50 text-rose-200",
    ok: "border-emerald-800 bg-emerald-950/40 text-emerald-200",
  }[tone];
  return <div className={`rounded-md border px-3 py-2 text-sm ${styles}`}>{children}</div>;
}
