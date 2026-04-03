# Filter 2: 추세 확인 필터 구현 명세

> **대상 파일**: `market_analyzer.py`
> **연동 파일**: `weight_adjuster.py`, `orchestrator.py`
> **원칙**: 기존 `_classify_6phase()`, `scan_oversold_candidates()` 등을 수정하지 않고, 독립적인 메서드로 추가

---

## 1. 아키텍처 개요

```
기존 흐름 (변경 없음):
  Data Collector → Market Analyzer._classify_6phase() → 국면 판정
                   Market Analyzer.analyze_leading_indicators() → 선행지표

추가 흐름 (새로 추가):
  Market Analyzer.check_trend_filter(symbol, price_data)
      → trend_score (0.0~1.0) + 상세 분석 결과
      → weight_adjuster._decide_targets()에서 trend_score < 0.5 종목 제외
```

### 기존 코드와의 관계

| 기존 기능 | 역할 | 변경 여부 |
|-----------|------|-----------|
| `_classify_6phase()` | 시장 전체 국면 판단 | 변경 없음 |
| `scan_oversold_candidates()` | RSI 기반 과매도 종목 스캔 | 변경 없음 |
| `analyze_leading_indicators()` | US→KR 선행지표 13개 | 변경 없음 |
| `_calc_rsi()` | RSI 계산 (재사용) | 변경 없음, 내부에서 호출 |
| **`check_trend_filter()`** | **종목별 추세 점수 계산** | **신규 추가** |
| **`_calc_adx()`** | **ADX 계산 유틸리티** | **신규 추가** |
| **`_calc_macd()`** | **MACD 계산 유틸리티** | **신규 추가** |
| **`check_trend_batch()`** | **여러 종목 일괄 필터링** | **신규 추가** |

---

## 2. 신규 메서드: `check_trend_filter()`

### 메서드 시그니처

```python
def check_trend_filter(
    self,
    symbol: str,
    price_data: dict,
    market_phase: str = None  # 현재 6국면 중 하나 (선택적)
) -> dict:
    """
    개별 종목의 추세 상태를 종합 점수로 평가한다.

    Parameters:
        symbol: 종목 코드 (예: "005930")
        price_data: 아래 형식의 가격 데이터 딕셔너리
            {
                "closes": list[float],     # 최근 200일 종가 (오래된→최신)
                "highs": list[float],      # 최근 200일 고가
                "lows": list[float],       # 최근 200일 저가
                "volumes": list[float],    # 최근 200일 거래량
            }
        market_phase: 현재 시장 국면 (6국면 분류 결과)
            - 전달 시: 국면에 따라 통과 기준을 동적으로 조정
            - 미전달 시: 기본 기준 적용

    Returns:
        {
            "symbol": str,
            "trend": str,           # "STRONG_UP" | "MODERATE_UP" | "WEAK" | "DOWN"
            "trend_score": float,   # 0.0 ~ 1.0
            "pass": bool,           # True면 매매 대상, False면 제외
            "details": {
                "ma_alignment": {...},
                "rsi": {...},
                "adx": {...},
                "macd": {...},
                "volume": {...}
            },
            "pass_threshold": float,  # 적용된 통과 기준값
            "reason": str             # 사람이 읽을 수 있는 판정 근거
        }
    """
```

### 핵심 로직

