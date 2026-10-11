"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";

import { OptimizePanel } from "@/components/backtest/OptimizePanel";
import { ResultView } from "@/components/backtest/ResultView";
import { Button, Card, Field, Notice, inputCls } from "@/components/ui";
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

  const [dl, setDl] = useState({ symbol: "BTCUSDT", interval: "1h", start: "2024-01-01", end: isoDay(new Date()), poolSize: 15 });
  const [bulk, setBulk] = useState<{ done: number; total: number; current: string } | null>(null);

  const [interval, setIntervalValue] = useState("1h");
  const [selected, setSelected] = useState<string[]>([]);
  const [form, setForm] = useState({
    strategy: "bb_ema_volume",
    initial_equity: 500,
    taker_fee_bps: 5,
    slippage_bps: 2,
    min_notional: 5,
    apply_loss_limits: true,
    universe_mode: "dynamic" as "fixed" | "dynamic",
    top_k: 5,
    lookback_days: 7,
    split_on: true,
    train: 60,
    validation: 20,
    test: 20,
    corr_threshold: 0.8,
  });
  const [params, setParams] = useState<Record<string, unknown>>({});
  const [result, setResult] = useState<BacktestDetail | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ tone: "error" | "ok"; text: string } | null>(null);

  const available = useMemo(() => datasets.filter((d) => d.interval === interval), [datasets, interval]);

  const refresh = useCallback(async () => {
    const [d, r] = await Promise.all([api<Dataset[]>("/api/data/datasets"), api<BacktestSummary[]>("/api/backtests")]);
    setDatasets(d);
    setRuns(r);
    return d;
  }, []);

  useEffect(() => {
    api<StrategyInfo[]>("/api/strategies").then((s) => {
      setStrategies(s);
      if (s[0]) setParams(s[0].defaults);
    });
    refresh()
      .then((d) => setSelected(d.filter((x) => x.interval === "1h").map((x) => x.symbol)))
      .catch((e) => setMsg({ tone: "error", text: e.message }));
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

  const range = () => ({ start: `${dl.start}T00:00:00Z`, end: `${dl.end}T00:00:00Z` });

  const download = () =>
    run("download", async () => {
      const d = await api<Dataset>("/api/data/download", { method: "POST", json: { symbol: dl.symbol, interval: dl.interval, ...range() } });
      setMsg({ tone: "ok", text: `${d.symbol} ${d.interval} ${fmt(d.bars, 0)}봉 수집 완료` });
      await refresh();
      setSelected((s) => (s.includes(d.symbol) ? s : [...s, d.symbol]));
    });

  // 후보 풀: 현재 거래대금 상위 N개를 순서대로 수집 → 동적 유니버스가 과거 시점마다 상위 K를 다시 고른다
  const downloadPool = () =>
    run("pool", async () => {
      const top = await api<{ symbol: string }[]>(`/api/data/universe?n=${dl.poolSize}`);
      const failed: string[] = [];
      for (let i = 0; i < top.length; i++) {
        setBulk({ done: i, total: top.length, current: top[i].symbol });
        try {
          await api("/api/data/download", { method: "POST", json: { symbol: top[i].symbol, interval: dl.interval, ...range() } });
        } catch {
          failed.push(top[i].symbol);
        }
      }
      setBulk(null);
      const d = await refresh();
      setIntervalValue(dl.interval);
      setSelected(d.filter((x) => x.interval === dl.interval).map((x) => x.symbol));
      setMsg({
        tone: failed.length ? "error" : "ok",
        text: `후보 풀 ${top.length - failed.length}/${top.length}개 수집 완료${failed.length ? ` · 실패: ${failed.join(", ")}` : ""}`,
      });
    });

  const loadUniverse = () => run("universe", async () => setUniverse(await api("/api/data/universe?n=5")));

  function buildRequest(overrideParams?: Record<string, unknown>) {
    if (selected.length === 0) {
      setMsg({ tone: "error", text: "종목을 하나 이상 선택하세요" });
      return null;
    }
    const total = form.train + form.validation + form.test;
    if (form.split_on && total !== 100) {
      setMsg({ tone: "error", text: `구간 비율 합이 100이어야 합니다 (현재 ${total})` });
      return null;
    }
    return {
      strategy: form.strategy,
      symbols: selected,
      interval,
      params: overrideParams ?? params,
      initial_equity: form.initial_equity,
      apply_loss_limits: form.apply_loss_limits,
      cost: { taker_fee_bps: form.taker_fee_bps, slippage_bps: form.slippage_bps, min_notional: form.min_notional },
      universe: { mode: form.universe_mode, top_k: form.top_k, lookback_days: form.lookback_days },
      split: form.split_on ? { train: form.train / 100, validation: form.validation / 100, test: form.test / 100 } : null,
      portfolio: { corr_threshold: form.corr_threshold },
    };
  }

  const backtest = (overrideParams?: Record<string, unknown>) => {
    const req = buildRequest(overrideParams);
    if (!req) return;
    return run("backtest", async () => {
      setResult(await api<BacktestDetail>("/api/backtests", { method: "POST", json: req }));
      await refresh();
      document.getElementById("result")?.scrollIntoView({ behavior: "smooth" });
    });
  };

  const num = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [key]: +e.target.value });

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
              {busy === "download" ? "수집 중…" : "이 종목 수집"}
            </Button>
            <Button onClick={loadUniverse} disabled={!!busy}>
              현재 상위 5 보기
            </Button>
          </div>
          {universe.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
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
          <div className="mt-4 border-t border-zinc-800 pt-3">
            <div className="flex items-end gap-2">
              <Field label="후보 풀 크기 (현재 거래대금 상위 N)">
                <input type="number" min={5} max={40} className={`${inputCls} w-24`} value={dl.poolSize} onChange={(e) => setDl({ ...dl, poolSize: +e.target.value })} />
              </Field>
              <Button onClick={downloadPool} disabled={!!busy}>
                {busy === "pool" ? "수집 중…" : "후보 풀 일괄 수집"}
              </Button>
            </div>
            {bulk && (
              <div className="mt-2 text-xs text-zinc-400">
                <div className="mb-1 h-1.5 rounded bg-zinc-800">
                  <div className="h-1.5 rounded bg-sky-500" style={{ width: `${(bulk.done / bulk.total) * 100}%` }} />
                </div>
                {bulk.done}/{bulk.total} · {bulk.current} 수집 중
              </div>
            )}
            <p className="mt-2 text-xs text-zinc-500">
              동적 유니버스는 이 풀 안에서 매일 직전 7일 거래대금 상위 K를 고릅니다. 이미 상장 폐지된 종목은 풀에 없으므로
              생존 편향이 일부 남습니다.
            </p>
          </div>
        </Card>

        <Card title="2. 실행 설정">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs text-zinc-400">
              종목 {selected.length}/{available.length}
            </span>
            <div className="flex gap-2 text-xs">
              <select className="rounded border border-zinc-700 bg-zinc-950 px-1" value={interval} onChange={(e) => setIntervalValue(e.target.value)}>
                {[...new Set(datasets.map((d) => d.interval))].map((i) => (
                  <option key={i}>{i}</option>
                ))}
              </select>
              <button className="text-sky-400" onClick={() => setSelected(available.map((d) => d.symbol))}>
                전체
              </button>
              <button className="text-sky-400" onClick={() => setSelected([])}>
                해제
              </button>
            </div>
          </div>
          <div className="mb-3 flex max-h-24 flex-wrap gap-1 overflow-y-auto">
            {available.length === 0 && <span className="text-xs text-zinc-500">데이터 없음 — 먼저 수집하세요</span>}
            {available.map((d) => {
              const on = selected.includes(d.symbol);
              return (
                <button
                  key={d.symbol}
                  onClick={() => setSelected(on ? selected.filter((s) => s !== d.symbol) : [...selected, d.symbol])}
                  className={`rounded px-2 py-0.5 font-mono text-xs ${on ? "bg-sky-700 text-white" : "bg-zinc-800 text-zinc-400"}`}
                >
                  {d.symbol}
                </button>
              );
            })}
          </div>
          <div className="grid grid-cols-3 gap-2">
            <Field label="유니버스">
              <select className={inputCls} value={form.universe_mode} onChange={(e) => setForm({ ...form, universe_mode: e.target.value as "fixed" | "dynamic" })}>
                <option value="dynamic">동적 (거래대금)</option>
                <option value="fixed">고정 (선택 전부)</option>
              </select>
            </Field>
            <Field label="상위 K">
              <input type="number" min={1} max={20} className={inputCls} disabled={form.universe_mode === "fixed"} value={form.top_k} onChange={num("top_k")} />
            </Field>
            <Field label="거래대금 기간(일)">
              <input type="number" min={1} max={60} className={inputCls} disabled={form.universe_mode === "fixed"} value={form.lookback_days} onChange={num("lookback_days")} />
            </Field>
            <Field label="초기 자본">
              <input type="number" className={inputCls} value={form.initial_equity} onChange={num("initial_equity")} />
            </Field>
            <Field label="수수료(bp)">
              <input type="number" step="0.5" className={inputCls} value={form.taker_fee_bps} onChange={num("taker_fee_bps")} />
            </Field>
            <Field label="슬리피지(bp)">
              <input type="number" step="0.5" className={inputCls} value={form.slippage_bps} onChange={num("slippage_bps")} />
            </Field>
            <Field label="최소 주문(USDT)">
              <input type="number" className={inputCls} value={form.min_notional} onChange={num("min_notional")} />
            </Field>
            <Field label="상관 그룹 |ρ|">
              <input type="number" step="0.05" min={0} max={1} className={inputCls} value={form.corr_threshold} onChange={num("corr_threshold")} />
            </Field>
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
                    {s.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <div className="mt-3 space-y-2 text-sm text-zinc-300">
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={form.apply_loss_limits} onChange={(e) => setForm({ ...form, apply_loss_limits: e.target.checked })} />
              일일 손실·누적 낙폭 잠금 적용
            </label>
            <div className="flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={form.split_on} onChange={(e) => setForm({ ...form, split_on: e.target.checked })} />
                구간 분리 (%)
              </label>
              {(["train", "validation", "test"] as const).map((k) => (
                <input
                  key={k}
                  type="number"
                  title={k}
                  disabled={!form.split_on}
                  className={`${inputCls} w-16`}
                  value={form[k]}
                  onChange={num(k)}
                />
              ))}
              <span className="text-xs text-zinc-500">학습/검증/최종</span>
            </div>
          </div>
          <p className="mt-2 text-xs text-zinc-500">리스크 한도는 현재 리스크 설정 버전을 사용합니다.</p>
          <Button variant="primary" className="mt-3" onClick={() => backtest()} disabled={!!busy || selected.length === 0}>
            {busy === "backtest" ? "실행 중…" : "백테스트 실행"}
          </Button>
        </Card>

        <Card title="3. 전략 파라미터">
          <div className="grid max-h-[28rem] grid-cols-2 gap-2 overflow-y-auto pr-1">
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

      <div id="result">{result && <ResultView result={result} />}</div>

      <OptimizePanel
        params={params}
        buildBase={() => buildRequest()}
        onApply={(p) => {
          const next = { ...params, ...p };
          setParams(next);
          backtest(next);
        }}
      />

      <Card title="실행 이력">
        <div className="max-h-80 overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-zinc-900 text-left text-xs text-zinc-500">
              <tr>
                <th className="py-1">#</th>
                <th>시각</th>
                <th>종목</th>
                <th className="text-right">전체 수익</th>
                <th className="text-right">MDD</th>
                <th className="text-right">거래</th>
                <th className="text-right">검증 수익</th>
                <th className="text-right">최종 수익</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              {runs.map((r) => {
                const seg = r.metrics.segments;
                const syms = r.symbol.split(",");
                return (
                  <tr
                    key={r.id}
                    className="cursor-pointer border-t border-zinc-800 hover:bg-zinc-800/50"
                    onClick={() => api<BacktestDetail>(`/api/backtests/${r.id}`).then(setResult)}
                  >
                    <td className="py-1">{r.id}</td>
                    <td>{r.created_at.slice(5, 16).replace("T", " ")}</td>
                    <td title={r.symbol}>{syms.length > 1 ? `${syms.length}종목` : syms[0]}</td>
                    <td className={`text-right ${r.metrics.return_pct >= 0 ? "text-emerald-400" : "text-rose-400"}`}>{fmt(r.metrics.return_pct)}%</td>
                    <td className="text-right">{fmt(r.metrics.max_drawdown_pct)}%</td>
                    <td className="text-right">{r.metrics.trades}</td>
                    <td className="text-right">{seg?.validation ? `${fmt(seg.validation.return_pct)}%` : "–"}</td>
                    <td className="text-right">{seg?.test ? `${fmt(seg.test.return_pct)}%` : "–"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
