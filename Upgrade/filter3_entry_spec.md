# Filter 3: 진입 타이밍 필터 구현 명세

> **대상 파일**: `weight_adjuster.py` (메인 로직) + `market_analyzer.py` (보조 데이터)
> **의존**: Filter 2 `check_trend_filter()` 결과를 입력으로 받음
> **원칙**: 기존 코드(테마부스트, 섹터감쇠, RS필터, 선매도시그널 등) 수정 없이 독립 메서드 추가

---

## 1. Filter 3의 위치

```
Filter 2 (추세 확인)                     Filter 3 (진입 타이밍)
   "이 종목이 상승 추세인가?"     →       "지금 이 순간이 좋은 진입점인가?"
   market_analyzer.py                     weight_adjuster.py
   check_trend_filter()                   check_entry_timing()

   종목 단위 판단 (느린 변화)             시점 단위 판단 (빠른 변화)
   하루 1~2회 체크면 충분                  매매 직전에 체크
```

### 비유로 설명

Filter 2가 "이 기차가 올바른 방향으로 가고 있는가?"라면,
Filter 3은 "지금 기차가 잠깐 역에 서 있으니 탈 수 있는가?"예요.

상승 추세(Filter 2 통과)인데 이미 10% 급등한 직후라면 → 지금 타면 비싼 값에 사는 거예요.
상승 추세인데 일시적으로 2% 빠진 상태라면 → 할인된 가격에 탈 수 있는 기회예요.

---

## 2. 아키텍처

### 기존 코드와의 관계

| 기존 기능 (수정 없음) | 역할 | Filter 3과의 관계 |
|----------------------|------|-------------------|
| `_decide_targets()` | 매매 대상 결정 | Filter 3 결과를 이 안에서 활용 |
| `_decide_weight_config()` | 비중 결정 | 변경 없음 |
| 테마부스트 (1.3×) | 테마 가중치 | 병렬로 적용 (충돌 없음) |
| 섹터감쇠 | 분산투자 | 변경 없음 |
| RS필터 | 상대강도 | 변경 없음 |
| 선매도시그널 | 하락 대비 | 변경 없음 |
| 외국인 순매수 부스트 | 수급 반영 | 변경 없음 |
| **`check_entry_timing()`** | **진입 타이밍 판단** | **신규 추가** |
| **`_check_entry_blockers()`** | **진입 금지 조건** | **신규 추가** |

### 호출 순서

```
weight_adjuster._decide_targets() 내부:

  기존 로직 (유지)
    │
    ├─ 종목 후보 선정 (기존)
    ├─ Filter 2: check_trend_batch() → trend_score < threshold 제거 (방금 추가됨)
    │
    ├─ ★ Filter 3: check_entry_timing() → 진입 타이밍 판단 (이번에 추가)
    │     ├─ 진입 금지 조건 체크
    │     ├─ 5개 진입 신호 평가
    │     └─ 2개 미만이면 "WAIT" (매수 보류, 제거는 아님)
    │
    ├─ 테마부스트, 섹터감쇠, RS필터 (기존, 유지)
    ├─ 외국인 순매수 부스트 (기존, 유지)
    └─ 최종 비중 할당 (기존, 유지)
```

---

## 3. 핵심 메서드: `check_entry_timing()`

### 메서드 시그니처

```python
def check_entry_timing(
    self,
    symbol: str,
    price_data: dict,
    trend_result: dict,
    leading_indicators: dict = None,
    market_phase: str = None
) -> dict:
    """
    Filter 2를 통과한 종목에 대해, 지금이 좋은 진입 시점인지 판단한다.

    Parameters:
        symbol: 종목 코드
        price_data: 가격 데이터 (Filter 2와 동일 형식 + 추가 필드)
            {
                "closes": list[float],
                "highs": list[float],
                "lows": list[float],
                "volumes": list[float],
                "opens": list[float],          # 시가 (양봉/음봉 판단용)
            }
        trend_result: Filter 2의 check_trend_filter() 반환값
            {
                "trend_score": float,
                "trend": str,
                "details": { "ma_alignment": {"values": {"ma_20": ...}} }
            }
        leading_indicators: market_analyzer.analyze_leading_indicators() 결과 (선택)
            - US 시장 섹터별 등락률 등 포함
        market_phase: 현재 6국면 분류 결과 (선택)

    Returns:
        {
            "symbol": str,
            "entry_allowed": bool,        # True: 진입 가능, False: 대기
            "entry_decision": str,         # "ENTER" | "WAIT" | "BLOCKED"
            "signal_count": int,           # 충족된 신호 수
            "signal_strength": str,        # "strong" | "normal" | "weak"
            "signals": list[dict],         # 각 신호별 상세 결과
            "blockers": list[dict],        # 진입 금지 조건 (해당 시)
            "confidence": float,           # 0.0~1.0 종합 확신도
            "reason": str                  # 판정 근거
        }
    """
```

