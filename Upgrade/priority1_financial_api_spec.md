# 우선순위 1: KIS 투자지표 API 연동 구현 명세

> **목표**: PER/PBR/EPS/ROE를 수집하여 가격 예측 정확도 향상 + Filter 3 강화
> **비용**: 0원 (기존 KIS API 인증으로 호출 가능)
> **원칙**: 기존 코드 최소 수정, 신규 메서드/테이블 추가 방식

---

## 1. 왜 이게 가격 예측 정확도를 높이나?

### 현재 예측의 한계

```
현재 _forecast_single() 구조:
  예측가 = 모멘텀(60%) + 평균회귀(15%) + 미국연동(25%)    ← 1주 예측
  예측가 = 모멘텀(25%) + 평균회귀(45%) + 미국연동(30%)    ← 1개월 예측

문제: 모멘텀과 평균회귀 모두 "과거 가격"만 봄.
      "이 종목이 지금 싼지 비싼지" 기준이 없음.

예시:
  삼성전자가 PBR 0.8 (자산가치 대비 저평가) → 하방 리스크 작음
  한미반도체가 PER 80 (이익 대비 고평가) → 상방 제한적
  → 이런 정보 없이 둘 다 같은 방식으로 예측
```

### 펀더멘탈이 추가되면

```
개선된 예측 구조:
  예측가 = 모멘텀(45%) + 평균회귀(15%) + 미국연동(20%) + 적정가괴리(20%)

적정가괴리 (Fundamental Anchor):
  - BPS × 업종평균PBR = 적정가 추정
  - 현재가가 적정가 대비 -30% → "저평가, 상승 여력 있음" → 예측 상향
  - 현재가가 적정가 대비 +50% → "고평가, 상승 제한적" → 예측 하향
```

---

## 2. KIS API 호출 추가 (data_collector.py)

### 2-1. 투자지표 API (`FHKST66430300`)

```python
# data_collector.py에 추가할 메서드

async def fetch_financial_indicators(self, symbol: str) -> dict:
    """
    KIS API로 종목의 투자지표(PER/PBR/EPS/BPS/배당수익률)를 조회한다.

    Parameters:
        symbol: 종목 코드 (예: "005930")

    Returns:
        {
            "symbol": "005930",
            "per": 12.5,           # PER (주가수익비율)
            "pbr": 1.1,            # PBR (주가순자산비율)
            "eps": 5820,           # EPS (주당순이익, 원)
            "bps": 65400,          # BPS (주당순자산, 원)
            "dividend_yield": 2.1, # 배당수익률 (%)
            "market_cap": 3500000, # 시가총액 (억원)
            "fetched_at": "2026-04-02T09:00:00"
        }
    """
    # 기존 KIS API 호출 패턴 그대로 사용
    # (data_collector.py의 _call_kis_api 또는 유사 메서드 참조)

    path = "/uapi/domestic-stock/v1/quotations/inquire-invest-opinion"
    # 또는 실제 경로: /uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice
    # KIS 개발자 문서에서 FHKST66430300 경로 확인 필요

    params = {
        "FID_COND_MRKT_DIV_CODE": "J",  # 주식
        "FID_INPUT_ISCD": symbol,
    }

    headers = {
        "tr_id": "FHKST66430300",  # 투자지표 TR ID
        # 기존 인증 헤더는 _call_kis_api에서 처리
    }

    try:
        response = await self._call_kis_api(path, params, headers)
        output = response.get("output", {})

        return {
            "symbol": symbol,
            "per": self._safe_float(output.get("per", "0")),
            "pbr": self._safe_float(output.get("pbr", "0")),
            "eps": self._safe_float(output.get("eps", "0")),
            "bps": self._safe_float(output.get("bps", "0")),
            "dividend_yield": self._safe_float(output.get("ssts_divi_rate", "0")),
            "market_cap": self._safe_float(output.get("hts_avls", "0")),
            "fetched_at": datetime.now().isoformat()
        }
    except Exception as e:
        self.logger.error(f"[재무지표] {symbol} 조회 실패: {e}")
        return None


def _safe_float(self, value: str, default: float = 0.0) -> float:
    """문자열을 안전하게 float로 변환. KIS API는 숫자를 문자열로 반환함."""
    try:
        result = float(value.replace(",", ""))
        return result if result != 0 else default
    except (ValueError, AttributeError):
        return default
```

