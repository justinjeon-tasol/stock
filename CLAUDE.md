1# 미국-한국 주식 연계 자동매매 시스템

## 프로젝트 개요

미국 증시(선행)와 한국 증시(후행)의 상관관계를 분석하여
시장 국면을 자동 판단하고 전략과 가중치를 조정하며
모의/실전 자동매매를 수행하는 멀티에이전트 시스템.

### 핵심 철학
- 전략(로직)과 코드(시스템)를 완전히 분리
- 전략은 JSON 설정 파일로 관리, 코드는 안정적으로 유지
- 에이전트 하나씩 만들고 테스트 확인 후 다음 연결
- 과최적화 방지: 구간별 독립 분석, 단순 조건 우선
- 전략 라이브러리와 이슈 라이브러리를 자산으로 누적

---

## 기술 스택

| 항목 | 기술 | 비고 |
|------|------|------|
| 언어 | Python 3.11 | |
| DB | Supabase (PostgreSQL) | 무료 플랜으로 시작 |
| 주문 API | 한국투자증권 KIS API | 모의투자 기준 |
| 미국 데이터 | yfinance | 무료 |
| 한국 데이터 | pykrx + KIS API | |
| AI 판단 | Claude API (Sonnet 4.6) | 복잡한 판단만 호출 |
| 알림 | 텔레그램 Bot API | |
| 뉴스 | RSS 피드 (무료) | 추후 유료 API 고려 |

---

## 에이전트 구조 (11개)

### 레이어별 구성

```
[🎯 오케스트레이터]
        │
┌───────┼───────────────────┐
↓       ↓                   ↓
데이터  전략                 운영
레이어  레이어               레이어
```

### 데이터 레이어 (3개)

| # | 에이전트 | 파일 | 핵심 역할 |
|---|---------|------|---------|
| 1 | 🎯 오케스트레이터 | orchestrator.py | 전체 지휘, 에이전트 시작/중지, 최종 판단 |
| 2 | 🌐 데이터수집 | data_collector.py | 미국/한국/원자재/뉴스 수집 (4개 모듈) |
| 3 | 📦 전처리 | preprocessor.py | 표준 데이터폼 변환, 유효성 검증, 이상값 처리 |

### 전략 레이어 (6개)

| # | 에이전트 | 파일 | 핵심 역할 |
|---|---------|------|---------|
| 4 | 🧠 시장분석 | market_analyzer.py | 국면감지 + 추세예측 + 선후행 상관관계 분석 |
| 5 | 📚 이슈관리 | issue_manager.py | 뉴스→이슈 분류, 라이브러리 매핑, 신규 등록 |
| 6 | ⚖️ 가중치조정 | weight_adjuster.py | 국면+이슈 반영한 전략 비중 자동 재배분 |
| 7 | 🔬 전략연구 | strategy_researcher.py | 전략 탐색/백테스팅/최적화/라이브러리 관리 |
| 8 | 🎮 로직적용 | logic_applier.py | 검증된 전략 실전 적용, 국면별 전략 교체 |
| 9 | ⚡ 실행 | executor.py | KIS API 주문, 손절/익절 관리, 텔레그램 알림 |

### 운영 레이어 (2개)

| # | 에이전트 | 파일 | 핵심 역할 |
|---|---------|------|---------|
| 10 | 🔧 시스템관리 | system_manager.py | 코어개발, 코드 자동수정, 패치 적용 |
| 11 | 🐛 디버깅 | debugger.py | 독립적 24시간 오류 감시, 즉각 보고 (지시 안 받음) |

### 디버깅 에이전트 독립 원칙
- 어떤 에이전트의 지시도 받지 않음
- 오직 오케스트레이터에만 보고
- 모든 에이전트를 24시간 감시
- 다른 업무 없이 오류 감시만 전담

---

## 통신 프로토콜

### 표준 메시지 구조 (모든 통신 필수)

