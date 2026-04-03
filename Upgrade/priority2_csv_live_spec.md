# 우선순위 2: 분석 CSV를 라이브 예측에 연결

> **목표**: 이미 분석해놓고 방치 중인 CSV 데이터를 라이브 코드에 연결하여 가격 예측 정확도 향상
> **비용**: 0원, API 호출 없음, 코드 수정만
> **핵심**: fallback/하드코딩 값을 실측 데이터로 교체

---

## 1. 현재 문제

```
분석은 했다 → CSV로 저장했다 → 라이브 코드에서 안 읽는다 → 하드코딩 fallback 사용

구체적 사례:

1) lead_lag_analysis.csv
   - US→KR 선행 지표별 실측 상관계수와 최적 lag일수가 있음
   - 그런데 _forecast_single()에서는 get_lead_lag_corr()가 실패하면
     fallback 0.3을 사용 → 정밀한 분석 결과 무시

2) conditional_win_rates.csv
   - 국면×지표 조합별 실제 승률(win rate)이 있음
   - 그런데 _get_trend_threshold()에서는
     하드코딩 {"대상승장": 0.40, "일반장": 0.50, ...} 사용

3) best_signals.json
   - 최적 진입 신호 조합이 분석되어 있음
   - 라이브 코드에서 전혀 참조 안 함

4) full_period_correlation.csv
   - 전체 기간 상관관계 분석 결과
   - LEADING_INDICATOR_MAP에 하드코딩으로 대체됨
```

---

## 2. 수정 대상 파일 목록

### 수정할 CSV (읽기 전용, 수정 안 함)

| CSV 파일 | 위치 | 핵심 내용 |
|----------|------|-----------|
| `lead_lag_analysis.csv` | `data/history/correlation/` | 지표별 상관계수, 최적 lag |
| `conditional_win_rates.csv` | `data/history/analysis/` | 국면×지표별 승률 |
| `best_signals.json` | `data/history/analysis/` | 최적 신호 조합 |
| `ic_by_phase.csv` | `data/history/analysis/` | 국면별 Information Coefficient |

### 수정할 코드

| 파일 | 수정 부분 | 변경 내용 |
|------|-----------|-----------|
| `market_analyzer.py` | `get_lead_lag_corr()` 또는 fallback 로직 | CSV 실측값 로딩 |
| `market_analyzer.py` | `_forecast_single()` US연동 부분 | 동적 상관계수 적용 |
| `market_analyzer.py` | `_get_trend_threshold()` | 승률 기반 동적 임계값 |
| `market_analyzer.py` | 신규: `_load_analysis_data()` | CSV 로더 + 캐시 |

---

## 3. CSV 로더 (공통 유틸리티)

```python
# market_analyzer.py에 추가

import csv
import json
from pathlib import Path

def _load_analysis_data(self):
    """
    분석 결과 CSV/JSON을 하루 1회 로딩하여 메모리에 캐시.
    파일이 없거나 파싱 실패해도 시스템 작동에 영향 없음 (기존 fallback 유지).
    """
    if hasattr(self, '_analysis_cache') and self._analysis_cache.get('loaded'):
        return  # 이미 로딩됨

    self._analysis_cache = {'loaded': True}
    base_path = Path(__file__).parent.parent  # 프로젝트 루트

    # 1. lead_lag_analysis.csv 로딩
    self._analysis_cache['lead_lag'] = self._load_lead_lag(base_path)

    # 2. conditional_win_rates.csv 로딩
    self._analysis_cache['win_rates'] = self._load_win_rates(base_path)

    # 3. best_signals.json 로딩
    self._analysis_cache['best_signals'] = self._load_best_signals(base_path)

    # 4. ic_by_phase.csv 로딩
    self._analysis_cache['ic_by_phase'] = self._load_ic_by_phase(base_path)

    loaded_count = sum(
        1 for v in self._analysis_cache.values()
        if v is not None and v != True
    )
    self.logger.info(f"[분석데이터] {loaded_count}/4개 분석 파일 로딩 완료")
```

