# 다중 필터 매매 시스템 설계 명세서

> **용도**: 이 문서를 Claude Code에 제공하여 현재 코드베이스와 비교 분석하세요.
> **프롬프트 예시**: "이 명세서를 읽고, 현재 프로젝트 코드가 이 명세와 어떻게 다른지 분석해줘. 빠진 부분, 다르게 구현된 부분, 이미 구현된 부분을 구분해서 알려줘."

---

## 시스템 개요

매매 판단은 5단계 필터를 순차적으로 통과해야 한다. 각 필터를 통과하지 못하면 해당 매매 기회는 무시된다. 이 구조의 목적은 **나쁜 매매를 사전에 걸러내는 것**이다.

```
[모든 매매 기회] → 필터1 → 필터2 → 필터3 → 필터4 → 필터5 → [실행]
                   ↓제거     ↓제거     ↓대기     ↓비중조절   ↓손절/익절
                  ~40%      ~30%      ~15%
```

### 필터 흐름 요약

| 필터 | 이름 | 질문 | 담당 에이전트 |
|------|------|------|---------------|
| 1 | 시장 환경 판단 | 지금 시장이 매매하기 좋은가? | Market Analyzer |
| 2 | 추세 확인 | 이 종목이 올바른 방향인가? | Market Analyzer + Strategy Researcher |
| 3 | 진입 타이밍 | 지금이 좋은 진입점인가? | Logic Applier |
| 4 | 포지션 크기 결정 | 얼마나 살 것인가? | Weight Adjuster |
| 5 | 이탈 규칙 | 언제 나올 것인가? | Executor |

---

## 필터 1: 시장 환경 판단 (Market Regime Filter)

### 목적
매일 장 시작 전에 시장 전체의 상태를 판단하여, 매매 자체를 할지 말지를 결정한다.

### 실행 시점
- **매일 한국 장 시작 전 (08:30~08:50 KST)**
- 전날 밤 미국 시장 마감 데이터를 기반으로 판단
- 장중에는 급변 시에만 재판단 (VIX 급등 등)

### 입력 데이터

```python
# 필수 입력 데이터
market_regime_inputs = {
    # US 시장 데이터 (선행 지표) - yfinance로 수집
    "sp500_close_change_pct": float,     # S&P 500 전일 등락률 (%)
    "sp500_close_vs_50ma": str,          # "above" 또는 "below"
    "sp500_close_vs_200ma": str,         # "above" 또는 "below"
    "vix_current": float,               # VIX 현재값
    "vix_change_pct": float,            # VIX 전일 대비 변화율 (%)
    "nasdaq_close_change_pct": float,    # 나스닥 전일 등락률 (%)

    # KR 시장 데이터 - KIS API로 수집
    "kospi_close_vs_50ma": str,          # "above" 또는 "below"
    "kospi_close_vs_200ma": str,         # "above" 또는 "below"
    "kospi_rsi_14": float,              # KOSPI RSI(14일)
    "kospi_5day_change_pct": float,      # KOSPI 5일간 누적 등락률 (%)
    "kospi_daily_range_avg_5d": float,   # 최근 5일 평균 일일 변동폭 (%)
}
```

### 시장 국면 분류 (4가지)

#### 국면 1: 안정 상승 (STABLE_UPTREND)

```python
def is_stable_uptrend(inputs):
    conditions = [
        inputs["kospi_close_vs_50ma"] == "above",
        inputs["kospi_close_vs_200ma"] == "above",
        inputs["vix_current"] < 20,
        inputs["sp500_close_change_pct"] > -1.0,  # 전일 1% 이상 하락 아님
        inputs["kospi_daily_range_avg_5d"] < 1.5,  # 변동성 낮음
    ]
    return sum(conditions) >= 4  # 5개 중 4개 이상 충족
```