### 핵심 로직

```python
def check_entry_timing(self, symbol, price_data, trend_result,
                       leading_indicators=None, market_phase=None):
    closes = price_data["closes"]
    highs = price_data["highs"]
    lows = price_data["lows"]
    volumes = price_data["volumes"]
    opens = price_data.get("opens", closes)  # opens 없으면 closes로 대체

    current_price = closes[-1]
    prev_price = closes[-2] if len(closes) >= 2 else current_price

    # ===== 0단계: 진입 금지 조건 체크 (최우선) =====
    blockers = self._check_entry_blockers(
        symbol, price_data, trend_result
    )
    if blockers:
        return {
            "symbol": symbol,
            "entry_allowed": False,
            "entry_decision": "BLOCKED",
            "signal_count": 0,
            "signal_strength": "none",
            "signals": [],
            "blockers": blockers,
            "confidence": 0.0,
            "reason": f"진입 금지: {blockers[0]['reason']}"
        }

    # ===== 1단계: 5개 진입 신호 평가 =====
    signals = []

    # --- 신호 1: RSI 반등 감지 ---
    rsi_signal = self._check_rsi_bounce(closes)
    if rsi_signal["triggered"]:
        signals.append(rsi_signal)

    # --- 신호 2: 이동평균 지지 확인 ---
    ma_signal = self._check_ma_support(
        current_price, trend_result
    )
    if ma_signal["triggered"]:
        signals.append(ma_signal)

    # --- 신호 3: 거래량 동반 양봉 ---
    candle_signal = self._check_volume_candle(
        closes, opens, volumes
    )
    if candle_signal["triggered"]:
        signals.append(candle_signal)

    # --- 신호 4: MACD 골든크로스 ---
    macd_signal = self._check_macd_cross(closes)
    if macd_signal["triggered"]:
        signals.append(macd_signal)

    # --- 신호 5: US 시장 선행 신호 ---
    us_signal = self._check_us_leading_signal(
        symbol, leading_indicators
    )
    if us_signal["triggered"]:
        signals.append(us_signal)

    # ===== 2단계: 종합 판정 =====
    signal_count = len(signals)

    # 국면별 필요 신호 수 조정
    required_signals = self._get_required_signals(market_phase)

    entry_allowed = signal_count >= required_signals

    # 신호 강도 판정
    if signal_count >= 4:
        signal_strength = "very_strong"
    elif signal_count >= 3:
        signal_strength = "strong"
    elif signal_count >= required_signals:
        signal_strength = "normal"
    else:
        signal_strength = "weak"

    # 종합 확신도 계산
    # trend_score(0~1)와 신호 비율(0~1)을 조합
    signal_ratio = signal_count / 5
    trend_score = trend_result.get("trend_score", 0.5)
    confidence = round(trend_score * 0.4 + signal_ratio * 0.6, 3)

    # 판정 결과
    if entry_allowed:
        entry_decision = "ENTER"
        signal_names = [s["name"] for s in signals]
        reason = (
            f"진입 허용: {signal_count}개 신호 충족 "
            f"({', '.join(signal_names)}). "
            f"확신도 {confidence:.0%}"
        )
    else:
        entry_decision = "WAIT"
        reason = (
            f"대기: {signal_count}/{required_signals}개 신호 "
            f"(부족 {required_signals - signal_count}개). "
            f"다음 체크에서 재평가"
        )

    return {
        "symbol": symbol,
        "entry_allowed": entry_allowed,
        "entry_decision": entry_decision,
        "signal_count": signal_count,
        "signal_strength": signal_strength,
        "signals": signals,
        "blockers": [],
        "confidence": confidence,
        "reason": reason
    }
```

---

## 4. 진입 금지 조건: `_check_entry_blockers()`

