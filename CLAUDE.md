# 미국-한국 주식 연계 자동매매 시스템

## 프로젝트 개요

미국 증시(선행)와 한국 증시(후행)의 상관관계를 분석하여
시장 국면을 자동 판단하고 전략과 가중치를 조정하며
KIS API를 통한 모의투자 자동매매를 수행하는 멀티에이전트 시스템.

### 핵심 철학
- 전략(로직)과 코드(시스템)를 완전히 분리
- 전략은 JSON 설정 파일로 관리, 코드는 안정적으로 유지
- 과최적화 방지: 구간별 독립 분석, 단순 조건 우선
- 전략 라이브러리와 이슈 라이브러리를 자산으로 누적

### 현재 상태
- **모의투자 운영 중** (GCP VM에서 PM2로 30분 주기 실행)
- 전체 에이전트 구현 완료, 프론트엔드 완성
- 상세 보고서: `SYSTEM_REPORT.md` 참조

---

## 배포 구조

| 구분 | 호스팅 | 실행 방식 |
|------|--------|----------|
| Python 백엔드 | GCP VM | PM2 (`python main.py --mode schedule`) |
| Next.js 프론트엔드 | Vercel | GitHub main push 시 자동 배포 |
| 데이터베이스 | Supabase | PostgreSQL + Realtime |

### Git 브랜치 전략
- `dev`: 모든 개발 작업 → `main`: 검증 후 merge (배포)
- 상세: `GIT_WORKFLOW.md` 참조

---

## 기술 스택

| 항목 | 기술 |
|------|------|
| 백엔드 | Python 3.11 (async/await) |
| 프론트엔드 | Next.js 14 + TypeScript + Tailwind CSS + Recharts |
| DB | Supabase (PostgreSQL + Realtime 구독) |
| 주문 API | 한국투자증권 KIS API (모의투자) |
| 미국 데이터 | yfinance |
| 한국 데이터 | pykrx + KIS API |
| 알림 | 텔레그램 Bot API |
| 프로세스 관리 | PM2 |

---

## 파이프라인 흐름

```
[사전 체크] KIS 토큰 → DSL/WSL 확인
     │
[Step 1] DC: 데이터수집 (미국/한국/원자재)
     │
[Step 2] MA + IM: 시장분석 + 이슈감지 (병렬)
     │         + 보유 포지션 검토 + 청산 계획
     │
[Step 3] WA: 가중치조정 → 공격/방어/현금 비중 + 종목 선정
     │
[Step 4] SR: 전략매칭 → 전략 라이브러리에서 조건 필터링
     │
[Step 5] EX: 주문실행 → KIS API + 포지션 기록 + 텔레그램
```

### 독립 실행 루프 (파이프라인과 별도)
- 손절/익절 감시: 1분(고변동성) ~ 3분(일반) 간격
- 디버거: 전 에이전트 30초 헬스체크
- 일간 백테스트: 장 종료 후 자동 실행

---

## 에이전트 구조

### 핵심 에이전트 (파이프라인)

| 코드 | 에이전트 | 파일 | 역할 |
|------|---------|------|------|
| OR | 오케스트레이터 | `orchestrator.py` | 파이프라인 지휘, 세션 관리, 최종 판단 |
| DC | 데이터수집 | `agents/data_collector.py` | yfinance/pykrx 실시간 수집 |
| PP | 전처리 | `agents/preprocessor.py` | 표준화, 이상값 탐지 |
| MA | 시장분석 | `agents/market_analyzer.py` | 6단계 국면 판별, 12개 선행지표 |
| IM | 이슈관리 | `agents/issue_manager.py` | 7개 카테고리 이슈 탐지 |
| WA | 가중치조정 | `agents/weight_adjuster.py` | 비중 배분, 종목 선정, SIGNAL 생성 |
| SR | 전략연구 | `agents/strategy_researcher.py` | 전략 매칭 + 일간 백테스팅 |
| EX | 실행 | `agents/executor.py` | KIS 주문, DCA, 분할익절, 텔레그램 |
| DB | 디버깅 | `agents/debugger.py` | 독립 24시간 감시, 오류만 전담 |