**매매 규칙:**
- `trading_allowed`: True
- `max_position_size_pct`: 100% (정상)
- `max_open_positions`: 제한 없음 (설정된 최대값)
- `stop_loss_pct`: 표준값 (예: -3%)
- `new_entry_allowed`: True

#### 국면 2: 급등 / 과열 (SURGE)

```python
def is_surge(inputs):
    conditions = [
        inputs["kospi_rsi_14"] > 70,
        inputs["kospi_5day_change_pct"] > 5.0,     # 5일간 5% 이상 상승
        inputs["sp500_close_change_pct"] > 2.0,     # 미국도 급등
    ]
    return sum(conditions) >= 2  # 3개 중 2개 이상 충족
```

**매매 규칙:**
- `trading_allowed`: True (보유 종목 관리만)
- `max_position_size_pct`: 50% (절반으로 축소)
- `new_entry_allowed`: False (신규 매수 중단)
- `take_profit_action`: "보유 종목 30~50% 이익 확정 검토"
- `trailing_stop_tighten`: True (트레일링 스탑 타이트하게)

#### 국면 3: 고변동성 (HIGH_VOLATILITY)

```python
def is_high_volatility(inputs):
    conditions = [
        inputs["vix_current"] >= 25,
        inputs["kospi_daily_range_avg_5d"] >= 2.0,  # 일일 변동 2% 이상
        abs(inputs["sp500_close_change_pct"]) >= 1.5,  # 미국 큰 변동
        inputs["vix_change_pct"] > 15,               # VIX 자체가 급등
    ]
    return sum(conditions) >= 2  # 4개 중 2개 이상 충족
```

**매매 규칙:**
- `trading_allowed`: True (매우 제한적)
- `max_position_size_pct`: 50%
- `max_open_positions`: 3 (최대 3종목)
- `new_entry_allowed`: True (단, 높은 확신도 신호만)
- `stop_loss_pct`: 표준값 × 1.5 (변동성만큼 여유)
- `required_signal_strength`: "strong" (약한 신호 무시)

#### 국면 4: 하락 / 폭락 (CRASH)

```python
def is_crash(inputs):
    conditions = [
        inputs["kospi_close_vs_200ma"] == "below",
        inputs["vix_current"] >= 30,
        inputs["sp500_close_change_pct"] < -2.0,   # 미국 2% 이상 하락
        inputs["kospi_5day_change_pct"] < -5.0,     # 5일간 5% 이상 하락
    ]
    return sum(conditions) >= 2  # 4개 중 2개 이상 충족
```

**매매 규칙:**
- `trading_allowed`: False (매매 완전 중단)
- `new_entry_allowed`: False
- `existing_positions_action`: "전량 손절 검토"
- `cash_target_pct`: 80 (현금 비중 80% 이상)
- `system_mode`: "WATCH_ONLY" (관망 모드)

### 판정 우선순위

국면 판정은 다음 우선순위로 적용된다 (위험한 것부터 먼저 체크):

```python
def determine_market_regime(inputs):
    # 1순위: 폭락 체크 (가장 위험)
    if is_crash(inputs):
        return "CRASH"

    # 2순위: 고변동성 체크
    if is_high_volatility(inputs):
        return "HIGH_VOLATILITY"

    # 3순위: 과열 체크
    if is_surge(inputs):
        return "SURGE"

    # 4순위: 안정 상승 체크
    if is_stable_uptrend(inputs):
        return "STABLE_UPTREND"

    # 어디에도 해당 안 되면 고변동성으로 보수적 처리
    return "HIGH_VOLATILITY"
```

### 출력 형식 (다른 에이전트에 전달)