### 3-1. lead_lag_analysis.csv 로더

```python
def _load_lead_lag(self, base_path):
    """
    lead_lag_analysis.csv 로딩.

    예상 CSV 구조 (실제 파일 확인 필요):
        indicator,correlation,best_lag,p_value,...
        SPY,0.45,1,0.001,...
        QQQ,0.52,1,0.0005,...
        VIX,-0.38,0,0.002,...
        SOXX,0.61,1,0.0001,...

    Returns:
        {
            "SPY": {"corr": 0.45, "lag": 1, "p_value": 0.001},
            "QQQ": {"corr": 0.52, "lag": 1, "p_value": 0.0005},
            ...
        }
    """
    file_path = base_path / "data" / "history" / "correlation" / "lead_lag_analysis.csv"

    if not file_path.exists():
        self.logger.warning(f"[분석데이터] lead_lag_analysis.csv 없음: {file_path}")
        return None

    try:
        result = {}
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            # 실제 컬럼명은 파일 확인 후 조정 필요
            for row in reader:
                indicator = row.get('indicator') or row.get('symbol') or row.get('name', '')
                if not indicator:
                    continue

                corr_val = self._safe_csv_float(
                    row.get('correlation') or row.get('corr') or row.get('lead_lag_corr', '0')
                )
                lag_val = int(self._safe_csv_float(
                    row.get('best_lag') or row.get('lag') or row.get('optimal_lag', '1')
                ))
                p_val = self._safe_csv_float(
                    row.get('p_value') or row.get('pvalue', '1')
                )

                result[indicator.strip()] = {
                    "corr": corr_val,
                    "lag": lag_val,
                    "p_value": p_val
                }

        self.logger.info(f"[분석데이터] lead_lag: {len(result)}개 지표 로딩")
        return result

    except Exception as e:
        self.logger.error(f"[분석데이터] lead_lag 로딩 실패: {e}")
        return None


def _safe_csv_float(self, value, default=0.0):
    """CSV 값을 안전하게 float로 변환"""
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return default
```

### 3-2. conditional_win_rates.csv 로더

```python
def _load_win_rates(self, base_path):
    """
    conditional_win_rates.csv 로딩.

    예상 CSV 구조 (실제 파일 확인 필요):
        phase,signal,win_rate,sample_size,avg_return,...
        대상승장,RSI_oversold,0.72,45,3.2,...
        일반장,MA_cross,0.58,120,1.8,...
        하락장,RSI_oversold,0.45,30,-0.5,...

    Returns:
        {
            "대상승장": {"overall_win_rate": 0.68, "signals": {...}},
            "일반장": {"overall_win_rate": 0.55, "signals": {...}},
            ...
        }
    """
    file_path = base_path / "data" / "history" / "analysis" / "conditional_win_rates.csv"

    if not file_path.exists():
        self.logger.warning(f"[분석데이터] conditional_win_rates.csv 없음: {file_path}")
        return None

    try:
        result = {}
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                phase = row.get('phase') or row.get('market_phase', '')
                signal = row.get('signal') or row.get('indicator', '')
                win_rate = self._safe_csv_float(
                    row.get('win_rate') or row.get('wr', '0')
                )
                sample = int(self._safe_csv_float(
                    row.get('sample_size') or row.get('n', '0')
                ))

                if not phase:
                    continue

                if phase not in result:
                    result[phase] = {"signals": {}, "total_wr": 0, "total_n": 0}

                result[phase]["signals"][signal] = {
                    "win_rate": win_rate,
                    "sample_size": sample
                }
                # 가중 평균 계산용
                result[phase]["total_wr"] += win_rate * sample
                result[phase]["total_n"] += sample

        # 국면별 가중 평균 승률 계산
        for phase in result:
            n = result[phase]["total_n"]
            result[phase]["overall_win_rate"] = (
                result[phase]["total_wr"] / n if n > 0 else 0.5
            )

        self.logger.info(f"[분석데이터] win_rates: {len(result)}개 국면 로딩")
        return result

    except Exception as e:
        self.logger.error(f"[분석데이터] win_rates 로딩 실패: {e}")
        return None
```

