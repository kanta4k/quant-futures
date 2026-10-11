"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Button, Card, Field, Notice, Stat, inputCls } from "@/components/ui";
import { api, fmt, type BacktestDetail, type BacktestSummary, type Dataset } from "@/lib/api";

type StrategyInfo = { name: string; version: string; label: string; defaults: Record<string, unknown> };

const isoDay = (d: Date) => d.toISOString().slice(0, 10);

export default function BacktestPage() {
  return (
    <Suspense>
      <Backtest />
    </Suspense>
  );
}

function Backtest() {
  const search = useSearchParams();
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [runs, setRuns] = useState<BacktestSummary[]>([]);
  const [universe, setUniverse] = useState<{ symbol: string; quote_volume_24h: number }[]>([]);

  const [dl, setDl] = useState({ symbol: "BTCUSDT", interval: "1h", start: "2024-01-01", end: isoDay(new Date()) });
  const [form, setForm] = useState({
    strategy: "bb_ema_volume",
    dataset: "",
    initial_equity: 500,
    taker_fee_bps: 5,
    slippage_bps: 2,
    min_notional: 5,
    apply_loss_limits: true,
  });
  const [params, setParams] = useState<Record<string, unknown>>({});
  const [result, setResult] = useState<BacktestDetail | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ tone: "error" | "ok"; text: string } | null>(null);

  const refresh = useCallback(async () => {
    const [d, r] = await Promise.all([api<Dataset[]>("/api/data/datasets"), api<BacktestSummary[]>("/api/backtests")]);
    setDatasets(d);
    setRuns(r);
    setForm((f) => (f.dataset || d.length === 0 ? f : { ...f, dataset: `${d[0].symbol}|${d[0].interval}` }));
  }, []);

  useEffect(() => {
    api<StrategyInfo[]>("/api/strategies").then((s) => {
      setStrategies(s);
      if (s[0]) setParams(s[0].defaults);
    });
    refresh().catch((e) => setMsg({ tone: "error", text: e.message }));
  }, [refresh]);

  useEffect(() => {
    const id = search.get("run");
    if (id) api<BacktestDetail>(`/api/backtests/${id}`).then(setResult);
  }, [search]);

  async function run<T>(label: string, fn: () => Promise<T>) {
    setBusy(label);
    setMsg(null);
    try {
      return await fn();
    } catch (e) {
      setMsg({ tone: "error", text: (e as Error).message });
    } finally {
      setBusy(null);
    }
  }

  const download = () =>
    run("download", async () => {
      const d = await api<Dataset>("/api/data/download", {
        method: "POST",
        json: { ...dl, start: `${dl.start}T00:00:00Z`, end: `${dl.end}T00:00:00Z` },
      });
      setMsg({ tone: "ok", text: `${d.symbol} ${d.interval} ${fmt(d.bars, 0)}봉 수집 완료` });
      setForm((f) => ({ ...f, dataset: `${d.symbol}|${d.interval}` }));
      await refresh();
    });

  const loadUniverse = () => run("universe", async () => setUniverse(await api("/api/data/universe?n=5")));

  const backtest = () =>
    run("backtest", async () => {
      const [symbol, interval] = form.dataset.split("|");
      const r = await api<BacktestDetail>("/api/backtests", {
        method: "POST",
        json: {
          strategy: form.strategy,
          symbol,
          interval,
          params,
          initial_equity: form.initial_equity,
          apply_loss_limits: form.apply_loss_limits,
          cost: { taker_fee_bps: form.taker_fee_bps, slippage_bps: form.slippage_bps, min_notional: form.min_notional },
        },
      });
      setResult(r);
      await refresh();
    });

  const m = result?.metrics;
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">백테스트</h1>
      {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="1. 데이터 수집 (Binance 공개 API, 키 불필요)">
          <div className="grid grid-cols-2 gap-2">
            <Field label="종목">
              <input className={inputCls} value={dl.symbol} onChange={(e) => setDl({ ...dl, symbol: e.target.value.toUpperCase() })} />
            </Field>
            <Field label="봉">
              <select className={inputCls} value={dl.interval} onChange={(e) => setDl({ ...dl, interval: e.target.value })}>
                {["15m", "1h", "4h", "1d"].map((i) => (
                  <option key={i}>{i}</option>
                ))}
              </select>
            </Field>
            <Field label="시작">
              <input type="date" className={inputCls} value={dl.start} onChange={(e) => setDl({ ...dl, start: e.target.value })} />
            </Field>
            <Field label="종료">
              <input type="date" className={inputCls} value={dl.end} onChange={(e) => setDl({ ...dl, end: e.target.value })} />
            </Field>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="primary" onClick={download} disabled={!!busy}>
              {busy === "download" ? "수집 중…" : "수집"}
            </Button>
            <Button onClick={loadUniverse} disabled={!!busy}>
              거래대금 상위 5
            </Button>
          </div>
          {universe.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1">
              {universe.map((u) => (
                <button
                  key={u.symbol}
                  onClick={() => setDl({ ...dl, symbol: u.symbol })}
                  className="rounded bg-zinc-800 px-2 py-0.5 font-mono text-xs hover:bg-zinc-700"
                >
                  {u.symbol}
                </button>
              ))}
            </div>
          )}
        </Card>

        <Card title="2. 실행 설정">
          <div className="grid grid-cols-2 gap-2">
            <Field label="전략">
              <select
                className={inputCls}
                value={form.strategy}
                onChange={(e) => {
                  setForm({ ...form, strategy: e.target.value });
                  setParams(strategies.find((s) => s.name === e.target.value)?.defaults ?? {});
                }}
              >
                {strategies.map((s) => (
                  <option key={s.name} value={s.name}>
                    {s.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="데이터셋">
              <select className={inputCls} value={form.dataset} onChange={(e) => setForm({ ...form, dataset: e.target.value })}>
                {datasets.length === 0 && <option value="">(없음)</option>}
                {datasets.map((d) => (
                  <option key={`${d.symbol}|${d.interval}`} value={`${d.symbol}|${d.interval}`}>
                    {d.symbol} {d.interval}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="초기 자본 (USDT)">
              <input type="number" className={inputCls} value={form.initial_equity} onChange={(e) => setForm({ ...form, initial_equity: +e.target.value })} />
            </Field>
            <Field label="최소 주문금액 (USDT)">
              <input type="number" className={inputCls} value={form.min_notional} onChange={(e) => setForm({ ...form, min_notional: +e.target.value })} />
            </Field>
            <Field label="테이커 수수료 (bp)">
              <input type="number" step="0.5" className={inputCls} value={form.taker_fee_bps} onChange={(e) => setForm({ ...form, taker_fee_bps: +e.target.value })} />
            </Field>
            <Field label="슬리피지 (bp)">
              <input type="number" step="0.5" className={inputCls} value={form.slippage_bps} onChange={(e) => setForm({ ...form, slippage_bps: +e.target.value })} />
            </Field>
          </div>
          <label className="mt-3 flex items-center gap-2 text-sm text-zinc-300">
            <input type="checkbox" checked={form.apply_loss_limits} onChange={(e) => setForm({ ...form, apply_loss_limits: e.target.checked })} />
            일일 손실·누적 낙폭 잠금 적용
          </label>
          <p className="mt-2 text-xs text-zinc-500">리스크 한도는 현재 리스크 설정 버전을 사용합니다.</p>
          <Button variant="primary" className="mt-3" onClick={backtest} disabled={!!busy || !form.dataset}>
            {busy === "backtest" ? "실행 중…" : "백테스트 실행"}
          </Button>
        </Card>

        <Card title="3. 전략 파라미터">
          <div className="grid max-h-80 grid-cols-2 gap-2 overflow-y-auto pr-1">
            {Object.entries(params).map(([k, val]) => (
              <Field key={k} label={k}>
                {typeof val === "boolean" ? (
                  <select className={inputCls} value={String(val)} onChange={(e) => setParams({ ...params, [k]: e.target.value === "true" })}>
                    <option value="true">true</option>
                    <option value="false">false</option>
                  </select>
                ) : typeof val === "number" ? (
                  <input type="number" step="any" className={inputCls} value={val} onChange={(e) => setParams({ ...params, [k]: +e.target.value })} />
                ) : (
                  <input className={inputCls} value={String(val)} onChange={(e) => setParams({ ...params, [k]: e.target.value })} />
                )}
              </Field>
            ))}
          </div>
        </Card>
      </div>

      {result && m && (
        <Card title={`결과 #${result.id}`}>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
            <Stat label="수익률" value={`${fmt(m.return_pct)}%`} tone={m.return_pct >= 0 ? "pos" : "neg"} />
            <Stat label="순손익" value={fmt(m.net_pnl)} tone={m.net_pnl >= 0 ? "pos" : "neg"} />
            <Stat label="최대 낙폭" value={`${fmt(m.max_drawdown_pct)}%`} />
            <Stat label="거래 수" value={m.trades} />
            <Stat label="승률" value={`${fmt(m.win_rate_pct)}%`} />
            <Stat label="PF" value={fmt(m.profit_factor)} />
            <Stat label="수수료" value={fmt(m.fees)} />
            <Stat label="펀딩" value={fmt(m.funding)} />
          </div>
          {Object.keys(result.skipped_signals).length > 0 && (
            <p className="mt-2 text-xs text-zinc-500">
              건너뛴 신호:{" "}
              {Object.entries(result.skipped_signals)
                .map(([k, n]) => `${k} ${n}`)
                .join(", ")}
              {m.ambiguous_bars > 0 && ` · 같은 봉 손절/익절 동시 도달 ${m.ambiguous_bars}건(손절 처리)`}
            </p>
          )}
          <div className="mt-4 h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={result.equity_curve.filter((_, i, a) => i % Math.ceil(a.length / 1500) === 0)}>
                <CartesianGrid stroke="#27272a" />
                <XAxis dataKey="time" tickFormatter={(t: string) => t.slice(0, 10)} stroke="#71717a" fontSize={11} minTickGap={60} />
                <YAxis stroke="#71717a" fontSize={11} domain={["auto", "auto"]} width={60} />
                <Tooltip contentStyle={{ background: "#18181b", border: "1px solid #3f3f46" }} />
                <Area type="monotone" dataKey="equity" stroke="#38bdf8" fill="#38bdf833" dot={false} isAnimationActive={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-4 max-h-80 overflow-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-zinc-900 text-left text-zinc-500">
                <tr>
                  <th className="py-1">방향</th>
                  <th>진입</th>
                  <th className="text-right">진입가</th>
                  <th className="text-right">수량</th>
                  <th>청산</th>
                  <th className="text-right">청산가</th>
                  <th>사유</th>
                  <th className="text-right">순손익</th>
                </tr>
              </thead>
              <tbody className="font-mono">
                {result.trades.map((t, i) => (
                  <tr key={i} className="border-t border-zinc-800">
                    <td className={`py-1 ${t.side === "long" ? "text-emerald-400" : "text-rose-400"}`}>{t.side}</td>
                    <td>{t.entry_time.slice(0, 16)}</td>
                    <td className="text-right">{fmt(t.entry_price, 4)}</td>
                    <td className="text-right">{fmt(t.qty, 6)}</td>
                    <td>{t.exit_time.slice(0, 16)}</td>
                    <td className="text-right">{fmt(t.exit_price, 4)}</td>
                    <td>{t.exit_reason}</td>
                    <td className={`text-right ${t.net_pnl >= 0 ? "text-emerald-400" : "text-rose-400"}`}>{fmt(t.net_pnl, 4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <Card title="실행 이력">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-zinc-500">
            <tr>
              <th className="py-1">#</th>
              <th>시각</th>
              <th>전략</th>
              <th>종목</th>
              <th className="text-right">수익률</th>
              <th className="text-right">MDD</th>
              <th className="text-right">거래</th>
            </tr>
          </thead>
          <tbody className="font-mono">
            {runs.map((r) => (
              <tr
                key={r.id}
                className="cursor-pointer border-t border-zinc-800 hover:bg-zinc-800/50"
                onClick={() => api<BacktestDetail>(`/api/backtests/${r.id}`).then(setResult)}
              >
                <td className="py-1">{r.id}</td>
                <td>{r.created_at.slice(0, 16).replace("T", " ")}</td>
                <td>
                  {r.strategy} v{r.strategy_version}
                </td>
                <td>
                  {r.symbol} {r.interval}
                </td>
                <td className={`text-right ${r.metrics.return_pct >= 0 ? "text-emerald-400" : "text-rose-400"}`}>{fmt(r.metrics.return_pct)}%</td>
                <td className="text-right">{fmt(r.metrics.max_drawdown_pct)}%</td>
                <td className="text-right">{r.metrics.trades}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