```json
{
    "timestamp": "2025-04-02T08:45:00+09:00",
    "market_regime": "STABLE_UPTREND",
    "confidence": 0.85,
    "trading_rules": {
        "trading_allowed": true,
        "new_entry_allowed": true,
        "max_position_size_pct": 100,
        "max_open_positions": 10,
        "stop_loss_pct": -3.0,
        "trailing_stop_tighten": false,
        "required_signal_strength": "normal",
        "system_mode": "ACTIVE"
    },
    "reasoning": "KOSPI 50MA·200MA 위, VIX 18.5, S&P500 +0.3% 마감. 5개 조건 중 5개 충족.",
    "us_market_summary": {
        "sp500_change": "+0.3%",
        "vix": 18.5,
        "nasdaq_change": "+0.5%"
    },
    "next_review": "장중 VIX 25 돌파 시 재판단",
    "regime_history": ["STABLE_UPTREND", "STABLE_UPTREND", "HIGH_VOLATILITY"]
}
```

### 구현 시 주의사항

1. **국면 전환 히스테리시스**: 국면이 너무 자주 바뀌면 whipsaw(잦은 방향전환)가 발생한다. 국면 전환은 **2일 연속** 새로운 국면 조건을 충족해야 전환되도록 한다 (CRASH 제외 — CRASH는 즉시 전환).
2. **로깅**: 매일의 국면 판정 결과와 근거를 Supabase에 저장하여 나중에 백테스팅에 활용한다.
3. **수동 오버라이드**: 사용자가 수동으로 국면을 강제 설정할 수 있는 기능을 둔다.

---

## 필터 2: 추세 확인 (Trend Filter)

### 목적
필터 1을 통과한 상태에서, 개별 종목이 매매하기 좋은 추세를 보이고 있는지 확인한다.

### 실행 시점
- 매매 대상 종목 풀(pool)에 대해 실시간 또는 정기적으로 실행
- 필터 1에서 `trading_allowed == True`일 때만 작동

### 입력 데이터 (종목별)

```python
trend_filter_inputs = {
    "symbol": str,                       # 종목 코드
    "current_price": float,              # 현재가
    "ma_20": float,                      # 20일 이동평균
    "ma_50": float,                      # 50일 이동평균
    "ma_200": float,                     # 200일 이동평균
    "rsi_14": float,                     # RSI(14)
    "volume_ratio": float,              # 현재 거래량 / 20일 평균 거래량
    "adx_14": float,                     # ADX(14) - 추세 강도
    "macd_histogram": float,             # MACD 히스토그램 값
    "price_change_20d_pct": float,       # 20일간 등락률
}
```

### 추세 판정 로직

```python
def check_trend(inputs):
    score = 0
    max_score = 0

    # 이동평균 배열 (가중치: 3점)
    max_score += 3
    if inputs["current_price"] > inputs["ma_20"] > inputs["ma_50"]:
        score += 3  # 정배열 = 강한 상승추세
    elif inputs["current_price"] > inputs["ma_50"]:
        score += 2  # 50MA 위 = 중간 상승추세
    elif inputs["current_price"] > inputs["ma_200"]:
        score += 1  # 200MA 위 = 약한 상승추세
    # else: 0점 = 하락추세

    # RSI 위치 (가중치: 2점)
    max_score += 2
    if 40 <= inputs["rsi_14"] <= 65:
        score += 2  # 건강한 상승 범위
    elif 30 <= inputs["rsi_14"] < 40 or 65 < inputs["rsi_14"] <= 70:
        score += 1  # 경계 범위
    # else: 0점 = 과매수/과매도

    # 추세 강도 - ADX (가중치: 2점)
    max_score += 2
    if inputs["adx_14"] >= 25:
        score += 2  # 강한 추세
    elif inputs["adx_14"] >= 20:
        score += 1  # 보통 추세
    # else: 0점 = 추세 없음 (횡보)

    # MACD 방향 (가중치: 1점)
    max_score += 1
    if inputs["macd_histogram"] > 0:
        score += 1  # 상승 모멘텀

    # 거래량 확인 (가중치: 1점)
    max_score += 1
    if inputs["volume_ratio"] >= 0.8:
        score += 1  # 정상 이상의 거래량

    # 결과 판정
    trend_score = score / max_score  # 0.0 ~ 1.0

    if trend_score >= 0.7:
        return {"trend": "STRONG_UP", "score": trend_score, "pass": True}
    elif trend_score >= 0.5:
        return {"trend": "MODERATE_UP", "score": trend_score, "pass": True}
    elif trend_score >= 0.3:
        return {"trend": "WEAK", "score": trend_score, "pass": False}  # 필터에서 제거
    else:
        return {"trend": "DOWN", "score": trend_score, "pass": False}  # 필터에서 제거
```