```python
def _check_entry_blockers(self, symbol, price_data, trend_result):
    """
    어떤 신호가 있든 절대 진입하면 안 되는 조건을 체크한다.
    하나라도 해당하면 즉시 BLOCKED 반환.

    이 조건들은 '손실 회피'를 위한 안전장치이다.
    """
    closes = price_data["closes"]
    volumes = price_data["volumes"]
    current_price = closes[-1]

    blockers = []

    # --- 차단 1: 극심한 과매수 (RSI > 75) ---
    # 이미 너무 올라서 추격 매수하면 고점에 물림
    rsi = self._calc_rsi_simple(closes, 14)
    if rsi > 75:
        blockers.append({
            "type": "OVERBOUGHT",
            "reason": f"RSI {rsi:.1f} > 75 (극심한 과매수)",
            "severity": "HIGH"
        })

    # --- 차단 2: 당일 급등 추격 금지 (당일 +5% 이상) ---
    # 이미 많이 올랐는데 뒤늦게 추격하면 위험
    if len(closes) >= 2:
        today_change_pct = (closes[-1] - closes[-2]) / closes[-2] * 100
        if today_change_pct > 5.0:
            blockers.append({
                "type": "CHASING",
                "reason": f"당일 {today_change_pct:.1f}% 급등 (추격 매수 금지)",
                "severity": "HIGH"
            })

    # --- 차단 3: 비정상 거래량 (평균의 5배 이상) ---
    # 작전주, 뉴스 과반응 등 비정상 상황 의심
    if len(volumes) >= 20:
        vol_avg_20 = sum(volumes[-20:]) / 20
        if vol_avg_20 > 0:
            vol_ratio = volumes[-1] / vol_avg_20
            if vol_ratio > 5.0:
                blockers.append({
                    "type": "ABNORMAL_VOLUME",
                    "reason": f"거래량 {vol_ratio:.1f}배 (비정상, 이상 징후)",
                    "severity": "MEDIUM"
                })

    # --- 차단 4: 갭하락 발생 (전일 종가 대비 -3% 이상 갭) ---
    # 악재로 인한 갭하락 시 추가 하락 가능성
    opens = price_data.get("opens", closes)
    if len(opens) >= 2 and len(closes) >= 2:
        gap_pct = (opens[-1] - closes[-2]) / closes[-2] * 100
        if gap_pct < -3.0:
            blockers.append({
                "type": "GAP_DOWN",
                "reason": f"갭하락 {gap_pct:.1f}% (악재 가능성)",
                "severity": "MEDIUM"
            })

    # --- 차단 5: 연속 하락 (5일 연속 음봉) ---
    # 낙하하는 나이프는 잡지 않는다
    if len(closes) >= 6:
        consecutive_down = all(
            closes[-i] < closes[-i-1] for i in range(1, 6)
        )
        if consecutive_down:
            total_drop = (closes[-1] - closes[-6]) / closes[-6] * 100
            blockers.append({
                "type": "FALLING_KNIFE",
                "reason": f"5일 연속 하락 ({total_drop:.1f}%, 낙하 나이프)",
                "severity": "HIGH"
            })

    return blockers


def _calc_rsi_simple(self, closes, period=14):
    """
    간단한 RSI 계산. 기존 _calc_rsi()가 접근 불가한 경우 대비.
    기존 메서드 접근 가능하면 이것 대신 기존 것을 사용.
    """
    if len(closes) < period + 1:
        return 50.0  # 데이터 부족 시 중립

    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    recent = deltas[-period:]

    gains = [d for d in recent if d > 0]
    losses = [-d for d in recent if d < 0]

    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0.001

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))
```

---

## 5. 5개 진입 신호 상세 구현

### 신호 1: RSI 반등 감지

```python
def _check_rsi_bounce(self, closes):
    """
    RSI가 과매도 영역(30~45)에 있으면서 반등하기 시작한 경우.
    '바닥에서 올라오는 종목'을 잡는 신호.
    """
    if len(closes) < 16:
        return {"name": "RSI 반등", "triggered": False, "reason": "데이터 부족"}

    rsi_now = self._calc_rsi_simple(closes, 14)
    rsi_prev = self._calc_rsi_simple(closes[:-1], 14)

    triggered = (30 <= rsi_now <= 45) and (rsi_now > rsi_prev)

    return {
        "name": "RSI 반등",
        "triggered": triggered,
        "weight": 1.0,
        "details": {
            "rsi_current": round(rsi_now, 1),
            "rsi_previous": round(rsi_prev, 1),
            "direction": "상승" if rsi_now > rsi_prev else "하락"
        },
        "reason": (
            f"RSI {rsi_now:.1f} (이전 {rsi_prev:.1f}에서 반등)"
            if triggered else
            f"RSI {rsi_now:.1f} (반등 조건 미충족)"
        )
    }
```