### 2-2. 재무비율 API (`CTPF1002R`) — 선택적 추가

```python
async def fetch_financial_ratios(self, symbol: str) -> dict:
    """
    KIS API로 종목의 재무비율(ROE/ROA/부채비율/영업이익률)을 조회한다.
    투자지표 API보다 상세한 재무 건전성 데이터.

    Returns:
        {
            "symbol": "005930",
            "roe": 15.2,             # ROE (자기자본이익률, %)
            "roa": 8.1,              # ROA (총자산이익률, %)
            "debt_ratio": 35.2,      # 부채비율 (%)
            "operating_margin": 12.5, # 영업이익률 (%)
            "fetched_at": "2026-04-02T09:00:00"
        }
    """
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": symbol,
    }

    headers = {
        "tr_id": "CTPF1002R",
    }

    try:
        response = await self._call_kis_api(path, params, headers)
        output = response.get("output", {})

        return {
            "symbol": symbol,
            "roe": self._safe_float(output.get("roe_val", "0")),
            "roa": self._safe_float(output.get("roa_val", "0")),
            "debt_ratio": self._safe_float(output.get("lblt_rate", "0")),
            "operating_margin": self._safe_float(output.get("bsop_prfi_rate", "0")),
            "fetched_at": datetime.now().isoformat()
        }
    except Exception as e:
        self.logger.error(f"[재무비율] {symbol} 조회 실패: {e}")
        return None
```

### 2-3. 배치 조회

```python
async def fetch_financial_data_batch(self, symbols: list) -> dict:
    """
    여러 종목의 재무 데이터를 일괄 조회.
    KIS API 속도제한(초당 20건) 고려하여 간격 두고 호출.

    Returns:
        {
            "005930": {"per": 12.5, "pbr": 1.1, ...},
            "000660": {"per": 8.3, "pbr": 1.8, ...},
            ...
        }
    """
    results = {}
    for i, symbol in enumerate(symbols):
        # KIS API 속도제한 대응 (초당 20건 제한)
        if i > 0 and i % 18 == 0:
            await asyncio.sleep(1.1)

        indicator = await self.fetch_financial_indicators(symbol)
        if indicator:
            # 재무비율도 함께 조회 (선택적)
            ratios = await self.fetch_financial_ratios(symbol)
            if ratios:
                indicator.update(ratios)
            results[symbol] = indicator

    self.logger.info(
        f"[재무데이터] {len(results)}/{len(symbols)}개 종목 조회 완료"
    )
    return results
```

---

## 3. DB 테이블 추가 (Supabase)

### 신규 테이블: `financial_indicators`

```sql
CREATE TABLE financial_indicators (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- 투자지표 (FHKST66430300)
    per FLOAT,               -- PER (주가수익비율)
    pbr FLOAT,               -- PBR (주가순자산비율)
    eps FLOAT,               -- EPS (주당순이익, 원)
    bps FLOAT,               -- BPS (주당순자산, 원)
    dividend_yield FLOAT,    -- 배당수익률 (%)
    market_cap FLOAT,        -- 시가총액 (억원)

    -- 재무비율 (CTPF1002R) - 선택적
    roe FLOAT,               -- ROE (%)
    roa FLOAT,               -- ROA (%)
    debt_ratio FLOAT,        -- 부채비율 (%)
    operating_margin FLOAT,  -- 영업이익률 (%)

    -- 계산 필드 (적정가 추정용)
    fair_value_pbr FLOAT,    -- PBR 기반 적정가 = BPS × 업종평균PBR
    price_to_fair FLOAT,     -- 현재가 / 적정가 비율

    UNIQUE(symbol, fetched_at::date)  -- 하루 1건만 저장
);

-- 인덱스
CREATE INDEX idx_fi_symbol ON financial_indicators(symbol);
CREATE INDEX idx_fi_fetched ON financial_indicators(fetched_at DESC);
```