```json
{
  "header": {
    "msg_id":    "[에이전트코드]_[날짜]_[시분초]_[순번]",
    "version":   "1.0",
    "from":      "송신 에이전트명",
    "to":        "수신 에이전트명",
    "timestamp": "ISO 8601 형식",
    "priority":  "CRITICAL | HIGH | NORMAL | LOW",
    "msg_type":  "DATA | SIGNAL | ORDER | RESPONSE | ERROR | HEARTBEAT | COMMAND | ALERT"
  },
  "body": {
    "data_type": "데이터 타입명",
    "payload":   {}
  },
  "status": {
    "code":    "OK | ERROR | TIMEOUT | RETRY",
    "message": "상태 메시지"
  }
}
```

### 에이전트 코드 (msg_id 생성용)

| 코드 | 에이전트 |
|------|---------|
| OR | 오케스트레이터 |
| DC | 데이터수집 |
| PP | 전처리 |
| MA | 시장분석 |
| IM | 이슈관리 |
| WA | 가중치조정 |
| SR | 전략연구 |
| LA | 로직적용 |
| EX | 실행 |
| SM | 시스템관리 |
| DB | 디버깅 |

### 데이터 타입 8종 페이로드 정의

#### US_MARKET
```json
{
  "nasdaq":  { "value": 0.0, "change_pct": 0.0, "volume_ratio": 0.0 },
  "sox":     { "value": 0.0, "change_pct": 0.0, "volume_ratio": 0.0 },
  "sp500":   { "value": 0.0, "change_pct": 0.0, "volume_ratio": 0.0 },
  "vix":     { "value": 0.0, "change_pct": 0.0 },
  "usd_krw": { "value": 0.0, "change_pct": 0.0 },
  "futures": { "value": 0.0, "direction": "UP | DOWN | FLAT" }
}
```

#### KR_MARKET
```json
{
  "kospi":           { "value": 0.0, "change_pct": 0.0, "volume_ratio": 0.0 },
  "kosdaq":          { "value": 0.0, "change_pct": 0.0, "volume_ratio": 0.0 },
  "foreign_net":     0,
  "institution_net": 0,
  "stocks": {
    "종목코드": { "name": "종목명", "price": 0, "change_pct": 0.0 }
  }
}
```

#### COMMODITY
```json
{
  "wti":     { "value": 0.0, "change_pct": 0.0 },
  "gold":    { "value": 0.0, "change_pct": 0.0 },
  "copper":  { "value": 0.0, "change_pct": 0.0 },
  "lithium": { "value": 0.0, "change_pct": 0.0 }
}
```

#### MARKET_PHASE
```json
{
  "phase":        "안정화 | 급등장 | 급락장 | 변동폭큰",
  "confidence":   0.0,
  "elapsed_days": 0,
  "forecast": {
    "duration_days": { "min": 0, "max": 0 },
    "end_date":      "YYYY-MM-DD",
    "next_phase":    "예측 다음 국면"
  },
  "strategy_timeline": {
    "D0_D3": { "cash_pct": 0, "strategy": "전략명" }
  }
}
```

#### ISSUE
```json
{
  "issue_id":           "이슈 ID",
  "category":          "통화금리 | 지정학 | 경제지표 | 산업섹터 | 시장구조 | 블랙스완",
  "severity":          "LOW | MEDIUM | HIGH | CRITICAL",
  "confidence":        0.0,
  "duration_forecast": { "min": 0, "max": 0 },
  "affected_sectors":  [],
  "strategy_override": false
}
```

#### SIGNAL
```json
{
  "signal_id":    "신호 ID",
  "direction":    "BUY | SELL | HOLD",
  "confidence":   0.0,
  "phase":        "시장 국면",
  "issue_factor": null,
  "targets": [
    { "code": "종목코드", "name": "종목명", "weight": 0.0 }
  ],
  "weight_config": {
    "strategy_a": 0.0,
    "cash_pct":   0.0
  },
  "reason": "신호 생성 근거"
}
```

#### ORDER
```json
{
  "order_id":    "주문 ID",
  "signal_id":   "신호 ID",
  "action":      "BUY | SELL",
  "code":        "종목코드",
  "name":        "종목명",
  "quantity":    0,
  "price_type":  "MARKET | LIMIT",
  "strategy_id": "전략 ID",
  "stop_loss":   0.0,
  "take_profit": 0.0,
  "mode":        "MOCK | REAL"
}
```