### 3-3. best_signals.json 로더

```python
def _load_best_signals(self, base_path):
    """best_signals.json 로딩"""
    file_path = base_path / "data" / "history" / "analysis" / "best_signals.json"

    if not file_path.exists():
        return None

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.logger.info(f"[분석데이터] best_signals 로딩 완료")
        return data
    except Exception as e:
        self.logger.error(f"[분석데이터] best_signals 로딩 실패: {e}")
        return None
```

### 3-4. ic_by_phase.csv 로더

```python
def _load_ic_by_phase(self, base_path):
    """
    ic_by_phase.csv 로딩.
    Information Coefficient = 지표의 예측력 (높을수록 그 지표가 유용)

    Returns:
        {
            "대상승장": {"RSI": 0.15, "MACD": 0.22, "volume": 0.08, ...},
            ...
        }
    """
    file_path = base_path / "data" / "history" / "analysis" / "ic_by_phase.csv"

    if not file_path.exists():
        return None

    try:
        result = {}
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                phase = row.get('phase') or row.get('market_phase', '')
                if not phase:
                    continue
                result[phase] = {
                    k: self._safe_csv_float(v)
                    for k, v in row.items()
                    if k not in ('phase', 'market_phase')
                }
        self.logger.info(f"[분석데이터] ic_by_phase: {len(result)}개 국면 로딩")
        return result
    except Exception as e:
        self.logger.error(f"[분석데이터] ic_by_phase 로딩 실패: {e}")
        return None
```

---

## 4. 적용 1: _forecast_single() — 동적 상관계수

### 현재 문제

```python
# 현재 코드 (market_analyzer.py, _forecast_single 내부)
# US 연동 예측 부분에서:

corr = self.get_lead_lag_corr(symbol, us_indicator)
# get_lead_lag_corr()가 실패하면 → fallback 0.3 사용
# 이 0.3은 대충 넣은 값. 실제 상관계수는 CSV에 있음
```

### 수정 방법

```python
def get_lead_lag_corr_enhanced(self, symbol, us_indicator):
    """
    기존 get_lead_lag_corr()를 감싸는 향상 버전.
    1순위: 기존 메서드 시도
    2순위: lead_lag_analysis.csv 실측값
    3순위: LEADING_INDICATOR_MAP 하드코딩
    4순위: fallback 0.3 (최후의 수단)
    """
    # 1순위: 기존 메서드
    try:
        corr = self.get_lead_lag_corr(symbol, us_indicator)
        if corr is not None and corr != 0.3:  # fallback이 아닌 실제값
            return corr
    except Exception:
        pass

    # 2순위: CSV 실측값
    self._load_analysis_data()  # 캐시 로딩 (이미 로딩됐으면 스킵)
    lead_lag = self._analysis_cache.get('lead_lag')
    if lead_lag:
        # us_indicator 이름으로 검색
        indicator_key = us_indicator.replace("^", "").upper()
        for key, data in lead_lag.items():
            if indicator_key in key.upper() or key.upper() in indicator_key:
                if data.get("p_value", 1) < 0.05:  # 통계적 유의성 체크
                    return data["corr"]

    # 3순위: LEADING_INDICATOR_MAP 하드코딩 (기존 코드에 있음)
    # 이 부분은 기존 코드가 이미 처리

    # 4순위: fallback
    return 0.3


def get_optimal_lag(self, us_indicator):
    """CSV에서 최적 lag 일수 조회"""
    self._load_analysis_data()
    lead_lag = self._analysis_cache.get('lead_lag')
    if lead_lag:
        indicator_key = us_indicator.replace("^", "").upper()
        for key, data in lead_lag.items():
            if indicator_key in key.upper() or key.upper() in indicator_key:
                return data.get("lag", 1)
    return 1  # 기본값: 1일 선행
```

