# 다중 필터 매매 시스템 — 명세서 vs 현재 코드 비교 분석

> **분석일:** 2026-04-02
> **명세서:** `trading_filter_spec.md`
> **대상 코드:** agents/, orchestrator.py, config/, database/

---

## 1. 이미 구현된 부분

명세서의 내용과 일치하거나 유사하게 이미 코드에 있는 것.

| # | 명세서 항목 | 현재 코드 위치 | 구현 상태 |
|---|---|---|---|
| 1 | 시장 국면 분류 | `market_analyzer.py:353` `_classify_6phase()` | 4국면→6국면으로 더 세분화하여 구현 |
| 2 | 국면별 포트폴리오 비중 | `strategy_config.json` phase_weights + `weight_adjuster.py:21-28` | 공격/방어/현금 비율 완전 일치 |
| 3 | 트레일링 스탑 | `horizon_manager.py:113-195` `check_exit()` | 4개 투자기간별 구현 완료 |
| 4 | 국면 전환 시 청산 | `horizon_manager.py:182-195` | exit_on_phase_change 리스트로 구현 |
| 5 | 시간 기반 청산 | `horizon_manager.py:170-181` | 초단기 15:20 강제청산 + 최대보유일 체크 |
| 6 | 손절/익절 기준 | `horizon_config.json` | 투자기간별 SL/TP 설정 완료 |
| 7 | 국면별 최대 포지션 수 | `risk_config.json` max_positions_per_phase | 대상승장5 → 대폭락장1 |
| 8 | 선행지표 분석 (US→KR) | `market_analyzer.py:396` `analyze_leading_indicators()` | 13개 지표 매핑 |
| 9 | RSI 분석 | `market_analyzer.py:818` `_calc_rsi()` + `scan_oversold_candidates()` | 과매도 스캔 구현 |
| 10 | 분할 익절 | `executor.py:624` `_try_partial_take_profit()` | 단계별 매도 구현 |
| 11 | 단일종목 비중 제한 | `executor.py:62` `_max_stock_weight_pct=0.15` | 15% 상한 |
| 12 | 파이프라인 흐름 | `orchestrator.py:48` `run_once()` 5단계 | DC→MA→WA→SR→EX |
| 13 | 국면 판정 로깅 | `orchestrator.py` → market_phases 테이블 | DB 저장 구현 |
| 14 | 장중 모니터링 | `orchestrator.py:383` `_stop_take_loop()` | 1~3분 간격 체크 |
| 15 | 세션 시간 관리 | `orchestrator.py:354` `_get_session_mode()` | 6개 시간대별 모드 |

---

## 2. 다르게 구현된 부분

비슷한 기능이 있지만 로직이나 구조가 다른 것.

### 2-1. 시장 국면 분류 방식

| 비교 항목 | 명세서 | 현재 코드 |
|---|---|---|
| **국면 수** | 4개 (STABLE_UPTREND, SURGE, HIGH_VOL, CRASH) | 6개 (대상승/상승/일반/변동폭큰/하락/대폭락) |
| **분류 기준** | MA(50/200) + RSI + VIX + SP500 등락률 | KOSPI 20일 수익률 + VIX + 10일 변동성 |
| **판정 방식** | 점수제 (5개중 4개, 3개중 2개 등) | 임계값 비교 (ret20 ≥ 10% → 대상승장) |
| **출력** | `trading_rules` 객체 (trading_allowed, signal_strength 등) | phase 문자열만 출력, 규칙은 별도 config |
| **코드 위치** | 명세서 `determine_market_regime()` | `market_analyzer.py:353` `_classify_6phase()` |

**명세서 장점:** MA 기반 분류가 추세를 더 정확히 반영. 점수제가 노이즈에 강건함.
**코드 장점:** 6단계가 더 세밀한 대응 가능 (일반장/상승장 구분).

### 2-2. 포지션 크기 결정 방식

| 비교 항목 | 명세서 | 현재 코드 |
|---|---|---|
| **방식** | 곱셈식 (base 10% × regime × trend × signal × diversification) | 가중치 할당 (phase → 공격/방어/현금 비율) |
| **종목별 조정** | trend_score, signal_strength 반영 | 테마 부스트(1.3×), 섹터감쇠, RS필터 |
| **최소/최대** | 3% ~ 20% | 단일종목 max 15% |
| **총 노출도** | 명시적 risk budget (80%/50%/40%/10%) | phase_weights의 cash 비율로 간접 관리 |
| **코드 위치** | 명세서 `calculate_position_size()` | `weight_adjuster.py:360` `_decide_weight_config()` |