### db.py에 CRUD 추가

```python
# database/db.py에 추가

async def upsert_financial_indicators(self, data: dict):
    """재무 지표 저장 (하루 1건 upsert)"""
    await self.supabase.table("financial_indicators").upsert(
        data,
        on_conflict="symbol,fetched_at::date"
    ).execute()

async def get_financial_indicators(self, symbol: str) -> dict:
    """최신 재무 지표 조회"""
    result = await self.supabase.table("financial_indicators") \
        .select("*") \
        .eq("symbol", symbol) \
        .order("fetched_at", desc=True) \
        .limit(1) \
        .execute()
    return result.data[0] if result.data else None

async def get_financial_indicators_batch(self, symbols: list) -> dict:
    """여러 종목 최신 재무 지표 일괄 조회"""
    result = await self.supabase.rpc(
        "get_latest_financial_indicators",
        {"p_symbols": symbols}
    ).execute()
    return {row["symbol"]: row for row in result.data} if result.data else {}
```

---

## 4. 가격 예측 개선 (market_analyzer.py)

### `_forecast_single()` 수정

기존 코드의 `_forecast_single()` 메서드에 **4번째 예측 요소** 추가.

```python
# market_analyzer.py의 _forecast_single() 내부
# 기존 3개 요소 이후에 추가

def _forecast_single(self, symbol, closes, horizon_days, ...):
    # === 기존 코드 (유지) ===
    momentum_pred = ...      # 모멘텀 예측
    mean_rev_pred = ...      # 평균회귀 예측
    us_corr_pred = ...       # 미국연동 예측

    # === 신규 추가: 적정가 괴리 예측 ===
    fundamental_pred = self._calc_fundamental_anchor(
        symbol, current_price, horizon_days
    )

    # === 가중치 조합 수정 ===
    if horizon_days <= 5:
        # 단기: 모멘텀 중심, 펀더멘탈 약하게
        weights = {
            "momentum": 0.45,      # 기존 0.60 → 0.45
            "mean_reversion": 0.15, # 유지
            "us_correlation": 0.20, # 기존 0.25 → 0.20
            "fundamental": 0.20,   # 신규
        }
    else:
        # 중장기: 펀더멘탈 중요도 상승
        weights = {
            "momentum": 0.20,      # 기존 0.25 → 0.20
            "mean_reversion": 0.30, # 기존 0.45 → 0.30
            "us_correlation": 0.20, # 기존 0.30 → 0.20
            "fundamental": 0.30,   # 신규 (장기일수록 중요)
        }

    # 종합 예측
    if fundamental_pred is not None:
        forecast = (
            momentum_pred * weights["momentum"]
            + mean_rev_pred * weights["mean_reversion"]
            + us_corr_pred * weights["us_correlation"]
            + fundamental_pred * weights["fundamental"]
        )
    else:
        # 재무 데이터 없으면 기존 방식으로 fallback
        forecast = (
            momentum_pred * 0.60  # 기존 가중치 유지
            + mean_rev_pred * 0.15
            + us_corr_pred * 0.25
        ) if horizon_days <= 5 else (
            momentum_pred * 0.25
            + mean_rev_pred * 0.45
            + us_corr_pred * 0.30
        )

    return forecast
```

### 적정가 괴리 계산 메서드