```python
def check_trend_filter(self, symbol: str, price_data: dict, market_phase: str = None) -> dict:
    closes = price_data["closes"]
    highs = price_data["highs"]
    lows = price_data["lows"]
    volumes = price_data["volumes"]

    current_price = closes[-1]

    # ===== 지표 계산 =====

    # 1. 이동평균 계산
    ma_20 = sum(closes[-20:]) / 20
    ma_50 = sum(closes[-50:]) / 50
    ma_200 = sum(closes[-200:]) / 200 if len(closes) >= 200 else sum(closes) / len(closes)

    # 2. RSI (기존 _calc_rsi() 재사용)
    rsi_14 = self._calc_rsi(closes, period=14)

    # 3. ADX (신규 유틸리티 메서드)
    adx_14 = self._calc_adx(highs, lows, closes, period=14)

    # 4. MACD (신규 유틸리티 메서드)
    macd_result = self._calc_macd(closes)  # histogram, signal, macd_line

    # 5. 거래량 비율
    vol_avg_20 = sum(volumes[-20:]) / 20
    volume_ratio = volumes[-1] / vol_avg_20 if vol_avg_20 > 0 else 1.0

    # ===== 점수 계산 (총 9점 만점) =====

    score = 0
    max_score = 9
    details = {}

    # --- 항목 1: 이동평균 배열 (3점 만점, 가장 중요) ---
    ma_score = 0
    if current_price > ma_20 > ma_50:
        ma_score = 3  # 완전 정배열
        ma_status = "정배열 (가격 > 20MA > 50MA)"
    elif current_price > ma_50 > ma_200:
        ma_score = 2  # 중기 정배열
        ma_status = "중기 정배열 (가격 > 50MA > 200MA)"
    elif current_price > ma_50:
        ma_score = 1.5  # 50MA 위
        ma_status = "50MA 위"
    elif current_price > ma_200:
        ma_score = 1  # 200MA 위
        ma_status = "200MA 위 (약한 상승)"
    else:
        ma_score = 0  # 모든 MA 아래
        ma_status = "주요 MA 하회 (하락추세)"

    score += ma_score
    details["ma_alignment"] = {
        "score": ma_score,
        "max": 3,
        "status": ma_status,
        "values": {
            "price": round(current_price, 0),
            "ma_20": round(ma_20, 0),
            "ma_50": round(ma_50, 0),
            "ma_200": round(ma_200, 0)
        }
    }

    # --- 항목 2: RSI 위치 (2점 만점) ---
    rsi_score = 0
    if 40 <= rsi_14 <= 65:
        rsi_score = 2  # 건강한 상승 범위
        rsi_status = f"건강한 상승 범위 ({rsi_14:.1f})"
    elif 30 <= rsi_14 < 40:
        rsi_score = 1.5  # 반등 가능 영역
        rsi_status = f"반등 가능 영역 ({rsi_14:.1f})"
    elif 65 < rsi_14 <= 70:
        rsi_score = 1  # 경계 범위
        rsi_status = f"과매수 경계 ({rsi_14:.1f})"
    elif rsi_14 < 30:
        rsi_score = 0.5  # 극심한 과매도 (반등 가능성)
        rsi_status = f"극심한 과매도 ({rsi_14:.1f})"
    else:
        rsi_score = 0  # RSI > 70 (과매수)
        rsi_status = f"과매수 ({rsi_14:.1f})"

    score += rsi_score
    details["rsi"] = {
        "score": rsi_score,
        "max": 2,
        "value": round(rsi_14, 1),
        "status": rsi_status
    }

    # --- 항목 3: ADX 추세 강도 (2점 만점) ---
    adx_score = 0
    if adx_14 >= 25:
        adx_score = 2  # 강한 추세
        adx_status = f"강한 추세 ({adx_14:.1f})"
    elif adx_14 >= 20:
        adx_score = 1  # 보통 추세
        adx_status = f"보통 추세 ({adx_14:.1f})"
    elif adx_14 >= 15:
        adx_score = 0.5  # 약한 추세
        adx_status = f"약한 추세 ({adx_14:.1f})"
    else:
        adx_score = 0  # 추세 없음 (횡보)
        adx_status = f"추세 없음/횡보 ({adx_14:.1f})"

    score += adx_score
    details["adx"] = {
        "score": adx_score,
        "max": 2,
        "value": round(adx_14, 1),
        "status": adx_status
    }

    # --- 항목 4: MACD 방향 (1점 만점) ---
    macd_score = 0
    histogram = macd_result["histogram"]
    histogram_prev = macd_result["histogram_prev"]

    if histogram > 0 and histogram > histogram_prev:
        macd_score = 1  # 양수이면서 확대 중
        macd_status = "상승 모멘텀 강화"
    elif histogram > 0:
        macd_score = 0.7  # 양수이지만 축소 중
        macd_status = "상승 모멘텀 (둔화)"
    elif histogram < 0 and histogram > histogram_prev:
        macd_score = 0.3  # 음수이지만 회복 중
        macd_status = "하락 모멘텀 약화 (회복 징후)"
    else:
        macd_score = 0  # 음수이면서 확대 중
        macd_status = "하락 모멘텀"

    score += macd_score
    details["macd"] = {
        "score": macd_score,
        "max": 1,
        "histogram": round(histogram, 2),
        "status": macd_status
    }

    # --- 항목 5: 거래량 확인 (1점 만점) ---
    vol_score = 0
    if volume_ratio >= 1.2:
        vol_score = 1  # 평균 이상 거래량
        vol_status = f"활발 ({volume_ratio:.1f}배)"
    elif volume_ratio >= 0.8:
        vol_score = 0.7  # 정상 거래량
        vol_status = f"정상 ({volume_ratio:.1f}배)"
    elif volume_ratio >= 0.5:
        vol_score = 0.3  # 다소 부족
        vol_status = f"부족 ({volume_ratio:.1f}배)"
    else:
        vol_score = 0  # 매우 부족 (유동성 위험)
        vol_status = f"매우 부족 ({volume_ratio:.1f}배)"

    score += vol_score
    details["volume"] = {
        "score": vol_score,
        "max": 1,
        "ratio": round(volume_ratio, 2),
        "status": vol_status
    }

    # ===== 최종 판정 =====

    trend_score = round(score / max_score, 3)  # 0.0 ~ 1.0 정규화

    # 국면별 통과 기준 조정
    pass_threshold = self._get_trend_threshold(market_phase)

    if trend_score >= 0.7:
        trend = "STRONG_UP"
    elif trend_score >= pass_threshold:
        trend = "MODERATE_UP"
    elif trend_score >= 0.3:
        trend = "WEAK"
    else:
        trend = "DOWN"

    passed = trend_score >= pass_threshold

    # 판정 근거 생성
    top_factors = sorted(
        [
            (details["ma_alignment"]["score"] / 3, "MA배열"),
            (details["rsi"]["score"] / 2, "RSI"),
            (details["adx"]["score"] / 2, "ADX"),
            (details["macd"]["score"] / 1, "MACD"),
            (details["volume"]["score"] / 1, "거래량"),
        ],
        key=lambda x: x[0],
        reverse=True
    )
    strong = [f[1] for f in top_factors if f[0] >= 0.7]
    weak = [f[1] for f in top_factors if f[0] < 0.3]

    reason_parts = []
    if strong:
        reason_parts.append(f"강점: {', '.join(strong)}")
    if weak:
        reason_parts.append(f"약점: {', '.join(weak)}")
    reason = f"trend_score={trend_score:.2f} ({trend}). {'. '.join(reason_parts)}"

    return {
        "symbol": symbol,
        "trend": trend,
        "trend_score": trend_score,
        "pass": passed,
        "details": details,
        "pass_threshold": pass_threshold,
        "reason": reason
    }
```