### 신호 2: 이동평균 지지 확인

```python
def _check_ma_support(self, current_price, trend_result):
    """
    가격이 20MA 또는 50MA에 접근(±2%)한 상태.
    상승 추세에서 MA까지 눌렸다가 반등하는 '풀백 매수' 기회.
    """
    ma_values = trend_result.get("details", {}).get(
        "ma_alignment", {}
    ).get("values", {})

    ma_20 = ma_values.get("ma_20", 0)
    ma_50 = ma_values.get("ma_50", 0)

    if ma_20 == 0:
        return {"name": "MA 지지", "triggered": False, "reason": "MA 데이터 없음"}

    # 현재가와 20MA의 거리 (%)
    dist_20 = (current_price - ma_20) / ma_20 * 100 if ma_20 > 0 else 999
    # 현재가와 50MA의 거리 (%)
    dist_50 = (current_price - ma_50) / ma_50 * 100 if ma_50 > 0 else 999

    # 20MA 근처 (-2% ~ +1.5%) 또는 50MA 근처 (-2% ~ +1.5%)
    near_20ma = -2.0 <= dist_20 <= 1.5
    near_50ma = -2.0 <= dist_50 <= 1.5

    triggered = near_20ma or near_50ma
    support_level = "20MA" if near_20ma else "50MA" if near_50ma else "없음"

    return {
        "name": "MA 지지",
        "triggered": triggered,
        "weight": 1.2,  # MA 지지는 약간 높은 가중치
        "details": {
            "price": round(current_price, 0),
            "ma_20": round(ma_20, 0),
            "ma_50": round(ma_50, 0),
            "dist_from_20ma_pct": round(dist_20, 2),
            "dist_from_50ma_pct": round(dist_50, 2),
            "support_level": support_level
        },
        "reason": (
            f"{support_level} 지지 접근 (거리 {min(abs(dist_20), abs(dist_50)):.1f}%)"
            if triggered else
            f"MA 지지선에서 먼 상태 (20MA: {dist_20:+.1f}%, 50MA: {dist_50:+.1f}%)"
        )
    }
```

### 신호 3: 거래량 동반 양봉

```python
def _check_volume_candle(self, closes, opens, volumes):
    """
    오늘이 양봉(종가 > 시가)이면서 거래량이 평균의 1.3배 이상.
    '돈이 몰리면서 올라가는 종목'을 잡는 신호.
    """
    if len(closes) < 21 or len(volumes) < 21:
        return {"name": "거래량 양봉", "triggered": False, "reason": "데이터 부족"}

    current_close = closes[-1]
    current_open = opens[-1] if opens else closes[-2]
    current_volume = volumes[-1]

    # 양봉 확인
    is_bullish = current_close > current_open
    bullish_body_pct = (
        (current_close - current_open) / current_open * 100
        if current_open > 0 else 0
    )

    # 거래량 비율
    vol_avg_20 = sum(volumes[-21:-1]) / 20  # 오늘 제외 20일 평균
    vol_ratio = current_volume / vol_avg_20 if vol_avg_20 > 0 else 1.0

    # 양봉 + 거래량 1.3배 이상 + 양봉 실체 0.3% 이상 (너무 작은 양봉 제외)
    triggered = is_bullish and vol_ratio >= 1.3 and bullish_body_pct >= 0.3

    return {
        "name": "거래량 양봉",
        "triggered": triggered,
        "weight": 1.0,
        "details": {
            "candle": "양봉" if is_bullish else "음봉",
            "body_pct": round(bullish_body_pct, 2),
            "volume_ratio": round(vol_ratio, 2)
        },
        "reason": (
            f"양봉(+{bullish_body_pct:.1f}%) + 거래량 {vol_ratio:.1f}배"
            if triggered else
            f"{'음봉' if not is_bullish else f'거래량 부족({vol_ratio:.1f}배)'}"
        )
    }
```

### 신호 4: MACD 골든크로스