```python
def _calc_fundamental_anchor(
    self, symbol: str, current_price: float, horizon_days: int
) -> float:
    """
    PBR/PER 기반으로 적정가를 추정하고,
    현재가와의 괴리를 예측 수익률로 변환한다.

    원리:
    - BPS × 업종평균PBR = 적정가 (PBR 기반)
    - 현재가 < 적정가 → 저평가 → 가격이 적정가 방향으로 회귀할 가능성
    - 현재가 > 적정가 → 고평가 → 상승 제한적

    Returns:
        float: 예상 수익률 (%) 또는 None (데이터 없으면)
    """
    # DB에서 재무 데이터 조회
    fin_data = self._get_cached_financial_data(symbol)
    if not fin_data or not fin_data.get("bps") or not fin_data.get("pbr"):
        return None

    bps = fin_data["bps"]
    current_pbr = fin_data["pbr"]
    per = fin_data.get("per", 0)

    # 업종 평균 PBR (config 또는 동적 계산)
    sector_avg_pbr = self._get_sector_avg_pbr(symbol)

    # 적정가 추정 (PBR 기반)
    fair_value = bps * sector_avg_pbr

    if fair_value <= 0 or current_price <= 0:
        return None

    # 괴리율 계산
    discount_pct = (fair_value - current_price) / current_price * 100
    # discount_pct > 0 → 저평가 (상승 여력)
    # discount_pct < 0 → 고평가 (하락 가능)

    # 회귀 속도 조정 (장기일수록 적정가에 가까이 감)
    if horizon_days <= 5:
        reversion_rate = 0.05  # 단기: 괴리의 5%만 회귀
    elif horizon_days <= 20:
        reversion_rate = 0.15  # 중기: 15% 회귀
    else:
        reversion_rate = 0.30  # 장기: 30% 회귀

    # 예측 수익률 = 괴리율 × 회귀 속도
    fundamental_return = discount_pct * reversion_rate

    # 극단값 제한 (-10% ~ +10%)
    fundamental_return = max(-10.0, min(10.0, fundamental_return))

    # PER 보정: 극단적 고PER은 추가 감점
    if per > 50:
        fundamental_return -= 1.0  # 고PER 페널티
    elif per < 8 and per > 0:
        fundamental_return += 0.5  # 저PER 보너스

    return fundamental_return


def _get_sector_avg_pbr(self, symbol: str) -> float:
    """
    종목이 속한 섹터의 평균 PBR 반환.
    초기에는 간단한 매핑, 나중에 동적 계산으로 발전.
    """
    # stock_classification.json 또는 별도 config에서 섹터 매핑
    sector_pbr = {
        "반도체": 1.5,
        "자동차": 0.7,
        "바이오": 3.0,
        "은행": 0.5,
        "방산": 1.8,
        "2차전지": 2.5,
        "IT": 2.0,
        "화학": 0.9,
        "철강": 0.6,
        "건설": 0.7,
    }

    # symbol → 섹터 매핑 (기존 stock_classification.json 활용)
    sector = self._get_stock_sector(symbol)
    return sector_pbr.get(sector, 1.2)  # 기본값 1.2


def _get_cached_financial_data(self, symbol: str) -> dict:
    """
    캐시된 재무 데이터 반환.
    매 사이클마다 DB 조회 안 하고, 하루 1회 로딩 후 메모리에 보관.
    """
    if not hasattr(self, '_fin_cache'):
        self._fin_cache = {}
        self._fin_cache_date = None

    today = datetime.now().strftime("%Y-%m-%d")
    if self._fin_cache_date != today:
        # 하루 1회 전체 로딩
        self._fin_cache = {}
        self._fin_cache_date = today

    if symbol not in self._fin_cache:
        # DB에서 개별 조회 (또는 배치 로딩)
        data = self.db.get_financial_indicators(symbol)
        self._fin_cache[symbol] = data

    return self._fin_cache.get(symbol)
```

---

## 5. Filter 3 강화 — 펀더멘탈 기반 진입 금지

### `_check_entry_blockers()`에 추가

```python
# weight_adjuster.py의 _check_entry_blockers()에 추가할 조건

# --- 차단 6: 극심한 고평가 (PER > 업종평균 × 3) ---
fin_data = self._get_financial_data(symbol)
if fin_data and fin_data.get("per"):
    per = fin_data["per"]
    sector_avg_per = self._get_sector_avg_per(symbol)
    if per > 0 and sector_avg_per > 0 and per > sector_avg_per * 3:
        blockers.append({
            "type": "OVERVALUED_PER",
            "reason": f"PER {per:.1f} > 업종평균({sector_avg_per:.1f})의 3배 (극심한 고평가)",
            "severity": "MEDIUM"
        })

# --- 차단 7: 재무 부실 (ROE < 0 또는 부채비율 > 300%) ---
if fin_data and fin_data.get("roe") is not None:
    if fin_data["roe"] < 0:
        blockers.append({
            "type": "NEGATIVE_ROE",
            "reason": f"ROE {fin_data['roe']:.1f}% (적자 기업)",
            "severity": "MEDIUM"
        })
if fin_data and fin_data.get("debt_ratio"):
    if fin_data["debt_ratio"] > 300:
        blockers.append({
            "type": "HIGH_DEBT",
            "reason": f"부채비율 {fin_data['debt_ratio']:.0f}% > 300% (재무 위험)",
            "severity": "MEDIUM"
        })
```

