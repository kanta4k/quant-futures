# Quant Futures

코인 무기한 선물(Binance USDⓈ-M) 퀀트 자동매매 시스템. 요구사항은 [docs/PRD.md](docs/PRD.md) (v0.4) 참고.

> 현재 단계: **M1 — 데이터 수집 · 전략 · 백테스트 · 대시보드**.
> 페이퍼/실거래 엔진과 거래소 계정 연동은 백테스트 검증 후 추가한다. API 키는 지금도 입력·저장·연결 테스트(읽기 전용)까지 가능하다.

## 구성

```
backend/   Python 3.11+ · FastAPI · pandas — 전략, 백테스트, 리스크 설정, 데이터 수집
  app/strategies/   전략 플러그인 (base.py 인터페이스, bb_ema_volume.py 초기 전략)
  app/backtest/     포트폴리오 백테스트 엔진 (다음 봉 시가 체결, 수수료·슬리피지·펀딩, 보수적 손절,
                    포트폴리오·상관 그룹 한도, 동적 유니버스), 구간 분리, 파라미터 탐색
  app/core/risk.py  리스크 설정표 · 하드 상한 · 프리셋 · 위험 증가/축소 판정
  app/data/         Binance 공개 API 수집 (키 불필요) → Parquet
  app/exchange/     API 키 저장(OS 키체인) · 읽기 전용 연결 테스트
web/       Next.js 대시보드 — /api/* 를 백엔드로 프록시
docs/      PRD 및 이전 버전
```

## 실행 (로컬 PC)

```bash
./scripts/dev.sh
```

- 대시보드: http://127.0.0.1:3000 · API: http://127.0.0.1:8000/docs
- 처음 실행 시 `backend/.env`가 생성된다. **`DASHBOARD_PASSWORD`를 바꿀 것** (위험 증가 리스크 변경 시 확인용).
- 데이터·DB는 `backend/var/` (git 제외).

수동 실행:

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
cd web && npm install && npm run dev
```

## 사용 흐름

1. **백테스트** → "후보 풀 일괄 수집"(현재 거래대금 상위 N) → 동적 유니버스(매일 직전 7일 거래대금 상위 K) + 학습/검증/최종 구간 분리로 실행
   → "파라미터 탐색"은 학습·검증 구간만 보고 순위를 매긴다. 고른 조합을 "적용·실행"해 최종 평가 구간을 확인
2. **리스크** → 프리셋 또는 슬라이더로 변경, 저장 전 USDT 기준 미리보기. 위험 축소는 즉시, 위험 증가는 비밀번호 확인
3. **설정** → Binance API 키(testnet/mainnet) 저장·연결 테스트. 키는 OS 키체인에만 저장

## 테스트

```bash
cd backend && .venv/bin/pytest && .venv/bin/ruff check app tests
cd web && npm run lint && npm run build
```

## 다음 단계 (PRD 10장)

- [x] 다종목(상위 5) 포트폴리오 백테스트 · 상관 그룹 한도 · 학습/검증/최종 구간 분리
- [x] 7일 거래대금 기준 유니버스 선정 (FR-15) — 백테스트용. 실시간 선정은 페이퍼 단계에서
- [x] 파라미터 그리드 탐색 (최대 200조합, 최종 평가 구간 제외)
- [ ] 워크포워드 분석, 상장 폐지 종목 데이터(생존 편향 보정), 종목별 실제 최소 주문·수량 단위 반영
- [ ] 페이퍼 트레이딩 엔진 · 킬스위치 · 알림(Telegram/Discord)
- [ ] M0: Binance testnet 주문·보호 주문 동작 검증
- [ ] 로컬 LIVE 사전 조건 체크리스트 (FR-17)

> 본 소프트웨어는 투자 자문이 아니며, 레버리지 거래는 원금 손실 위험이 있다.
