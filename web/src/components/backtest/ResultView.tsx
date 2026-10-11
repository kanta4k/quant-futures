"use client";

import { useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card, Stat } from "@/components/ui";
import {
  fmt,
  SEGMENT_LABELS,
  SKIP_LABELS,
  type BacktestDetail,
  type Metrics,
  type SegmentName,
} from "@/lib/api";

const SEGMENT_FILL: Record<SegmentName, string> = {
  train: "#38bdf81f",
  validation: "#a78bfa2e",
  test: "#f59e0b2e",
};

const tone = (n: number) => (n >= 0 ? "text-emerald-400" : "text-rose-400");

export function MetricRow({ m }: { m: Metrics }) {
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
      <Stat label="수익률" value={`${fmt(m.return_pct)}%`} tone={m.return_pct >= 0 ? "pos" : "neg"} />
      <Stat label="순손익 (USDT)" value={fmt(m.net_pnl)} tone={m.net_pnl >= 0 ? "pos" : "neg"} />
      <Stat label="최대 낙폭" value={`${fmt(m.max_drawdown_pct)}%`} />
      <Stat label="거래 수" value={m.trades} />
      <Stat label="승률" value={`${fmt(m.win_rate_pct)}%`} />
      <Stat label="Profit Factor" value={fmt(m.profit_factor)} />
      <Stat label="수수료" value={fmt(m.fees)} />
      <Stat label="펀딩" value={fmt(m.funding)} />
    </div>
  );
}

