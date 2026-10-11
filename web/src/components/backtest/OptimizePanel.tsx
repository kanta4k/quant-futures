"use client";

import { useEffect, useMemo, useState } from "react";

import { Button, Card, Field, Notice, inputCls } from "@/components/ui";
import { api, fmt, type OptimizeJob, type OptimizeRow } from "@/lib/api";

const OBJECTIVES = {
  sharpe: "Sharpe",
  return_pct: "수익률",
  profit_factor: "Profit Factor",
  return_over_dd: "수익률 / MDD",
};
const MAX_COMBOS = 200;

const tone = (n: number) => (n >= 0 ? "text-emerald-400" : "text-rose-400");

function parseList(text: string): number[] {
  return text
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map(Number)
    .filter((n) => Number.isFinite(n));
}

export function OptimizePanel({
  params,
  buildBase,
  onApply,
}: {
  params: Record<string, unknown>;
  buildBase: () => Record<string, unknown> | null;
  onApply: (params: Record<string, unknown>) => void;
}) {
  const numeric = useMemo(() => Object.keys(params).filter((k) => typeof params[k] === "number"), [params]);
  const [grid, setGrid] = useState<Record<string, string>>({
    bb_stddev: "1.5, 2, 2.5",
    volume_multiplier: "1.2, 1.5, 2",
    stop_atr_multiple: "1.5, 2, 3",
  });
  const [objective, setObjective] = useState<keyof typeof OBJECTIVES>("sharpe");
  const [minTrades, setMinTrades] = useState(20);
  const [job, setJob] = useState<OptimizeJob | null>(null);
  const [error, setError] = useState<string | null>(null);

  const parsed = Object.fromEntries(
    Object.entries(grid)
      .map(([k, v]) => [k, parseList(v)] as const)
      .filter(([, v]) => v.length > 0),
  );
  const combos = Object.values(parsed).reduce((n, v) => n * v.length, 1);

  useEffect(() => {
    if (!job || job.status !== "running") return;
    const t = setTimeout(() => api<OptimizeJob>(`/api/optimize/${job.id}`).then(setJob).catch(() => {}), 1000);
    return () => clearTimeout(t);
  }, [job]);

  async function start() {
    setError(null);
    const base = buildBase();
    if (!base) return;
    try {
      setJob(await api<OptimizeJob>("/api/optimize", { method: "POST", json: { base, grid: parsed, objective, min_trades: minTrades } }));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const keys = Object.keys(parsed);
  const row = (r: OptimizeRow, i: number, dim = false) => (
    <tr key={i} className={`border-t border-zinc-800 ${dim ? "opacity-50" : ""}`}>
      <td className="py-1">{dim ? "–" : i + 1}</td>
      {keys.map((k) => (
        <td key={k}>{String(r.params[k])}</td>
      ))}
      <td className="text-right font-semibold">{fmt(r.score, 3)}</td>
      <td className={`text-right ${tone(r.validation.return_pct)}`}>{fmt(r.validation.return_pct)}%</td>
      <td className="text-right">{fmt(r.validation.max_drawdown_pct)}%</td>
      <td className="text-right">{r.validation.trades}</td>
      <td className={`text-right ${tone(r.train.return_pct)}`}>{fmt(r.train.return_pct)}%</td>
      <td className="text-right">{fmt(r.train.sharpe_hourly_annualized)}</td>
      <td className="text-right">
        <Button className="px-2 py-0.5 text-xs" onClick={() => onApply(r.params)}>
          적용·실행
        </Button>
      </td>
    </tr>
  );

  return (
    <Card title="파라미터 탐색 (학습·검증 구간만 사용)">
      <p className="mb-3 text-xs text-zinc-500">
        쉼표로 값 목록을 입력하세요. 각 조합을 학습·검증 구간에서 돌려 <b>검증 구간 점수</b>로 순위를 매깁니다. 최종 평가
        구간은 보지 않으며, 고른 조합은 “적용·실행”으로 전체 백테스트를 돌려 최종 평가 결과를 확인합니다.
      </p>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {numeric.map((k) => (
          <Field key={k} label={`${k} (현재 ${String(params[k])})`}>
            <input
              className={inputCls}
              placeholder="예: 1.5, 2, 2.5"
              value={grid[k] ?? ""}
              onChange={(e) => setGrid({ ...grid, [k]: e.target.value })}
            />
          </Field>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <Field label="목표">
          <select className={inputCls} value={objective} onChange={(e) => setObjective(e.target.value as keyof typeof OBJECTIVES)}>
            {Object.entries(OBJECTIVES).map(([k, v]) => (
              <option key={k} value={k}>
                검증 {v}
              </option>
            ))}
          </select>
        </Field>
        <Field label="검증 최소 거래 수">
          <input type="number" className={`${inputCls} w-28`} value={minTrades} onChange={(e) => setMinTrades(+e.target.value)} />
        </Field>
        <span className={`pb-2 text-sm ${combos > MAX_COMBOS ? "text-rose-400" : "text-zinc-400"}`}>
          조합 {combos}개 {combos > MAX_COMBOS && `(최대 ${MAX_COMBOS})`}
        </span>
        <Button
          variant="primary"
          onClick={start}
          disabled={job?.status === "running" || keys.length === 0 || combos > MAX_COMBOS}
        >
          {job?.status === "running" ? "탐색 중…" : "탐색 시작"}
        </Button>
      </div>
      {error && (
        <div className="mt-3">
          <Notice tone="error">{error}</Notice>
        </div>
      )}
      {job && (
        <div className="mt-4">
          <div className="mb-2 flex items-center gap-3 text-xs text-zinc-400">
            <div className="h-1.5 flex-1 rounded bg-zinc-800">
              <div className="h-1.5 rounded bg-sky-500" style={{ width: `${(job.done / job.total) * 100}%` }} />
            </div>
            <span>
              {job.done}/{job.total} · {job.elapsed_sec}s
            </span>
          </div>
          {job.error && <Notice tone="error">{job.error}</Notice>}
          {job.ranked.length + job.excluded.length > 0 && (
            <div className="max-h-96 overflow-auto">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-zinc-900 text-left text-zinc-500">
                  <tr>
                    <th className="py-1">#</th>
                    {keys.map((k) => (
                      <th key={k}>{k}</th>
                    ))}
                    <th className="text-right">점수</th>
                    <th className="text-right">검증 수익</th>
                    <th className="text-right">검증 MDD</th>
                    <th className="text-right">검증 거래</th>
                    <th className="text-right">학습 수익</th>
                    <th className="text-right">학습 Sharpe</th>
                    <th />
                  </tr>
                </thead>
                <tbody className="font-mono">
                  {job.ranked.map((r, i) => row(r, i))}
                  {job.excluded.map((r, i) => row(r, i, true))}
                </tbody>
              </table>
              {job.excluded.length > 0 && (
                <p className="mt-1 text-xs text-zinc-500">흐린 행: 검증 거래 수가 최소 기준 미만이라 순위에서 제외</p>
              )}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