### 출력 형식

```json
{
    "symbol": "005930",
    "trend": "STRONG_UP",
    "trend_score": 0.78,
    "pass": true,
    "details": {
        "ma_alignment": "정배열 (가격 > 20MA > 50MA)",
        "rsi": 55.3,
        "adx": 28.4,
        "macd": "양수 (상승 모멘텀)",
        "volume": "정상 (1.2배)"
    }
}
```

---

## 필터 3: 진입 타이밍 (Entry Signal Filter)

### 목적
추세가 확인된 종목에서, **지금 이 순간이 좋은 진입점인지** 판단한다.

### 핵심 개념: 풀백 매수 (Buy the Dip in Uptrend)
상승 추세인 종목이 일시적으로 하락했다가 다시 올라가려는 시점에 진입한다.

### 진입 신호 조건 (3개 중 2개 이상 충족 시 진입)

```python
def check_entry_signal(inputs, trend_result):
    if not trend_result["pass"]:
        return {"entry_allowed": False, "reason": "추세 필터 미통과"}

    signals = []

    # 신호 1: RSI 반등
    # RSI가 과매도 근처(30~40)에서 반등하기 시작
    if 30 <= inputs["rsi_14"] <= 45 and inputs["rsi_14_prev"] < inputs["rsi_14"]:
        signals.append("RSI 반등 (과매도 탈출)")

    # 신호 2: 이동평균 지지 확인
    # 가격이 20MA 또는 50MA에 닿았다가 반등
    price_to_ma20_pct = (inputs["current_price"] - inputs["ma_20"]) / inputs["ma_20"] * 100
    if -2.0 <= price_to_ma20_pct <= 1.0:
        signals.append("20MA 지지선 접근/반등")

    # 신호 3: 거래량 증가 + 양봉
    if inputs["price_change_today_pct"] > 0 and inputs["volume_ratio"] >= 1.3:
        signals.append("거래량 동반 양봉")

    # 신호 4: MACD 골든크로스
    if inputs["macd_histogram"] > 0 and inputs["macd_histogram_prev"] <= 0:
        signals.append("MACD 골든크로스")

    # 신호 5: US 시장 선행 신호
    # 전일 밤 S&P 500 관련 섹터가 상승
    if inputs["us_sector_change_pct"] > 0.5:
        signals.append("US 관련 섹터 상승 (선행 신호)")

    # 2개 이상 신호 충족 시 진입 허용
    entry_allowed = len(signals) >= 2

    # 신호 강도 계산
    signal_strength = "strong" if len(signals) >= 3 else "normal" if len(signals) >= 2 else "weak"

    return {
        "entry_allowed": entry_allowed,
        "signal_count": len(signals),
        "signal_strength": signal_strength,
        "signals": signals,
        "timestamp": "current_time"
    }
```

### 진입 금지 조건 (어떤 경우에도 진입하지 않음)

```python
entry_blockers = [
    inputs["rsi_14"] > 75,                    # 극심한 과매수
    inputs["price_change_today_pct"] > 5.0,    # 당일 5% 이상 급등 (추격 매수 금지)
    inputs["volume_ratio"] > 5.0,              # 비정상적 거래량 (이상 징후)
    inputs["earnings_within_3days"],           # 실적 발표 3일 이내 (불확실성)
]
# 하나라도 True면 진입 금지
```

