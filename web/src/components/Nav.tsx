"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { api, type Health } from "@/lib/api";

const LINKS = [
  { href: "/", label: "운영 개요" },
  { href: "/backtest", label: "백테스트" },
  { href: "/risk", label: "리스크" },
  { href: "/settings", label: "설정" },
];

export function Nav() {
  const pathname = usePathname();
  const [health, setHealth] = useState<Health | null>(null);
  const [down, setDown] = useState(false);

  useEffect(() => {
    const load = () =>
      api<Health>("/api/health")
        .then((h) => {
          setHealth(h);
          setDown(false);
        })
        .catch(() => setDown(true));
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  return (
    <header className="border-b border-zinc-800 bg-zinc-950">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
        <span className="font-semibold tracking-tight">Quant Futures</span>
        <nav className="flex gap-1">
          {LINKS.map((l) => {
            const active = l.href === "/" ? pathname === "/" : pathname.startsWith(l.href);
            return (
              <Link
                key={l.href}
                href={l.href}
                className={`rounded-md px-3 py-1.5 text-sm ${active ? "bg-zinc-800 text-white" : "text-zinc-400 hover:text-zinc-200"}`}
              >
                {l.label}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto flex items-center gap-2 text-xs">
          {down ? (
            <span className="rounded bg-rose-900/70 px-2 py-1 text-rose-200">백엔드 연결 끊김</span>
          ) : health ? (
            <>
              <span className="rounded bg-zinc-800 px-2 py-1">{health.mode}</span>
              <span className="rounded bg-zinc-800 px-2 py-1">{health.location}</span>
              <span className="rounded bg-zinc-800 px-2 py-1 text-zinc-400">
                LIVE {health.live_enabled ? "활성" : "비활성"}
              </span>
            </>
          ) : (
            <span className="text-zinc-500">연결 중…</span>
          )}
        </div>
      </div>
    </header>
  );
}