### _forecast_single()에서 사용

```python
# _forecast_single() 내부, US 연동 예측 계산 부분

# 기존:
# corr = self.get_lead_lag_corr(symbol, us_ind)

# 변경:
corr = self.get_lead_lag_corr_enhanced(symbol, us_ind)
optimal_lag = self.get_optimal_lag(us_ind)

# optimal_lag를 활용하여 US 데이터의 참조 시점도 조정
# (기존에 lag=1 하드코딩이면 여기서 동적으로 변경)
```

---

## 5. 적용 2: _get_trend_threshold() — 승률 기반 동적 임계값

### 현재 문제

```python
# 현재 _get_trend_threshold() (market_analyzer.py)
# 하드코딩된 임계값:
thresholds = {
    "대상승장": 0.40,
    "상승장": 0.45,
    "일반장": 0.50,
    "변동폭큰장": 0.55,
    "하락장": 0.60,
    "대폭락장": 0.70,
}
# 이 값들은 "감"으로 정한 것. 실증 데이터가 있는데 안 쓰고 있음.
```

### 수정 방법

```python
def _get_trend_threshold_enhanced(self, market_phase=None):
    """
    승률 데이터 기반 동적 임계값.

    원리: conditional_win_rates.csv의 국면별 승률을 기반으로
    "이 국면에서 매매하면 몇 % 확률로 이기는가?"를 파악하고,
    승률이 낮은 국면일수록 임계값을 높여서 더 확실한 종목만 통과시킨다.

    승률 → 임계값 변환:
    - 승률 70%+ → 임계값 0.35 (많이 이기니까 문을 넓게)
    - 승률 60%  → 임계값 0.45
    - 승률 50%  → 임계값 0.55
    - 승률 40%  → 임계값 0.65 (잘 안 이기니까 문을 좁게)
    - 승률 30%  → 임계값 0.75 (거의 닫힘)
    """
    # 1순위: 실증 데이터 기반
    self._load_analysis_data()
    win_rates = self._analysis_cache.get('win_rates')

    if win_rates and market_phase and market_phase in win_rates:
        wr = win_rates[market_phase].get("overall_win_rate", 0.5)
        sample = win_rates[market_phase].get("total_n", 0)

        # 샘플이 충분할 때만 실증 데이터 사용 (최소 20건)
        if sample >= 20:
            # 승률 → 임계값 변환 (선형 매핑)
            # wr=0.7 → threshold=0.35, wr=0.3 → threshold=0.75
            threshold = round(1.05 - wr, 2)
            threshold = max(0.30, min(0.80, threshold))

            self.logger.debug(
                f"[추세임계값] {market_phase}: 승률 {wr:.0%} "
                f"(n={sample}) → 임계값 {threshold}"
            )
            return threshold

    # 2순위: 하드코딩 fallback (기존 값)
    fallback = {
        "대상승장": 0.40,
        "상승장": 0.45,
        "일반장": 0.50,
        "변동폭큰장": 0.55,
        "하락장": 0.60,
        "대폭락장": 0.70,
    }

    if market_phase and market_phase in fallback:
        return fallback[market_phase]

    return 0.50
```

---

## 6. 적용 3: IC 기반 지표 가중치 조정 (선택적 고급)