---

## 3. 국면별 통과 기준 동적 조정

```python
def _get_trend_threshold(self, market_phase: str = None) -> float:
    """
    시장 국면에 따라 추세 필터 통과 기준을 조정한다.

    - 대상승장: 기준을 낮춰서 더 많은 종목 허용 (모멘텀 활용)
    - 대폭락장: 기준을 높여서 정말 강한 추세만 통과
    - 기본값: 0.5 (9점 만점에 4.5점 이상)
    """
    thresholds = {
        "대상승장": 0.40,       # 넓은 문: 대세 상승 시 기회 포착
        "상승장": 0.45,         # 약간 넓은 문
        "일반장": 0.50,         # 기본값
        "변동폭큰장": 0.55,    # 좁은 문: 확실한 추세만
        "하락장": 0.60,         # 매우 좁은 문
        "대폭락장": 0.70,       # 거의 닫힌 문: 극소수만 통과
    }

    if market_phase and market_phase in thresholds:
        return thresholds[market_phase]

    return 0.50  # 기본값
```

---

## 4. 신규 유틸리티 메서드

### `_calc_adx()` — ADX(Average Directional Index) 계산

```python
def _calc_adx(self, highs: list, lows: list, closes: list, period: int = 14) -> float:
    """
    ADX를 계산한다. 추세의 강도를 측정 (방향은 측정하지 않음).
    - ADX >= 25: 강한 추세
    - ADX >= 20: 보통 추세
    - ADX < 15: 추세 없음 (횡보)

    Parameters:
        highs: 고가 리스트 (최소 period * 2 + 1개)
        lows: 저가 리스트
        closes: 종가 리스트
        period: 계산 기간 (기본 14)

    Returns:
        float: ADX 값 (0~100)
    """
    if len(highs) < period * 2 + 1:
        return 15.0  # 데이터 부족 시 중립값 반환

    # True Range 계산
    tr_list = []
    plus_dm_list = []
    minus_dm_list = []

    for i in range(1, len(highs)):
        high = highs[i]
        low = lows[i]
        prev_high = highs[i - 1]
        prev_low = lows[i - 1]
        prev_close = closes[i - 1]

        # True Range
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_list.append(tr)

        # Directional Movement
        up_move = high - prev_high
        down_move = prev_low - low

        plus_dm = up_move if (up_move > down_move and up_move > 0) else 0
        minus_dm = down_move if (down_move > up_move and down_move > 0) else 0

        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)

    # Wilder's Smoothing (첫 번째 값은 단순 합, 이후는 smoothing)
    def wilder_smooth(data, period):
        smoothed = [sum(data[:period])]
        for i in range(period, len(data)):
            smoothed.append(smoothed[-1] - smoothed[-1] / period + data[i])
        return smoothed

    atr = wilder_smooth(tr_list, period)
    smooth_plus_dm = wilder_smooth(plus_dm_list, period)
    smooth_minus_dm = wilder_smooth(minus_dm_list, period)

    # +DI, -DI 계산
    dx_list = []
    min_len = min(len(atr), len(smooth_plus_dm), len(smooth_minus_dm))
    for i in range(min_len):
        if atr[i] == 0:
            continue
        plus_di = 100 * smooth_plus_dm[i] / atr[i]
        minus_di = 100 * smooth_minus_dm[i] / atr[i]

        di_sum = plus_di + minus_di
        if di_sum == 0:
            continue
        dx = 100 * abs(plus_di - minus_di) / di_sum
        dx_list.append(dx)

    if len(dx_list) < period:
        return 15.0  # 데이터 부족

    # ADX = DX의 이동평균
    adx_values = wilder_smooth(dx_list, period)

    return adx_values[-1] if adx_values else 15.0
```