#### ERROR
```json
{
  "error_id":   "오류 ID",
  "level":      "LOW | MEDIUM | HIGH | CRITICAL",
  "from_agent": "발생 에이전트",
  "error_code": "오류 코드",
  "message":    "오류 메시지",
  "retry_count": 0,
  "auto_fix":   false,
  "action":     "조치 내용"
}
```

### 통신 방식

| 구간 | 방식 | 설명 |
|------|------|------|
| 데이터수집 → 전처리 | 단방향 | 응답 불필요 |
| 전처리 → 시장분석 | 단방향 | |
| 전처리 → 이슈관리 | 단방향 | |
| 시장분석 → 가중치조정 | 단방향 | |
| 이슈관리 → 가중치조정 | 단방향 | |
| 가중치조정 → 전략연구 | 양방향 | 전략 요청/응답 |
| 가중치조정 → 로직적용 | 단방향 | |
| 로직적용 → 실행 | 단방향 | |
| 모든 에이전트 → 디버깅 | 단방향 | 감시용 |
| 모든 에이전트 → 오케스트레이터 | 단방향 | 보고용 |

### 타임아웃 규약

| 에이전트 | 타임아웃 | 재시도 |
|---------|---------|-------|
| 데이터수집 | 30초 | 3회 |
| 전처리 | 1초 | 3회 |
| 시장분석 | 5초 | 3회 |
| 이슈관리 | 3초 | 3회 |
| 가중치조정 | 2초 | 3회 |
| 전략연구 | 60초 | 2회 |
| 로직적용 | 2초 | 3회 |
| 실행 | 5초 | 3회 |
| 디버깅 | 즉시 | - |

### HEARTBEAT 규약
- 모든 에이전트 30초마다 HEARTBEAT 전송
- 30초 무응답 → 디버깅: 경고
- 60초 무응답 → 디버깅: HIGH 오류
- 90초 무응답 → 오케스트레이터: 강제 재시작

### 오류 처리 4단계
1. 발생 에이전트: ERROR 메시지 생성 → 디버깅에 전송 → 자체 재시도 (최대 3회)
2. 디버깅 에이전트: 등급 판단 → CRITICAL 시 전체 매매 중단
3. 시스템관리 에이전트: 원인 분석 → 자동 수정 시도
4. 오케스트레이터: 최종 판단 → 재시작 또는 텔레그램 알림

### 버전 관리 원칙
- 필드 추가: 1.0 → 1.1 (하위 호환)
- 구조 변경: 1.0 → 2.0 (호환 불가)
- 버전 불일치 시 ERROR 반환

---

## 시장 국면 분류 (6단계)

KOSPI 20일 누적 수익률 + VIX + 10일 실현 변동성 기반 자동 분류.
`data/history/phase_classifier.py` → `phase_classified.csv` 생성.

| 국면 | KOSPI 20일 수익률 | VIX | 특징 |
|------|----------------|-----|------|
| 대상승장 | +10% 이상 | - | 강한 상승 추세, 풀 공격 |
| 상승장   | +3% ~ +10% | - | 상승 추세, 80% 공격 |
| 일반장   | -3% ~ +3% | 20 이하 | 낮은 변동성, 60% 공격 |
| 변동폭큰 | -3% ~ +3% | 20~35 | 방향 불명확, 매매 보류 |
| 하락장   | -3% ~ -10% | - | 하락 추세, 방어 전환 |
| 대폭락장 | -10% 이하 or VIX≥35 | 35+ | 패닉 구간, 현금 유지 |

### 국면별 기본 가중치

| 국면 | 공격전략 | 방어전략 | 현금 |
|------|---------|---------|------|
| 대상승장 | 100% | 0% | 0% |
| 상승장   | 80% | 0% | 20% |
| 일반장   | 60% | 0% | 40% |
| 변동폭큰 | 20% | 20% | 60% |
| 하락장   | 0% | 40% | 60% |
| 대폭락장 | 0% | 20% | 80% |