### 신호 강화 — 저평가 종목 부스트

```python
# check_entry_timing()의 신호 평가에 추가

# --- 신호 6: 펀더멘탈 저평가 (신규) ---
def _check_fundamental_value(self, symbol):
    """
    PBR < 업종평균 × 0.7이면 저평가 신호.
    '싼 가격에 살 수 있는 종목'을 잡는 신호.
    """
    fin_data = self._get_financial_data(symbol)
    if not fin_data or not fin_data.get("pbr"):
        return {"name": "펀더멘탈 저평가", "triggered": False, "reason": "재무 데이터 없음"}

    pbr = fin_data["pbr"]
    sector_avg_pbr = self._get_sector_avg_pbr(symbol)

    # 업종 평균의 70% 미만이면 저평가
    undervalued = 0 < pbr < sector_avg_pbr * 0.7

    # 추가 조건: ROE가 양수여야 (적자 기업의 저PBR은 함정)
    roe = fin_data.get("roe", 0)
    quality_ok = roe > 5 if roe else True  # ROE 데이터 없으면 통과

    triggered = undervalued and quality_ok

    return {
        "name": "펀더멘탈 저평가",
        "triggered": triggered,
        "weight": 1.3,  # 펀더멘탈 신호는 높은 가중치
        "details": {
            "pbr": round(pbr, 2),
            "sector_avg_pbr": round(sector_avg_pbr, 2),
            "roe": round(roe, 1) if roe else None,
            "discount": f"{(1 - pbr/sector_avg_pbr)*100:.0f}%" if sector_avg_pbr > 0 else "N/A"
        },
        "reason": (
            f"PBR {pbr:.2f} < 업종평균 {sector_avg_pbr:.2f}의 70% (저평가 {(1-pbr/sector_avg_pbr)*100:.0f}%)"
            if triggered else
            f"PBR {pbr:.2f} (적정 범위)"
        )
    }
```

---

## 6. 파이프라인 통합 — 하루 1회 재무 데이터 수집

### orchestrator.py 수정

```python
# orchestrator.py의 run_once() 또는 일일 초기화 루틴에 추가

async def _daily_init(self):
    """매일 장 시작 전 1회 실행하는 초기화 작업"""

    # 기존 초기화 로직...

    # 재무 데이터 수집 (하루 1회)
    if not self._financial_data_fetched_today():
        self.logger.info("[일일초기화] 재무 데이터 수집 시작")

        # 매매 대상 종목 풀 가져오기
        target_symbols = self._get_all_target_symbols()

        # KIS API로 일괄 조회
        fin_data = await self.data_collector.fetch_financial_data_batch(
            target_symbols
        )

        # DB 저장
        for symbol, data in fin_data.items():
            await self.db.upsert_financial_indicators(data)

        self.logger.info(
            f"[일일초기화] 재무 데이터 {len(fin_data)}개 종목 저장 완료"
        )
```

### 수집 타이밍

```
08:00 KST  일일 초기화 시작
08:10      재무 데이터 수집 (KIS API, 50종목 × 2API = ~6초)
08:20      시장 국면 판정 (기존)
08:50      정규장 시작
09:00~     30분 사이클 시작 (재무 데이터는 메모리 캐시에서 읽음)
```

---

## 7. 예측 정확도 측정 추가

### 기존 예측 vs 실제 비교