### 2-3. 이탈 규칙 (Exit Rules)

| 비교 항목 | 명세서 | 현재 코드 |
|---|---|---|
| **구조** | 5가지 이탈 조건 (SL, TP, 추세반전, 국면, 시간) | 4가지 추세유형 (PROFIT_UP/FLAT/RECOVERING/LOSS_ZONE) |
| **TP 단계** | +10% → 30% 매도, +15% → 50% 매도 | 예측 기반 3단계 분할 (exit_plan stages) |
| **SL 조정** | 국면별 배수 (1.0× / 0.7× / 1.5× / 0.5×) | 추세유형별 배수 (0.6× ~ 1.2×) |
| **트리거** | 가격 기반 고정 임계값 | 가격 예측(momentum+mean-reversion) 기반 동적 |
| **코드 위치** | 명세서 `check_exit_conditions()` | `executor.py:734` `_check_exit_plan()` + `horizon_manager.py` |

### 2-4. 파이프라인 에이전트 순서

| 명세서 | 현재 코드 |
|---|---|
| MA(필터1) → SR(필터2) → LA(필터3) → WA(필터4) → EX(필터5) | MA → WA → SR → EX |

**코드 위치:** `orchestrator.py:48` `run_once()` — LA(로직적용)는 SR에 통합됨.

### 2-5. 손절폭 국면 조정

| 비교 항목 | 명세서 | 현재 코드 |
|---|---|---|
| **조정 기준** | 국면(regime)별 고정 배수 | exit_plan의 forecast 추세유형별 배수 |
| **STABLE / PROFIT_UP** | 1.0× (표준) | confidence > 0.7이면 1.2× (여유 확대) |
| **SURGE / PROFIT_FLAT** | 0.7× (타이트) | 0.9× |
| **HIGH_VOL / RECOVERING** | 1.5× (여유) | 0.8× |
| **CRASH / LOSS_ZONE** | 0.5× (매우 타이트) | 0.6× |

---

## 3. 아직 없는 부분

명세서에는 있지만 코드에 전혀 없는 것. 우선순위별 정렬.

### 높은 우선순위

#### 3-1. 추세 확인 필터 (Filter 2)

명세서의 핵심 필터. 종목별 기술적 지표를 종합 점수화하여 0.5 미만이면 매매 차단.

| 항목 | 현재 상태 | 필요한 것 |
|---|---|---|
| MA 정배열 체크 (20/50/200) | **없음** | 가격 > 20MA > 50MA 확인 (3점) |
| ADX 추세 강도 | **없음** | ADX ≥ 25 강한 추세 (2점) |
| MACD 히스토그램 | **없음** | 양수 = 상승 모멘텀 (1점) |
| RSI 위치 점수 | 과매도 스캔만 있음 | 40~65 건강 범위 체크 (2점) |
| 거래량 비율 점수 | RS에서 일부 사용 | ≥ 0.8 정상 거래량 (1점) |
| 종합 trend_score | **없음** | 0.0~1.0 정규화 → 0.5 미만 차단 |

```
추가 위치: market_analyzer.py에 check_trend_filter(symbol, prices) 메서드
사용 위치: weight_adjuster.py의 _decide_targets()에서 trend_score < 0.5 종목 제외
```

#### 3-2. 진입 타이밍 필터 (Filter 3)

"5개 신호 중 2개 이상" 충족해야 진입하는 복합 판단 로직.

| 진입 신호 | 현재 상태 | 설명 |
|---|---|---|
| RSI 반등 (30~45에서 상승) | **없음** | RSI 전일 대비 상승 확인 |
| MA 지지 확인 (20MA ±2%) | **없음** | 가격이 20MA에 닿고 반등 |
| 거래량 동반 양봉 | **없음** | 당일 상승 + 거래량 1.3배 이상 |
| MACD 골든크로스 | **없음** | MACD 히스토그램 음→양 전환 |
| US 관련 섹터 상승 | 선행지표에 일부 | 전일 밤 관련 US 섹터 +0.5% |

| 진입 금지 조건 | 현재 상태 | 설명 |
|---|---|---|
| RSI > 75 (극심한 과매수) | **없음** | 어떤 경우에도 진입 금지 |
| 당일 +5% 이상 급등 | **없음** | 추격 매수 방지 |
| 거래량 5배 이상 (이상 징후) | **없음** | 비정상적 거래 감지 |
| 실적 발표 3일 이내 | **없음** | 불확실성 회피 |

```
추가 위치: weight_adjuster.py에 _check_entry_timing(target, ma_payload) 메서드
         또는 별도 agents/entry_filter.py 모듈
```