### 추세 전환 신호 (3개 이상 동시 충족 시 전환)
- 하락→상승: RSI 30 이하 반등 / 거래량 급감 / VIX 고점 하락 / 외국인 순매도 감소
- 상승→하락: RSI 70 이상 / 거래량 감소하며 상승 / 외국인 순매수 감소 / VIX 상승

---

## 투자 기간 (Holding Period)

전략 카드의 `holding_period` 필드로 관리. 기간별 청산 기준이 다르다.
설정 파일: `config/horizon_config.json`

| 기간 | 보유 기간 | 익절 | 손절 | 트레일링 스탑 | 강제 청산 조건 |
|------|---------|------|------|------------|-------------|
| 초단기 | 1~3시간 | +0.8% | -0.5% | 없음 | 15:20 장 마감 전 전량 청산 |
| 단기 | 1~3일 | +2.5% | -1.5% | 없음 | 하락장/대폭락장 국면 전환 시 |
| 중기 | 1~4주 | +8.0% | -3.0% | +3% 이상 수익 시 -2% 하락 청산 | 변동폭큰 이하 국면 전환 시 |
| 장기 | 1~3개월 | +20.0% | -7.0% | +8% 이상 수익 시 -5% 하락 청산 | 하락장/대폭락장 전환 시 |

### 국면별 기본 투자 기간
| 국면 | 기본 기간 | 이유 |
|------|---------|------|
| 대상승장 | 중기 | 추세 지속 기간 길고 변동성 낮음 |
| 상승장 | 단기 | 방향성은 있으나 지속 불확실 |
| 일반장 | 단기 | 전일 미국 신호 추종, 1~3일 유효 |
| 변동폭큰 | 초단기 | 방향 불명확, 오버나이트 리스크 높음 |
| 하락장 | 초단기 | 반등 포착만, 장중 청산 필수 |
| 대폭락장 | 초단기 | 현금 기본, 반등 포착 시에만 |

### 청산 우선순위
1. 손절 (SL) — 즉시
2. 초단기 시간 청산 (15:20) — 당일 강제
3. 트레일링 스탑 (중기/장기) — 고점 대비 하락
4. 최대 보유일 초과
5. 국면 전환 (PHASE_CHANGE)
6. 신호 역전 (SIGNAL_EXIT, 초단기/단기만)

---

## 전략 라이브러리

### 폴더 구조
```
data/strategy_library/
├── 대상승구간/   (STR_B1 - SOX +1% 이상)
├── 상승구간/     (STR_B2 - NASDAQ +1.5% 이상)
├── 일반구간/     (STR_B3 - NASDAQ +1.5% 이상)
├── 변동큰구간/   (STR_B4 - SOX +3% 이상)
├── 하락구간/     (STR_B5 - NVDA +5% 이상)
└── 대폭락구간/   (STR_B6 - 현금 전략)
```

### 전략 카드 JSON 구조
```json
{
  "id":          "전략 고유 ID",
  "group":       "미국지수 | 환율매크로 | 섹터연계 | 시장국면 | 타이밍",
  "phase":       "적용 국면",
  "description": "전략 설명",
  "conditions": {
    "진입": "진입 조건",
    "청산": "청산 조건",
    "제외": "제외 조건"
  },
  "performance": {
    "backtest_win_rate":   0.0,
    "backtest_return_pct": 0.0,
    "real_win_rate":       0.0,
    "real_return_pct":     0.0,
    "mdd":                 0.0,
    "status":              "백테스팅중 | 검증완료 | 실전검증완료 | 비활성"
  },
  "compatible":   ["호환 전략 ID 목록"],
  "incompatible": ["비호환 전략 ID 목록"],
  "created_at":   "생성일",
  "updated_at":   "수정일"
}
```

### 전략 채택 기준 (과최적화 방지)
- 3개 이상 다른 기간에서 승률 55% 이상
- 상승장/하락장/횡보장 모두 테스트 통과
- 조건 개수 5개 이하 (단순성 유지)
- MDD -10% 이내
- Validation 데이터 성과 급락 시 자동 폐기