### `_calc_macd()` — MACD 계산

```python
def _calc_macd(
    self,
    closes: list,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9
) -> dict:
    """
    MACD(Moving Average Convergence Divergence)를 계산한다.

    Returns:
        {
            "macd_line": float,       # MACD 선 (fast EMA - slow EMA)
            "signal_line": float,     # 시그널 선 (MACD의 EMA)
            "histogram": float,       # 히스토그램 (MACD - Signal)
            "histogram_prev": float,  # 전일 히스토그램 (방향 판단용)
        }
    """
    if len(closes) < slow_period + signal_period:
        return {
            "macd_line": 0.0,
            "signal_line": 0.0,
            "histogram": 0.0,
            "histogram_prev": 0.0
        }

    def ema(data, period):
        """지수이동평균 계산"""
        multiplier = 2 / (period + 1)
        result = [sum(data[:period]) / period]  # 첫 값은 SMA
        for i in range(period, len(data)):
            result.append((data[i] - result[-1]) * multiplier + result[-1])
        return result

    fast_ema = ema(closes, fast_period)
    slow_ema = ema(closes, slow_period)

    # MACD Line = Fast EMA - Slow EMA
    # fast_ema와 slow_ema의 길이가 다르므로 정렬
    offset = len(fast_ema) - len(slow_ema)
    macd_line_values = [
        fast_ema[offset + i] - slow_ema[i]
        for i in range(len(slow_ema))
    ]

    # Signal Line = MACD의 EMA
    if len(macd_line_values) < signal_period:
        return {
            "macd_line": macd_line_values[-1] if macd_line_values else 0.0,
            "signal_line": 0.0,
            "histogram": 0.0,
            "histogram_prev": 0.0
        }

    signal_values = ema(macd_line_values, signal_period)

    # Histogram = MACD - Signal
    sig_offset = len(macd_line_values) - len(signal_values)
    histograms = [
        macd_line_values[sig_offset + i] - signal_values[i]
        for i in range(len(signal_values))
    ]

    return {
        "macd_line": round(macd_line_values[-1], 4),
        "signal_line": round(signal_values[-1], 4),
        "histogram": round(histograms[-1], 4) if histograms else 0.0,
        "histogram_prev": round(histograms[-2], 4) if len(histograms) >= 2 else 0.0
    }
```

---

## 5. 배치 처리: `check_trend_batch()`