#### 3-3. trading_allowed / new_entry_allowed 플래그

| 플래그 | 현재 상태 | 명세서 동작 |
|---|---|---|
| `trading_allowed` | **없음** (방향 BUY/HOLD/SELL로 간접 제어) | CRASH → false → 전체 매매 중단 |
| `new_entry_allowed` | **없음** | SURGE → false → 보유관리만, 신규매수 차단 |
| `required_signal_strength` | **없음** | HIGH_VOL → "strong" → 약한 신호 무시 |
| `system_mode` | **없음** | CRASH → "WATCH_ONLY" 관망 모드 |

```
추가 위치: market_analyzer.py의 detect_phase() 출력에 trading_rules 객체 추가
사용 위치: orchestrator.py에서 trading_allowed=false면 Step 3~4 스킵
```

### 중간 우선순위

#### 3-4. 국면 전환 히스테리시스

```
명세서: 국면 전환은 2일 연속 새 국면 조건을 충족해야 전환 (CRASH 제외 → 즉시)
현재:   매 사이클마다 즉시 전환 (market_analyzer.py:353)
문제:   whipsaw — 국면이 매일 바뀌면서 불필요한 매매 발생
```

```
추가 위치: market_analyzer.py의 _classify_6phase()에
          DB에서 직전 국면 조회 → 2일 연속 확인 로직 추가
          CRASH(대폭락장)만 즉시 전환 허용
예상 규모: +30줄
```

#### 3-5. 추세 반전 이탈 (Trend Reversal Exit)

```
명세서: 진입 시 trend_score vs 현재 trend_score → 60% 이상 하락 시 매도
현재:   exit_plan에 가격 예측 기반 매도만 있음. 추세 점수 비교 없음
```

```
추가 위치: executor.py의 _check_stop_take()에 추세 점수 비교 로직
필요 사항: positions 테이블에 trend_score_at_entry 컬럼 추가
          매수 시점의 trend_score 저장 → 매 체크 시 현재 score와 비교
예상 규모: DB migration +1, executor.py +30줄
```

#### 3-6. 총 노출도 체크 (Risk Budget)

| 국면 | 명세서 최대 총 투자비중 | 현재 코드 |
|---|---|---|
| STABLE_UPTREND | 80% | phase_weights로 간접 관리 (명시적 체크 없음) |
| SURGE | 50% | 상동 |
| HIGH_VOLATILITY | 40% | 상동 |
| CRASH | 10% | 상동 |

```
추가 위치: executor.py의 execute() BUY 직전에
          현재 총 투자비중(stock_evlu / total) 계산 → 한도 초과 시 거부
예상 규모: +25줄
```

### 낮은 우선순위

#### 3-7. filter_log 테이블

```
현재: 종목별 필터 통과/실패 기록이 없음
명세서: filter_1~4 통과 여부 + 최종 판단(BUY/SKIP/WATCH) 로깅

추가: database/migrations/ 새 마이그레이션
     database/db.py에 save_filter_log() 추가
     각 에이전트에서 필터 결과 기록
```

#### 3-8. trades 테이블 컬럼 확장

```
현재 없는 컬럼:
  - market_regime (매매 시점 국면)
  - trend_score (매매 시점 추세 점수)
  - entry_signals (진입 근거 JSONB)
  - exit_type (STOP_LOSS/TAKE_PROFIT/TREND_REVERSAL/REGIME_EXIT/TIME_EXIT)

추가: database/migrations/ 새 마이그레이션 (ALTER TABLE trades ADD COLUMN)
```

#### 3-9. 수동 국면 오버라이드

```
현재: 없음
명세서: 사용자가 수동으로 국면 강제 설정 가능

추가 위치: config/ 또는 DB에 manual_override 플래그
          market_analyzer.py에서 override 존재 시 자동 판정 스킵
          frontend settings 페이지에 오버라이드 UI 추가
```

#### 3-10. 장중 국면 재판단 트리거

```
명세서: VIX 25 돌파 등 급변 시 장중 재판단
현재:   _stop_take_loop()에서 가격 체크만. 국면 재판단 트리거 없음

추가 위치: orchestrator.py의 _stop_take_loop()에
          VIX 급등 감지 → detect_phase() 재호출 로직
```

---

## 4. 코드에만 있는 부분

명세서에는 없지만 현재 코드에 있는 것. 삭제 여부 판단 포함.

