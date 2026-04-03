# 프로젝트 재무 데이터 활용 감사 보고서

> **분석일:** 2026-04-02
> **대상:** stock-agent 프로젝트 전체 (agents/, config/, data/, database/, scripts/, frontend/)

---

## 섹션 1: 현재 사용 중인 재무/기술 지표

### 매매 판단에 실제 사용되는 지표

| 지표 | 파일 | 메서드 | 용도 |
|------|------|--------|------|
| RSI(14) | `market_analyzer.py:818` | `_calc_rsi()` | 과매도/과매수 판단, 추세 필터 점수 |
| MA(20/50/200) | `market_analyzer.py:1020-1023` | `check_trend_filter()` | 이동평균 정배열/역배열 판단 |
| ADX(14) | `market_analyzer.py:848` | `_calc_adx()` | 추세 강도 측정 |
| MACD(12,26,9) | `market_analyzer.py:910` | `_calc_macd()` | 모멘텀 방향 + 골든크로스 |
| 거래량 비율 | `market_analyzer.py:642` | `scan_relative_strength()` | 20일 평균 대비 비율 |
| VIX | `market_analyzer.py:310` | `detect_phase()` | 시장 국면 분류 (20/35 임계값) |
| KOSPI 20일 수익률 | `market_analyzer.py:353` | `_classify_6phase()` | 6국면 분류 핵심 지표 |
| 10일 실현 변동성 | `market_analyzer.py:353` | `_classify_6phase()` | 변동폭큰 국면 판단 |
| 5일/20일 상대강도(RS) | `market_analyzer.py:642` | `scan_relative_strength()` | 시장 대비 종목 강도 |
| 외국인 순매수 | `data_collector.py:406` | KIS API `FHKST01010900` | 수급 부스트 (1.2x/0.7x) |

### 가격 예측에 사용되는 요소

| 요소 | 파일 | 가중치(1주/1개월) | 설명 |
|------|------|-------------------|------|
| 모멘텀 | `market_analyzer.py:919-921` | 60% / 25% | 5일 추세 선형 외삽 (감쇠 적용) |
| 평균회귀 | `market_analyzer.py:924-926` | 15% / 45% | 60일 평균 z-score 기반 |
| 미국연동 | `market_analyzer.py:929-941` | 25% / 30% | 상관 US 지표 × lead-lag 상관계수 |
| VIX 할인 | `market_analyzer.py:875` | 전체 적용 | VIX 25 초과 시 -0.5%/pt |
| RSI 백분위 상승여력 | `market_analyzer.py:972-1017` | 보정용 | 유사 RSI 기간 forward return 분석 |

### 분류 태그 (직접 매매 판단은 아님)

| 태그 | 파일 | 사용 위치 |
|------|------|-----------|
| `대형우량주` | `stock_classification.json:171` | `scan_oversold_candidates()`에서 +1점 가산 |
| `고배당주` | `stock_classification.json:172` | 정의만 존재, **매매 로직에서 미사용** |
| `중소형성장주` | `stock_classification.json:173` | 정의만 존재, **매매 로직에서 미사용** |

> **핵심 발견:** 시스템은 100% 기술적/모멘텀 기반. PER, PBR, EPS, ROE 등 **펀더멘탈 지표는 단 하나도 사용하지 않는다.** 유일한 "재무적" 요소는 `대형우량주` 태그가 낙폭과대 스캔에서 +1점을 주는 것뿐이다.

---

## 섹션 2: KIS API 재무 데이터

### 현재 사용 중인 KIS API 엔드포인트

| TR ID | 이름 | 파일 | 용도 |
|-------|------|------|------|
| `FHKST01010100` | 주식현재가 시세 | `position_manager.py:421` | 실시간 종목 가격 조회 |
| `FHKST01010900` | 주식현재가 투자자 | `data_collector.py:406` | 외국인 순매수 데이터 |
| `VTTC0802U` | 모의투자 매수 | `executor.py:258` | 매수 주문 실행 |
| `VTTC0801U` | 모의투자 매도 | `executor.py:264` | 매도 주문 실행 |
| `VTTC8434R` | 모의투자 잔고조회 | `executor.py:1382` | 계좌 잔고/보유종목 |
| `VTTC8036R` | 모의 미체결조회 | `tests/test_order_flow.py:110` | 미체결 주문 확인 (테스트) |
| `VTTC0803U` | 모의 취소/정정 | `tests/test_order_flow.py:159` | 주문 취소 (테스트) |