```python
def check_trend_batch(
    self,
    candidates: list[dict],
    market_phase: str = None
) -> dict:
    """
    여러 종목을 일괄 평가하고, 통과/실패로 분류한다.

    Parameters:
        candidates: 종목 리스트
            [
                {"symbol": "005930", "price_data": {...}},
                {"symbol": "000660", "price_data": {...}},
                ...
            ]
        market_phase: 현재 시장 국면

    Returns:
        {
            "passed": [
                {"symbol": "005930", "trend_score": 0.72, "trend": "STRONG_UP", ...},
                ...
            ],
            "filtered_out": [
                {"symbol": "003490", "trend_score": 0.31, "trend": "WEAK", ...},
                ...
            ],
            "summary": {
                "total": 15,
                "passed": 8,
                "filtered": 7,
                "pass_rate": 0.53,
                "avg_score_passed": 0.68,
                "avg_score_filtered": 0.29,
                "phase": "일반장",
                "threshold": 0.50
            }
        }
    """
    results_passed = []
    results_filtered = []

    for candidate in candidates:
        result = self.check_trend_filter(
            symbol=candidate["symbol"],
            price_data=candidate["price_data"],
            market_phase=market_phase
        )
        if result["pass"]:
            results_passed.append(result)
        else:
            results_filtered.append(result)

    # 통과한 종목을 점수 순으로 정렬 (높은 점수가 우선)
    results_passed.sort(key=lambda x: x["trend_score"], reverse=True)

    total = len(candidates)
    passed_count = len(results_passed)

    return {
        "passed": results_passed,
        "filtered_out": results_filtered,
        "summary": {
            "total": total,
            "passed": passed_count,
            "filtered": total - passed_count,
            "pass_rate": round(passed_count / total, 2) if total > 0 else 0,
            "avg_score_passed": round(
                sum(r["trend_score"] for r in results_passed) / passed_count, 3
            ) if passed_count > 0 else 0,
            "avg_score_filtered": round(
                sum(r["trend_score"] for r in results_filtered) / (total - passed_count), 3
            ) if total - passed_count > 0 else 0,
            "phase": market_phase or "기본",
            "threshold": self._get_trend_threshold(market_phase)
        }
    }
```

---

## 6. weight_adjuster.py 연동

### 수정 위치: `_decide_targets()` 메서드

```python
# weight_adjuster.py 내 _decide_targets() 또는 이에 해당하는 메서드에서
# 기존 종목 선별 로직 이후, 실제 비중 할당 전에 추세 필터 적용

# === 추가할 코드 (기존 로직 사이에 삽입) ===

# 기존: candidates = [...종목 리스트...]  (이미 있는 부분)

# 추세 필터 적용 (신규 추가)
if hasattr(self.market_analyzer, 'check_trend_batch'):
    trend_results = self.market_analyzer.check_trend_batch(
        candidates=candidate_data_list,  # 종목별 price_data 포함
        market_phase=current_phase       # 현재 6국면 분류 결과
    )

    # 통과한 종목만 남기기
    filtered_candidates = trend_results["passed"]

    # 로깅
    summary = trend_results["summary"]
    self.logger.info(
        f"[추세 필터] {summary['total']}개 → {summary['passed']}개 통과 "
        f"(제거 {summary['filtered']}개, 통과율 {summary['pass_rate']:.0%}, "
        f"기준 {summary['threshold']}, 국면 {summary['phase']})"
    )

    # 제거된 종목 상세 로깅 (디버깅용)
    for filtered in trend_results["filtered_out"]:
        self.logger.debug(
            f"  [제거] {filtered['symbol']}: {filtered['reason']}"
        )

    # 이후 비중 할당은 filtered_candidates로 진행
    # candidates = filtered_candidates  # 기존 변수명에 맞게 조정

# 기존: 비중 할당 로직 계속... (이미 있는 부분)
```

### trend_score를 비중 계산에도 활용 (선택적 강화)

```python
# weight_adjuster.py의 비중 계산 로직에서 trend_score를 가중치로 사용
# 기존 테마부스트(1.3×), 섹터감쇠, RS필터와 동일한 레벨로 추가

def _apply_trend_boost(self, base_weight: float, trend_score: float) -> float:
    """
    추세 점수에 따라 비중을 미세 조정한다.

    - trend_score >= 0.8: 비중 1.2× (강한 추세 = 확신 있는 배팅)
    - trend_score >= 0.6: 비중 1.0× (유지)
    - trend_score >= 0.5: 비중 0.8× (겨우 통과 = 소극적 배팅)
    """
    if trend_score >= 0.8:
        return base_weight * 1.2
    elif trend_score >= 0.6:
        return base_weight * 1.0
    else:
        return base_weight * 0.8
```