| # | 기능 | 파일 위치 | 판단 | 이유 |
|---|---|---|---|---|
| 1 | **DCA (분할 매수)** | `executor.py:489` `_check_pending_dca()` | **유지** | 진입 가격 최적화에 유용. 명세서에 없지만 실전에서 가치 있음 |
| 2 | **가격 예측 시스템** | `market_analyzer.py:861` `_generate_price_forecasts()` | **유지** | exit_plan의 핵심 기반. momentum + mean-reversion + US 연동 |
| 3 | **exit_plan 4유형** | `executor.py:860` `build_exit_plan()` | **유지** | 명세서 TP보다 진화된 구조 (PROFIT_UP/FLAT/RECOVERING/LOSS_ZONE) |
| 4 | **테마 모멘텀 분석** | `market_analyzer.py:494` `analyze_theme_momentum()` | **유지** | 섹터별 강도 분석으로 종목 선택 정확도 향상 |
| 5 | **투자기간 관리 (4단계)** | `horizon_manager.py` 전체 | **유지** | 초단기~장기 4단계 + 동적 전환은 명세서에 없지만 핵심 기능 |
| 6 | **동적 투자기간 전환** | `horizon_manager.py:228` `suggest_horizon_change()` | **유지** | 국면 변화에 따른 보유기간 자동 조정 |
| 7 | **전략 라이브러리** | `strategy_researcher.py` 전체 | **유지** | 전략 관리 인프라. 명세서의 전략 개념보다 체계적 |
| 8 | **백테스트 과최적화 방지** | `strategy_researcher.py:419` `_validate_anti_overfit()` | **유지** | 전략 검증 핵심. 3개 구간 독립 테스트 |
| 9 | **이슈 관리 시스템** | `agents/issue_manager.py` + issue_library/ | **유지** | 뉴스→이슈 분류→전략 조정. 리스크 관리 보강 |
| 10 | **외국인 순매수 부스트** | `weight_adjuster.py:735` `_apply_foreign_net_boost()` | **유지** | 한국 시장 고유 특성 반영 (외국인 비중 큼) |
| 11 | **섹터 상관관계 감쇠** | `weight_adjuster.py:657` `_apply_portfolio_correlation()` | **유지** | 동일 섹터 과집중 방지. 분산투자 |
| 12 | **선매도 시그널** | `weight_adjuster.py:787` `_get_preemptive_sell_targets()` | **유지** | 하락 신호 감지 시 선제적 매도 |
| 13 | **히스토리 데이터 파이프라인** | `data/history/` | **유지** | 30년 데이터 기반 백테스팅 인프라 |
| 14 | **usePositionAnalyses 훅** | `frontend/hooks/usePositionAnalyses.ts` | **삭제 가능** | PA 에이전트 삭제됨. position_analyses 테이블 미존재 |

**결론:** 코드에만 있는 기능은 **모두 유지**해야 합니다 (14번 제외).
명세서는 초기 설계이고, 코드는 실전 운용 과정에서 진화한 결과입니다.
특히 DCA, 가격예측, exit_plan, 투자기간 관리는 명세서보다 더 정교합니다.

---

## 종합 권장 로드맵

구현 효과가 크고 기존 코드 변경이 적은 순서로 정렬.

| 순서 | 작업 | 수정 파일 | 예상 규모 | 기대 효과 |
|---|---|---|---|---|
| **1** | 추세 필터 (Filter 2) 추가 | `market_analyzer.py` + `weight_adjuster.py` | +100줄 | 역추세 매매 차단 (~30% 불량매매 감소) |
| **2** | 진입 타이밍 필터 (Filter 3) 추가 | `weight_adjuster.py` | +80줄 | 진입 정확도 향상 |
| **3** | trading_allowed 플래그 | `market_analyzer.py` + `orchestrator.py` | +35줄 | CRASH/SURGE 시 매매 자동 차단 |
| **4** | 국면 히스테리시스 | `market_analyzer.py` | +30줄 | whipsaw(잦은 국면전환) 방지 |
| **5** | 총 노출도 체크 | `executor.py` | +25줄 | 과도한 투자비중 방지 |
| **6** | 추세 반전 이탈 | `executor.py` + DB migration | +35줄 | 추세 꺾인 종목 조기 탈출 |
| **7** | filter_log 테이블 | DB + 각 에이전트 | +50줄 | 사후 분석 및 전략 개선 데이터 |
| **8** | trades 컬럼 확장 | DB migration + `executor.py` | +20줄 | 매매 근거 추적 |
| **9** | 수동 국면 오버라이드 | config + MA + frontend | +40줄 | 긴급 상황 대응 |
| **10** | 장중 재판단 트리거 | `orchestrator.py` | +20줄 | VIX 급등 등 실시간 대응 |
