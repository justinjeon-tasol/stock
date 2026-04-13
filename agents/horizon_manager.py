"""
투자 기간(Horizon) 관리 서비스.

투자 기간 4단계:
  초단기 — 장중 1~3시간, 마감 전 강제 청산
  단기   — 1~3 거래일, 전일 미국 신호 기반
  중기   — 1~4주, 국면 유지 중 보유 + 트레일링 스탑
  장기   — 1~3개월, 트레일링 스탑 + 대폭락장 전환 청산

각 전략 카드의 holding_period 필드가 기간을 결정한다.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
from typing import Optional

logger = logging.getLogger(__name__)

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
    "horizon_config.json",
)

# 기본 설정 (JSON 로드 실패 시 fallback)
_FALLBACK_HORIZONS = {
    "초단기": {"max_hold_hours": 3,  "time_exit": "15:20", "take_profit_pct": 1.5,  "stop_loss_pct": -1.5,  "trailing_stop": False, "trailing_stop_pct": 0.0, "trailing_activate_pct": 0.0, "exit_on_phase_change": []},
    "단기":   {"max_hold_days":  5,  "time_exit": None,    "take_profit_pct": 10.0, "stop_loss_pct": -2.0,  "trailing_stop": True,  "trailing_stop_pct": 1.5, "trailing_activate_pct": 2.0, "exit_on_phase_change": ["하락장", "대폭락장"]},
    "중기":   {"max_hold_days":  20, "time_exit": None,    "take_profit_pct": 15.0, "stop_loss_pct": -3.0,  "trailing_stop": True,  "trailing_stop_pct": 2.5, "trailing_activate_pct": 3.0, "exit_on_phase_change": ["변동폭큰", "하락장", "대폭락장"]},
    "장기":   {"max_hold_days":  90, "time_exit": None,    "take_profit_pct": 25.0, "stop_loss_pct": -5.0,  "trailing_stop": True,  "trailing_stop_pct": 4.0, "trailing_activate_pct": 8.0, "exit_on_phase_change": ["하락장", "대폭락장"]},
}

_FALLBACK_PHASE_DEFAULT = {
    "대상승장": "중기",
    "상승장":   "단기",
    "일반장":   "단기",
    "변동폭큰": "초단기",
    "하락장":   "초단기",
    "대폭락장": "초단기",
}

# 청산 사유 상수
EXIT_TAKE_PROFIT   = "TAKE_PROFIT"
EXIT_STOP_LOSS     = "STOP_LOSS"
EXIT_TRAILING_STOP = "TRAILING_STOP"
EXIT_TIME_EXIT     = "TIME_EXIT"
EXIT_MAX_HOLD      = "MAX_HOLD"
EXIT_PHASE_CHANGE  = "PHASE_CHANGE"


class HorizonManager:
    """
    투자 기간별 매도 조건 판단 서비스.

    Executor와 PositionManager에서 공유한다.
    """

    def __init__(self) -> None:
        self._horizons: dict = {}
        self._phase_default: dict = {}
        self._load_config()

    def _load_config(self) -> None:
        try:
            with open(_CONFIG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
            self._horizons      = cfg.get("horizons", _FALLBACK_HORIZONS)
            self._phase_default = cfg.get("phase_default_horizon", _FALLBACK_PHASE_DEFAULT)
        except Exception as exc:
            logger.warning(f"horizon_config.json 로드 실패: {exc} → fallback 사용")
            self._horizons      = _FALLBACK_HORIZONS
            self._phase_default = _FALLBACK_PHASE_DEFAULT

    # ──────────────────────────────────────────────
    # 공개 헬퍼
    # ──────────────────────────────────────────────

    def get_horizon_params(self, holding_period: str) -> dict:
        """holding_period 문자열에 해당하는 파라미터 반환. 없으면 단기 기본값."""
        return self._horizons.get(holding_period, self._horizons.get("단기", {}))

    def default_horizon_for_phase(self, phase: str) -> str:
        """국면에 대한 기본 투자 기간 반환."""
        return self._phase_default.get(phase, "단기")

    def get_tp_sl(self, holding_period: str) -> tuple:
        """(take_profit_pct, stop_loss_pct) 반환."""
        p = self.get_horizon_params(holding_period)
        return float(p.get("take_profit_pct", 2.5)), float(p.get("stop_loss_pct", -1.5))

    def calc_max_exit_date(self, holding_period: str, entry_dt: datetime) -> Optional[datetime]:
        """최대 보유 만기일 계산. 초단기는 당일 time_exit 기준."""
        p = self.get_horizon_params(holding_period)
        if holding_period == "초단기":
            # 당일 time_exit (예: '15:20')
            time_str = p.get("time_exit", "15:20")
            hh, mm = int(time_str[:2]), int(time_str[3:])
            exit_dt = entry_dt.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if exit_dt <= entry_dt:            # 이미 지났으면 다음 거래일 같은 시간
                exit_dt += timedelta(days=1)
            return exit_dt
        days = p.get("max_hold_days")
        if days:
            return entry_dt + timedelta(days=days)
        return None

    # ──────────────────────────────────────────────
    # 청산 조건 판단 (핵심 메서드)
    # ──────────────────────────────────────────────

    def check_exit(
        self,
        position: dict,
        current_price: float,
        current_phase: str,
        current_dt: Optional[datetime] = None,
    ) -> Optional[str]:
        """
        포지션의 청산 조건을 종합적으로 판단한다.

        Parameters
        ----------
        position     : DB 포지션 레코드 (avg_price, holding_period, entry_time,
                       peak_price, max_exit_date 포함)
        current_price: 현재 주가
        current_phase: 현재 시장 국면
        current_dt   : 현재 시각 (None이면 datetime.now())

        Returns
        -------
        EXIT_* 상수 문자열 또는 None (청산 불필요)
        """
        if current_dt is None:
            current_dt = datetime.now(KST)

        holding_period = position.get("holding_period", "단기")
        avg_price      = float(position.get("avg_price", 0))
        peak_price     = float(position.get("peak_price") or avg_price)
        entry_time_str = position.get("entry_time")
        max_exit_str   = position.get("max_exit_date")

        if avg_price <= 0:
            return None

        p = self.get_horizon_params(holding_period)
        pnl_pct = (current_price - avg_price) / avg_price * 100

        # 1. 손절 (모든 기간 공통)
        sl = float(p.get("stop_loss_pct", -1.5))
        if pnl_pct <= sl:
            return EXIT_STOP_LOSS

        # 2. 익절
        tp = float(p.get("take_profit_pct", 2.5))
        if pnl_pct >= tp:
            return EXIT_TAKE_PROFIT

        # 3. 트레일링 스탑 (중기/장기)
        if p.get("trailing_stop"):
            activate_pct    = float(p.get("trailing_activate_pct", 3.0))
            trailing_pct    = float(p.get("trailing_stop_pct", 2.0))
            peak_pnl        = (peak_price - avg_price) / avg_price * 100
            drawdown_from_peak = (current_price - peak_price) / peak_price * 100

            if peak_pnl >= activate_pct and drawdown_from_peak <= -trailing_pct:
                return EXIT_TRAILING_STOP

        # 4. 시간 청산 (초단기: 장 마감 전 강제, KST 기준)
        if holding_period == "초단기":
            time_exit_str = p.get("time_exit", "15:20")
            hh, mm = int(time_exit_str[:2]), int(time_exit_str[3:])
            local_dt = current_dt.astimezone(KST) if current_dt.tzinfo else current_dt
            if local_dt.hour > hh or (local_dt.hour == hh and local_dt.minute >= mm):
                return EXIT_TIME_EXIT

        # 5. 최대 보유일 초과
        if max_exit_str:
            try:
                max_exit_dt = datetime.fromisoformat(max_exit_str)
                if max_exit_dt.tzinfo is None:
                    max_exit_dt = max_exit_dt.replace(tzinfo=timezone.utc)
                if current_dt.tzinfo is None:
                    current_dt = current_dt.replace(tzinfo=timezone.utc)
                if current_dt >= max_exit_dt:
                    return EXIT_MAX_HOLD
            except ValueError:
                pass

        # 6. 국면 전환 청산 (중기/장기/단기)
        exit_phases = p.get("exit_on_phase_change", [])
        if exit_phases and current_phase in exit_phases:
            return EXIT_PHASE_CHANGE

        return None

    def update_peak_price(self, position: dict, current_price: float) -> float:
        """
        peak_price를 현재가로 갱신. 갱신된 값을 반환.
        트레일링 스탑 계산에 사용.
        """
        peak = float(position.get("peak_price") or position.get("avg_price", 0))
        return max(peak, current_price)

    # ──────────────────────────────────────────────
    # 요약 출력
    # ──────────────────────────────────────────────

    def describe(self, holding_period: str) -> str:
        """투자 기간 요약 문자열 반환."""
        p = self.get_horizon_params(holding_period)
        tp, sl = p.get("take_profit_pct", 0), p.get("stop_loss_pct", 0)
        days   = p.get("max_hold_days", p.get("max_hold_hours", "?"))
        unit   = "일" if "max_hold_days" in p else "시간"
        trail  = f" / 트레일링:{p.get('trailing_stop_pct', 0)}%" if p.get("trailing_stop") else ""
        return (
            f"{holding_period} | TP:{tp:+.1f}% SL:{sl:+.1f}% | "
            f"최대보유:{days}{unit}{trail}"
        )

    # ──────────────────────────────────────────────
    # 동적 기간 변경 제안
    # ──────────────────────────────────────────────

    # 업그레이드/다운그레이드 순서
    _HORIZON_ORDER = ["초단기", "단기", "중기", "장기"]

    def suggest_horizon_change(
        self,
        position: dict,
        current_phase: str,
        pnl_pct: float,
    ) -> Optional[str]:
        """
        현재 국면과 수익률을 기반으로 holding_period 변경을 제안한다.

        업그레이드 (더 긴 기간):
          - 초단기→단기: 일반장 이상 + pnl > 0%
          - 단기→중기:  상승장 이상 + pnl > +1.0%
          - 중기→장기:  대상승장   + pnl > +3.0%

        다운그레이드 (더 짧은 기간):
          - 장기→중기:  변동폭큰 이하 국면
          - 중기→단기:  하락장 국면
          - 단기→초단기: 대폭락장 국면

        반환: 새 holding_period 문자열 또는 None (변경 없음)
        """
        current_hp = position.get("holding_period", "단기")
        if current_hp not in self._HORIZON_ORDER:
            return None

        idx = self._HORIZON_ORDER.index(current_hp)

        # ── 다운그레이드 규칙 (안전 우선, 먼저 평가) ──
        downgrade_rules = {
            "대폭락장": ("단기",   0),   # 대폭락장 → 최대 단기까지 (초단기는 수동)
            "하락장":   ("단기",   1),
            "변동폭큰": ("중기",   2),
        }
        if current_phase in downgrade_rules:
            target_hp, target_idx = downgrade_rules[current_phase]
            if idx > target_idx:
                return target_hp

        # ── 업그레이드 규칙 ──
        upgrade_rules = [
            # (최소 국면, 최소 pnl, 현재→다음 기간)
            ("일반장",  0.0,  "초단기", "단기"),
            ("상승장",  1.0,  "단기",   "중기"),
            ("대상승장", 3.0, "중기",   "장기"),
        ]
        _PHASE_RANK = {
            "일반장": 1, "상승장": 2, "대상승장": 3,
            "변동폭큰": 0, "하락장": 0, "대폭락장": 0,
        }
        current_rank = _PHASE_RANK.get(current_phase, 0)

        for min_phase, min_pnl, from_hp, to_hp in upgrade_rules:
            min_rank = _PHASE_RANK.get(min_phase, 0)
            if current_rank >= min_rank and pnl_pct >= min_pnl and current_hp == from_hp:
                return to_hp

        return None

    def get_all_horizons(self) -> list:
        """정의된 모든 투자 기간 목록 반환."""
        return list(self._horizons.keys())