---

## 7. price_data 구성 방법

### Data Collector 또는 Preprocessor에서 준비

```python
# data_collector 또는 preprocessor에서 이미 수집하는 가격 데이터를
# check_trend_filter()가 요구하는 형식으로 변환

def prepare_trend_data(self, symbol: str, raw_prices: list) -> dict:
    """
    raw_prices: KIS API 등에서 받은 일봉 데이터
    각 항목이 {"date": ..., "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}
    형식이라고 가정

    최소 50일, 권장 200일 데이터 필요
    """
    # 오래된 순서 → 최신 순서로 정렬
    sorted_prices = sorted(raw_prices, key=lambda x: x["date"])

    return {
        "closes": [p["close"] for p in sorted_prices],
        "highs": [p["high"] for p in sorted_prices],
        "lows": [p["low"] for p in sorted_prices],
        "volumes": [p["volume"] for p in sorted_prices],
    }
```

---

## 8. orchestrator.py 연동

### 파이프라인에서의 호출 위치

```
현재 흐름: DC → MA(국면판정) → WA(비중결정) → SR(전략) → EX(실행)

추세 필터 적용 후 흐름:
DC → MA(국면판정)
       ↓
     MA(추세필터) ← 여기서 check_trend_batch() 호출
       ↓
     WA(비중결정) ← trend_score 기반 종목 필터링 + 비중 조정
       ↓
     SR(전략) → EX(실행)
```

### orchestrator.py 수정 사항

```python
# orchestrator.py의 run_once() 내 Step 2 (MA 실행 후) 에서:

# 기존: market_analysis = self.market_analyzer.detect_phase(...)

# 추가: 추세 필터 실행
if market_analysis.get("trading_allowed", True):  # 매매 허용 시에만
    # 매매 후보 종목에 대해 추세 필터 실행
    trend_batch_result = self.market_analyzer.check_trend_batch(
        candidates=candidate_list,
        market_phase=market_analysis["phase"]
    )

    # 추세 필터 결과를 WA에 전달할 payload에 포함
    ma_payload["trend_filter_results"] = trend_batch_result
    ma_payload["trend_passed_symbols"] = [
        r["symbol"] for r in trend_batch_result["passed"]
    ]
```

---

## 9. 테스트 시나리오

### 정상 작동 확인

```python
# 테스트 1: 삼성전자 (정배열 + 강한 추세)
# 예상: trend_score >= 0.7, trend = "STRONG_UP", pass = True

# 테스트 2: 횡보 중인 종목 (MA 뒤엉킴, ADX < 15)
# 예상: trend_score < 0.4, trend = "WEAK", pass = False

# 테스트 3: 급등 후 과매수 (RSI > 75, MA 위이지만 과열)
# 예상: trend_score ~ 0.5 전후, RSI 감점으로 간신히 통과 또는 탈락

# 테스트 4: 대폭락장에서의 필터링
# 예상: threshold = 0.70, 대부분의 종목 필터링됨
```

### 기존 기능 영향 없음 확인

```python
# 확인 1: _classify_6phase()가 동일한 결과를 반환하는지
# 확인 2: scan_oversold_candidates()가 동일하게 작동하는지
# 확인 3: analyze_leading_indicators()에 변경 없는지
# 확인 4: 추세 필터를 비활성화하면 기존과 동일한 매매 결과가 나오는지
```

---

## 10. Claude Code 실행 프롬프트

```
이 명세서(filter2_trend_spec.md)를 읽고 다음을 실행해줘:

1. market_analyzer.py에 다음 메서드 추가:
   - check_trend_filter()
   - check_trend_batch()
   - _calc_adx()
   - _calc_macd()
   - _get_trend_threshold()

2. 기존 _calc_rsi()가 check_trend_filter() 내부에서 호출 가능한지 확인.
   만약 접근이 안 되면 호환되는 방식으로 조정.

3. weight_adjuster.py의 _decide_targets() (또는 해당하는 메서드)에서
   check_trend_batch() 결과를 받아 trend_score < threshold 종목을 제외하는
   로직 추가.

4. 기존 _classify_6phase(), scan_oversold_candidates(),
   analyze_leading_indicators()는 절대 수정하지 말 것.

5. 추가한 코드가 기존 파이프라인(DC→MA→WA→SR→EX)에서
   정상 작동하는지 확인.
```