```python
def _check_macd_cross(self, closes):
    """
    MACD 히스토그램이 음수→양수로 전환 (골든크로스).
    또는 양수이면서 전일보다 확대 중 (모멘텀 강화).
    """
    if len(closes) < 35:  # MACD 계산에 최소 26+9일 필요
        return {"name": "MACD 크로스", "triggered": False, "reason": "데이터 부족"}

    # market_analyzer의 _calc_macd 사용 가능하면 사용
    # 아니면 로컬 계산
    macd = self._calc_macd_local(closes)

    histogram = macd["histogram"]
    histogram_prev = macd["histogram_prev"]

    # 골든크로스: 음수→양수 전환
    golden_cross = histogram > 0 and histogram_prev <= 0

    # 모멘텀 강화: 양수이면서 확대 중
    momentum_up = histogram > 0 and histogram > histogram_prev

    triggered = golden_cross or momentum_up

    signal_type = (
        "골든크로스" if golden_cross
        else "모멘텀 강화" if momentum_up
        else "없음"
    )

    return {
        "name": "MACD 크로스",
        "triggered": triggered,
        "weight": 1.0 if golden_cross else 0.7,  # 골든크로스가 더 강력
        "details": {
            "histogram": round(histogram, 4),
            "histogram_prev": round(histogram_prev, 4),
            "signal_type": signal_type
        },
        "reason": (
            f"MACD {signal_type} (hist: {histogram_prev:.3f}→{histogram:.3f})"
            if triggered else
            f"MACD 하락 모멘텀 (hist: {histogram:.3f})"
        )
    }


def _calc_macd_local(self, closes, fast=12, slow=26, signal=9):
    """MACD 로컬 계산 (market_analyzer 접근 불가 시 사용)"""
    def ema(data, period):
        mult = 2 / (period + 1)
        result = [sum(data[:period]) / period]
        for i in range(period, len(data)):
            result.append((data[i] - result[-1]) * mult + result[-1])
        return result

    fast_ema = ema(closes, fast)
    slow_ema = ema(closes, slow)
    offset = len(fast_ema) - len(slow_ema)
    macd_line = [fast_ema[offset + i] - slow_ema[i] for i in range(len(slow_ema))]

    if len(macd_line) < signal:
        return {"histogram": 0, "histogram_prev": 0}

    sig = ema(macd_line, signal)
    so = len(macd_line) - len(sig)
    hists = [macd_line[so + i] - sig[i] for i in range(len(sig))]

    return {
        "histogram": hists[-1] if hists else 0,
        "histogram_prev": hists[-2] if len(hists) >= 2 else 0
    }
```

### 신호 5: US 시장 선행 신호

```python
def _check_us_leading_signal(self, symbol, leading_indicators):
    """
    전일 밤 US 시장에서 관련 섹터가 상승한 경우.
    Justin 시스템의 핵심 강점: US→KR 선행 지표 활용.

    leading_indicators는 market_analyzer.analyze_leading_indicators()의
    반환값에서 필요한 정보를 추출.
    """
    if not leading_indicators:
        return {
            "name": "US 선행신호",
            "triggered": False,
            "weight": 0,
            "reason": "선행지표 데이터 없음"
        }

    # leading_indicators에서 관련 데이터 추출
    # 구조는 기존 analyze_leading_indicators() 반환 형식에 맞춤
    # 아래는 예시 — 실제 필드명은 기존 코드에 맞게 조정 필요

    sp500_change = leading_indicators.get("sp500_change_pct", 0)
    nasdaq_change = leading_indicators.get("nasdaq_change_pct", 0)
    vix_level = leading_indicators.get("vix_current", 20)
    sector_signals = leading_indicators.get("sector_signals", {})

    # 종합 US 신호 점수
    us_score = 0

    # S&P 500 양호 (+0.3% 이상)
    if sp500_change >= 0.3:
        us_score += 1
    # 나스닥 양호 (+0.5% 이상)
    if nasdaq_change >= 0.5:
        us_score += 1
    # VIX 안정 (20 미만)
    if vix_level < 20:
        us_score += 1
    # 관련 섹터 상승 (종목-섹터 매핑은 기존 코드 참조)
    # sector_signals가 있고 관련 섹터가 양수인 경우
    if sector_signals:
        # 기존 analyze_leading_indicators()의 섹터 분석 결과 활용
        relevant_sector_up = any(
            v > 0.3 for v in sector_signals.values()
        )
        if relevant_sector_up:
            us_score += 1

    triggered = us_score >= 2  # 4개 중 2개 이상 양호

    return {
        "name": "US 선행신호",
        "triggered": triggered,
        "weight": 1.1,  # US 선행신호는 Justin 시스템의 핵심 강점
        "details": {
            "sp500": f"{sp500_change:+.1f}%",
            "nasdaq": f"{nasdaq_change:+.1f}%",
            "vix": round(vix_level, 1),
            "us_score": f"{us_score}/4"
        },
        "reason": (
            f"US 양호 ({us_score}/4): S&P {sp500_change:+.1f}%, "
            f"NASDAQ {nasdaq_change:+.1f}%, VIX {vix_level:.0f}"
            if triggered else
            f"US 부진 ({us_score}/4)"
        )
    }
```