### 서비스 클래스 (에이전트가 아닌 공유 모듈)

| 파일 | 역할 |
|------|------|
| `agents/risk_manager.py` | DSL/WSL, 연속손실, 회복모드, 포지션 한도 |
| `agents/position_manager.py` | 포지션 CRUD, 청산 조건 판단 |
| `agents/horizon_manager.py` | 4단계 보유기간 관리, 트레일링 스탑 |
| `agents/classification_loader.py` | 종목 분류 로더 (섹터/테마 역인덱싱) |

### 기타 파일 (비활성 또는 보조)

| 파일 | 상태 |
|------|------|
| `agents/logic_applier.py` | 비활성 — SR에 흡수됨 |
| `agents/system_manager.py` | 비활성 — 디버거가 대체 |
| `agents/recommender.py` | 보조 — 추천 텍스트 생성 |
| `agents/position_analyst.py` | 보조 — 포트폴리오 분석 |

---

## 시장 국면 분류 (6단계)

KOSPI 20일 누적 수익률 + VIX 기반 자동 분류.

| 국면 | 조건 | 공격 | 방어 | 현금 |
|------|------|------|------|------|
| 대상승장 | KOSPI 20일 ≥ +10% | 100% | 0% | 0% |
| 상승장 | +3% ~ +10% | 80% | 0% | 20% |
| 일반장 | -3% ~ +3%, VIX < 20 | 60% | 0% | 40% |
| 변동폭큰 | -3% ~ +3%, VIX ≥ 20 | 20% | 20% | 60% |
| 하락장 | -3% ~ -10% | 0% | 40% | 60% |
| 대폭락장 | ≤ -10% 또는 VIX ≥ 35 | 0% | 20% | 80% |

---

## 보유기간별 청산 기준

설정 파일: `config/horizon_config.json`

| 기간 | 보유 | 익절 | 손절 | 트레일링 (활성/하락) |
|------|------|------|------|-------------------|
| 초단기 | ~3시간 | +1.5% | -0.7% | 없음 (15:20 강제청산) |
| 단기 | 1~5일 | +10% | -2.0% | +2.0% 활성 → -1.5% 청산 |
| 중기 | 1~20일 | +15% | -3.0% | +3.0% 활성 → -2.5% 청산 |
| 장기 | 1~90일 | +25% | -5.0% | +8.0% 활성 → -4.0% 청산 |

### 국면별 기본 보유기간
| 국면 | 기본 기간 |
|------|---------|
| 대상승장 | 중기 |
| 상승장 | 단기 |
| 일반장 | 단기 |
| 변동폭큰 | 초단기 |
| 하락장 | 초단기 |
| 대폭락장 | 초단기 |

---

## 리스크 관리

설정 파일: `config/risk_config.json`

| 항목 | 값 | 동작 |
|------|------|------|
| 일간 손실한도 (DSL) | -3% | 신규 매수 중단 |
| 주간 손실한도 (WSL) | -5% | 신규 매수 중단 |
| 연속 손실 | 3회 | 공격 배분 × 0.5 |
| 회복 모드 | DSL + 상승추세 | 30% 규모 제한 진입 |
| DCA 분할매수 | 1차 60% / 2차 40% | -1% 하락 시 4시간 내 |
| 분할익절 | +1.5%: 30%, +3%: 30% | 나머지 트레일링 |

### 포지션 한도 (국면별)
대상승장 5개 / 상승장 4개 / 일반장 3개 / 변동폭큰 2개 / 하락장·대폭락장 1개

---

## 미국→한국 선행지표 매핑