---

## 필터 4: 포지션 크기 결정 (Position Sizing)

### 목적
진입이 결정된 종목에 대해 **얼마나 살 것인지**를 확신도에 따라 조절한다.

### 포지션 크기 계산

```python
def calculate_position_size(
    total_capital,          # 총 투자 가능 금액
    market_regime,          # 필터 1 결과
    trend_score,            # 필터 2 결과 (0.0~1.0)
    signal_strength,        # 필터 3 결과 ("weak", "normal", "strong")
    current_open_positions  # 현재 보유 종목 수
):
    # 기본 포지션 크기 (총 자본의 10%)
    base_size_pct = 10.0

    # 시장 환경에 따른 조정
    regime_multiplier = {
        "STABLE_UPTREND": 1.0,
        "SURGE": 0.5,
        "HIGH_VOLATILITY": 0.5,
        "CRASH": 0.0  # 매매 중단이므로 여기 오면 안 됨
    }

    # 추세 강도에 따른 조정
    trend_multiplier = trend_score  # 0.0 ~ 1.0

    # 신호 강도에 따른 조정
    signal_multiplier = {
        "strong": 1.2,
        "normal": 1.0,
        "weak": 0.7
    }

    # 분산 투자 제한 (이미 많이 보유 중이면 축소)
    diversification_multiplier = max(0.5, 1.0 - (current_open_positions * 0.05))

    # 최종 포지션 크기 계산
    position_size_pct = (
        base_size_pct
        * regime_multiplier[market_regime]
        * trend_multiplier
        * signal_multiplier[signal_strength]
        * diversification_multiplier
    )

    # 최소/최대 제한
    position_size_pct = max(3.0, min(position_size_pct, 20.0))

    position_size_krw = total_capital * (position_size_pct / 100)

    return {
        "position_size_pct": round(position_size_pct, 1),
        "position_size_krw": int(position_size_krw),
        "multipliers": {
            "regime": regime_multiplier[market_regime],
            "trend": round(trend_multiplier, 2),
            "signal": signal_multiplier[signal_strength],
            "diversification": round(diversification_multiplier, 2)
        }
    }
```

### 총 노출도 제한 (Risk Budget)

```python
# 전체 포트폴리오 차원의 위험 관리
MAX_TOTAL_EXPOSURE_PCT = {
    "STABLE_UPTREND": 80,     # 최대 80%까지 투자
    "SURGE": 50,              # 최대 50%
    "HIGH_VOLATILITY": 40,    # 최대 40%
    "CRASH": 10               # 최대 10% (기존 잔여 포지션)
}

def check_risk_budget(market_regime, current_exposure_pct, new_position_pct):
    max_allowed = MAX_TOTAL_EXPOSURE_PCT[market_regime]
    if current_exposure_pct + new_position_pct > max_allowed:
        allowed = max(0, max_allowed - current_exposure_pct)
        return {"allowed": False, "max_additional_pct": allowed}
    return {"allowed": True}
```

---

## 필터 5: 이탈 규칙 (Exit Rules)

### 목적
보유 중인 종목에 대해 **언제 나올 것인지**를 관리한다.

### 현재 구현 상태: 트레일링 스탑 (구현 완료)

기존 트레일링 스탑 로직은 유지하되, 다음을 추가/확인한다:

### 이탈 규칙 체계 (3가지 이탈 조건)

