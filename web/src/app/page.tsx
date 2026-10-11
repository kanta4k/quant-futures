"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Card, Notice, Stat } from "@/components/ui";
import { api, fmt, type BacktestSummary, type Dataset, type RiskSettingsRes } from "@/lib/api";

export default function OverviewPage() {
  const [risk, setRisk] = useState<RiskSettingsRes | null>(null);
  const [runs, setRuns] = useState<BacktestSummary[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api<RiskSettingsRes>("/api/risk/settings"),
      api<BacktestSummary[]>("/api/backtests"),
      api<Dataset[]>("/api/data/datasets"),
    ])
      .then(([r, b, d]) => {
        setRisk(r);
        setRuns(b);
        setDatasets(d);
      })
      .catch((e) => setError(String(e.message ?? e)));
  }, []);

  const v = risk?.values;
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">운영 개요</h1>
      {error && <Notice tone="error">백엔드에 연결할 수 없습니다: {error}</Notice>}
      <Notice>
        현재 단계: <b>M1 — 데이터 수집 · 전략 · 백테스트</b>. 페이퍼·실거래 엔진과 거래소 계정 연동은 백테스트 검증 후
        추가됩니다. API 키 입력은 <Link className="text-sky-400 underline" href="/settings">설정</Link>에서 미리 할 수
        있습니다.
      </Notice>

      <Card
        title={`리스크 설정 (v${risk?.version ?? "–"})`}
        actions={
          <Link href="/risk" className="text-sm text-sky-400">
            변경 →
          </Link>
        }
      >
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="자본 사용률" value={v ? `${v.capital_usage_pct}%` : "–"} />
          <Stat label="레버리지" value={v ? `${v.leverage}x ${v.margin_mode === "isolated" ? "격리" : "교차"}` : "–"} />
          <Stat label="주문별 위험" value={v ? `${v.risk_per_trade_pct}%` : "–"} />
          <Stat label="일일 손실 한도" value={v ? `${v.daily_loss_pct}%` : "–"} />
          <Stat label="누적 낙폭 한도" value={v ? `${v.max_drawdown_pct}%` : "–"} />
          <Stat label="동시 포지션" value={v ? `${v.max_positions}개` : "–"} />
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card
          title="최근 백테스트"
          actions={
            <Link href="/backtest" className="text-sm text-sky-400">
              백테스트 →
            </Link>
          }
        >
          {runs.length === 0 ? (
            <p className="text-sm text-zinc-500">아직 실행한 백테스트가 없습니다.</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-zinc-500">
                <tr>
                  <th className="py-1">#</th>
                  <th>종목</th>
                  <th className="text-right">수익률</th>
                  <th className="text-right">MDD</th>
                  <th className="text-right">거래</th>
                </tr>
              </thead>
              <tbody className="font-mono">
                {runs.slice(0, 8).map((r) => (
                  <tr key={r.id} className="border-t border-zinc-800">
                    <td className="py-1">
                      <Link className="text-sky-400" href={`/backtest?run=${r.id}`}>
                        {r.id}
                      </Link>
                    </td>
                    <td title={r.symbol}>{r.symbol.includes(",") ? `${r.symbol.split(",").length}종목` : r.symbol}</td>
                    <td className={`text-right ${r.metrics.return_pct >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                      {fmt(r.metrics.return_pct)}%
                    </td>
                    <td className="text-right">{fmt(r.metrics.max_drawdown_pct)}%</td>
                    <td className="text-right">{r.metrics.trades}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        <Card title="보유 데이터셋">
          {datasets.length === 0 ? (
            <p className="text-sm text-zinc-500">수집된 데이터가 없습니다. 백테스트 화면에서 수집하세요.</p>
          ) : (
            <ul className="space-y-1 font-mono text-sm">
              {datasets.map((d) => (
                <li key={`${d.symbol}_${d.interval}`} className="flex justify-between border-b border-zinc-800 py-1">
                  <span>
                    {d.symbol} · {d.interval}
                  </span>
                  <span className="text-zinc-500">
                    {d.start?.slice(0, 10)} ~ {d.end?.slice(0, 10)} ({fmt(d.bars, 0)}봉)
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