---

## 이슈 라이브러리

### 카테고리
```
data/issue_library/
├── 통화금리/     (Fed금리, 환율급변 등)
├── 지정학/       (전쟁, 무역분쟁 등)
├── 경제지표/     (CPI쇼크, 고용급감 등)
├── 산업섹터/     (반도체공급과잉, AI테마 등)
├── 시장구조/     (서킷브레이커, 공매도 등)
└── 블랙스완/     (팬데믹, 금융기관파산 등)
```

### 이슈 카드 JSON 구조
```json
{
  "issue_id":   "이슈 고유 ID",
  "category":   "카테고리",
  "name":       "이슈명",
  "발생패턴": {
    "선행신호": [],
    "확인신호": []
  },
  "시장영향": {
    "즉각반응":   "당일 예상 등락",
    "지속기간":   { "평균": 0, "최소": 0, "최대": 0 },
    "하락폭":     { "평균": 0.0, "최대": 0.0 },
    "반등패턴":   "패턴 설명",
    "섹터영향":   { "가장큰피해": [], "상대강세": [] }
  },
  "한국특이점": {
    "외국인반응": "설명",
    "환율영향":   "설명",
    "회복속도":   "설명"
  },
  "역대사례": [
    { "날짜": "", "내용": "", "코스피하락": 0.0, "지속일": 0, "회복일": 0 }
  ],
  "전략대응": {
    "D0":     "즉시 대응",
    "D1_D3":  "초반 대응",
    "D5_이후": "후반 대응"
  },
  "confidence":   0.0,
  "data_count":   0,
  "updated_at":   "최근수정일"
}
```

---

## 미국→한국 선행 지표 매핑

| 미국 지표 | 한국 반응 섹터 |
|---------|-------------|
| 나스닥100 급등 | 코스닥 추종 |
| SOX 급등 | 삼성전자, SK하이닉스, 한미반도체 |
| 테슬라/리비안 강세 | LG엔솔, 삼성SDI (2차전지) |
| 엔비디아/AMD 급등 | SK하이닉스 (HBM) |
| WTI 급등 | SK이노, S-Oil (정유) |
| 구리 강세 | 경기회복 신호 → 코스피 전반 |
| 금 강세 | 안전자산 선호 → 위험자산 하락 |
| VIX 30 돌파 | 외국인 대량 매도 예고 |
| 달러 강세 | 외국인 순매도 → 코스피 하락 |
| 리튬/코발트 급등 | LG엔솔 원가 상승 압박 |

---

## 데이터베이스 (Supabase)

### 테이블 구조

```sql
-- 전략 라이브러리
strategies (
  id, name, group_name, phase,
  win_rate, return_pct, mdd,
  conditions jsonb, status,
  created_at, updated_at
)

-- 이슈 라이브러리
issues (
  id, category, name, severity,
  duration_avg, affected_sectors jsonb,
  historical_cases jsonb, confidence,
  updated_at
)

-- 포지션 (보유 종목)
positions (
  id, code, name, quantity, avg_price,
  buy_order_id, buy_trade_id,
  phase_at_buy, strategy_id, mode,
  holding_period,    -- 초단기 | 단기 | 중기 | 장기
  entry_time,        -- 진입 시각 (ISO8601)
  max_exit_date,     -- 최대 보유 만기 (ISO8601)
  peak_price,        -- 트레일링 스탑 기준 고가
  status,            -- OPEN | CLOSED
  closed_at, close_reason, result_pct
)

-- 매매 기록
trades (
  id, order_id, code, name,
  action, quantity, price,
  strategy_id, phase, result_pct,
  mode, created_at
)

-- 시장 국면 이력
market_phases (
  id, phase, confidence,
  start_date, end_date,
  issue_id, forecast_accuracy
)

-- 에이전트 로그
agent_logs (
  id, agent, level,
  message, error_code, timestamp
)

-- 백테스팅 결과
backtest_results (
  id, strategy_id, phase,
  period_start, period_end,
  win_rate, return_pct, mdd,
  created_at
)
```

---

