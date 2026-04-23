"""
RiskManager.check_sector_concentration_limit 단위 테스트 (BT-02).

외부 의존(DB, KIS API) 없이 config 주입만으로 동작 검증.
"""
from __future__ import annotations

import pytest

from agents.risk_manager import RiskManager


def _make_rm(cfg: dict) -> RiskManager:
    """risk_config.json 로드를 건너뛰고 테스트용 config를 직접 주입."""
    rm = RiskManager.__new__(RiskManager)
    rm._config = cfg
    return rm


def _default_cfg(**sector_overrides) -> dict:
    """sector_concentration_limit 설정이 포함된 기본 config."""
    base = {
        "max_positions_by_phase": {
            "대상승장": 7,
            "상승장": 4,
            "일반장": 3,
            "변동폭큰": 2,
            "하락장": 1,
            "대폭락장": 1,
        },
        "sector_concentration_limit": {
            "enabled": True,
            "max_single_sector_ratio": 0.50,
            "by_phase_override": {
                "일반장": 0.30,
                "변동폭큰": 0.40,
            },
            "action_when_exceeded": "BLOCK_NEW_ENTRY",
        },
    }
    base["sector_concentration_limit"].update(sector_overrides)
    return base


# ----------------------------------------------------------
# 기본 동작 (enabled = True, cap = 0.50)
# ----------------------------------------------------------

def test_allow_when_no_holdings():
    rm = _make_rm(_default_cfg())
    allowed, reason = rm.check_sector_concentration_limit("반도체", [], "상승장")
    assert allowed is True
    assert reason == ""


def test_allow_when_under_cap():
    # 상승장 max_pos=4, 현재 반도체 1개 → 추가 시 2/4=50% == cap 0.50
    # 0.50 초과(> cap)가 아니므로 허용
    rm = _make_rm(_default_cfg())
    allowed, _ = rm.check_sector_concentration_limit(
        "반도체", ["반도체"], "상승장",
    )
    assert allowed is True


def test_block_when_exceeds_cap():
    # 상승장 max_pos=4, 반도체 2개 보유 → 추가 시 3/4=75% > cap 0.50 → 차단
    rm = _make_rm(_default_cfg())
    allowed, reason = rm.check_sector_concentration_limit(
        "반도체", ["반도체", "반도체"], "상승장",
    )
    assert allowed is False
    assert "반도체" in reason
    assert "75%" in reason
    assert "50%" in reason


def test_block_matches_bt02_scenario():
    """4/23 시나리오: 2차전지 2포지션 상태에서 3번째 2차전지 진입."""
    rm = _make_rm(_default_cfg())
    allowed, reason = rm.check_sector_concentration_limit(
        "2차전지", ["2차전지", "2차전지"], "상승장",
    )
    assert allowed is False
    assert "2차전지" in reason


def test_different_sectors_allowed():
    # 반도체 1개, 2차전지 1개 보유 상태에서 3번째 반도체 진입
    # 같은 섹터만 카운트 → 2/4 = 50% (<= 0.50은 허용)
    rm = _make_rm(_default_cfg())
    allowed, _ = rm.check_sector_concentration_limit(
        "반도체", ["반도체", "2차전지"], "상승장",
    )
    assert allowed is True


# ----------------------------------------------------------
# 국면별 override
# ----------------------------------------------------------

def test_stricter_cap_in_normal_phase():
    # 일반장 cap=0.30, max_pos=3 → 반도체 1개 보유 상태에서 추가 시 2/3=66.7% > 0.30 → 차단
    rm = _make_rm(_default_cfg())
    allowed, reason = rm.check_sector_concentration_limit(
        "반도체", ["반도체"], "일반장",
    )
    assert allowed is False
    assert "30%" in reason


def test_stricter_cap_in_volatile_phase():
    # 변동폭큰 cap=0.40, max_pos=2 → 반도체 0개 보유 → 추가 시 1/2=50% > 0.40 → 차단
    rm = _make_rm(_default_cfg())
    allowed, reason = rm.check_sector_concentration_limit(
        "반도체", [], "변동폭큰",
    )
    assert allowed is False
    assert "40%" in reason


def test_phase_fallback_to_default_cap():
    # 대상승장은 override 없음 → default 0.50 사용
    # 대상승장 max_pos=7, 반도체 3개 보유 → 추가 시 4/7=57.1% > 0.50 → 차단
    rm = _make_rm(_default_cfg())
    allowed, reason = rm.check_sector_concentration_limit(
        "반도체", ["반도체"] * 3, "대상승장",
    )
    assert allowed is False

    # 반도체 2개만 보유 → 3/7=42.9% < 0.50 → 허용
    allowed, _ = rm.check_sector_concentration_limit(
        "반도체", ["반도체"] * 2, "대상승장",
    )
    assert allowed is True


# ----------------------------------------------------------
# disabled 케이스
# ----------------------------------------------------------

def test_disabled_always_allows():
    cfg = _default_cfg(enabled=False)
    rm = _make_rm(cfg)
    # cap을 한참 초과해도 enabled=False면 통과
    allowed, reason = rm.check_sector_concentration_limit(
        "반도체", ["반도체"] * 10, "상승장",
    )
    assert allowed is True
    assert reason == ""


def test_missing_section_defaults_to_allow():
    # sector_concentration_limit 섹션 자체가 없을 때
    cfg = {"max_positions_by_phase": {"상승장": 4}}
    rm = _make_rm(cfg)
    allowed, _ = rm.check_sector_concentration_limit(
        "반도체", ["반도체"] * 5, "상승장",
    )
    assert allowed is True


# ----------------------------------------------------------
# 엣지 케이스
# ----------------------------------------------------------

def test_zero_max_positions_allows():
    cfg = _default_cfg()
    cfg["max_positions_by_phase"]["상승장"] = 0
    rm = _make_rm(cfg)
    allowed, _ = rm.check_sector_concentration_limit(
        "반도체", [], "상승장",
    )
    # max_pos=0 일 때는 division 보호, True 반환 (이 경로에선 상위 레벨이 한도로 차단)
    assert allowed is True


def test_unknown_phase_uses_default_cap():
    # 알 수 없는 phase는 fallback: get_max_positions 기본값 3 + default cap 0.50
    rm = _make_rm(_default_cfg())
    # 반도체 1개 보유 → 2/3=66.7% > 0.50 → 차단
    allowed, _ = rm.check_sector_concentration_limit(
        "반도체", ["반도체"], "unknown_phase",
    )
    assert allowed is False
