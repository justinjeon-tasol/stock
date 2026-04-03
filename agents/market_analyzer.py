"""
시장 분석 에이전트 모듈
Preprocessor의 PREPROCESSED_DATA를 받아 시장 국면(6종) 판단 및
미국→한국 선행지표 분석을 수행한다.

6국면:
  대상승장  - KOSPI 20일 수익률 +10% 이상
  상승장    - KOSPI 20일 수익률 +3% ~ +10%
  일반장    - 낮은 변동성, -3% ~ +3%
  변동폭큰  - 높은 변동성 또는 VIX 20+
  하락장    - KOSPI 20일 수익률 -3% ~ -10%
  대폭락장  - KOSPI 20일 수익률 -10% 이하 또는 VIX 35 이상
"""

import os
from pathlib import Path

from agents.base_agent import BaseAgent
from agents.issue_manager import IssueManager
from protocol.protocol import (
    StandardMessage,
    MarketPhasePayload,
    dataclass_to_dict,
)

# 히스토리 기반 국면 분류 데이터 (있으면 사용)
_PHASE_CSV = Path(__file__).resolve().parent.parent / "data" / "history" / "phase_classified.csv"


class MarketAnalyzer(BaseAgent):
    """
    시장 국면을 판단하고 선행지표 신호를 분석하는 에이전트.
    PREPROCESSED_DATA → MARKET_ANALYSIS
    """

    # 6국면 분류 임계값
    PHASE_CRITERIA = {
        "대폭락장": {"ret20_max": -10.0, "vix_min": 35.0},
        "하락장":   {"ret20_max":  -3.0},
        "대상승장": {"ret20_min":  10.0},
        "상승장":   {"ret20_min":   3.0},
        "변동폭큰": {"vix_min":    20.0, "vol_high": 1.2},
        "일반장":   {},   # 나머지
    }

    # CLAUDE.md의 미국→한국 선행지표 매핑
    LEADING_INDICATOR_MAP = {
        "nasdaq_surge": {
            "threshold_pct": 1.5,
            "kr_sectors": ["지수ETF"],
            "kr_themes": [],
            "direction": "BUY",
            "description": "나스닥100 급등 → 코스닥 추종",
        },
        "sox_surge": {
            "threshold_pct": 2.0,
            "kr_sectors": ["반도체"],
            "kr_themes": ["AI/HBM", "반도체장비"],
            "direction": "BUY",
            "description": "SOX 급등 → 반도체 수혜",
        },
        "nvidia_surge": {
            "threshold_pct": 3.0,
            "kr_sectors": ["반도체"],
            "kr_themes": ["AI/HBM"],
            "direction": "BUY",
            "description": "엔비디아 급등 → HBM/AI 반도체",
        },
        "amd_surge": {
            "threshold_pct": 3.0,
            "kr_sectors": ["반도체"],
            "kr_themes": ["AI/HBM"],
            "direction": "BUY",
            "description": "AMD 급등 → 반도체 섹터 강세",
        },
        "tesla_strong": {
            "threshold_pct": 2.0,
            "kr_sectors": ["2차전지"],
            "kr_themes": [],
            "direction": "BUY",
            "description": "테슬라 강세 → 2차전지 수혜",
        },
        "wti_surge": {
            "threshold_pct": 3.0,
            "kr_sectors": ["정유"],
            "kr_themes": [],
            "direction": "BUY",
            "description": "WTI 급등 → 정유주 수혜",
        },
        "gold_strong": {
            "threshold_pct": 1.5,
            "kr_sectors": [],
            "kr_themes": [],
            "direction": "AVOID",
            "description": "금 강세 → 안전자산 선호, 위험자산 하락",
        },
        "vix_spike": {
            "threshold_val": 30.0,
            "kr_sectors": [],
            "kr_themes": [],
            "direction": "AVOID",
            "description": "VIX 30 돌파 → 외국인 대량 매도 예고",
        },
        "dollar_strong": {
            "threshold_pct": 1.0,
            "kr_sectors": [],
            "kr_themes": [],
            "direction": "AVOID",
            "description": "달러 강세 → 외국인 순매도 압력",
        },
        "copper_strong": {
            "threshold_pct": 2.0,
            "kr_sectors": ["전반"],
            "kr_themes": [],
            "direction": "BUY",
            "description": "구리 강세 → 경기회복 신호",
        },
        "nasdaq_crash": {
            "threshold_pct": -2.0,
            "kr_sectors": ["지수ETF"],
            "kr_themes": [],
            "direction": "SELL",
            "description": "나스닥 급락 → 지수ETF 선제 매도",
        },
        "sox_crash": {
            "threshold_pct": -3.0,
            "kr_sectors": ["반도체"],
            "kr_themes": ["AI/HBM", "반도체장비"],
            "direction": "SELL",
            "description": "SOX 급락 → 반도체 선제 매도",
        },
        "tesla_crash": {
            "threshold_pct": -3.0,
            "kr_sectors": ["2차전지"],
            "kr_themes": [],
            "direction": "SELL",
            "description": "테슬라 급락 → 2차전지 선제 매도",
        },
        "vix_warning": {
            "threshold_val": 25.0,
            "kr_sectors": [],
            "kr_themes": [],
            "direction": "REDUCE",
            "reduce_pct": 50,
            "description": "VIX 25+ → 전체 포지션 50% 축소 권고",
        },
    }

    def __init__(self):
        super().__init__("MA", "시장분석", timeout=5, max_retries=3)
        self._issue_manager = IssueManager()
        self._theme_indicator_map = self._load_theme_indicator_map()
        self._rs_stock_map, self._oversold_stock_map = self._build_stock_maps()

    def _build_stock_maps(self) -> tuple:
        """
        stock_classification.json에서 RS 분석 및 낙폭과대 스캔용 맵을 동적으로 빌드한다.
        _CODE_TO_HISTORY에 심볼이 있는 종목만 포함 (history 데이터 없으면 분석 불가).

        반환: (rs_stock_map, oversold_stock_map)
          rs_stock_map: {code: symbol}
          oversold_stock_map: {code: (symbol, name, is_quality)}
        """
        import os
        from agents.classification_loader import ClassificationLoader
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "stock_classification.json",
        )
        loader = ClassificationLoader(path)
        stocks = loader.get_all_stocks()

        # history_loader 심볼 매핑 (히스토리 CSV가 있는 종목만)
        code_to_history = {
            "005930": "samsung",
            "000660": "sk_hynix",
            "373220": "lg_energy",
            "006400": "samsung_sdi",
            "042700": "hanmi_semi",
            "096770": "sk_inno",
        }

        rs_map = {}
        oversold_map = {}
        for code, symbol in code_to_history.items():
            if code not in stocks:
                continue
            info = stocks[code]
            rs_map[code] = symbol
            chars = info.get("characteristics", [])
            is_quality = "대형우량주" in chars
            oversold_map[code] = (symbol, info.get("name", code), is_quality)

        return rs_map, oversold_map

    def _load_theme_indicator_map(self) -> dict:
        """strategy_config.json의 theme_indicator_mapping 로드. 없으면 빈 dict."""
        import json, os
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "strategy_config.json"
        )
        try:
            with open(config_path, encoding="utf-8") as f:
                cfg = json.load(f)
            return cfg.get("theme_indicator_mapping", {})
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # 공개 인터페이스
    # ------------------------------------------------------------------

    async def execute(self, input_data: StandardMessage) -> StandardMessage:
        """
        PREPROCESSED_DATA → MARKET_ANALYSIS 변환.
        payload = {
            "market_phase": MarketPhasePayload를 dict로,
            "active_signals": [활성화된 선행지표 신호 목록],
            "trend_reversal": {전환 신호 감지 결과}
        }
        """
        self.log("info", "시장 분석 시작")

        raw_payload = input_data.body.get("payload", {})
        us          = raw_payload.get("us_market",   {})
        kr          = raw_payload.get("kr_market",   {})
        commodities = raw_payload.get("commodities", {})

        # 국면 판단
        phase_name, confidence = self.detect_phase(us, kr)
        self.log("info", f"국면 판단: {phase_name} (신뢰도: {confidence:.2f})")

        # MarketPhasePayload 생성
        market_phase = MarketPhasePayload(
            phase=phase_name,
            confidence=confidence,
        )

        # 선행지표 분석
        active_signals = self.analyze_leading_indicators(us, commodities)
        self.log("info", f"활성 신호: {len(active_signals)}개")

        # 테마 모멘텀 분석
        theme_signals = self.analyze_theme_momentum(us, commodities)
        self.log("info", f"테마 신호: {len(theme_signals)}개")

        # 추세 전환 탐지
        trend_reversal = self.detect_trend_reversal(us, kr)
        self.log("info", "추세 전환 탐지 완료")

        # 상대강도 분석 (A안)
        rs_scores = self.scan_relative_strength(kr)
        self.log("info", f"RS 분석: {len(rs_scores)}종목")

        # 대폭락장 반등 포착 스캔
        oversold_candidates = self.scan_oversold_candidates(kr)
        if oversold_candidates:
            self.log("info", f"낙폭과대 후보: {len(oversold_candidates)}종목 "
                             f"({', '.join(c['name'] for c in oversold_candidates)})")

        # ── 추세 필터 (Filter 2) — 전 종목 일괄 평가 ──
        trend_filter_results = {}
        try:
            trend_candidates = []
            for code, symbol in self._rs_stock_map.items():
                name = ""
                if code in self._oversold_stock_map:
                    name = self._oversold_stock_map[code][1]
                trend_candidates.append({
                    "symbol": code,
                    "name": name,
                    "history_symbol": symbol,
                })
            if trend_candidates:
                trend_filter_results = self.check_trend_batch(
                    trend_candidates, market_phase=phase_name
                )
                s = trend_filter_results.get("summary", {})
                self.log("info",
                         f"추세 필터: {s.get('total', 0)}종목 → "
                         f"{s.get('passed', 0)}종목 통과 "
                         f"(기준 {s.get('threshold', 0.5)}, 국면 {phase_name})")
        except Exception as exc:
            self.log("warning", f"추세 필터 실패 (무시): {exc}")

        payload = {
            "market_phase":         dataclass_to_dict(market_phase),
            "active_signals":       active_signals,
            "theme_signals":        theme_signals,
            "trend_reversal":       trend_reversal,
            "rs_scores":            rs_scores,                          # A안
            "stock_foreign_net":    kr.get("stock_foreign_net", {}),   # C안
            "stock_institution_net": kr.get("stock_institution_net", {}),  # C안 기관
            "oversold_candidates":  oversold_candidates,                # 대폭락장 반등
            "trend_filter_results": trend_filter_results,               # Filter 2
        }

        # ── 이슈 감지 (IssueManager 흡수) ──
        try:
            issue_result = await self._issue_manager.execute(input_data)
            issue_payload = issue_result.body.get("payload", {})
            payload["issue_analysis"] = issue_payload
            issue_count = issue_payload.get("issue_count", 0)
            if issue_count > 0:
                self.log("info", f"이슈 감지: {issue_count}건 (max={issue_payload.get('max_severity', 'LOW')})")
        except Exception as exc:
            self.log("warning", f"이슈 감지 실패 (무시): {exc}")
            payload["issue_analysis"] = {
                "active_issues": [], "issue_count": 0,
                "max_severity": "LOW", "summary": "이슈 감지 실패",
            }

        # ── 보유종목 가격 예측 ──
        try:
            from database.db import get_open_positions
            open_positions = get_open_positions()
            if open_positions:
                forecasts = self._generate_price_forecasts(open_positions, us, kr, commodities)
                payload["price_forecasts"] = forecasts
                if forecasts:
                    self.log("info", f"가격 예측 생성: {len(forecasts)}종목")
        except Exception as exc:
            self.log("warning", f"가격 예측 실패 (무시): {exc}")

        self.log("info", "시장 분석 완료")
        return self.create_message(
            to="WA",
            data_type="MARKET_ANALYSIS",
            payload=payload,
        )

    # ------------------------------------------------------------------
    # 국면 판단
    # ------------------------------------------------------------------

    def detect_phase(self, us: dict, kr: dict) -> tuple:
        """
        6국면 판단 로직.
        우선순위: 대폭락장 > 대상승장 > 하락장 > 상승장 > 변동폭큰 > 일반장

        히스토리 CSV(phase_classified.csv)에서 20일 추세를 읽어 판단.
        파일이 없으면 당일 지표 기반 fallback 사용.

        반환: (phase_name, confidence)
        """
        vix_value = us.get("vix", {}).get("value", 0.0) or 0.0

        # ── 히스토리 기반 판단 (주 경로) ──────────────────────────────
        ret20, vol10 = self._load_latest_phase_stats()
        if ret20 is not None:
            return self._classify_6phase(ret20, vol10 or 0.0, vix_value)

        # ── Fallback: 당일 지표만으로 간이 판단 ──────────────────────
        kospi_change = kr.get("kospi", {}).get("change_pct", 0.0) or 0.0
        kospi_vol    = kr.get("kospi", {}).get("volume_ratio", 1.0) or 1.0

        # 당일 등락률을 20일 추세 대용으로 사용 (정밀도 낮음)
        approx_ret20 = kospi_change * 15   # 하루 등락 × 15 ≈ 3주치 추세 근사
        approx_vol   = 1.0 if kospi_vol < 1.5 else 1.5
        return self._classify_6phase(approx_ret20, approx_vol, vix_value, confidence_penalty=0.3)

    def _load_latest_phase_stats(self):
        """
        phase_classified.csv 마지막 행에서 kospi_ret20, kospi_vol10 읽기.
        파일이 없거나 읽기 실패 시 (None, None) 반환.
        """
        try:
            if not _PHASE_CSV.exists():
                return None, None
            import pandas as pd
            df = pd.read_csv(_PHASE_CSV, index_col=0, parse_dates=True)
            if df.empty:
                return None, None
            last = df.iloc[-1]
            return float(last.get("kospi_ret20", 0) or 0), float(last.get("kospi_vol10", 0) or 0)
        except Exception:
            return None, None

    def _classify_6phase(
        self,
        ret20: float,
        vol10: float,
        vix: float,
        confidence_penalty: float = 0.0,
    ) -> tuple:
        """
        20일 수익률 + 변동성 + VIX로 6국면 분류.
        우선순위: 대폭락장 > 대상승장 > 하락장 > 상승장 > 변동폭큰 > 일반장
        """
        # ① 대폭락장
        if ret20 <= -10.0 or vix >= 35.0:
            conf = 0.95 if ret20 <= -10.0 and vix >= 35.0 else 0.80
            return ("대폭락장", round(conf - confidence_penalty, 2))

        # ② 대상승장
        if ret20 >= 10.0:
            return ("대상승장", round(0.90 - confidence_penalty, 2))

        # ③ 하락장
        if ret20 <= -3.0:
            conf = min(0.85, 0.50 + abs(ret20) * 0.03)
            return ("하락장", round(conf - confidence_penalty, 2))

        # ④ 상승장
        if ret20 >= 3.0:
            conf = min(0.85, 0.50 + ret20 * 0.03)
            return ("상승장", round(conf - confidence_penalty, 2))

        # ⑤ 변동폭큰 (-3% ~ +3% 사이에서 변동성/VIX 높음)
        if vol10 >= 1.2 or vix >= 20.0:
            conf = min(0.75, 0.50 + (vix - 20) * 0.02 + vol10 * 0.05)
            return ("변동폭큰", round(max(0.3, conf) - confidence_penalty, 2))

        # ⑥ 일반장
        conf = min(0.70, 0.55 + (3.0 - abs(ret20)) * 0.03)
        return ("일반장", round(max(0.3, conf) - confidence_penalty, 2))

    # ------------------------------------------------------------------
    # 선행지표 분석
    # ------------------------------------------------------------------

    def analyze_leading_indicators(self, us: dict, commodities: dict) -> list:
        """
        LEADING_INDICATOR_MAP 기준으로 현재 활성화된 신호 탐지.

        각 신호 평가:
        - threshold_pct 기준: change_pct가 threshold 이상이면 활성화
        - threshold_val 기준: value가 threshold 이상이면 활성화 (VIX)

        반환: [
            {
                "signal_id": "sox_surge",
                "direction": "BUY",
                "kr_sectors": ["반도체"],
                "description": "SOX 급등 → 반도체 수혜",
                "strength": 1.5,  # change_pct / threshold_pct
                "value": 3.8      # 실제 change_pct 값
            },
            ...
        ]
        우선순위: AVOID 신호가 있으면 list 앞에 오게 정렬
        """
        # 각 신호별 데이터 소스 매핑
        signal_value_map = {
            "nasdaq_surge": us.get("nasdaq",     {}).get("change_pct", 0.0) or 0.0,
            "sox_surge":    us.get("sox",        {}).get("change_pct", 0.0) or 0.0,
            "nvidia_surge": (us.get("individual", {}).get("NVDA", {}) or {}).get("change_pct", 0.0) or 0.0,
            "amd_surge":    (us.get("individual", {}).get("AMD",  {}) or {}).get("change_pct", 0.0) or 0.0,
            "tesla_strong": (us.get("individual", {}).get("TSLA", {}) or {}).get("change_pct", 0.0) or 0.0,
            "wti_surge":    commodities.get("wti",    {}).get("change_pct", 0.0) or 0.0,
            "gold_strong":  commodities.get("gold",   {}).get("change_pct", 0.0) or 0.0,
            "vix_spike":    us.get("vix",        {}).get("value",      0.0) or 0.0,  # threshold_val 기준
            "dollar_strong": us.get("usd_krw",   {}).get("change_pct", 0.0) or 0.0,
            "copper_strong": commodities.get("copper", {}).get("change_pct", 0.0) or 0.0,
            # 하락 신호 (동일 데이터 소스, threshold가 음수)
            "nasdaq_crash":  us.get("nasdaq",  {}).get("change_pct", 0.0) or 0.0,
            "sox_crash":     us.get("sox",     {}).get("change_pct", 0.0) or 0.0,
            "tesla_crash":   (us.get("individual", {}).get("TSLA", {}) or {}).get("change_pct", 0.0) or 0.0,
            "vix_warning":   us.get("vix",     {}).get("value",      0.0) or 0.0,  # threshold_val 기준
        }

        active_signals = []

        for signal_id, cfg in self.LEADING_INDICATOR_MAP.items():
            actual_value = signal_value_map.get(signal_id, 0.0)

            if "threshold_val" in cfg:
                # VIX처럼 절대값 비교
                threshold = cfg["threshold_val"]
                if actual_value >= threshold:
                    strength = round(actual_value / threshold, 2) if threshold != 0 else 0.0
                    signal_entry = {
                        "signal_id":   signal_id,
                        "direction":   cfg["direction"],
                        "axis":        "sector",
                        "kr_sectors":  cfg["kr_sectors"],
                        "kr_themes":   cfg.get("kr_themes", []),
                        "description": cfg["description"],
                        "strength":    strength,
                        "value":       round(actual_value, 2),
                    }
                    if cfg.get("reduce_pct"):
                        signal_entry["reduce_pct"] = cfg["reduce_pct"]
                    active_signals.append(signal_entry)
            else:
                # 등락률(change_pct) 기준 비교
                threshold = cfg["threshold_pct"]
                # 하락 신호: threshold가 음수 → actual_value가 threshold 이하면 활성화
                if threshold < 0:
                    triggered = actual_value <= threshold
                else:
                    triggered = actual_value >= threshold
                if triggered:
                    strength = round(abs(actual_value / threshold), 2) if threshold != 0 else 0.0
                    signal_entry = {
                        "signal_id":   signal_id,
                        "direction":   cfg["direction"],
                        "axis":        "sector",
                        "kr_sectors":  cfg["kr_sectors"],
                        "kr_themes":   cfg.get("kr_themes", []),
                        "description": cfg["description"],
                        "strength":    strength,
                        "value":       round(actual_value, 2),
                    }
                    # REDUCE 신호에 reduce_pct 포함
                    if cfg.get("reduce_pct"):
                        signal_entry["reduce_pct"] = cfg["reduce_pct"]
                    active_signals.append(signal_entry)

        # SELL/REDUCE/AVOID 신호를 리스트 앞으로 정렬 (위험 우선)
        _DIRECTION_PRIORITY = {"SELL": 0, "REDUCE": 1, "AVOID": 2, "BUY": 3}
        active_signals.sort(key=lambda s: _DIRECTION_PRIORITY.get(s["direction"], 3))

        return active_signals

    # ------------------------------------------------------------------
    # 테마 모멘텀 분석
    # ------------------------------------------------------------------

    def analyze_theme_momentum(self, us: dict, commodities: dict) -> list:
        """
        strategy_config.json의 theme_indicator_mapping 기반으로
        테마 단위 모멘텀 신호를 감지한다.

        각 테마의 proxy 티커들의 평균 change_pct를 계산하여
        threshold를 초과하면 신호를 생성한다.

        반환:
        [
          {
            "signal_id":   "theme_AI/HBM",
            "direction":   "BUY",
            "axis":        "theme",
            "kr_themes":   ["AI/HBM"],
            "kr_sectors":  ["반도체"],
            "strength":    1.8,
            "value":       5.4,   # proxy 티커 평균 change_pct
            "description": "AI/HBM 테마 모멘텀 (NVDA/AMD 평균 +5.40%)"
          },
          ...
        ]
        """
        if not self._theme_indicator_map:
            return []

        individual = us.get("individual", {}) or {}
        theme_signals = []

        for theme_name, cfg in self._theme_indicator_map.items():
            tickers    = cfg.get("tickers", [])
            threshold  = cfg.get("threshold_pct", 0.0)
            direction  = cfg.get("direction", "BUY")
            kr_sectors = cfg.get("kr_sectors", [])

            # proxy 티커들의 change_pct 수집 (0이 아닌 유효값만)
            values = []
            for ticker in tickers:
                chg = (individual.get(ticker) or {}).get("change_pct", 0.0) or 0.0
                if chg != 0.0:
                    values.append(chg)

            if not values:
                continue

            avg_change = sum(values) / len(values)

            if avg_change >= threshold:
                strength = round(avg_change / threshold, 2) if threshold != 0 else 0.0
                ticker_str = "/".join(tickers)
                theme_signals.append({
                    "signal_id":   f"theme_{theme_name}",
                    "direction":   direction,
                    "axis":        "theme",
                    "kr_themes":   [theme_name],
                    "kr_sectors":  kr_sectors,
                    "strength":    strength,
                    "value":       round(avg_change, 2),
                    "description": f"{theme_name} 테마 모멘텀 ({ticker_str} 평균 {avg_change:+.2f}%)",
                })

        return theme_signals

    # ------------------------------------------------------------------
    # 추세 전환 탐지
    # ------------------------------------------------------------------

    def detect_trend_reversal(self, us: dict, kr: dict) -> dict:
        """
        추세 전환 신호 감지 (CLAUDE.md 기준: 3개 이상 동시 충족 시 전환).

        급락→상승 신호:
        - VIX 고점 하락 (vix.change_pct < -5.0)
        - 거래량 급감 (volume_ratio < 0.7)
        - 외국인 순매도 감소 (foreign_net 양수면 매수 유입)

        상승→하락 신호:
        - 거래량 감소하며 상승 (kospi.change_pct > 0 but volume_ratio < 1.0)
        - VIX 상승 (vix.change_pct > 5.0)
        - 달러 강세 (usd_krw.change_pct > 0.5)

        반환: {
            "reversal_up":   {"count": int, "signals": [str], "triggered": bool},
            "reversal_down": {"count": int, "signals": [str], "triggered": bool}
        }
        """
        # 필요한 값 추출
        vix_change    = us.get("vix",      {}).get("change_pct",   0.0) or 0.0
        usd_change    = us.get("usd_krw",  {}).get("change_pct",   0.0) or 0.0
        kospi_change  = kr.get("kospi",    {}).get("change_pct",   0.0) or 0.0
        kospi_vol     = kr.get("kospi",    {}).get("volume_ratio", 1.0) or 1.0
        foreign_net   = kr.get("foreign_net", 0) or 0

        # --- 급락→상승 전환 신호 ---
        reversal_up_signals = []

        # VIX 고점 하락 (VIX가 크게 내려갔으면 공포 완화)
        if vix_change < -5.0:
            reversal_up_signals.append(f"VIX 하락({vix_change:.1f}%) → 공포 완화")

        # 거래량 급감 (패닉 셀링 마무리 신호)
        if kospi_vol < 0.7:
            reversal_up_signals.append(f"거래량 급감({kospi_vol:.2f}) → 패닉 완화")

        # 외국인 순매수 전환 (양수면 매수 유입)
        if foreign_net > 0:
            reversal_up_signals.append(f"외국인 순매수({foreign_net}억원) → 매수 전환")

        reversal_up_count = len(reversal_up_signals)
        reversal_up_triggered = reversal_up_count >= 2  # 2개 이상 충족 시 전환 신호

        # --- 상승→하락 전환 신호 ---
        reversal_down_signals = []

        # 거래량 감소하며 상승 (약한 상승 → 하락 전환 경고)
        if kospi_change > 0 and kospi_vol < 1.0:
            reversal_down_signals.append(
                f"거래량 감소({kospi_vol:.2f}) 상승({kospi_change:.1f}%) → 약세 상승"
            )

        # VIX 급등 (공포 확대)
        if vix_change > 5.0:
            reversal_down_signals.append(f"VIX 급등({vix_change:.1f}%) → 공포 확대")

        # 달러 강세 (외국인 매도 압력)
        if usd_change > 0.5:
            reversal_down_signals.append(f"달러 강세({usd_change:.1f}%) → 외국인 매도 압력")

        reversal_down_count = len(reversal_down_signals)
        reversal_down_triggered = reversal_down_count >= 2  # 2개 이상 충족 시 전환 신호

        return {
            "reversal_up": {
                "count":     reversal_up_count,
                "signals":   reversal_up_signals,
                "triggered": reversal_up_triggered,
            },
            "reversal_down": {
                "count":     reversal_down_count,
                "signals":   reversal_down_signals,
                "triggered": reversal_down_triggered,
            },
        }

    # ------------------------------------------------------------------
    # 상대강도 스캔 (A안)
    # ------------------------------------------------------------------

    def scan_relative_strength(self, kr_market: dict) -> dict:
        """
        추적 종목의 KOSPI 대비 5일/20일 상대강도(RS) 계산.

        RS = 종목 수익률 / KOSPI 수익률
          > 1.0: 시장 대비 강세 (하락장에서도 버티는 종목)
          < 0.5: 시장 대비 약세

        반환:
        {
          "005930": {"rs_5d": 1.2, "rs_20d": 0.9, "signal": "NEUTRAL"},
          "000660": {"rs_5d": 1.5, "rs_20d": 1.3, "signal": "STRONG"},
          ...
        }
        signal: "STRONG" (5일+20일 모두 > 1.0) | "WEAK" (둘 다 < 0.5) | "NEUTRAL" | "UNKNOWN"
        """
        try:
            from data.history.history_loader import get_loader
            loader = get_loader()

            kospi_close = loader._load_close("KOSPI")
            if kospi_close is None or len(kospi_close) < 21:
                return {}

            stocks_data = kr_market.get("stocks", {})
            rs_scores = {}

            for code, symbol in self._rs_stock_map.items():
                try:
                    close = loader._load_close(symbol)
                    if close is None or len(close) < 21:
                        continue

                    # 오늘 실시간 가격 우선, 없으면 히스토리 최신값
                    today_price = (stocks_data.get(code) or {}).get("price")
                    latest = float(today_price) if (today_price and today_price > 0) else float(close.iloc[-1])

                    # 5일 수익률
                    stock_ret5  = latest / float(close.iloc[-6])  - 1.0
                    kospi_ret5  = float(kospi_close.iloc[-1]) / float(kospi_close.iloc[-6])  - 1.0

                    # 20일 수익률
                    stock_ret20 = latest / float(close.iloc[-21]) - 1.0
                    kospi_ret20 = float(kospi_close.iloc[-1]) / float(kospi_close.iloc[-21]) - 1.0

                    rs_5  = (stock_ret5  / kospi_ret5)  if kospi_ret5  != 0 else None
                    rs_20 = (stock_ret20 / kospi_ret20) if kospi_ret20 != 0 else None

                    if rs_5 is not None and rs_20 is not None:
                        if rs_5 > 1.0 and rs_20 > 1.0:
                            signal = "STRONG"
                        elif rs_5 < 0.5 and rs_20 < 0.5:
                            signal = "WEAK"
                        else:
                            signal = "NEUTRAL"
                    else:
                        signal = "UNKNOWN"

                    rs_scores[code] = {
                        "rs_5d":  round(rs_5,  3) if rs_5  is not None else None,
                        "rs_20d": round(rs_20, 3) if rs_20 is not None else None,
                        "signal": signal,
                    }
                except Exception:
                    continue

            return rs_scores
        except Exception as exc:
            self.log("warning", f"RS 분석 실패: {exc}")
            return {}

    # ------------------------------------------------------------------
    # 대폭락장 반등 포착 스캔
    # ------------------------------------------------------------------

    def scan_oversold_candidates(self, kr_market: dict) -> list:
        """
        대폭락장에서 추가 하락 여지가 제한된 종목을 탐색한다.

        채점 기준 (score 3 이상 → 반등 후보):
          ① RSI_14 < 25             → +1  (과매도)
             RSI_14 < 20            → +1  (극단적 과매도, 추가)
          ② 52주 고점 대비 낙폭 < -40%  → +1
             낙폭 < -50%            → +1  (추가)
          ③ 낙폭 / 역사적 MDD > 0.80   → +1  (하방 여지 80% 소진)
             > 0.90                 → +1  (추가)
          ④ 대형우량주              → +1  (부도 리스크 낮음)

        반환:
        [
          {
            "code": "000660",
            "name": "SK하이닉스",
            "rsi_14": 22.1,
            "drawdown_52w_pct": -45.2,
            "historical_mdd":   -55.0,
            "mdd_utilization":   0.82,
            "score": 4,
            "signal": "OVERSOLD_BOUNCE"
          },
          ...
        ]
        score 내림차순 정렬. 최대 3종목.
        """
        try:
            from data.history.history_loader import get_loader
            loader = get_loader()
            stocks_data = kr_market.get("stocks", {})
            candidates  = []

            for code, (symbol, name, is_quality) in self._oversold_stock_map.items():
                try:
                    close = loader._load_close(symbol)
                    if close is None or len(close) < 30:
                        continue

                    closes = [float(v) for v in close.tolist()]

                    # 오늘 실시간 가격 우선
                    today_price = (stocks_data.get(code) or {}).get("price")
                    current = float(today_price) if (today_price and today_price > 0) else closes[-1]

                    # ① RSI_14
                    rsi = self._calc_rsi(closes + [current])

                    # ② 52주 고점 대비 낙폭
                    window_52w = min(252, len(closes))
                    peak_52w   = max(closes[-window_52w:] + [current])
                    dd_52w     = (current / peak_52w - 1) * 100

                    # ③ 역사적 MDD
                    hist_mdd = self._calc_historical_mdd(closes)
                    if hist_mdd == 0:
                        mdd_util = 0.0
                    else:
                        mdd_util = round(dd_52w / hist_mdd, 3)  # > 1이면 역대 최악 초과

                    # 채점
                    score = 0
                    if rsi < 25:
                        score += 1
                    if rsi < 20:
                        score += 1
                    if dd_52w < -40:
                        score += 1
                    if dd_52w < -50:
                        score += 1
                    if mdd_util > 0.80:
                        score += 1
                    if mdd_util > 0.90:
                        score += 1
                    if is_quality:
                        score += 1

                    if score >= 3:
                        candidates.append({
                            "code":              code,
                            "name":              name,
                            "rsi_14":            rsi,
                            "drawdown_52w_pct":  round(dd_52w,   2),
                            "historical_mdd":    round(hist_mdd, 2),
                            "mdd_utilization":   mdd_util,
                            "score":             score,
                            "signal":            "OVERSOLD_BOUNCE",
                        })
                except Exception:
                    continue

            candidates.sort(key=lambda x: x["score"], reverse=True)
            return candidates[:3]

        except Exception as exc:
            self.log("warning", f"낙폭과대 스캔 실패: {exc}")
            return []

    @staticmethod
    def _calc_rsi(closes: list, period: int = 14) -> float:
        """단순 RSI 계산 (Wilder 평활 미적용 — 빠른 근사치)."""
        if len(closes) < period + 1:
            return 50.0
        deltas = [closes[i] - closes[i - 1] for i in range(-period, 0)]
        gains  = sum(d for d in deltas if d > 0)
        losses = sum(-d for d in deltas if d < 0)
        avg_gain = gains  / period
        avg_loss = losses / period
        if avg_loss == 0:
            return 100.0
        return round(100 - 100 / (1 + avg_gain / avg_loss), 2)

    @staticmethod
    def _calc_historical_mdd(closes: list) -> float:
        """전체 히스토리 기반 최대 낙폭(MDD) 계산. 음수 반환."""
        if len(closes) < 2:
            return 0.0
        peak   = closes[0]
        max_dd = 0.0
        for c in closes:
            if c > peak:
                peak = c
            dd = (c / peak - 1) * 100
            if dd < max_dd:
                max_dd = dd
        return round(max_dd, 2)

    # ------------------------------------------------------------------
    # 분석 CSV/JSON 로더 (하루 1회 캐시)
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_csv_float(value, default=0.0):
        """CSV 값을 안전하게 float로 변환."""
        try:
            return float(str(value).strip())
        except (ValueError, TypeError):
            return default

    def _load_analysis_data(self):
        """분석 결과 CSV/JSON을 하루 1회 로딩하여 메모리에 캐시."""
        if hasattr(self, "_analysis_cache") and self._analysis_cache.get("loaded"):
            return
        self._analysis_cache = {"loaded": True}
        base = Path(__file__).resolve().parent.parent

        self._analysis_cache["lead_lag"] = self._load_lead_lag(base)
        self._analysis_cache["win_rates"] = self._load_win_rates(base)
        self._analysis_cache["best_signals"] = self._load_best_signals(base)
        self._analysis_cache["ic_by_phase"] = self._load_ic_by_phase(base)

        n = sum(1 for k, v in self._analysis_cache.items()
                if k != "loaded" and v is not None)
        self.log("info", f"[분석데이터] {n}/4개 파일 로딩 완료")

    def _load_lead_lag(self, base):
        """
        lead_lag_detailed.json 로딩.
        실제 구조: lead_lag_matrix → {
            "QQQ_to_KOSPI": {"lag_0": 0.077, "lag_1": 0.443, "best_lag": 1},
            "SOX_to_SK하이닉스": {"lag_1": 0.416, "best_lag": 1}, ...
        }
        반환: {"sox": {"corr": 0.416, "lag": 1}, "nasdaq": {"corr": 0.443, "lag": 1}, ...}
        """
        import json as _json
        fp = base / "data" / "history" / "correlation" / "lead_lag_detailed.json"
        if not fp.exists():
            return None
        try:
            with open(fp, "r", encoding="utf-8") as f:
                raw = _json.load(f)
            matrix = raw.get("lead_lag_matrix", {})
            result = {}
            # 키에서 US 지표명 추출하여 정규화
            key_map = {
                "QQQ": "nasdaq", "SOX": "sox", "SOXX": "sox",
                "NVDA": "nvidia", "USDKRW": "usd_krw", "Gold": "gold",
                "WTI": "wti", "AMD": "amd", "SPY": "sp500",
            }
            for key, data in matrix.items():
                best_lag = data.get("best_lag", 1)
                corr_val = data.get(f"lag_{best_lag}", data.get("lag_1", 0))
                # "QQQ_to_KOSPI" → "QQQ"
                us_part = key.split("_to_")[0] if "_to_" in key else key
                norm = key_map.get(us_part, us_part.lower())
                # 가장 높은 상관 유지
                if norm not in result or abs(corr_val) > abs(result[norm]["corr"]):
                    result[norm] = {"corr": round(corr_val, 4), "lag": best_lag}
            self.log("info", f"[분석데이터] lead_lag: {len(result)}개 지표")
            return result
        except Exception as exc:
            self.log("warning", f"[분석데이터] lead_lag 로딩 실패: {exc}")
            return None

    def _load_win_rates(self, base):
        """
        conditional_win_rates.csv 로딩.
        실제 컬럼: phase,signal,threshold,direction,n,win_rate,avg_ret,edge
        반환: {"대상승장": {"overall_win_rate": 0.86, "total_n": 64, ...}, ...}
        """
        import csv
        fp = base / "data" / "history" / "analysis" / "conditional_win_rates.csv"
        if not fp.exists():
            return None
        try:
            result = {}
            with open(fp, "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    phase = row.get("phase", "")
                    if not phase:
                        continue
                    wr = self._safe_csv_float(row.get("win_rate"))
                    n = int(self._safe_csv_float(row.get("n", 0)))
                    if phase not in result:
                        result[phase] = {"total_wr": 0.0, "total_n": 0}
                    result[phase]["total_wr"] += wr * n
                    result[phase]["total_n"] += n
            for phase in result:
                tn = result[phase]["total_n"]
                result[phase]["overall_win_rate"] = (
                    result[phase]["total_wr"] / tn if tn > 0 else 0.5
                )
            self.log("info", f"[분석데이터] win_rates: {len(result)}개 국면")
            return result
        except Exception as exc:
            self.log("warning", f"[분석데이터] win_rates 로딩 실패: {exc}")
            return None

    def _load_best_signals(self, base):
        """best_signals.json 로딩 (국면별 매수/방어 최적 신호)."""
        import json as _json
        fp = base / "data" / "history" / "analysis" / "best_signals.json"
        if not fp.exists():
            return None
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = _json.load(f)
            self.log("info", f"[분석데이터] best_signals: {len(data)}개 국면")
            return data
        except Exception:
            return None

    def _load_ic_by_phase(self, base):
        """
        ic_by_phase.csv 로딩.
        실제 컬럼: phase,nasdaq_ret1,sox_ret1,nvda_ret1,amd_ret1,usd_krw_ret1,gold_ret1
        반환: {"대상승장": {"nasdaq": 0.275, "sox": 0.304, ...}, ...}
        """
        import csv
        fp = base / "data" / "history" / "analysis" / "ic_by_phase.csv"
        if not fp.exists():
            return None
        try:
            # 컬럼명 → 정규화 키 매핑
            col_map = {
                "nasdaq_ret1": "nasdaq", "sox_ret1": "sox",
                "nvda_ret1": "nvidia", "amd_ret1": "amd",
                "usd_krw_ret1": "usd_krw", "gold_ret1": "gold",
            }
            result = {}
            with open(fp, "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    phase = row.get("phase", "")
                    if not phase:
                        continue
                    result[phase] = {
                        col_map.get(k, k): self._safe_csv_float(v)
                        for k, v in row.items() if k != "phase"
                    }
            self.log("info", f"[분석데이터] ic_by_phase: {len(result)}개 국면")
            return result
        except Exception:
            return None

    # ------------------------------------------------------------------
    # 분석 데이터 활용: 동적 상관계수 / 임계값
    # ------------------------------------------------------------------

    def get_lead_lag_corr_enhanced(self, us_indicator: str, symbol: str = ""):
        """
        US→KR 상관계수를 실측 데이터 우선으로 반환한다.
        1순위: lead_lag_detailed.json의 실측 상관계수
        2순위: history_loader.get_lead_lag_corr()
        3순위: fallback 0.3
        """
        self._load_analysis_data()
        ll = self._analysis_cache.get("lead_lag")

        if ll:
            # us_indicator → 정규화 키 매핑
            norm_map = {
                "sox": "sox", "nasdaq": "nasdaq", "tesla": "nvidia",
                "wti": "wti", "gold": "gold", "sp500": "sp500",
                "usd_krw": "usd_krw", "amd": "amd",
            }
            key = norm_map.get(us_indicator, us_indicator.lower())
            if key in ll:
                return ll[key]["corr"]

        # 2순위: history_loader (기존)
        try:
            from data.history.history_loader import get_loader
            hl = get_loader()
            val = hl.get_lead_lag_corr(us_indicator, symbol, lag=1)
            if val is not None:
                return val
        except Exception:
            pass

        return 0.3

    def get_optimal_lag(self, us_indicator: str) -> int:
        """CSV에서 최적 lag 일수 조회."""
        self._load_analysis_data()
        ll = self._analysis_cache.get("lead_lag")
        if ll:
            norm_map = {
                "sox": "sox", "nasdaq": "nasdaq", "tesla": "nvidia",
                "wti": "wti", "gold": "gold",
            }
            key = norm_map.get(us_indicator, us_indicator.lower())
            if key in ll:
                return ll[key].get("lag", 1)
        return 1

    # ------------------------------------------------------------------
    # Filter 2: 추세 확인 필터 (Trend Filter)
    # ------------------------------------------------------------------

    @staticmethod
    def _calc_adx(highs: list, lows: list, closes: list, period: int = 14) -> float:
        """
        ADX(Average Directional Index)를 계산한다.
        추세의 강도를 측정 (방향 무관).
          ADX >= 25  강한 추세
          ADX >= 20  보통 추세
          ADX <  15  추세 없음(횡보)
        데이터 부족 시 중립값 15.0 반환.
        """
        if len(highs) < period * 2 + 1:
            return 15.0

        tr_list, plus_dm_list, minus_dm_list = [], [], []
        for i in range(1, len(highs)):
            h, lo = highs[i], lows[i]
            ph, pl, pc = highs[i - 1], lows[i - 1], closes[i - 1]

            tr_list.append(max(h - lo, abs(h - pc), abs(lo - pc)))

            up_move = h - ph
            down_move = pl - lo
            plus_dm_list.append(up_move if (up_move > down_move and up_move > 0) else 0)
            minus_dm_list.append(down_move if (down_move > up_move and down_move > 0) else 0)

        def _wilder(data, p):
            smoothed = [sum(data[:p])]
            for i in range(p, len(data)):
                smoothed.append(smoothed[-1] - smoothed[-1] / p + data[i])
            return smoothed

        atr = _wilder(tr_list, period)
        sm_plus = _wilder(plus_dm_list, period)
        sm_minus = _wilder(minus_dm_list, period)

        dx_list = []
        for i in range(min(len(atr), len(sm_plus), len(sm_minus))):
            if atr[i] == 0:
                continue
            pdi = 100 * sm_plus[i] / atr[i]
            mdi = 100 * sm_minus[i] / atr[i]
            di_sum = pdi + mdi
            if di_sum == 0:
                continue
            dx_list.append(100 * abs(pdi - mdi) / di_sum)

        if len(dx_list) < period:
            return 15.0

        adx_vals = _wilder(dx_list, period)
        return adx_vals[-1] if adx_vals else 15.0

    @staticmethod
    def _calc_macd(
        closes: list,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
    ) -> dict:
        """
        MACD 계산.
        반환: {"macd_line", "signal_line", "histogram", "histogram_prev"}
        데이터 부족 시 모두 0.0.
        """
        _zero = {"macd_line": 0.0, "signal_line": 0.0,
                 "histogram": 0.0, "histogram_prev": 0.0}
        if len(closes) < slow_period + signal_period:
            return _zero

        def _ema(data, p):
            m = 2 / (p + 1)
            result = [sum(data[:p]) / p]
            for i in range(p, len(data)):
                result.append((data[i] - result[-1]) * m + result[-1])
            return result

        fast = _ema(closes, fast_period)
        slow = _ema(closes, slow_period)
        offset = len(fast) - len(slow)
        macd_vals = [fast[offset + i] - slow[i] for i in range(len(slow))]

        if len(macd_vals) < signal_period:
            return {**_zero, "macd_line": macd_vals[-1] if macd_vals else 0.0}

        sig_vals = _ema(macd_vals, signal_period)
        sig_off = len(macd_vals) - len(sig_vals)
        hists = [macd_vals[sig_off + i] - sig_vals[i] for i in range(len(sig_vals))]

        return {
            "macd_line":      round(macd_vals[-1], 4),
            "signal_line":    round(sig_vals[-1], 4),
            "histogram":      round(hists[-1], 4) if hists else 0.0,
            "histogram_prev": round(hists[-2], 4) if len(hists) >= 2 else 0.0,
        }

    def _get_trend_threshold(self, market_phase: str = None) -> float:
        """
        시장 국면에 따라 추세 필터 통과 기준을 조정한다.
        1순위: conditional_win_rates.csv 실증 승률 기반 동적 계산
        2순위: 하드코딩 fallback
        """
        # 1순위: 실증 데이터
        self._load_analysis_data()
        wr_data = self._analysis_cache.get("win_rates")
        if wr_data and market_phase and market_phase in wr_data:
            info = wr_data[market_phase]
            wr = info.get("overall_win_rate", 0.5)
            n = info.get("total_n", 0)
            if n >= 20:
                # 승률→임계값: wr=0.7→0.35, wr=0.5→0.55, wr=0.3→0.75
                threshold = round(1.05 - wr, 2)
                return max(0.30, min(0.80, threshold))

        # 2순위: fallback
        fallback = {
            "대상승장": 0.40, "상승장": 0.45, "일반장": 0.50,
            "변동폭큰": 0.55, "하락장": 0.60, "대폭락장": 0.70,
        }
        if market_phase and market_phase in fallback:
            return fallback[market_phase]
        return 0.50

    def check_trend_filter(
        self,
        symbol: str,
        price_data: dict,
        market_phase: str = None,
    ) -> dict:
        """
        개별 종목의 추세 상태를 종합 점수(0.0~1.0)로 평가한다.

        price_data 키: closes, highs, lows, volumes (각각 list[float], 오래된→최신)
        반환: {symbol, trend, trend_score, pass, details, pass_threshold, reason}
        """
        closes  = price_data["closes"]
        highs   = price_data["highs"]
        lows    = price_data["lows"]
        volumes = price_data["volumes"]
        current_price = closes[-1]

        # ── 지표 계산 ──
        ma_20  = sum(closes[-20:]) / 20
        ma_50  = sum(closes[-50:]) / 50
        ma_200 = sum(closes[-200:]) / 200 if len(closes) >= 200 else sum(closes) / len(closes)

        rsi_14 = self._calc_rsi(closes, period=14)
        adx_14 = self._calc_adx(highs, lows, closes, period=14)
        macd   = self._calc_macd(closes)

        vol_avg_20   = sum(volumes[-20:]) / 20
        volume_ratio = volumes[-1] / vol_avg_20 if vol_avg_20 > 0 else 1.0

        # ── 점수 (총 9점 만점) ──
        score     = 0
        max_score = 9
        details   = {}

        # 1) MA 배열 (3점)
        if current_price > ma_20 > ma_50:
            ma_score, ma_st = 3, "정배열 (가격 > 20MA > 50MA)"
        elif current_price > ma_50 > ma_200:
            ma_score, ma_st = 2, "중기 정배열 (가격 > 50MA > 200MA)"
        elif current_price > ma_50:
            ma_score, ma_st = 1.5, "50MA 위"
        elif current_price > ma_200:
            ma_score, ma_st = 1, "200MA 위 (약한 상승)"
        else:
            ma_score, ma_st = 0, "주요 MA 하회 (하락추세)"
        score += ma_score
        details["ma_alignment"] = {
            "score": ma_score, "max": 3, "status": ma_st,
            "values": {"price": round(current_price), "ma_20": round(ma_20),
                       "ma_50": round(ma_50), "ma_200": round(ma_200)},
        }

        # 2) RSI (2점)
        if 40 <= rsi_14 <= 65:
            rsi_sc, rsi_st = 2, f"건강한 상승 범위 ({rsi_14:.1f})"
        elif 30 <= rsi_14 < 40:
            rsi_sc, rsi_st = 1.5, f"반등 가능 영역 ({rsi_14:.1f})"
        elif 65 < rsi_14 <= 70:
            rsi_sc, rsi_st = 1, f"과매수 경계 ({rsi_14:.1f})"
        elif rsi_14 < 30:
            rsi_sc, rsi_st = 0.5, f"극심한 과매도 ({rsi_14:.1f})"
        else:
            rsi_sc, rsi_st = 0, f"과매수 ({rsi_14:.1f})"
        score += rsi_sc
        details["rsi"] = {"score": rsi_sc, "max": 2,
                          "value": round(rsi_14, 1), "status": rsi_st}

        # 3) ADX (2점)
        if adx_14 >= 25:
            adx_sc, adx_st = 2, f"강한 추세 ({adx_14:.1f})"
        elif adx_14 >= 20:
            adx_sc, adx_st = 1, f"보통 추세 ({adx_14:.1f})"
        elif adx_14 >= 15:
            adx_sc, adx_st = 0.5, f"약한 추세 ({adx_14:.1f})"
        else:
            adx_sc, adx_st = 0, f"추세 없음/횡보 ({adx_14:.1f})"
        score += adx_sc
        details["adx"] = {"score": adx_sc, "max": 2,
                          "value": round(adx_14, 1), "status": adx_st}

        # 4) MACD (1점)
        hist      = macd["histogram"]
        hist_prev = macd["histogram_prev"]
        if hist > 0 and hist > hist_prev:
            mc_sc, mc_st = 1, "상승 모멘텀 강화"
        elif hist > 0:
            mc_sc, mc_st = 0.7, "상승 모멘텀 (둔화)"
        elif hist < 0 and hist > hist_prev:
            mc_sc, mc_st = 0.3, "하락 모멘텀 약화 (회복 징후)"
        else:
            mc_sc, mc_st = 0, "하락 모멘텀"
        score += mc_sc
        details["macd"] = {"score": mc_sc, "max": 1,
                           "histogram": round(hist, 2), "status": mc_st}

        # 5) 거래량 (1점)
        if volume_ratio >= 1.2:
            vs, vst = 1, f"활발 ({volume_ratio:.1f}배)"
        elif volume_ratio >= 0.8:
            vs, vst = 0.7, f"정상 ({volume_ratio:.1f}배)"
        elif volume_ratio >= 0.5:
            vs, vst = 0.3, f"부족 ({volume_ratio:.1f}배)"
        else:
            vs, vst = 0, f"매우 부족 ({volume_ratio:.1f}배)"
        score += vs
        details["volume"] = {"score": vs, "max": 1,
                             "ratio": round(volume_ratio, 2), "status": vst}

        # ── 최종 판정 ──
        trend_score    = round(score / max_score, 3)
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

        # 판정 근거
        factors = sorted([
            (details["ma_alignment"]["score"] / 3, "MA배열"),
            (details["rsi"]["score"] / 2,          "RSI"),
            (details["adx"]["score"] / 2,          "ADX"),
            (details["macd"]["score"] / 1,         "MACD"),
            (details["volume"]["score"] / 1,       "거래량"),
        ], key=lambda x: x[0], reverse=True)
        strong = [f[1] for f in factors if f[0] >= 0.7]
        weak   = [f[1] for f in factors if f[0] < 0.3]

        parts = []
        if strong:
            parts.append(f"강점: {', '.join(strong)}")
        if weak:
            parts.append(f"약점: {', '.join(weak)}")
        reason = f"trend_score={trend_score:.2f} ({trend}). {'. '.join(parts)}"

        return {
            "symbol":         symbol,
            "trend":          trend,
            "trend_score":    trend_score,
            "pass":           passed,
            "details":        details,
            "pass_threshold": pass_threshold,
            "reason":         reason,
        }

    def _load_trend_price_data(self, symbol: str):
        """
        히스토리 CSV에서 OHLCV 데이터를 로드하여
        check_trend_filter() 입력 형식으로 변환한다.
        """
        from data.history.history_loader import _SYMBOL_MAP
        import pandas as pd

        path = _SYMBOL_MAP.get(symbol)
        if path is None or not path.exists():
            return None
        try:
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            # 컬럼명 통일 (한글/영문 모두 대응)
            col_map = {}
            for c in df.columns:
                cl = c.lower().strip()
                if cl in ("시가", "open"):
                    col_map["open"] = c
                elif cl in ("고가", "high"):
                    col_map["high"] = c
                elif cl in ("저가", "low"):
                    col_map["low"] = c
                elif cl in ("종가", "close"):
                    col_map["close"] = c
                elif cl in ("거래량", "volume"):
                    col_map["volume"] = c

            needed = {"high", "low", "close", "volume"}
            if not needed.issubset(col_map.keys()):
                return None

            df = df.dropna(subset=[col_map[k] for k in needed])
            n = min(len(df), 250)
            tail = df.tail(n)

            result = {
                "closes":  tail[col_map["close"]].astype(float).tolist(),
                "highs":   tail[col_map["high"]].astype(float).tolist(),
                "lows":    tail[col_map["low"]].astype(float).tolist(),
                "volumes": tail[col_map["volume"]].astype(float).tolist(),
            }
            if "open" in col_map:
                result["opens"] = tail[col_map["open"]].astype(float).tolist()
            return result
        except Exception:
            return None

    def check_trend_batch(
        self,
        candidates: list,
        market_phase: str = None,
    ) -> dict:
        """
        여러 종목을 일괄 평가하고 통과/실패로 분류한다.

        candidates:
            [{"symbol": "005930", "price_data": {...}}, ...]
            price_data가 없으면 히스토리 CSV에서 자동 로드.
        반환:
            {"passed": [...], "filtered_out": [...], "summary": {...}}
        """
        passed, filtered = [], []

        for c in candidates:
            sym = c.get("symbol", "")
            pdata = c.get("price_data")

            # price_data 미제공 시 히스토리에서 로드
            if pdata is None:
                hist_sym = c.get("history_symbol")
                if hist_sym:
                    pdata = self._load_trend_price_data(hist_sym)
            if pdata is None:
                continue
            if len(pdata.get("closes", [])) < 50:
                continue

            try:
                result = self.check_trend_filter(sym, pdata, market_phase)
                result["name"] = c.get("name", sym)
                result["history_symbol"] = c.get("history_symbol", "")
                if result["pass"]:
                    passed.append(result)
                else:
                    filtered.append(result)
            except Exception:
                continue

        passed.sort(key=lambda x: x["trend_score"], reverse=True)

        total   = len(passed) + len(filtered)
        p_count = len(passed)
        f_count = total - p_count

        return {
            "passed":       passed,
            "filtered_out": filtered,
            "summary": {
                "total":              total,
                "passed":             p_count,
                "filtered":           f_count,
                "pass_rate":          round(p_count / total, 2) if total > 0 else 0,
                "avg_score_passed":   round(sum(r["trend_score"] for r in passed) / p_count, 3) if p_count > 0 else 0,
                "avg_score_filtered": round(sum(r["trend_score"] for r in filtered) / f_count, 3) if f_count > 0 else 0,
                "phase":              market_phase or "기본",
                "threshold":          self._get_trend_threshold(market_phase),
            },
        }

    # ------------------------------------------------------------------
    # 가격 예측 (보유종목 1주/1개월 목표가)
    # ------------------------------------------------------------------

    # 종목코드 → HistoryLoader 심볼 + 상관 US 지표
    _STOCK_FORECAST_MAP = {
        "005930": {"symbol": "samsung",     "us": "sox"},
        "000660": {"symbol": "sk_hynix",    "us": "sox"},
        "042700": {"symbol": "hanmi_semi",  "us": "sox"},
        "373220": {"symbol": "lg_energy",   "us": "tesla"},
        "006400": {"symbol": "samsung_sdi", "us": "tesla"},
        "096770": {"symbol": "sk_inno",     "us": "wti"},
        "010950": {"symbol": "sk_inno",     "us": "wti"},   # S-Oil도 WTI 연동
    }

    # 종목코드 → 섹터 매핑 (업종 평균 PBR 조회용)
    _STOCK_SECTOR_MAP = {
        "005930": "반도체", "000660": "반도체", "042700": "반도체",
        "373220": "2차전지", "006400": "2차전지",
        "096770": "화학", "010950": "화학",
    }

    _SECTOR_AVG_PBR = {
        "반도체": 1.5, "2차전지": 2.5, "화학": 0.9,
        "자동차": 0.7, "바이오": 3.0, "은행": 0.5,
        "방산": 1.8, "IT": 2.0, "철강": 0.6, "건설": 0.7,
    }

    _SECTOR_AVG_PER = {
        "반도체": 15.0, "2차전지": 30.0, "화학": 10.0,
        "자동차": 8.0, "바이오": 50.0, "은행": 6.0,
        "방산": 20.0, "IT": 25.0, "철강": 8.0, "건설": 7.0,
    }

    def _get_sector_avg_pbr(self, code: str) -> float:
        """종목이 속한 섹터의 평균 PBR."""
        sector = self._STOCK_SECTOR_MAP.get(code, "")
        return self._SECTOR_AVG_PBR.get(sector, 1.2)

    def _get_sector_avg_per(self, code: str) -> float:
        """종목이 속한 섹터의 평균 PER."""
        sector = self._STOCK_SECTOR_MAP.get(code, "")
        return self._SECTOR_AVG_PER.get(sector, 15.0)

    def _get_cached_financial_data(self, code: str):
        """
        캐시된 재무 데이터 반환. 하루 1회 DB에서 로딩 후 메모리에 보관.
        """
        from datetime import datetime as _dt
        if not hasattr(self, "_fin_cache"):
            self._fin_cache = {}
            self._fin_cache_date = None

        today = _dt.now().strftime("%Y-%m-%d")
        if self._fin_cache_date != today:
            self._fin_cache = {}
            self._fin_cache_date = today

        if code not in self._fin_cache:
            try:
                from database.db import get_financial_indicators
                self._fin_cache[code] = get_financial_indicators(code)
            except Exception:
                self._fin_cache[code] = None

        return self._fin_cache.get(code)

    def _calc_fundamental_anchor(
        self, code: str, current_price: float, horizon_days: int
    ) -> float:
        """
        PBR/PER 기반 적정가를 추정하고, 현재가 괴리를 예측 가격으로 변환한다.
        재무 데이터 없으면 None 반환 (fallback 트리거).
        """
        fin = self._get_cached_financial_data(code)
        if not fin or not fin.get("bps") or not fin.get("pbr"):
            return None

        bps = float(fin["bps"])
        per = float(fin.get("per", 0))
        if bps <= 0:
            return None

        sector_avg_pbr = self._get_sector_avg_pbr(code)
        fair_value = bps * sector_avg_pbr
        if fair_value <= 0 or current_price <= 0:
            return None

        # 괴리율: 양수 = 저평가 (상승 여력), 음수 = 고평가 (상승 제한)
        discount_pct = (fair_value - current_price) / current_price * 100

        # 회귀 속도 (장기일수록 적정가에 가까이)
        if horizon_days <= 5:
            rev_rate = 0.05
        elif horizon_days <= 20:
            rev_rate = 0.15
        else:
            rev_rate = 0.30

        fund_return = discount_pct * rev_rate
        fund_return = max(-10.0, min(10.0, fund_return))

        # PER 보정
        if per > 50:
            fund_return -= 1.0
        elif 0 < per < 8:
            fund_return += 0.5

        # 적정가 기반 예측 가격 반환
        return current_price * (1 + fund_return / 100)

    def _generate_price_forecasts(
        self, positions: list, us: dict, kr: dict, comm: dict
    ) -> dict:
        """
        보유 종목별 1주/1개월 가격 예측.
        모멘텀(60/25%) + 평균회귀(15/45%) + 미국연동(25/30%) 가중 합산.
        """
        try:
            from data.history.history_loader import get_loader
            hl = get_loader()
        except Exception:
            return {}

        vix_val = us.get("vix", {}).get("value", 0) or 0
        vix_discount = max(0.9, 1.0 - max(0, vix_val - 25) * 0.005)

        forecasts = {}
        for pos in positions:
            code = pos.get("code", "")
            avg_price = float(pos.get("avg_price", 0))
            mapping = self._STOCK_FORECAST_MAP.get(code)
            if not mapping or avg_price <= 0:
                continue

            symbol = mapping["symbol"]
            us_indicator = mapping["us"]

            try:
                forecast = self._forecast_single(
                    hl, symbol, us_indicator, avg_price, us, comm, vix_discount
                )
                if forecast:
                    forecasts[code] = forecast
            except Exception as exc:
                self.log("debug", f"예측 실패 {code}: {exc}")

        return forecasts

    def _forecast_single(
        self, hl, symbol: str, us_indicator: str,
        avg_price: float, us: dict, comm: dict, vix_discount: float
    ) -> dict:
        """단일 종목 가격 예측."""
        # 종가 시리즈 로드
        hist = hl.historical_range(symbol, 60)
        if hist is None:
            return {}

        current = float(hist["latest"])
        mean_60 = float(hist["mean"])
        std_60 = float(hist["std"]) if hist["std"] > 0 else current * 0.02

        # === 모멘텀 ===
        close_series = hl._load_close(symbol)
        if close_series is None or len(close_series) < 6:
            return {}

        c = close_series.values
        daily_mom = (float(c[-1]) / float(c[-6]) - 1) / 5
        target_1w_mom = current * (1 + daily_mom * 5 * 0.8)
        target_1m_mom = current * (1 + daily_mom * 20 * 0.5)

        # === 평균회귀 ===
        z = (current - mean_60) / std_60
        target_1w_rev = current - z * 0.3 * std_60 * 0.25
        target_1m_rev = current - z * 0.3 * std_60

        # === 미국연동 ===
        us_change = 0.0
        if us_indicator == "sox":
            us_change = us.get("sox", {}).get("change_pct", 0) or 0
        elif us_indicator == "tesla":
            indiv = us.get("individual", {})
            us_change = indiv.get("TSLA", {}).get("change_pct", 0) or 0
        elif us_indicator == "wti":
            us_change = comm.get("wti", {}).get("change_pct", 0) or 0

        corr = self.get_lead_lag_corr_enhanced(us_indicator, symbol)
        corr_adj = current * us_change / 100 * corr * 0.5
        target_1w_corr = current + corr_adj
        target_1m_corr = current + corr_adj * 2

        # === 펀더멘탈 앵커 (4번째 컴포넌트) ===
        # _STOCK_FORECAST_MAP은 history 심볼(samsung)을 쓰지만 DB는 종목코드(005930)
        code_for_fin = ""
        for _c, _m in self._STOCK_FORECAST_MAP.items():
            if _m["symbol"] == symbol:
                code_for_fin = _c
                break

        fund_1w = self._calc_fundamental_anchor(code_for_fin, current, 5) if code_for_fin else None
        fund_1m = self._calc_fundamental_anchor(code_for_fin, current, 20) if code_for_fin else None

        # === 합산 (재무 데이터 있으면 4요소, 없으면 기존 3요소 fallback) ===
        if fund_1w is not None and fund_1m is not None:
            target_1w = (
                target_1w_mom * 0.45 + target_1w_rev * 0.15
                + target_1w_corr * 0.20 + fund_1w * 0.20
            ) * vix_discount
            target_1m = (
                target_1m_mom * 0.20 + target_1m_rev * 0.30
                + target_1m_corr * 0.20 + fund_1m * 0.30
            ) * vix_discount
        else:
            # 기존 3요소 가중치 유지 (재무 데이터 없는 종목)
            target_1w = (
                target_1w_mom * 0.60 + target_1w_rev * 0.15 + target_1w_corr * 0.25
            ) * vix_discount
            target_1m = (
                target_1m_mom * 0.25 + target_1m_rev * 0.45 + target_1m_corr * 0.30
            ) * vix_discount

        # === 신뢰도 ===
        confidence = 0.50
        if abs(daily_mom) > 0.005:
            confidence += 0.10
        if abs(z) < 1.0:
            confidence += 0.10
        if abs(corr) > 0.5:
            confidence += 0.10
        if vix_discount < 0.97:
            confidence -= 0.10
        confidence = max(0.2, min(0.85, confidence))

        # === 추세 판단 ===
        pct_1w = (target_1w / current - 1) * 100
        if pct_1w > 0.5:
            trend = "UP"
        elif pct_1w < -0.5:
            trend = "DOWN"
        else:
            trend = "SIDEWAYS"

        # === 과거 유사 RSI 기반 상승여력 분석 ===
        upside_p75 = 0.0
        upside_p90 = 0.0
        upside_days = 10
        try:
            import numpy as _np
            # RSI 14 계산
            delta = close_series.diff().tail(15)
            _gain = delta.clip(lower=0).mean()
            _loss = (-delta.clip(upper=0)).mean()
            rsi = 100 - 100 / (1 + _gain / _loss) if _loss > 0 else 50

            # 전체 기간 RSI 시리즈
            rsi_list = []
            for _i in range(14, len(close_series)):
                _d = close_series.iloc[_i-14:_i].diff().iloc[1:]
                _g = _d.clip(lower=0).mean()
                _l = (-_d.clip(upper=0)).mean()
                rsi_list.append(100 - 100/(1+_g/_l) if _l > 0 else 50)

            import pandas as _pd
            rsi_s = _pd.Series(rsi_list, index=close_series.index[14:])
            mask = (rsi_s >= max(30, rsi-10)) & (rsi_s <= min(70, rsi+10))
            sim_idx = rsi_s[mask].index

            fwd = []
            for _dt in sim_idx:
                _idx = close_series.index.get_loc(_dt)
                if _idx + upside_days < len(close_series):
                    fwd.append((float(close_series.iloc[_idx+upside_days]) / float(close_series.iloc[_idx]) - 1) * 100)

            if len(fwd) >= 30:
                upside_p75 = float(_np.percentile(fwd, 75))
                upside_p90 = float(_np.percentile(fwd, 90))
                # 상승여력이 있으면 target을 상향
                upside_target = current * (1 + upside_p75 / 100)
                if upside_target > target_1w:
                    target_1w = (target_1w + upside_target) / 2  # 기존 예측과 평균
                upside_target_1m = current * (1 + upside_p90 / 100)
                if upside_target_1m > target_1m:
                    target_1m = (target_1m + upside_target_1m) / 2
                # 신뢰도 보정
                if upside_p75 > 3:
                    confidence = min(0.85, confidence + 0.1)
        except Exception:
            pass

        # === 예측 로그 저장 ===
        try:
            from database.db import save_prediction_log
            for _hz, _tp, _tr in [(7, target_1w, target_1w_mom), (30, target_1m, target_1m_mom)]:
                save_prediction_log({
                    "symbol":              code_for_fin or symbol,
                    "horizon_days":        _hz,
                    "predicted_price":     round(_tp),
                    "predicted_return_pct": round((_tp / current - 1) * 100, 2),
                    "components": {
                        "momentum": round(_tr),
                        "mean_rev": round(target_1w_rev if _hz == 7 else target_1m_rev),
                        "us_corr":  round(target_1w_corr if _hz == 7 else target_1m_corr),
                        "fundamental": round(fund_1w or 0) if _hz == 7 else round(fund_1m or 0),
                        "has_fundamental": fund_1w is not None,
                    },
                })
        except Exception:
            pass

        return {
            "target_1w": round(target_1w),
            "target_1m": round(target_1m),
            "confidence": round(confidence, 2),
            "trend": trend,
            "current_price": round(current),
            "upside_p75": round(upside_p75, 2),
            "upside_p90": round(upside_p90, 2),
            "components": {
                "momentum_1w": round(target_1w_mom),
                "reversion_1w": round(target_1w_rev),
                "correlation_adj": round(corr_adj),
                "fundamental_1w": round(fund_1w) if fund_1w else None,
                "fundamental_1m": round(fund_1m) if fund_1m else None,
                "vix_discount": round(vix_discount, 3),
                "z_score": round(z, 2),
                "daily_momentum": round(daily_mom, 5),
            },
        }