## Claude API 사용 기준

### Sonnet 사용 (기본 - 80~85%)
- 데이터 수집/전처리 코드
- API 연결 코드
- 주문 실행 코드
- 단위 테스트 코드
- 단순 버그 수정
- 설정 파일 작성

### Opus 사용 (핵심만 - 15~20%)
- 전체 아키텍처 검토
- 구간 분류 알고리즘 설계
- 과최적화 방지 로직 설계
- 가중치 계산 공식
- 교착상태 디버깅
- 전략 성과 분석 및 개선

---

## 폴더 구조

```
stock-agent/
├── CLAUDE.md                    ← 이 파일 (항상 읽기)
├── main.py                      ← 전체 시스템 시작점
├── orchestrator.py              ← 오케스트레이터
│
├── config/
│   ├── settings.py              ← API 키, 환경 설정
│   └── strategy_config.json     ← 국면별 전략/가중치 설정
│
├── protocol/
│   └── protocol.py              ← 표준 메시지 클래스 (모든 에이전트 import)
│
├── agents/
│   ├── base_agent.py            ← 공통 베이스 클래스
│   ├── data_collector.py        ← 데이터수집
│   ├── preprocessor.py          ← 전처리
│   ├── market_analyzer.py       ← 시장분석
│   ├── issue_manager.py         ← 이슈관리
│   ├── weight_adjuster.py       ← 가중치조정
│   ├── strategy_researcher.py   ← 전략연구
│   ├── logic_applier.py         ← 로직적용
│   ├── executor.py              ← 실행
│   ├── system_manager.py        ← 시스템관리
│   └── debugger.py              ← 디버깅 (독립)
│
├── data/
│   ├── strategy_library/
│   │   ├── 안정화구간/
│   │   ├── 급등구간/
│   │   ├── 급락구간/
│   │   └── 변동큰구간/
│   └── issue_library/
│       ├── 통화금리/
│       ├── 지정학/
│       ├── 경제지표/
│       ├── 산업섹터/
│       ├── 시장구조/
│       └── 블랙스완/
│
├── tests/                       ← 에이전트별 단위 테스트
└── logs/                        ← 운영 로그 저장
```

---

## MVP 1단계 목표 (첫 4주)

모의투자 자동매매가 실제로 돌아가는 것 확인

### 포함 에이전트 (5개)
1. 데이터수집 (미국 + 한국)
2. 전처리
3. 시장분석 (국면감지 단순화)
4. 가중치조정 (기본 3단계: 상승/횡보/하락)
5. 실행 (모의투자 주문 + 텔레그램 알림)

### 주차별 목표
- 1주차: 환경세팅 + API 연결 확인
- 2주차: 데이터수집 + 전처리 완성 및 테스트
- 3주차: 시장분석 + 가중치조정 완성
- 4주차: 실행 연결 → 첫 모의 자동주문 🎉

---

## 개발 원칙 요약

1. **에이전트 순서**: base_agent.py → 데이터수집 → 전처리 → 분석 → 실행 → 오케스트레이터
2. **테스트 필수**: 에이전트 하나 완성 → 단독 테스트 통과 → 다음 연결
3. **표준폼 필수**: 모든 데이터는 protocol.py의 표준폼으로만 통신
4. **전략 분리**: 비즈니스 로직은 strategy_config.json, 코드는 건드리지 않음
5. **모의 먼저**: 실전 투자 전 최소 4주 모의투자 검증
6. **소액 시작**: 모의 안정화 후 실전은 소액부터

---

## 운영 비용 구조

| 항목 | 개발 기간 | 실전 운영 후 |
|------|---------|------------|
| Claude Max | $100 | $100 |
| Claude API | $3~5 | $5 |
| Supabase | 무료 | $25 |
| 서버 | 내 PC | $15 |
| KIS API | 무료 | 무료 |
| yfinance | 무료 | 무료 |
| **합계** | **~$105** | **~$145** |

---

*이 파일은 Claude Code가 프로젝트 시작 시 자동으로 읽습니다.*
*설계 변경 시 이 파일을 먼저 업데이트하세요.*