```python
def check_exit_conditions(position, market_regime, current_price):
    exit_signals = []

    # === 이탈 조건 1: 손절 (Stop Loss) ===
    # 기존 트레일링 스탑 유지
    # + 시장 환경에 따른 손절폭 조정
    stop_loss_adjustment = {
        "STABLE_UPTREND": 1.0,     # 표준 손절폭
        "SURGE": 0.7,              # 더 타이트하게 (이익 보호)
        "HIGH_VOLATILITY": 1.5,    # 더 넓게 (변동성 감안)
        "CRASH": 0.5               # 매우 타이트하게 (빠른 탈출)
    }

    adjusted_stop = position["stop_loss_pct"] * stop_loss_adjustment[market_regime]
    current_loss = (current_price - position["highest_price"]) / position["highest_price"] * 100

    if current_loss <= adjusted_stop:
        exit_signals.append({
            "type": "STOP_LOSS",
            "priority": "IMMEDIATE",
            "reason": f"트레일링 스탑 도달 ({current_loss:.1f}%)"
        })

    # === 이탈 조건 2: 목표가 도달 (Take Profit) ===
    profit_pct = (current_price - position["entry_price"]) / position["entry_price"] * 100

    # 단계별 이익 확정
    if profit_pct >= 15:
        exit_signals.append({
            "type": "TAKE_PROFIT",
            "priority": "HIGH",
            "action": "보유 수량 50% 매도",
            "reason": f"목표 수익률 15% 도달 ({profit_pct:.1f}%)"
        })
    elif profit_pct >= 10:
        exit_signals.append({
            "type": "TAKE_PROFIT",
            "priority": "MEDIUM",
            "action": "보유 수량 30% 매도",
            "reason": f"목표 수익률 10% 도달 ({profit_pct:.1f}%)"
        })

    # === 이탈 조건 3: 추세 반전 (Trend Reversal) ===
    if position["trend_score_current"] < 0.3 and position["trend_score_entry"] >= 0.5:
        exit_signals.append({
            "type": "TREND_REVERSAL",
            "priority": "HIGH",
            "reason": "추세 점수 급락 (진입 시 대비 60% 이상 하락)"
        })

    # === 이탈 조건 4: 시장 환경 악화 ===
    if market_regime == "CRASH":
        exit_signals.append({
            "type": "REGIME_EXIT",
            "priority": "IMMEDIATE",
            "action": "전량 매도",
            "reason": "시장 국면 CRASH 전환"
        })

    # === 이탈 조건 5: 보유 기간 초과 ===
    holding_days = (datetime.now() - position["entry_time"]).days
    if holding_days > 20 and profit_pct < 2.0:
        exit_signals.append({
            "type": "TIME_EXIT",
            "priority": "LOW",
            "reason": f"20일 보유 중 수익률 {profit_pct:.1f}% (자본 효율성 낮음)"
        })

    return {
        "has_exit_signal": len(exit_signals) > 0,
        "exit_signals": sorted(exit_signals, key=lambda x: {"IMMEDIATE": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}[x["priority"]]),
        "recommended_action": exit_signals[0] if exit_signals else None
    }
```

---

## 에이전트 간 메시지 흐름

### 매일 아침 루틴 (장 시작 전)

```
1. Orchestrator → Data Collector: "US 시장 데이터 수집"
2. Data Collector → Preprocessor: "원시 데이터 전처리"
3. Preprocessor → Market Analyzer: "전처리된 데이터 전달"
4. Market Analyzer: 필터 1 실행 → 시장 국면 판정
5. Market Analyzer → Orchestrator: 국면 판정 결과 + 매매 규칙
6. IF trading_allowed:
   6a. Orchestrator → Strategy Researcher: "매매 대상 종목 스캔"
   6b. Strategy Researcher → Logic Applier: "종목별 필터 2, 3 실행"
   6c. Logic Applier → Weight Adjuster: "통과 종목 + 포지션 크기 요청"
   6d. Weight Adjuster → Executor: "매매 지시 (종목, 수량, 가격)"
   6e. Executor: 실행 + 결과 보고
7. IF NOT trading_allowed:
   7a. System → WATCH_ONLY 모드 전환
   7b. 기존 보유 종목만 모니터링 (이탈 규칙만 작동)
```

### 장중 모니터링