```python
# market_analyzer.py 또는 별도 모듈

async def measure_prediction_accuracy(self, days_back=30):
    """
    과거 예측과 실제 결과를 비교하여 정확도를 측정한다.
    이걸 해야 "펀더멘탈 추가 전/후 차이"를 정량적으로 확인할 수 있다.

    Returns:
        {
            "total_predictions": 150,
            "direction_accuracy": 0.62,   # 방향(상승/하락) 맞춘 비율
            "avg_error_pct": 3.2,         # 평균 오차 (%)
            "rmse": 4.1,                  # Root Mean Square Error
            "by_horizon": {
                "1week": {"accuracy": 0.65, "avg_error": 2.8},
                "1month": {"accuracy": 0.58, "avg_error": 4.5}
            },
            "by_component": {
                "momentum": {"contribution": 0.60, "accuracy": 0.61},
                "mean_reversion": {"contribution": 0.15, "accuracy": 0.55},
                "us_correlation": {"contribution": 0.25, "accuracy": 0.59},
                "fundamental": {"contribution": 0.00, "accuracy": "N/A"}
            }
        }
    """
    # 구현: exit_plans 또는 trades 테이블에서 과거 예측값과
    # 실제 결과를 비교
    # 펀더멘탈 추가 전에 한 번 측정 → 추가 후 재측정 → 비교
```

### DB 테이블: 예측 기록

```sql
-- 예측 정확도 추적용
CREATE TABLE prediction_log (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    predicted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    horizon_days INT NOT NULL,
    predicted_price FLOAT NOT NULL,
    predicted_return_pct FLOAT NOT NULL,
    components JSONB,          -- {"momentum": 2.1, "mean_rev": -0.5, ...}
    actual_price FLOAT,        -- 나중에 채움
    actual_return_pct FLOAT,   -- 나중에 채움
    filled_at TIMESTAMPTZ      -- 실제값 채운 시점
);
```

---

## 8. Claude Code 실행 프롬프트

```
이 명세서(priority1_financial_api_spec.md)를 읽고 다음을 순서대로 실행해줘:

### Phase 1: 데이터 수집 (먼저)
1. data_collector.py에 fetch_financial_indicators(),
   fetch_financial_ratios(), fetch_financial_data_batch() 추가.
   기존 KIS API 호출 패턴(_call_kis_api 등)을 그대로 따라서 구현.

2. KIS API 엔드포인트 경로와 파라미터는 한국투자증권 OpenAPI 문서에서
   FHKST66430300과 CTPF1002R을 확인하고 정확하게 적용.

3. Supabase에 financial_indicators 테이블 생성.
   db.py에 upsert/get 메서드 추가.

4. 테스트: 삼성전자(005930) 1개 종목으로 API 호출 → DB 저장 → 조회 확인.

### Phase 2: 예측 연동 (데이터 수집 확인 후)
5. market_analyzer.py에 _calc_fundamental_anchor(),
   _get_sector_avg_pbr(), _get_cached_financial_data() 추가.

6. _forecast_single()에 fundamental 요소를 4번째 예측 컴포넌트로 추가.
   기존 3개 요소의 가중치를 명세서대로 조정.
   재무 데이터 없는 종목은 기존 가중치로 fallback.

### Phase 3: Filter 3 강화 (예측 연동 확인 후)
7. weight_adjuster.py의 _check_entry_blockers()에
   고PER 차단, 적자기업 차단, 고부채 차단 조건 추가.

8. _check_fundamental_value() 신호를 check_entry_timing()에 추가.
   기존 5개 신호에 6번째로 추가 (기존 신호 수정 없음).

### Phase 4: 정확도 측정 (전체 완료 후)
9. prediction_log 테이블 생성.
   _forecast_single() 실행 시 예측 결과를 prediction_log에 저장.

10. 기존 코드 절대 수정 금지 목록:
    - _classify_6phase()
    - scan_oversold_candidates()
    - analyze_leading_indicators()
    - check_trend_filter() (Filter 2)
    - 기존 _forecast_single()의 momentum/mean_rev/us_corr 계산 로직
      (가중치만 조정, 계산 로직 자체는 유지)
```