### KIS API에서 제공하지만 코드에 없는 재무 API

| TR ID | API 이름 | 제공 데이터 | 코드 존재 여부 |
|-------|---------|------------|---------------|
| `FHKST01010400` | 주식현재가 일자별 | 일별 시세 (OHLCV) | **없음** (pykrx/yfinance로 대체) |
| `FHKST66430300` | 주식현재가 투자지표 | **PER, PBR, EPS, BPS, 배당수익률** | **없음** |
| `FHKST01010800` | 주식현재가 시세2 | 시가총액, 상장주수 | **없음** |
| `CTPF1002R` | 재무비율 | **ROE, ROA, 부채비율, 영업이익률** | **없음** |
| `FHKST01010700` | 주식현재가 호가 | 매수/매도 호가 10단계 | **없음** |
| `FHKST03010100` | 업종 현재가 | 업종별 등락률 | **없음** |

```
현재 KIS API 활용도:
  ┌─────────────────────────────────────────┐
  │  사용 중     │  미사용 (재무)            │
  │  ■■■■□□□□   │  □□□□□□□□□□□□            │
  │  시세/주문   │  PER PBR EPS ROE 배당     │
  │  잔고/외인   │  시총 호가 업종 재무비율   │
  └─────────────────────────────────────────┘
  활용률: ~30% (7개 / 20+개 API)
```

> **핵심 발견:** KIS API는 `FHKST66430300`(투자지표)과 `CTPF1002R`(재무비율)로 **PER, PBR, EPS, ROE, 배당수익률을 무료로 제공**하는데, 코드에 전혀 없다. 추가 비용 없이 즉시 활용 가능한 데이터가 방치되어 있다.

---

## 섹션 3: DB 테이블

### 현재 Supabase 테이블 목록

| 테이블 | 파일 | 재무 데이터 여부 | 용도 |
|--------|------|-----------------|------|
| `positions` | `db.py:242` | 없음 | 보유 포지션 (가격/수량만) |
| `trades` | `db.py:98` | 없음 | 매매 기록 |
| `market_phases` | `db.py:158` | 없음 | 국면 이력 |
| `market_snapshots` | `db.py:621` | 없음 | 시장 스냅샷 |
| `strategies` | `db.py:520` | 없음 | 전략 카드 |
| `account_summary` | `db.py:667` | 없음 | 계좌 요약 |
| `account_history` | `db.py:1181` | 없음 | 계좌 일별 이력 |
| `backtest_results` | `db.py:584` | 없음 | 백테스트 결과 |
| `position_analyses` | `db.py:744` | 없음 | 포지션 기술 분석 |
| `pending_dca` | `db.py:1008` | 없음 | DCA 대기 주문 |
| `exit_plans` | `db.py:1095` | 없음 | 매도 계획 |
| `agent_logs` | `db.py:201` | 없음 | 에이전트 로그 |

### 재무 데이터 전용 테이블

**없음** — 12개 테이블 모두 시세/거래/운영 데이터만 저장.

```
재무 데이터 관련 테이블: 0개 / 12개
재무제표, 투자지표, 실적 데이터를 저장하는 테이블이 전혀 없다.
```

> **핵심 발견:** DB에 재무 데이터 테이블이 전무하다. KIS API로 PER/PBR/EPS를 수집해도 저장할 곳이 없는 상태.

---

## 섹션 4: DART API

### 검색 결과