---

## 6. 국면별 필요 신호 수 조정

```python
def _get_required_signals(self, market_phase=None):
    """
    시장 국면에 따라 진입에 필요한 최소 신호 수를 조정한다.

    - 대상승장: 1개만 있어도 진입 (모멘텀 적극 활용)
    - 일반장: 2개 (기본값)
    - 변동폭큰장/하락장: 3개 (확실할 때만 진입)
    - 대폭락장: 사실상 진입 불가 (Filter 1에서 차단되지만, 혹시 모를 때 4개)
    """
    required = {
        "대상승장": 1,
        "상승장": 2,
        "일반장": 2,
        "변동폭큰장": 3,
        "하락장": 3,
        "대폭락장": 4,
    }
    return required.get(market_phase, 2)
```

---

## 7. 배치 처리: `check_entry_timing_batch()`

```python
def check_entry_timing_batch(
    self,
    trend_passed_stocks: list,
    leading_indicators: dict = None,
    market_phase: str = None
) -> dict:
    """
    Filter 2를 통과한 종목들에 대해 일괄 진입 타이밍 평가.

    Parameters:
        trend_passed_stocks: Filter 2 통과 종목 리스트
            [
                {
                    "symbol": "005930",
                    "price_data": {...},
                    "trend_result": {...}  # check_trend_filter() 결과
                },
                ...
            ]

    Returns:
        {
            "enter": [...],      # 진입 허용 종목
            "wait": [...],       # 대기 종목 (다음 체크에서 재평가)
            "blocked": [...],    # 진입 금지 종목
            "summary": {
                "total": int,
                "enter": int,
                "wait": int,
                "blocked": int,
                "required_signals": int,
                "phase": str
            }
        }
    """
    results_enter = []
    results_wait = []
    results_blocked = []

    for stock in trend_passed_stocks:
        result = self.check_entry_timing(
            symbol=stock["symbol"],
            price_data=stock["price_data"],
            trend_result=stock["trend_result"],
            leading_indicators=leading_indicators,
            market_phase=market_phase
        )

        if result["entry_decision"] == "ENTER":
            results_enter.append(result)
        elif result["entry_decision"] == "BLOCKED":
            results_blocked.append(result)
        else:
            results_wait.append(result)

    # 진입 종목을 확신도 순으로 정렬
    results_enter.sort(key=lambda x: x["confidence"], reverse=True)

    total = len(trend_passed_stocks)

    return {
        "enter": results_enter,
        "wait": results_wait,
        "blocked": results_blocked,
        "summary": {
            "total": total,
            "enter": len(results_enter),
            "wait": len(results_wait),
            "blocked": len(results_blocked),
            "required_signals": self._get_required_signals(market_phase),
            "phase": market_phase or "기본"
        }
    }
```

---

## 8. _decide_targets() 연동

