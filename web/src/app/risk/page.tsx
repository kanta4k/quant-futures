"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Button, Card, Field, Notice, Stat, inputCls } from "@/components/ui";
import { api, fmt, type RiskSettingsRes, type RiskValues } from "@/lib/api";

type Preset = { label: string; values: RiskValues };
type Diff = { field: string; label: string; old: number | string; new: number | string; increases_risk: boolean };
type PreviewRes = {
  change_kind: "none" | "decrease" | "increase" | "mixed";
  diffs: Diff[];
  requires_password: boolean;
  preview: Record<string, number>;
};
type Version = { version: number; values: RiskValues; change_kind: string; note: string; created_at: string };

const PREVIEW_LABELS: [string, string][] = [
  ["bot_capital", "운용 자본"],
  ["max_loss_per_trade", "주문당 최대 손실"],
  ["max_total_open_risk", "전체 계획 손실"],
  ["daily_loss_limit", "일일 손실 한도"],
  ["drawdown_limit", "누적 낙폭 한도"],
  ["max_symbol_notional", "종목당 최대 명목"],
  ["max_gross_notional", "총 최대 명목"],
];

export default function RiskPage() {
  const [current, setCurrent] = useState<RiskSettingsRes | null>(null);
  const [draft, setDraft] = useState<RiskValues>({});
  const [presets, setPresets] = useState<Record<string, Preset>>({});
  const [equity, setEquity] = useState(500);
  const [pv, setPv] = useState<PreviewRes | null>(null);
  const [pvError, setPvError] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [history, setHistory] = useState<Version[]>([]);
  const [msg, setMsg] = useState<{ tone: "error" | "ok"; text: string } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    const [s, p, h] = await Promise.all([
      api<RiskSettingsRes>("/api/risk/settings"),
      api<Record<string, Preset>>("/api/risk/presets"),
      api<Version[]>("/api/risk/history"),
    ]);
    setCurrent(s);
    setDraft(s.values);
    setPresets(p);
    setHistory(h);
  }, []);

  useEffect(() => {
    load().catch((e) => setMsg({ tone: "error", text: e.message }));
  }, [load]);

  // 값이 바뀔 때마다 즉시 미리보기 (PRD FR-08)
  useEffect(() => {
    if (!current) return;
    const t = setTimeout(() => {
      api<PreviewRes>("/api/risk/preview", { method: "POST", json: { values: draft, equity } })
        .then((r) => {
          setPv(r);
          setPvError(null);
        })
        .catch((e) => {
          setPv(null);
          setPvError(e.message);
        });
    }, 200);
    return () => clearTimeout(t);
  }, [draft, equity, current]);

  async function save(values = draft, note = "") {
    setMsg(null);
    try {
      const r = await api<{ saved: boolean; version?: number; reason?: string }>("/api/risk/settings", {
        method: "PUT",
        json: { values, password: password || null, note },
      });
      setMsg({ tone: "ok", text: r.saved ? `v${r.version} 저장됨 — 다음 신규 주문부터 적용` : (r.reason ?? "") });
      setPassword("");
      await load();
    } catch (e) {
      setMsg({ tone: "error", text: (e as Error).message });
    }
  }

  async function rollback(version: number) {
    setMsg(null);
    try {
      await api(`/api/risk/rollback/${version}`, { method: "POST", json: { password: password || null } });
      setMsg({ tone: "ok", text: `v${version} 값으로 되돌렸습니다` });
      setPassword("");
      await load();
    } catch (e) {
      setMsg({ tone: "error", text: `${(e as Error).message} (위험 증가 되돌림은 비밀번호 필요)` });
    }
  }

  function exportJson() {
    const blob = new Blob([JSON.stringify(draft, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `risk-settings-v${current?.version ?? 0}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  async function importJson(file: File) {
    try {
      setDraft({ ...draft, ...JSON.parse(await file.text()) });
      setMsg({ tone: "ok", text: "파일 값을 불러왔습니다. 미리보기 확인 후 저장하세요." });
    } catch {
      setMsg({ tone: "error", text: "JSON 파일을 읽을 수 없습니다" });
    }
  }

  if (!current) return <p className="text-sm text-zinc-500">불러오는 중…</p>;
  const dirty = pv && pv.change_kind !== "none";
  const changed = new Set(pv?.diffs.map((d) => d.field));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">리스크 설정</h1>
        <span className="text-xs text-zinc-500">
          현재 v{current.version} · 하드 정책 {current.hard_policy_version}
        </span>
      </div>
      {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}

      <Card title="프리셋">
        <div className="flex flex-wrap gap-2">
          {Object.entries(presets).map(([k, p]) => (
            <Button key={k} onClick={() => setDraft(p.values)}>
              {p.label}
            </Button>
          ))}
          <Button onClick={() => setDraft(current.values)}>현재 저장값으로</Button>
          <span className="mx-1 border-l border-zinc-700" />
          <Button onClick={exportJson}>JSON 내보내기</Button>
          <Button onClick={() => fileRef.current?.click()}>JSON 가져오기</Button>
          <input
            ref={fileRef}
            type="file"
            accept="application/json"
            hidden
            onChange={(e) => e.target.files?.[0] && importJson(e.target.files[0])}
          />
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Card title="한도 (슬라이더 또는 숫자 입력)">
            <div className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
              {current.fields.map((f) => {
                const val = Number(draft[f.field]);
                return (
                  <div key={f.field} className={changed.has(f.field) ? "rounded-md bg-sky-950/30 p-1 -m-1" : ""}>
                    <div className="mb-1 flex items-baseline justify-between text-xs">
                      <span className="text-zinc-300">{f.label}</span>
                      <span className="text-zinc-500">
                        {f.min}~{f.max}
                        {f.unit} · 기본 {f.default}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <input
                        type="range"
                        min={f.min}
                        max={f.max}
                        step={f.step}
                        value={val}
                        onChange={(e) => setDraft({ ...draft, [f.field]: +e.target.value })}
                        className="flex-1 accent-sky-500"
                      />
                      <input
                        type="number"
                        min={f.min}
                        max={f.max}
                        step={f.step}
                        value={val}
                        onChange={(e) => setDraft({ ...draft, [f.field]: +e.target.value })}
                        className={`${inputCls} w-24`}
                      />
                      <span className="w-4 text-xs text-zinc-500">{f.unit}</span>
                    </div>
                  </div>
                );
              })}
              <Field label="마진 모드" hint="교차마진은 M0 검증 후 허용">
                <select
                  className={inputCls}
                  value={String(draft.margin_mode)}
                  onChange={(e) => setDraft({ ...draft, margin_mode: e.target.value })}
                >
                  <option value="isolated">격리 (isolated)</option>
                  <option value="cross">교차 (cross)</option>
                </select>
              </Field>
            </div>
          </Card>
        </div>

        <div className="space-y-4">
          <Card title="미리보기 (USDT)">
            <Field label="계좌 평가자산 가정">
              <input type="number" className={inputCls} value={equity} onChange={(e) => setEquity(+e.target.value)} />
            </Field>
            {pvError ? (
              <div className="mt-3">
                <Notice tone="error">{pvError}</Notice>
              </div>
            ) : (
              pv && (
                <div className="mt-3 grid grid-cols-2 gap-2">
                  {PREVIEW_LABELS.map(([k, label]) => (
                    <Stat key={k} label={label} value={fmt(pv.preview[k])} />
                  ))}
                </div>
              )
            )}
          </Card>

          <Card title="변경 사항">
            {!dirty ? (
              <p className="text-sm text-zinc-500">변경 없음</p>
            ) : (
              <>
                <ul className="space-y-1 text-sm">
                  {pv!.diffs.map((d) => (
                    <li key={d.field} className="flex justify-between font-mono">
                      <span className="font-sans">{d.label}</span>
                      <span className={d.increases_risk ? "text-amber-400" : "text-emerald-400"}>
                        {String(d.old)} → {String(d.new)} {d.increases_risk ? "▲" : "▼"}
                      </span>
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-xs text-zinc-500">
                  {pv!.requires_password
                    ? "위험 증가가 포함되어 비밀번호 확인이 필요합니다. 보유 포지션에는 소급하지 않고 다음 신규 주문부터 적용됩니다."
                    : "위험 축소 변경 — 확인 없이 즉시 적용됩니다."}
                </p>
                {pv!.requires_password && (
                  <input
                    type="password"
                    placeholder="대시보드 비밀번호"
                    className={`${inputCls} mt-2`}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                )}
                <Button
                  variant="primary"
                  className="mt-3 w-full"
                  disabled={!!pvError || (pv!.requires_password && !password)}
                  onClick={() => save()}
                >
                  저장
                </Button>
              </>
            )}
          </Card>
        </div>
      </div>

      <Card title="변경 이력">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-zinc-500">
            <tr>
              <th className="py-1">버전</th>
              <th>시각</th>
              <th>종류</th>
              <th>메모</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {history.map((h) => (
              <tr key={h.version} className="border-t border-zinc-800">
                <td className="py-1 font-mono">v{h.version}</td>
                <td className="font-mono">{h.created_at.slice(0, 19).replace("T", " ")}</td>
                <td>{h.change_kind}</td>
                <td className="text-zinc-400">{h.note}</td>
                <td className="text-right">
                  {h.version !== current.version && (
                    <Button className="py-0.5 text-xs" onClick={() => rollback(h.version)}>
                      되돌리기
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