| 미국 지표 | 한국 반응 섹터 |
|---------|-------------|
| 나스닥100 급등 | 지수ETF |
| SOX 급등 | 반도체, AI/HBM |
| 엔비디아 급등 | AI/HBM (SK하이닉스) |
| AMD 급등 | 반도체 |
| 테슬라 강세 | 2차전지 |
| WTI 급등 | 정유 |
| 구리 강세 | 경기회복 전반 |
| 금 강세 | 안전자산 선호 → AVOID |
| VIX ≥ 30 | 외국인 매도 예고 → AVOID |
| 달러 강세 | 외국인 순매도 → AVOID |

---

## 통신 프로토콜

### 표준 메시지 구조 (protocol/protocol.py)

```json
{
  "header": {
    "msg_id": "[에이전트코드]_[날짜]_[시분초]_[순번]",
    "from": "송신", "to": "수신",
    "priority": "CRITICAL | HIGH | NORMAL | LOW",
    "msg_type": "DATA | SIGNAL | ORDER | ERROR | HEARTBEAT | ALERT"
  },
  "body": { "data_type": "타입명", "payload": {} },
  "status": { "code": "OK | ERROR", "message": "" }
}
```

### 데이터 흐름

```
DC → PP: RAW_MARKET_DATA
PP → MA + IM: PREPROCESSED_DATA (병렬)
MA + IM → WA: MARKET_ANALYSIS + ISSUE_ANALYSIS
WA → SR: SIGNAL
SR → EX: SIGNAL (전략 적용됨)
EX → DB: ORDER
```

---

## 전략 라이브러리

### 폴더 구조
```
data/strategy_library/
├── 대상승구간/    ├── 상승구간/     ├── 일반구간/
├── 안정화구간/    ├── 변동큰구간/   ├── 급등구간/
├── 하락구간/      ├── 급락구간/     └── 대폭락구간/
```

### 전략 채택 기준 (과최적화 방지)
- 3개 이상 다른 기간에서 승률 58% 이상
- 평균 수익률 2% 이상
- MDD -10% 이내
- 기간당 최소 5회 거래
- 일간 백테스트로 자동 검증/폐기

---

## 이슈 라이브러리

```
data/issue_library/
├── 통화금리/   ├── 지정학/     ├── 경제지표/
├── 산업섹터/   ├── 시장구조/   └── 블랙스완/
```

CRITICAL 이슈 발생 시 전체 매매 중단, 기존 포지션 SELL 전환.

---

## 데이터베이스 (Supabase)

### 주요 테이블

| 테이블 | 용도 |
|--------|------|
| `positions` | 보유 포지션 (code, quantity, avg_price, holding_period, status, peak_price) |
| `trades` | 매매 기록 (action, quantity, price, strategy_id, result_pct) |
| `market_phases` | 국면 이력 (phase, confidence, start_date) |
| `agent_logs` | 에이전트 로그 |
| `account_summary` | 계좌 스냅샷 |
| `market_snapshots` | 시장 데이터 스냅샷 |
| `backtest_results` | 백테스트 결과 |
| `pending_dca` | DCA 대기 주문 |
| `exit_plans` | 청산 계획 |

---

## 프론트엔드 (Next.js)

### 페이지 구성

| 경로 | 기능 |
|------|------|
| `/` | 대시보드 — 국면 게이지, 계좌 요약, 에이전트 상태, 최근 신호 |
| `/agents` | 7개 에이전트 실시간 상태 모니터링 |
| `/positions` | 보유/청산 포지션 조회 |
| `/trades` | 매매내역 + 필터링 |
| `/account` | KIS 잔고, 체결내역, 투자 분석 (수익곡선, 승률) |
| `/strategy` | 백테스트 결과, 활성 전략, 청산 계획 |
| `/settings` | 리스크 한도, 국면별 현금비중 조정 |

### KIS API 프록시

| 엔드포인트 | 기능 |
|-----------|------|
| `GET /api/kis/balance` | 계좌 잔고 + 보유종목 |
| `GET /api/kis/price?code=005930` | 실시간 시세 |
| `GET /api/kis/trades` | 체결 내역 |

### 데이터 흐름
Python 백엔드 → Supabase → Next.js (Realtime 구독으로 실시간 반영)
프론트엔드 → KIS API 직접 호출 (잔고/시세/체결)