export function ResultView({ result }: { result: BacktestDetail }) {
  const [symbolFilter, setSymbolFilter] = useState("");
  const m = result.metrics;
  const segments = Object.entries(result.segments ?? {}) as [SegmentName, NonNullable<BacktestDetail["segments"][SegmentName]>][];
  const symbols = result.request?.symbols ?? [];
  const curve = result.equity_curve;
  // 구간 경계를 차트 x축(문자열 시각)에 맞춘다
  const areas = useMemo(
    () =>
      segments.map(([name, seg]) => {
        const a = curve.find((p) => p.time >= seg.start.replace("T", " "))?.time;
        const b = [...curve].reverse().find((p) => p.time < seg.end.replace("T", " "))?.time;
        return { name, a, b };
      }),
    [segments, curve],
  );
  const trades = symbolFilter ? result.trades.filter((t) => t.symbol === symbolFilter) : result.trades;
  const bySymbol = Object.entries(result.by_symbol ?? {}).sort((a, b) => b[1].net_pnl - a[1].net_pnl);

  return (
    <Card title={`결과 #${result.id}`}>
      <p className="mb-3 text-xs text-zinc-500">
        {symbols.length > 0 && <>종목 {symbols.length}개 · </>}
        {result.universe_mode === "dynamic" ? `동적 유니버스 상위 ${result.request?.universe?.top_k}` : "고정 종목"} ·{" "}
        {m.start?.slice(0, 10)} ~ {m.end?.slice(0, 10)} · 시장 노출 {fmt(m.time_in_market_pct)}%
      </p>
      <MetricRow m={m} />

      {segments.length > 0 && (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-zinc-500">
              <tr>
                <th className="py-1">구간 (각각 새 계좌)</th>
                <th>기간</th>
                <th className="text-right">수익률</th>
                <th className="text-right">MDD</th>
                <th className="text-right">거래</th>
                <th className="text-right">승률</th>
                <th className="text-right">PF</th>
                <th className="text-right">Sharpe</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              {segments.map(([name, seg]) => (
                <tr key={name} className="border-t border-zinc-800">
                  <td className="py-1 font-sans">
                    {SEGMENT_LABELS[name]}
                    {name === "test" && (
                      <span className="ml-2 rounded bg-amber-900/50 px-1.5 py-0.5 text-[10px] text-amber-300">
                        파라미터 선택에 사용 금지
                      </span>
                    )}
                  </td>
                  <td className="text-xs text-zinc-400">
                    {seg.start.slice(0, 10)} ~ {seg.end.slice(0, 10)}
                  </td>
                  <td className={`text-right ${tone(seg.metrics.return_pct)}`}>{fmt(seg.metrics.return_pct)}%</td>
                  <td className="text-right">{fmt(seg.metrics.max_drawdown_pct)}%</td>
                  <td className="text-right">{seg.metrics.trades}</td>
                  <td className="text-right">{fmt(seg.metrics.win_rate_pct)}%</td>
                  <td className="text-right">{fmt(seg.metrics.profit_factor)}</td>
                  <td className="text-right">{fmt(seg.metrics.sharpe_hourly_annualized)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {Object.keys(result.skipped_signals).length > 0 && (
        <p className="mt-3 text-xs text-zinc-500">
          건너뛴 신호:{" "}
          {Object.entries(result.skipped_signals)
            .sort((a, b) => b[1] - a[1])
            .map(([k, n]) => `${SKIP_LABELS[k] ?? k} ${fmt(n, 0)}`)
            .join(" · ")}
          {m.ambiguous_bars > 0 && ` · 같은 봉 손절/익절 동시 도달 ${m.ambiguous_bars}건(손절 처리)`}
        </p>
      )}

      <div className="mt-4 h-72">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={curve}>
            <CartesianGrid stroke="#27272a" />
            {areas.map(
              (s) =>
                s.a &&
                s.b && <ReferenceArea key={s.name} x1={s.a} x2={s.b} fill={SEGMENT_FILL[s.name]} strokeOpacity={0} />,
            )}
            <XAxis dataKey="time" tickFormatter={(t: string) => t.slice(0, 10)} stroke="#71717a" fontSize={11} minTickGap={60} />
            <YAxis stroke="#71717a" fontSize={11} domain={["auto", "auto"]} width={60} />
            <Tooltip
              contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", fontSize: 12 }}
              formatter={(v, name) => [fmt(Number(v)), name === "equity" ? "평가자산" : String(name)]}
            />
            <Area type="monotone" dataKey="equity" stroke="#38bdf8" fill="#38bdf833" dot={false} isAnimationActive={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      {segments.length > 0 && (
        <p className="mt-1 text-xs text-zinc-500">
          배경색: <span className="text-sky-300">학습</span> · <span className="text-violet-300">검증</span> ·{" "}
          <span className="text-amber-300">최종 평가</span> — 차트는 전체 구간을 한 계좌로 이어서 실행한 결과입니다.
        </p>
      )}

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <div>
          <h3 className="mb-2 text-xs font-semibold text-zinc-400">종목별</h3>
          <table className="w-full text-xs">
            <thead className="text-left text-zinc-500">
              <tr>
                <th className="py-1">종목</th>
                <th className="text-right">거래</th>
                <th className="text-right">승률</th>
                <th className="text-right">순손익</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              {bySymbol.map(([sym, s]) => (
                <tr
                  key={sym}
                  onClick={() => setSymbolFilter(symbolFilter === sym ? "" : sym)}
                  className={`cursor-pointer border-t border-zinc-800 hover:bg-zinc-800/50 ${symbolFilter === sym ? "bg-zinc-800" : ""}`}
                >
                  <td className="py-1">{sym}</td>
                  <td className="text-right">{s.trades}</td>
                  <td className="text-right">{fmt(s.win_rate_pct)}%</td>
                  <td className={`text-right ${tone(s.net_pnl)}`}>{fmt(s.net_pnl)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="lg:col-span-2">
          <h3 className="mb-2 text-xs font-semibold text-zinc-400">
            거래 내역 {symbolFilter && `· ${symbolFilter} (다시 클릭하면 전체)`} · {trades.length}건
          </h3>
          <div className="max-h-80 overflow-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-zinc-900 text-left text-zinc-500">
                <tr>
                  <th className="py-1">종목</th>
                  <th>방향</th>
                  <th>진입</th>
                  <th className="text-right">진입가</th>
                  <th>청산</th>
                  <th className="text-right">청산가</th>
                  <th>사유</th>
                  <th className="text-right">순손익</th>
                </tr>
              </thead>
              <tbody className="font-mono">
                {trades.map((t, i) => (
                  <tr key={i} className="border-t border-zinc-800">
                    <td className="py-1">{t.symbol}</td>
                    <td className={t.side === "long" ? "text-emerald-400" : "text-rose-400"}>{t.side}</td>
                    <td>{t.entry_time.slice(0, 16)}</td>
                    <td className="text-right">{fmt(t.entry_price, 4)}</td>
                    <td>{t.exit_time.slice(0, 16)}</td>
                    <td className="text-right">{fmt(t.exit_price, 4)}</td>
                    <td>{t.exit_reason}</td>
                    <td className={`text-right ${tone(t.net_pnl)}`}>{fmt(t.net_pnl, 4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </Card>
  );
}