```python
def _get_indicator_weights_by_phase(self, market_phase):
    """
    Information Coefficient 기반으로 지표별 가중치를 국면에 따라 동적 조정.

    예: 대상승장에서 MACD의 IC가 높으면 → MACD 가중치 높임
        하락장에서 RSI의 IC가 높으면 → RSI 가중치 높임

    check_trend_filter()의 점수 계산에서 활용 가능.
    """
    self._load_analysis_data()
    ic_data = self._analysis_cache.get('ic_by_phase')

    if not ic_data or not market_phase or market_phase not in ic_data:
        # fallback: 기본 가중치 (현재 check_trend_filter의 하드코딩 값)
        return {
            "ma_alignment": 3,
            "rsi": 2,
            "adx": 2,
            "macd": 1,
            "volume": 1,
        }

    phase_ic = ic_data[market_phase]

    # IC 값을 가중치로 변환 (IC가 높을수록 가중치 높게)
    # IC 범위: 보통 -0.1 ~ 0.3
    def ic_to_weight(ic_val, base_weight):
        """IC가 높으면 가중치 상향, 낮으면 하향"""
        if ic_val > 0.15:
            return base_weight * 1.3  # IC 높음 → 30% 부스트
        elif ic_val > 0.05:
            return base_weight * 1.0  # IC 보통 → 유지
        elif ic_val > -0.05:
            return base_weight * 0.8  # IC 낮음 → 20% 감소
        else:
            return base_weight * 0.5  # IC 음수 → 50% 감소

    weights = {
        "ma_alignment": ic_to_weight(phase_ic.get("MA", 0.1), 3),
        "rsi": ic_to_weight(phase_ic.get("RSI", 0.1), 2),
        "adx": ic_to_weight(phase_ic.get("ADX", 0.1), 2),
        "macd": ic_to_weight(phase_ic.get("MACD", 0.1), 1),
        "volume": ic_to_weight(phase_ic.get("volume", 0.05), 1),
    }

    return weights
```

---

## 7. 안전장치

### 모든 CSV 연동에 적용되는 원칙

```python
# 원칙 1: CSV 없어도 시스템 작동
# 모든 로더는 None 반환 가능, 사용처에서 fallback

# 원칙 2: 하루 1회 로딩, 메모리 캐시
# 매 사이클(30분)마다 파일 읽지 않음

# 원칙 3: 기존 하드코딩 값은 삭제하지 않고 fallback으로 유지
# CSV가 없거나 파싱 실패 시 기존 값 사용

# 원칙 4: 로깅으로 어떤 값이 사용됐는지 추적
self.logger.debug(f"[상관계수] {indicator}: CSV={csv_val} vs fallback=0.3 → 사용={final_val}")
```

---

## 8. Claude Code 실행 프롬프트

```
이 명세서(priority2_csv_live_spec.md)를 읽고 다음을 실행해줘:

### Step 1: CSV 파일 구조 확인
먼저 다음 파일들의 실제 구조(컬럼명, 데이터 예시)를 확인해줘:
- data/history/correlation/lead_lag_analysis.csv (첫 5행)
- data/history/analysis/conditional_win_rates.csv (첫 5행)
- data/history/analysis/best_signals.json (전체 구조)
- data/history/analysis/ic_by_phase.csv (첫 5행)

실제 컬럼명이 명세서의 예상과 다를 수 있으니,
확인 후 로더 코드의 컬럼명을 실제에 맞게 조정해줘.

### Step 2: CSV 로더 구현
market_analyzer.py에 다음 추가:
- _load_analysis_data() (통합 로더 + 캐시)
- _load_lead_lag()
- _load_win_rates()
- _load_best_signals()
- _load_ic_by_phase()
- _safe_csv_float()

### Step 3: 예측 연동
- get_lead_lag_corr_enhanced() 추가
- get_optimal_lag() 추가
- _forecast_single()에서 US 연동 부분의 상관계수를
  get_lead_lag_corr_enhanced()로 교체

### Step 4: 임계값 연동
- _get_trend_threshold()를 _get_trend_threshold_enhanced()로 교체
  (또는 기존 메서드 내부에 실증 데이터 우선 로직 추가)

### Step 5: 검증
- CSV 로딩이 정상 작동하는지 테스트
- CSV 없을 때 기존 fallback으로 정상 동작하는지 테스트
- 기존 코드(_classify_6phase, check_trend_filter 등) 미수정 확인

주의: Step 1에서 실제 CSV 구조를 먼저 확인한 후에
Step 2의 로더 코드를 실제 컬럼명에 맞게 작성해줘.
CSV가 존재하지 않는 파일이 있으면 해당 로더만 스킵.
```