| 검색 대상 | 결과 |
|-----------|------|
| `dart-fss` 패키지 | **없음** |
| `opendart` 패키지 | **없음** |
| DART API 키 설정 | **없음** (`config/settings.py`에 없음) |
| `전자공시`, `공시`, `DART` 문자열 | **없음** (node_modules 내 TypeScript 진단 메시지 1건만 검출) |
| 재무제표 파싱 코드 | **없음** |
| 사업보고서/분기보고서 관련 | **없음** |

```python
# config/settings.py 현재 상태:
KIS_APP_KEY     = os.getenv("KIS_APP_KEY")
KIS_APP_SECRET  = os.getenv("KIS_APP_SECRET")
KIS_ACCOUNT_NO  = os.getenv("KIS_ACCOUNT_NO")
TELEGRAM_TOKEN  = os.getenv("TELEGRAM_TOKEN")
# DART_API_KEY  → 없음
```

> **핵심 발견:** DART 관련 코드가 프로젝트에 단 1줄도 없다. 한국 상장사 재무제표의 가장 권위있는 소스(DART 전자공시)가 완전히 미연동 상태.

---

## 섹션 5: 미활용 데이터/기능

### A. 수집하지만 매매 판단에 미반영

| 기능/데이터 | 파일 위치 | 현재 상태 | 미활용 이유 (추정) |
|---|---|---|---|
| **리튬 ETF (LIT)** | `data_collector.py:581` | 매일 수집됨 | `LEADING_INDICATOR_MAP`에 리튬 신호 없음. 수집만 하고 분석 안 함 |
| **기관 순매수** (`institution_net`) | `data_collector.py:276,733` | 항상 `0`으로 하드코딩 | KIS API 호출 구현 미완성. 외국인은 있지만 기관은 빠짐 |
| **`고배당주` 태그** | `stock_classification.json:172` | 정의만 존재 | 분류용으로만 쓰이고 WA의 매매 로직에서 참조 안 함 |
| **`중소형성장주` 태그** | `stock_classification.json:173` | 정의만 존재 | 동일 — 분류 메타데이터이나 실제 가중치에 미반영 |

### B. 생성하지만 라이브 코드에서 안 읽는 파일

| 파일 | 위치 | 생성 주체 | 미활용 이유 |
|---|---|---|---|
| `conditional_win_rates.csv` | `data/history/analysis/` | `pattern_analyzer.py` | 분석 리서치용 — 에이전트에서 import 없음 |
| `ic_by_phase.csv` | `data/history/analysis/` | `pattern_analyzer.py` | 국면별 Information Coefficient — 참조 코드 없음 |
| `phase_basic_stats.csv` | `data/history/analysis/` | `pattern_analyzer.py` | 국면 기본 통계 — 참조 코드 없음 |
| `best_signals.json` | `data/history/analysis/` | `pattern_analyzer.py` | 최적 시그널 목록 — 참조 코드 없음 |
| `full_period_correlation.csv` | `data/history/correlation/` | `fetch_history.py` | 상관관계 — `LEADING_INDICATOR_MAP`에 하드코딩 대체 |
| `lead_lag_analysis.csv` | `data/history/correlation/` | `fetch_history.py` | lead-lag — 동일, 하드코딩 대체 |
| `yearly_correlation_summary.csv` | `data/history/correlation/` | `fetch_history.py` | 연간 상관 요약 — 참조 코드 없음 |
| `full_backtest_results.csv` | `data/history/extended/backtest_results/` | `backtest_extended.py` | 결과가 `strategy_config.json`에 이미 하드코딩됨 |
| `best_strategy_per_stock.csv` | `data/history/extended/backtest_results/` | `backtest_extended.py` | 동일 |

### C. 확장 데이터 (206개 CSV) — 백테스트 전용, 라이브 미사용