```python
# weight_adjuster.py의 _decide_targets() 내부
# Filter 2 적용 후, 비중 할당 전에 삽입

# === Filter 2 이후 (이미 추가됨) ===
# trend_passed = [trend_score >= threshold 종목들]

# === Filter 3 (이번에 추가) ===
if trend_passed:
    entry_results = self.check_entry_timing_batch(
        trend_passed_stocks=trend_passed_data,
        leading_indicators=ma_payload.get("leading_indicators"),
        market_phase=current_phase
    )

    summary = entry_results["summary"]
    self.logger.info(
        f"[진입 필터] {summary['total']}개 → "
        f"진입 {summary['enter']}개, "
        f"대기 {summary['wait']}개, "
        f"차단 {summary['blocked']}개 "
        f"(필요 신호 {summary['required_signals']}개, "
        f"국면 {summary['phase']})"
    )

    # 진입 허용 종목만 비중 할당 대상으로
    final_candidates = entry_results["enter"]

    # 차단 종목 상세 로깅
    for blocked in entry_results["blocked"]:
        self.logger.warning(
            f"  [차단] {blocked['symbol']}: {blocked['reason']}"
        )

    # 대기 종목 로깅 (다음 사이클에서 재평가)
    for waiting in entry_results["wait"]:
        self.logger.debug(
            f"  [대기] {waiting['symbol']}: {waiting['reason']}"
        )

# === 이후 기존 비중 할당 로직 (테마부스트, 섹터감쇠 등) ===
# final_candidates에 대해 기존 로직 실행
```

---

## 9. "WAIT" vs "FILTERED_OUT" 차이

Filter 2와 Filter 3의 중요한 차이점:

```
Filter 2 (추세 확인):
  PASS → 다음 필터로
  FAIL → 완전 제거 (추세가 나쁘면 당분간 매매 불가)

Filter 3 (진입 타이밍):
  ENTER → 매수 실행
  WAIT → 제거가 아니라 "보류" (다음 체크에서 재평가)
  BLOCKED → 즉시 제거 (위험 상황)
```

WAIT 종목은 삭제하지 않고, 다음 모니터링 사이클에서 다시 check_entry_timing()을
실행한다. 추세가 좋은 종목이 아직 타이밍이 안 맞을 뿐이므로, 나중에 풀백이
오면 진입할 수 있다.

---

## 10. 전체 필터 파이프라인 요약

```
종목 풀 (예: 50개)
    │
    ▼
[Filter 1: 시장 환경] ← 이미 있음 (_classify_6phase)
    │ 대폭락장이면 전체 중단
    ▼
[Filter 2: 추세 확인] ← 방금 추가됨 (check_trend_batch)
    │ trend_score < threshold → 제거 (예: 50→30개)
    ▼
[Filter 3: 진입 타이밍] ← 이번에 추가
    │ 신호 부족 → WAIT (예: 30→12개 ENTER, 15개 WAIT, 3개 BLOCKED)
    ▼
[기존 비중 로직] 테마부스트, 섹터감쇠, RS필터, 외국인부스트
    │
    ▼
[Filter 4: 포지션 크기] ← 기존 weight_config로 대부분 구현됨
    │
    ▼
[Filter 5: 이탈 규칙] ← 이미 있음 (trailing stop, exit_plan)
    │
    ▼
실제 매매 실행 (예: 8개 종목, 각각 적정 비중)
```

---

## 11. Claude Code 실행 프롬프트

```
이 명세서(filter3_entry_spec.md)를 읽고 다음을 실행해줘:

1. weight_adjuster.py에 다음 메서드 추가:
   - check_entry_timing()
   - check_entry_timing_batch()
   - _check_entry_blockers()
   - _check_rsi_bounce()
   - _check_ma_support()
   - _check_volume_candle()
   - _check_macd_cross()
   - _check_us_leading_signal()
   - _get_required_signals()
   - _calc_rsi_simple() (기존 _calc_rsi 접근 불가 시)
   - _calc_macd_local() (기존 _calc_macd 접근 불가 시)

2. _decide_targets() 메서드에서 Filter 2 적용 이후,
   비중 할당 전 위치에 check_entry_timing_batch() 호출 삽입.

3. check_entry_timing()에서 trend_result를 받을 때,
   Filter 2의 check_trend_filter() 출력 형식과 정확히 맞는지 확인.
   특히 trend_result["details"]["ma_alignment"]["values"]에서
   ma_20, ma_50 값을 가져오는 부분.

4. leading_indicators 파라미터는 기존 analyze_leading_indicators()
   반환값을 그대로 전달받도록. 필드명이 다르면 매핑 코드 추가.

5. 기존 코드(테마부스트, 섹터감쇠, RS필터, 선매도시그널,
   외국인 순매수 부스트) 절대 수정하지 말 것.

6. WAIT 상태 종목이 다음 사이클에서 재평가되도록,
   orchestrator.py의 _stop_take_loop() 또는 다음 run_once()에서
   이전 WAIT 종목을 우선 재체크하는 로직이 필요한지 판단하고,
   필요하면 추가해줘.
```
