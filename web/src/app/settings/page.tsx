"use client";

import { useCallback, useEffect, useState } from "react";

import { Button, Card, Field, Notice, inputCls } from "@/components/ui";
import { api } from "@/lib/api";

type Env = "testnet" | "mainnet";
type CredStatus = { env: Env; configured: boolean; api_key_masked: string | null };
type TestRes = { ok: boolean; error?: string; can_trade?: boolean; total_wallet_balance?: string; available_balance?: string };

const ENV_LABEL: Record<Env, string> = { testnet: "Testnet (모의)", mainnet: "Mainnet (실계좌)" };

export default function SettingsPage() {
  const [status, setStatus] = useState<CredStatus[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => api<CredStatus[]>("/api/exchange/credentials").then(setStatus), []);
  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, [load]);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">설정 · 거래소 API 키</h1>
      {error && <Notice tone="error">{error}</Notice>}
      <Notice>
        키는 이 PC의 <b>OS 키체인</b>에만 저장되며 브라우저·DB·로그에 남지 않습니다. 실거래 연동은 백테스트 이후 단계이며,
        지금은 키 저장과 <b>읽기 전용 연결 테스트</b>만 수행합니다(주문 전송 없음).
        <br />
        Binance에서 키 생성 시: <b>선물 거래 권한만</b> 허용, <b>출금 권한 비활성화</b>, 가능하면 IP 제한을 설정하세요.
      </Notice>
      <div className="grid gap-4 lg:grid-cols-2">
        {status.map((s) => (
          <CredentialCard key={s.env} status={s} onChange={load} />
        ))}
      </div>
    </div>
  );
}

function CredentialCard({ status, onChange }: { status: CredStatus; onChange: () => void }) {
  const [key, setKey] = useState("");
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "error" | "ok"; text: string } | null>(null);

  async function act(fn: () => Promise<void>) {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
    } catch (e) {
      setMsg({ tone: "error", text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  const save = () =>
    act(async () => {
      await api(`/api/exchange/credentials/${status.env}`, { method: "PUT", json: { api_key: key, api_secret: secret } });
      setKey("");
      setSecret("");
      setMsg({ tone: "ok", text: "키체인에 저장했습니다" });
      onChange();
    });

  const test = () =>
    act(async () => {
      const r = await api<TestRes>(`/api/exchange/credentials/${status.env}/test`, { method: "POST" });
      setMsg(
        r.ok
          ? { tone: "ok", text: `연결 성공 · 거래 가능 ${r.can_trade ? "예" : "아니오"} · 지갑 ${r.total_wallet_balance} USDT` }
          : { tone: "error", text: `연결 실패: ${r.error}` },
      );
    });

  const remove = () =>
    act(async () => {
      await api(`/api/exchange/credentials/${status.env}`, { method: "DELETE" });
      setMsg({ tone: "ok", text: "삭제했습니다" });
      onChange();
    });

  return (
    <Card
      title={ENV_LABEL[status.env]}
      actions={
        <span className={`rounded px-2 py-0.5 text-xs ${status.configured ? "bg-emerald-900/60 text-emerald-300" : "bg-zinc-800 text-zinc-400"}`}>
          {status.configured ? `저장됨 ${status.api_key_masked}` : "미설정"}
        </span>
      }
    >
      <div className="space-y-2">
        <Field label="API Key">
          <input className={inputCls} value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off" spellCheck={false} />
        </Field>
        <Field label="API Secret">
          <input type="password" className={inputCls} value={secret} onChange={(e) => setSecret(e.target.value)} autoComplete="new-password" />
        </Field>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button variant="primary" onClick={save} disabled={busy || key.length < 16 || secret.length < 16}>
          저장
        </Button>
        <Button onClick={test} disabled={busy || !status.configured}>
          연결 테스트
        </Button>
        <Button variant="danger" onClick={remove} disabled={busy || !status.configured}>
          삭제
        </Button>
      </div>
      {msg && (
        <div className="mt-3">
          <Notice tone={msg.tone}>{msg.text}</Notice>
        </div>
      )}
    </Card>
  );
}