```
매 5분 간격:
1. Data Collector: 보유 종목 실시간 가격 수집
2. Executor: 필터 5 (이탈 규칙) 체크
3. IF 이탈 신호 발생 → 즉시 매도 실행

매 30분 간격:
1. Market Analyzer: VIX, KOSPI 변동 체크
2. IF 국면 변경 조건 충족 → 국면 재판정 → 규칙 업데이트
```

---

## 데이터베이스 테이블 (Supabase)

### 신규 테이블

```sql
-- 시장 국면 판정 기록
CREATE TABLE market_regime_log (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    regime VARCHAR(20) NOT NULL,  -- STABLE_UPTREND, SURGE, HIGH_VOLATILITY, CRASH
    confidence FLOAT,
    vix_value FLOAT,
    sp500_change_pct FLOAT,
    kospi_vs_50ma VARCHAR(10),
    kospi_vs_200ma VARCHAR(10),
    trading_rules JSONB,          -- 해당 국면의 매매 규칙
    reasoning TEXT
);

-- 종목별 필터 통과 기록
CREATE TABLE filter_log (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol VARCHAR(20) NOT NULL,
    filter_1_regime VARCHAR(20),
    filter_2_trend VARCHAR(20),
    filter_2_score FLOAT,
    filter_2_pass BOOLEAN,
    filter_3_entry BOOLEAN,
    filter_3_signals JSONB,       -- 진입 신호 목록
    filter_4_position_size_pct FLOAT,
    filter_4_position_size_krw BIGINT,
    final_decision VARCHAR(20),   -- BUY, SKIP, WATCH
    reasoning TEXT
);

-- 매매 실행 기록 (기존 테이블 확장)
-- 기존 trades 테이블에 다음 컬럼 추가:
--   market_regime VARCHAR(20)
--   trend_score FLOAT
--   entry_signals JSONB
--   position_size_reason JSONB
--   exit_type VARCHAR(20)  -- STOP_LOSS, TAKE_PROFIT, TREND_REVERSAL, REGIME_EXIT, TIME_EXIT
```

---

## Claude Code 확인 요청 프롬프트

아래 프롬프트를 Claude Code에 이 명세서와 함께 전달하세요:

```
이 명세서(trading_filter_spec.md)를 읽고 현재 프로젝트 코드를 분석해줘.

다음 항목별로 비교해줘:

1. **이미 구현된 부분**: 명세서의 내용과 일치하거나 유사하게 이미 코드에 있는 것
2. **다르게 구현된 부분**: 비슷한 기능이 있지만 로직이나 구조가 다른 것
3. **아직 없는 부분**: 명세서에는 있지만 코드에 전혀 없는 것
4. **코드에만 있는 부분**: 명세서에는 없지만 현재 코드에 있는 것 (삭제 대상인지 판단)

각 항목에 대해 구체적으로 어떤 파일의 어떤 부분인지 알려주고,
없는 부분은 어떤 파일에 어떻게 추가해야 하는지 제안해줘.
```

---

## 구현 우선순위 로드맵

| 단계 | 작업 | 예상 기간 | 효과 |
|------|------|-----------|------|
| 1단계 | 필터 1 (시장 환경 판단) 구현 | 3-4일 | 불필요한 매매 30-40% 감소 |
| 2단계 | 필터 2 (추세 확인) 기존 로직 리팩토링 | 2-3일 | 역추세 매매 제거 |
| 3단계 | 필터 3 (진입 타이밍) 구현 | 3-4일 | 진입 정확도 향상 |
| 4단계 | 필터 4 (포지션 크기) 구현 | 2일 | 리스크 관리 체계화 |
| 5단계 | 필터 5 (이탈 규칙) 기존 로직 확장 | 2-3일 | 이익 확정 + 시간 손절 추가 |
| 6단계 | 전체 통합 테스트 + 백테스팅 | 3-5일 | 전체 시스템 검증 |
