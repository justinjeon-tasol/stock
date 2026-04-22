"""
리스크 관리 서비스 모듈.
Daily Stop Loss, 연속 손실 감지, 국면별 포지션 제한, 장 시간대 제어를 담당한다.
BaseAgent를 상속하지 않는 순수 서비스 클래스.
Orchestrator, WeightAdjuster, Executor에서 의존성 주입으로 사용한다.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
    "risk_config.json",
)

# 기본값 (JSON 로드 실패 시 fallback)
_FALLBACK_CONFIG = {
    "daily_stop_loss": {
        "max_daily_loss_pct": -3.0,
        "max_weekly_loss_pct": -5.0,
        "cooldown_hours": 24,
        "action": "HALT_NEW_ENTRY",
    },
    "consecutive_loss": {
        "trigger_count": 3,
        "reduce_aggressive_by": 0.5,
        "recovery_condition": "1_win",
    },
    "max_positions_by_phase": {
        "대상승장": 5, "상승장": 4, "일반장": 3,
        "변동폭큰": 2, "하락장": 1, "대폭락장": 1,
    },
    "market_session": {
        "no_entry_before": "09:30",
        "force_close_after": "15:20",
    },
    "sector_correlation": {
        "same_sector_dampen": 0.5,
    },
}


class RiskManager:
    """
    다층 리스크 관리 서비스.

    기능:
    1. Daily Stop Loss: 일일/주간 최대 손실 한도 초과 시 신규 매수 차단
    2. 연속 손실 감지: 연속 N회 손절 시 aggressive 비중 축소
    3. 국면별 포지션 제한: 시장 국면에 따라 최대 동시 보유 수 제한
    4. 장 시간대 제어: 변동성 구간 진입 보류
    5. 섹터 상관관계: 동일 섹터 중복 보유 시 비중 감쇠
    """

    def __init__(self) -> None:
        self._config: dict = {}
        self._load_config()

    def _load_config(self) -> None:
        """risk_config.json을 로드한다. 실패 시 fallback 사용."""
        try:
            with open(_CONFIG_PATH, encoding="utf-8") as f:
                self._config = json.load(f)
            logger.info("[리스크관리] risk_config.json 로드 완료")
        except Exception as exc:
            logger.warning(f"[리스크관리] risk_config.json 로드 실패: {exc} → fallback 사용")
            self._config = _FALLBACK_CONFIG

    # ------------------------------------------------------------------
    # 1. Daily Stop Loss
    # ------------------------------------------------------------------

    def check_daily_stop_loss(self, current_prices: dict = None) -> tuple[bool, float]:
        """
        오늘 (실현 + 미실현) 손익이 일일 최대 손실 한도를 초과했는지 확인한다.
        Mark-to-Market 기준: 실현 손익 + OPEN 포지션 미실현 손익 합산.

        Parameters
        ----------
        current_prices : {종목코드: 현재가} (없으면 avg_price 기준, 0% 가정)

        Returns
        -------
        (halted: bool, total_pnl: float)
            halted=True이면 신규 매수 중단.
        """
        dsl_config = self._config.get("daily_stop_loss", {})
        max_daily = float(dsl_config.get("max_daily_loss_pct", -3.0))

        # 1. 오늘 실현 손익
        try:
            from database.db import get_today_realized_pnl
            realized_pnl = get_today_realized_pnl()
        except Exception:
            realized_pnl = 0.0

        # 2. OPEN 포지션 미실현 손익 (mark-to-market, 가중 평균)
        unrealized_pnl = 0.0
        total_position_value = 0.0
        try:
            from database.db import get_open_positions_for_mtm
            positions = get_open_positions_for_mtm()
            current_prices = current_prices or {}
            for pos in positions:
                avg = float(pos.get("avg_price", 0))
                qty = int(pos.get("quantity", 0))
                code = pos.get("code", "")
                if avg <= 0 or qty <= 0:
                    continue
                cur = float(current_prices.get(code, 0))
                if cur <= 0:
                    continue  # 현재가 없으면 해당 포지션은 skip (보수적)
                position_value = avg * qty  # 포지션 평가금액
                pos_pnl_pct = (cur - avg) / avg * 100
                unrealized_pnl += pos_pnl_pct * position_value  # 가중 합산
                total_position_value += position_value
            if total_position_value > 0:
                unrealized_pnl = unrealized_pnl / total_position_value  # 가중 평균
            else:
                unrealized_pnl = 0.0
        except Exception:
            unrealized_pnl = 0.0

        total_pnl = realized_pnl + unrealized_pnl
        halted = total_pnl <= max_daily
        if halted:
            logger.critical(
                f"[리스크관리] Daily Stop Loss 발동: "
                f"실현={realized_pnl:+.2f}% + 미실현={unrealized_pnl:+.2f}% = "
                f"합계={total_pnl:+.2f}% ≤ 한도={max_daily}%"
            )
        return halted, round(total_pnl, 4)

    def check_weekly_stop_loss(self) -> tuple[bool, float]:
        """
        이번 주 실현 손익이 주간 최대 손실 한도를 초과했는지 확인한다.

        Returns
        -------
        (halted: bool, week_pnl: float)
            halted=True이면 신규 매수 중단.
        """
        dsl_config = self._config.get("daily_stop_loss", {})
        max_weekly = float(dsl_config.get("max_weekly_loss_pct", -5.0))

        try:
            from database.db import get_week_realized_pnl
            week_pnl = get_week_realized_pnl()
        except Exception:
            week_pnl = 0.0

        halted = week_pnl <= max_weekly
        if halted:
            logger.critical(
                f"[리스크관리] Weekly Stop Loss 발동: "
                f"이번 주 손익={week_pnl:+.2f}% ≤ 한도={max_weekly}%"
            )
        return halted, round(week_pnl, 4)

    # ------------------------------------------------------------------
    # 2. 연속 손실 감지
    # ------------------------------------------------------------------

    def check_consecutive_losses(self) -> tuple[bool, float]:
        """
        최근 청산 거래에서 연속 손실 여부를 확인한다.

        Returns
        -------
        (triggered: bool, dampen_factor: float)
            triggered=True이면 연속 손실 패턴 감지.
            dampen_factor: aggressive 비중에 곱할 감쇠 계수 (0.0~1.0)
                           감지되지 않으면 1.0 (감쇠 없음).
        """
        cl_config = self._config.get("consecutive_loss", {})
        trigger_count = int(cl_config.get("trigger_count", 3))
        reduce_by = float(cl_config.get("reduce_aggressive_by", 0.5))

        try:
            from database.db import get_recent_closed_trades
            recent = get_recent_closed_trades(limit=trigger_count + 2)
        except Exception:
            recent = []

        if len(recent) < trigger_count:
            return False, 1.0

        # 최근 trigger_count건이 모두 손실인지 확인
        consecutive_losses = 0
        for trade in recent:
            pnl = float(trade.get("result_pct", 0) or 0)
            if pnl < 0:
                consecutive_losses += 1
            else:
                break  # 이익 발생 → 연속 손실 중단

        triggered = consecutive_losses >= trigger_count
        dampen = reduce_by if triggered else 1.0

        if triggered:
            logger.warning(
                f"[리스크관리] 연속 손실 {consecutive_losses}회 감지 → "
                f"aggressive 비중 ×{dampen}"
            )

        return triggered, dampen

    # ------------------------------------------------------------------
    # 3. 국면별 최대 포지션 수
    # ------------------------------------------------------------------

    def get_max_positions(self, phase: str) -> int:
        """
        현재 국면에서 허용되는 최대 동시 보유 포지션 수를 반환한다.

        Parameters
        ----------
        phase : 시장 국면 (6단계)

        Returns
        -------
        int : 최대 포지션 수 (기본값 3)
        """
        mp_config = self._config.get("max_positions_by_phase", {})
        return int(mp_config.get(phase, 3))

    # ------------------------------------------------------------------
    # 4. 장 시간대 제어
    # ------------------------------------------------------------------

    def is_entry_allowed_now(self, now: Optional[datetime] = None) -> tuple[bool, str]:
        """
        현재 시간이 매수 허용 시간대인지 확인한다.

        Parameters
        ----------
        now : 현재 시각 (None이면 datetime.now())

        Returns
        -------
        (allowed: bool, reason: str)
            allowed=False이면 reason에 사유 기재.
        """
        if now is None:
            now = datetime.now()

        ms_config = self._config.get("market_session", {})
        no_entry_before = ms_config.get("no_entry_before", "09:30")

        # 시간 파싱
        try:
            hh, mm = int(no_entry_before[:2]), int(no_entry_before[3:])
        except (ValueError, IndexError):
            hh, mm = 9, 30

        current_hhmm = now.hour * 100 + now.minute
        block_hhmm = hh * 100 + mm

        if current_hhmm < block_hhmm:
            return False, f"장 시작 변동성 구간 ({no_entry_before} 이전) — 진입 보류"

        # 장 종료 후 (15:30 이후)
        if current_hhmm >= 1530:
            return False, "정규장 종료 — 진입 불가"

        return True, ""

    # ------------------------------------------------------------------
    # 5. 섹터 상관관계 체크
    # ------------------------------------------------------------------

    def get_sector_dampen_factor(
        self,
        target_sector: str,
        held_sectors: list[str],
    ) -> float:
        """
        매수 대상 섹터가 이미 보유 중인 섹터와 겹치면 감쇠 계수를 반환한다.

        Parameters
        ----------
        target_sector : 매수 대상 종목의 섹터
        held_sectors  : 현재 보유 포지션들의 섹터 리스트

        Returns
        -------
        float : 감쇠 계수 (겹치면 same_sector_dampen, 안 겹치면 1.0)
        """
        sc_config = self._config.get("sector_correlation", {})
        dampen = float(sc_config.get("same_sector_dampen", 0.5))

        if target_sector in held_sectors:
            return dampen
        return 1.0

    # ------------------------------------------------------------------
    # 유틸리티
    # ------------------------------------------------------------------

    def get_force_close_time(self) -> str:
        """초단기 강제 청산 시각을 반환한다."""
        ms_config = self._config.get("market_session", {})
        return ms_config.get("force_close_after", "15:20")

    # ------------------------------------------------------------------
    # 6. 회복 모드
    # ------------------------------------------------------------------

    def check_recovery_mode(self) -> bool:
        """회복 모드가 활성화되어 있는지 반환한다."""
        rc = self._config.get("recovery_mode", {})
        return bool(rc.get("enabled", False))

    def get_recovery_config(self) -> dict:
        """회복 모드 설정을 반환한다."""
        return self._config.get("recovery_mode", {})

    def get_recovery_size_ratio(self) -> float:
        """회복 모드 포지션 축소 비율을 반환한다."""
        rc = self._config.get("recovery_mode", {})
        return float(rc.get("position_size_ratio", 0.3))

    # ------------------------------------------------------------------
    # 7. 단일종목 집중도 제한 (CAP)
    # ------------------------------------------------------------------

    def check_concentration_limit(
        self,
        code: str,
        new_buy_amount: float,
        total_asset: float,
        existing_value: float = 0.0,
    ) -> tuple[float, bool]:
        """
        단일 종목의 (기존 평가액 + 신규 매수액)이 총자산 대비 한도를 넘지 않도록
        신규 매수 금액을 자동 축소(CAP)한다.

        Parameters
        ----------
        code            : 매수 대상 종목코드 (로그용)
        new_buy_amount  : 이번에 매수하려는 금액 (원)
        total_asset     : 총자산 평가액 (원)
        existing_value  : 이 종목의 현재 보유 평가액 (원, 없으면 0)

        Returns
        -------
        (capped_amount, was_capped)
            capped_amount : 집중도 한도 내로 축소된 매수 허용 금액 (원)
                             - 한도 미초과 시 = new_buy_amount 그대로
                             - 이미 한도 초과 시 = 0
            was_capped    : 축소가 발생했으면 True
        """
        cfg = self._config.get("concentration_limit", {})
        if not cfg.get("enabled", False):
            return float(new_buy_amount), False
        if total_asset <= 0 or new_buy_amount <= 0:
            return float(new_buy_amount), False

        max_ratio = float(cfg.get("max_single_stock_ratio", 0.25))
        max_allowed = total_asset * max_ratio
        headroom = max_allowed - float(existing_value)

        if headroom <= 0:
            logger.warning(
                f"[리스크관리] 집중도 한도 초과 ({code}): "
                f"기존 평가액 {existing_value:,.0f}원 ≥ 한도 {max_allowed:,.0f}원 "
                f"({max_ratio:.0%}) → 매수 금액 0원으로 CAP"
            )
            return 0.0, True

        if new_buy_amount <= headroom:
            return float(new_buy_amount), False

        logger.warning(
            f"[리스크관리] 집중도 한도 CAP ({code}): "
            f"요청 {new_buy_amount:,.0f}원 → 허용 {headroom:,.0f}원 "
            f"(기존 {existing_value:,.0f} + 한도 {max_allowed:,.0f}, "
            f"ratio={max_ratio:.0%})"
        )
        return float(headroom), True

    def get_config(self) -> dict:
        """현재 로드된 전체 리스크 설정을 반환한다."""
        return dict(self._config)

    def reload_config(self) -> None:
        """설정 파일을 디스크에서 다시 로드한다."""
        self._load_config()
