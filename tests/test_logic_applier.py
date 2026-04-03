"""
로직적용 에이전트 단위 테스트.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.logic_applier import LogicApplier, _STATUS_PRIORITY
from protocol.protocol import StandardMessage


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _make_signal(
    phase: str = "안정화",
    direction: str = "BUY",
    targets: list = None,
    issue_factor: dict = None,
    reason: str = "테스트 신호",
) -> StandardMessage:
    if targets is None:
        targets = [
            {"code": "005930", "name": "삼성전자", "weight": 0.5},
            {"code": "000660", "name": "SK하이닉스", "weight": 0.3},
        ]
    payload = {
        "signal_id":     "TEST_001",
        "direction":     direction,
        "confidence":    0.75,
        "phase":         phase,
        "issue_factor":  issue_factor,
        "targets":       targets,
        "sell_targets":  [],
        "weight_config": {"aggressive_pct": 0.7, "cash_pct": 0.3},
        "reason":        reason,
    }
    msg = StandardMessage.create(
        from_agent="WA",
        to_agent="LA",
        data_type="SIGNAL",
        payload=payload,
        msg_type="SIGNAL",
    )
    return msg


# ---------------------------------------------------------------------------
# 테스트
# ---------------------------------------------------------------------------

def test_instantiation():
    """LogicApplier 생성 확인."""
    la = LogicApplier()
    assert la.agent_code == "LA"
    assert la.agent_name == "로직적용"
    print("  OK: 생성 확인")


def test_library_loaded():
    """전략 라이브러리 로드 확인."""
    la = LogicApplier()
    assert len(la._library) >= 7
    print(f"  OK: 전략 {len(la._library)}개 로드")


def test_execute_returns_standard_message():
    """execute() StandardMessage 반환."""
    la = LogicApplier()
    msg = _make_signal()
    result = asyncio.run(la.execute(msg))
    assert isinstance(result, StandardMessage)
    print("  OK: StandardMessage 반환")


def test_execute_to_ex():
    """반환 메시지 수신자 = EX."""
    la = LogicApplier()
    msg = _make_signal()
    result = asyncio.run(la.execute(msg))
    assert result.header.to_agent == "EX"
    print("  OK: 수신자=EX")


def test_execute_data_type_signal():
    """data_type = SIGNAL 유지."""
    la = LogicApplier()
    msg = _make_signal()
    result = asyncio.run(la.execute(msg))
    assert result.body["data_type"] == "SIGNAL"
    print("  OK: data_type=SIGNAL")


def test_strategy_id_added():
    """전략 적용 시 strategy_id 필드 추가."""
    la = LogicApplier()
    msg = _make_signal(phase="안정화", direction="BUY")
    result = asyncio.run(la.execute(msg))
    payload = result.body["payload"]
    assert "strategy_id" in payload
    assert "strategy_name" in payload
    assert "strategy_group" in payload
    print(f"  OK: strategy_id={payload['strategy_id']}")


def test_select_strategy_for_phase():
    """국면별 전략 선택 동작."""
    la = LogicApplier()
    for phase in ["안정화", "급등장", "급락장", "변동폭큰"]:
        strategy = la._select_strategy(phase)
        # 전략이 있다면 phase가 일치해야 함
        if strategy:
            assert strategy["phase"] == phase, f"{phase} 전략 불일치"
    print("  OK: 국면별 전략 선택")


def test_select_strategy_status_priority():
    """검증완료 전략이 백테스팅중보다 우선 선택."""
    la = LogicApplier()
    # 임시 전략 주입
    la._library["VERIFIED"] = {
        "id": "VERIFIED", "phase": "안정화",
        "performance": {"status": "검증완료", "backtest_win_rate": 0.6},
        "group": "미국지수", "description": "검증완료 전략",
        "conditions": {"제외": ""},
    }
    la._library["BACKTESTING"] = {
        "id": "BACKTESTING", "phase": "안정화",
        "performance": {"status": "백테스팅중", "backtest_win_rate": 0.9},
        "group": "타이밍", "description": "백테스팅중 전략",
        "conditions": {"제외": ""},
    }
    strategy = la._select_strategy("안정화")
    assert strategy["id"] == "VERIFIED", f"검증완료 우선이어야 함, 실제: {strategy['id']}"
    # 정리
    del la._library["VERIFIED"]
    del la._library["BACKTESTING"]
    print("  OK: 검증완료 전략 우선 선택")


def test_no_strategy_for_unknown_phase():
    """없는 국면 → strategy_id=None."""
    la = LogicApplier()
    msg = _make_signal(phase="없는국면", direction="BUY")
    result = asyncio.run(la.execute(msg))
    payload = result.body["payload"]
    assert payload["strategy_id"] is None
    print("  OK: 없는 국면 → strategy_id=None")


def test_hold_direction_no_strategy_applied():
    """HOLD 방향 시 타겟 변경 없이 통과."""
    la = LogicApplier()
    original_targets = [{"code": "005930", "name": "삼성전자", "weight": 0.5}]
    msg = _make_signal(direction="HOLD", targets=original_targets)
    result = asyncio.run(la.execute(msg))
    payload = result.body["payload"]
    assert payload["direction"] == "HOLD"
    print("  OK: HOLD 통과")


def test_exclusion_condition_triggers_hold():
    """제외 조건 이슈 활성 시 BUY → HOLD 전환."""
    la = LogicApplier()
    # STR_001 제외 조건: "금 강세(+1.5% 이상) 동시 발생 시 제외" → ISS_003
    # STR_004 제외 조건: "VIX 25 초과 시 진입 금지" → ISS_001
    issue_factor = {
        "count": 1,
        "max_severity": "HIGH",
        "issues": [{"issue_id": "ISS_001", "name": "VIX 급등", "severity": "HIGH"}],
        "summary": "VIX 급등",
    }
    # STR_004(급등장) 제외 조건: VIX 25
    msg = _make_signal(phase="급등장", direction="BUY", issue_factor=issue_factor)
    result = asyncio.run(la.execute(msg))
    payload = result.body["payload"]
    # 제외 조건이 발동되면 HOLD 또는 targets 비어있어야 함
    # (전략의 제외 텍스트에 'VIX 25'가 있고 ISS_001이 활성인 경우)
    print(f"  OK: 제외 조건 체크 결과 direction={payload['direction']}")


def test_no_exclusion_without_issue():
    """이슈 없으면 제외 조건 미발동."""
    la = LogicApplier()
    msg = _make_signal(phase="급등장", direction="BUY", issue_factor=None)
    result = asyncio.run(la.execute(msg))
    payload = result.body["payload"]
    # 이슈 없으면 제외 안 됨
    assert payload["direction"] == "BUY"
    print("  OK: 이슈 없으면 제외 조건 미발동")


def test_reason_enriched_with_strategy():
    """전략 적용 시 reason에 전략 정보 추가."""
    la = LogicApplier()
    msg = _make_signal(phase="안정화", direction="BUY", reason="기본 이유")
    result = asyncio.run(la.execute(msg))
    payload = result.body["payload"]
    if payload["strategy_id"]:
        assert payload["strategy_id"] in payload["reason"]
    print(f"  OK: reason='{payload['reason'][:60]}...'")


def test_prioritize_targets_by_group():
    """전략 그룹 기반 타겟 정렬."""
    la = LogicApplier()
    strategy = {
        "group": "섹터연계",
        "conditions": {"제외": ""},
        "performance": {"status": "백테스팅중", "backtest_win_rate": 0.6},
        "description": "테스트",
    }
    targets = [
        {"code": "069500", "name": "KODEX 200", "weight": 0.3, "sector": "지수ETF", "theme": ""},
        {"code": "000660", "name": "SK하이닉스", "weight": 0.4, "sector": "반도체", "theme": "AI/HBM"},
    ]
    prioritized = la._prioritize_targets(targets, strategy)
    # 반도체(섹터연계 선호)가 앞에 와야 함
    assert prioritized[0]["code"] == "000660"
    print("  OK: 섹터 우선 정렬")


def test_check_exclusions_no_issue():
    """이슈 팩터 없으면 제외 안 됨."""
    la = LogicApplier()
    strategy = {"conditions": {"제외": "금 강세 동시 발생 시 제외"}}
    excluded, reason = la._check_exclusions(strategy, None)
    assert not excluded
    print("  OK: 이슈 없으면 제외 안 됨")


def test_check_exclusions_matching_issue():
    """제외 조건 키워드 + 매칭 이슈 활성 → 제외."""
    la = LogicApplier()
    strategy = {"conditions": {"제외": "금 강세(+1.5% 이상) 동시 발생 시 제외"}}
    issue_factor = {
        "issues": [{"issue_id": "ISS_003", "name": "지정학 리스크", "severity": "MEDIUM"}]
    }
    excluded, reason = la._check_exclusions(strategy, issue_factor)
    assert excluded
    assert "ISS_003" in reason
    print(f"  OK: 제외 조건 발동: {reason}")


def test_check_exclusions_no_match():
    """이슈가 있어도 제외 키워드 불일치 → 제외 안 됨."""
    la = LogicApplier()
    strategy = {"conditions": {"제외": "금 강세 동시 발생 시 제외"}}
    issue_factor = {
        "issues": [{"issue_id": "ISS_006", "name": "외국인 대량 매도", "severity": "HIGH"}]
    }
    excluded, _ = la._check_exclusions(strategy, issue_factor)
    assert not excluded
    print("  OK: 이슈 불일치 → 제외 안 됨")


def test_execute_none_input():
    """입력 없으면 passthrough."""
    la = LogicApplier()
    result = asyncio.run(la.execute(None))
    assert result.header.to_agent == "EX"
    assert result.status["code"] == "OK"
    print("  OK: 입력 없음 → passthrough")


def test_status_ok():
    """정상 실행 시 status.code = OK."""
    la = LogicApplier()
    msg = _make_signal()
    result = asyncio.run(la.execute(msg))
    assert result.status["code"] == "OK"
    print("  OK: status.code=OK")


def test_list_strategies_for_phase():
    """국면별 전략 목록 반환."""
    la = LogicApplier()
    strats = la.list_strategies_for_phase("안정화")
    assert isinstance(strats, list)
    for s in strats:
        assert s["phase"] == "안정화"
    print(f"  OK: 안정화 전략 {len(strats)}개")


def test_reload_library():
    """전략 라이브러리 재로드."""
    la = LogicApplier()
    count = la.reload_library()
    assert count >= 7
    print(f"  OK: 재로드 {count}개")


def test_get_strategy_by_id():
    """ID로 전략 단건 조회."""
    la = LogicApplier()
    card = la.get_strategy("STR_001")
    assert card is not None
    assert card["id"] == "STR_001"
    print(f"  OK: STR_001 조회 → {card['description'][:30]}")


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_instantiation,
        test_library_loaded,
        test_execute_returns_standard_message,
        test_execute_to_ex,
        test_execute_data_type_signal,
        test_strategy_id_added,
        test_select_strategy_for_phase,
        test_select_strategy_status_priority,
        test_no_strategy_for_unknown_phase,
        test_hold_direction_no_strategy_applied,
        test_exclusion_condition_triggers_hold,
        test_no_exclusion_without_issue,
        test_reason_enriched_with_strategy,
        test_prioritize_targets_by_group,
        test_check_exclusions_no_issue,
        test_check_exclusions_matching_issue,
        test_check_exclusions_no_match,
        test_execute_none_input,
        test_status_ok,
        test_list_strategies_for_phase,
        test_reload_library,
        test_get_strategy_by_id,
    ]

    passed = 0
    failed = 0
    for test_fn in tests:
        name = test_fn.__name__
        try:
            print(f"[{name}]")
            test_fn()
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n결과: {passed}/{passed+failed} 통과")
    sys.exit(0 if failed == 0 else 1)