| 디렉토리 | 파일 수 | 라이브 사용 | 비고 |
|-----------|---------|------------|------|
| `extended/kospi100/` | 97 | **0** | 백테스트 전용 |
| `extended/kr_stocks/` | 18 | **0** | 백테스트 전용 |
| `extended/us_stocks/` | 17 | **0** | 백테스트 전용 |
| `extended/sector_etf/` | 14 | **0** | 백테스트 전용 |
| `extended/commodities/` | 11 | **0** | 백테스트 전용 |
| `extended/global_index/` | 10 | **0** | 백테스트 전용 |
| `extended/bonds/` | 8 | **0** | 백테스트 전용 |
| `extended/us_index/` | 7 | **0** | 백테스트 전용 |
| `extended/forex/` | 6 | **0** | 백테스트 전용 |
| `extended/credit_risk/` | 4 | **0** | 백테스트 전용 |
| `extended/futures/` | 4 | **0** | 백테스트 전용 |
| `extended/analysis/` | 4 | **0** | 분석 결과물 |
| `extended/backtest_results/` | 3 | **0** | config에 하드코딩 |
| `extended/kr_index/` | 3 | **0** | 백테스트 전용 |
| **합계** | **206** | **0** | 전부 백테스트/리서치 전용 |

### D. 즉시 활용 가능한데 안 쓰고 있는 것 (가격 예측 정확도 향상 가능)

| 미활용 자원 | 즉시 활용 방법 | 기대 효과 |
|---|---|---|
| **KIS `FHKST66430300` (투자지표)** | PER/PBR로 고평가 종목 진입 차단, 저평가 종목 부스트 | Filter 3 진입 금지에 "PER > 업종평균×2" 추가 가능. **추가 비용 0원** |
| **KIS `CTPF1002R` (재무비율)** | ROE/부채비율로 재무 건전성 필터 | 부실 기업 제외. 낙폭과대 스캔에서 "ROE > 5%" 조건 추가 가능 |
| **기관 순매수 (`institution_net`)** | 외국인+기관 동시 순매수 = 강한 수급 신호 | `_apply_foreign_net_boost()`에 기관 데이터 병합. 현재 외국인만 보는 편향 해소 |
| **`conditional_win_rates.csv`** | 국면×지표별 실제 승률을 동적 임계값으로 활용 | `_get_trend_threshold()`를 하드코딩 대신 실증 데이터 기반으로 교체 |
| **`lead_lag_analysis.csv`** | 동적 lead-lag 상관계수로 `_forecast_single()` 정확도 향상 | 현재 `get_lead_lag_corr()` fallback 0.3 대신 실측값 사용 |

> **핵심 발견:** **가격 예측 정확도를 당장 높일 수 있는 가장 큰 기회는 KIS 투자지표 API (`FHKST66430300`)이다.** 추가 비용 없이 PER/PBR/EPS/배당수익률을 가져올 수 있고, 이를 Filter 3 진입 금지 조건("PER > 업종평균 2배 → BLOCKED")이나 가격 예측 보정("저PBR 종목은 평균회귀 목표 상향")에 즉시 적용할 수 있다. 두 번째로는 기관 순매수 데이터 — 현재 항상 0으로 하드코딩되어 있어 외국인만 편향적으로 반영하는 문제가 있다.

---

## 전체 요약 매트릭스

```
                     기술적 지표    재무 지표    수급 데이터    외부 공시
사용 중           ████████████   ░░░░░░░░░░   ████░░░░░░   ░░░░░░░░░░
코드 존재         ████████████   ░░░░░░░░░░   ████░░░░░░   ░░░░░░░░░░
API 제공          ████████████   ████████████   ████████░░   ████████████
                  ───────────   ───────────   ──────────   ───────────
활용률              ~90%           0%           ~50%          0%
```

| 카테고리 | 활용률 | 핵심 Gap |
|---|---|---|
| 기술적 지표 (RSI, MA, MACD, ADX) | **90%** | 거의 완전 활용 |
| 재무 지표 (PER, PBR, EPS, ROE) | **0%** | KIS API로 무료 수집 가능하나 전혀 미사용 |
| 수급 데이터 (외국인/기관) | **50%** | 외국인만 사용, 기관은 0으로 하드코딩 |
| 외부 공시 (DART 재무제표) | **0%** | 코드/API키 전무 |
| 히스토리 분석 결과 | **~10%** | 206개 CSV + 7개 분석 파일 → 라이브 코드에서 0개 참조 |