---

## 폴더 구조

```
stock-agent/
├── CLAUDE.md                    ← 이 파일
├── SYSTEM_REPORT.md             ← 상세 시스템 보고서
├── GIT_WORKFLOW.md              ← Git/배포 가이드
├── main.py                      ← 시스템 시작점 (4개 모드)
├── orchestrator.py              ← 오케스트레이터
│
├── config/
│   ├── settings.py              ← API 키, 환경 변수 (.env 로더)
│   ├── strategy_config.json     ← 국면별 가중치, 종목 유니버스, 선행지표
│   ├── risk_config.json         ← DSL/WSL, DCA, 분할익절 설정
│   ├── horizon_config.json      ← 4단계 보유기간별 청산 기준
│   └── stock_classification.json ← 종목 분류 (섹터/테마)
│
├── protocol/
│   └── protocol.py              ← 표준 메시지 클래스
│
├── agents/
│   ├── base_agent.py            ← 공통 베이스 (timeout, retry, logging)
│   ├── data_collector.py        ← DC: 데이터수집
│   ├── preprocessor.py          ← PP: 전처리
│   ├── market_analyzer.py       ← MA: 시장분석
│   ├── issue_manager.py         ← IM: 이슈관리
│   ├── weight_adjuster.py       ← WA: 가중치조정
│   ├── strategy_researcher.py   ← SR: 전략연구
│   ├── executor.py              ← EX: 실행
│   ├── debugger.py              ← DB: 디버깅 (독립)
│   ├── risk_manager.py          ← 리스크 관리 서비스
│   ├── position_manager.py      ← 포지션 CRUD 서비스
│   ├── horizon_manager.py       ← 보유기간 관리 서비스
│   └── classification_loader.py ← 종목 분류 로더
│
├── database/
│   └── db.py                    ← Supabase 연동 (14개 함수)
│
├── data/
│   ├── strategy_library/        ← 9개 국면별 전략 카드 (JSON)
│   ├── issue_library/           ← 6개 카테고리 이슈 카드 (JSON)
│   ├── history/                 ← 히스토리 수집/백테스트 엔진
│   └── reports/                 ← 전략 리포트 (일간 생성)
│
├── frontend/
│   ├── app/                     ← 7개 페이지 + API 라우트
│   ├── components/              ← UI 컴포넌트
│   ├── hooks/                   ← 데이터 페칭 훅
│   ├── lib/                     ← 유틸리티, KIS 클라이언트, 타입
│   └── providers/               ← Supabase 실시간 구독 프로바이더
│
├── tests/                       ← 단위 테스트
└── logs/                        ← 운영 로그
```

---

## 설정 파일 변경 원칙

- **전략/가중치 변경**: `config/strategy_config.json` 수정 → 코드 변경 불필요
- **리스크 파라미터 변경**: `config/risk_config.json` 수정
- **보유기간 기준 변경**: `config/horizon_config.json` 수정
- **종목 추가/제거**: `config/stock_classification.json` + `strategy_config.json` 수정
- **코드 변경 시**: `dev` 브랜치에서 작업 → 테스트 → `main` merge

---

## 개발 원칙

1. **전략 분리**: 비즈니스 로직은 JSON 설정, 코드는 건드리지 않음
2. **표준폼 필수**: 모든 에이전트 통신은 `protocol.py`의 `StandardMessage` 사용
3. **Graceful Degradation**: 개별 Step 실패 시 이전 결과로 계속 진행
4. **모의 먼저**: 실전 전환 전 충분한 모의투자 검증 필수
5. **dev 브랜치**: 모든 작업은 `dev`에서 → 검증 후 `main` merge

---

*이 파일은 Claude Code가 프로젝트 시작 시 자동으로 읽습니다.*
*설계 변경 시 이 파일을 먼저 업데이트하세요.*
*상세 내용은 `SYSTEM_REPORT.md` 참조.*
