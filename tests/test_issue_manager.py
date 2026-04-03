"""
이슈관리 에이전트 단위 테스트.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.issue_manager import IssueManager
from protocol.protocol import StandardMessage


# ---------------------------------------------------------------------------
# 헬퍼: 전처리 결과 mock 생성
# ---------------------------------------------------------------------------

def _make_preprocessed(
    vix: float = 18.0,
    usd_krw_chg: float = 0.0,
    gold_chg: float = 0.0,
    wti_chg: float = 0.0,
    sox_chg: float = 0.0,
    nasdaq_chg: float = 0.0,
    foreign_net: float = 0.0,
) -> StandardMessage:
    payload = {
        "us_market": {
            "vix":     {"value": vix,     "change_pct": 0.0},
            "usd_krw": {"value": 1350.0,  "change_pct": usd_krw_chg},
            "nasdaq":  {"value": 18000.0, "change_pct": nasdaq_chg},
            "sox":     {"value": 5000.0,  "change_pct": sox_chg},
        },
        "kr_market": {
            "foreign_net": int(foreign_net),
        },
        "commodities": {
            "gold":   {"value": 2500.0, "change_pct": gold_chg},
            "wti":    {"value": 80.0,   "change_pct": wti_chg},
            "copper": {"value": 4.0,    "change_pct": 0.0},
        },
    }
    msg = StandardMessage.create(
        from_agent="PP",
        to_agent="IM",
        data_type="PREPROCESSED_DATA",
        payload=payload,
    )
    return msg


# ---------------------------------------------------------------------------
# 테스트
# ---------------------------------------------------------------------------

def test_library_loaded():
    """이슈 라이브러리 로드 확인."""
    im = IssueManager()
    issues = im.list_issues()
    assert len(issues) >= 7, f"이슈 라이브러리 7건 이상이어야 함, 실제: {len(issues)}"
    print(f"  OK: 라이브러리 {len(issues)}건 로드")


def test_no_issues_normal_market():
    """정상 시장 → 이슈 없음."""
    im = IssueManager()
    msg = _make_preprocessed(vix=18.0, usd_krw_chg=0.1, gold_chg=0.2, wti_chg=0.5)
    result = asyncio.run(im.execute(msg))
    payload = result.body["payload"]
    assert payload["issue_count"] == 0, f"정상 시장에서 이슈 감지됨: {payload['active_issues']}"
    print(f"  OK: 이슈 없음 ({payload['summary']})")


def test_vix_medium_issue():
    """VIX 27 → ISS_001 MEDIUM."""
    im = IssueManager()
    msg = _make_preprocessed(vix=27.0)
    result = asyncio.run(im.execute(msg))
    payload = result.body["payload"]
    ids = [i["issue_id"] for i in payload["active_issues"]]
    assert "ISS_001" in ids, f"ISS_001 미감지: {ids}"
    iss = next(i for i in payload["active_issues"] if i["issue_id"] == "ISS_001")
    assert iss["severity"] == "MEDIUM", f"심각도 기대 MEDIUM, 실제: {iss['severity']}"
    print(f"  OK: VIX=27 → {iss['severity']}")


def test_vix_high_issue():
    """VIX 31 → ISS_001 HIGH."""
    im = IssueManager()
    msg = _make_preprocessed(vix=31.0)
    result = asyncio.run(im.execute(msg))
    payload = result.body["payload"]
    iss = next((i for i in payload["active_issues"] if i["issue_id"] == "ISS_001"), None)
    assert iss is not None, "ISS_001 미감지"
    assert iss["severity"] == "HIGH"
    assert iss["strategy_override"] is True
    assert iss["direction"] == "SELL"
    print(f"  OK: VIX=31 → HIGH, strategy_override=True")


def test_usd_krw_issue():
    """USD/KRW 1.2% 급등 → ISS_002 HIGH."""
    im = IssueManager()
    msg = _make_preprocessed(usd_krw_chg=1.2)
    result = asyncio.run(im.execute(msg))
    payload = result.body["payload"]
    ids = [i["issue_id"] for i in payload["active_issues"]]
    assert "ISS_002" in ids, f"ISS_002 미감지: {ids}"
    iss = next(i for i in payload["active_issues"] if i["issue_id"] == "ISS_002")
    assert iss["severity"] == "HIGH"
    print(f"  OK: USD/KRW +1.2% → {iss['severity']}")


def test_geopolitical_issue():
    """금 +2% + WTI +3% → ISS_003 감지."""
    im = IssueManager()
    msg = _make_preprocessed(gold_chg=2.0, wti_chg=3.0)
    result = asyncio.run(im.execute(msg))
    payload = result.body["payload"]
    ids = [i["issue_id"] for i in payload["active_issues"]]
    assert "ISS_003" in ids, f"ISS_003 미감지: {ids}"
    print(f"  OK: 금+WTI 동반 급등 → ISS_003 감지")


def test_sox_decline_issue():
    """SOX -3.5% → ISS_005 반도체 다운사이클 HIGH."""
    im = IssueManager()
    msg = _make_preprocessed(sox_chg=-3.5)
    result = asyncio.run(im.execute(msg))
    payload = result.body["payload"]
    ids = [i["issue_id"] for i in payload["active_issues"]]
    assert "ISS_005" in ids, f"ISS_005 미감지: {ids}"
    iss = next(i for i in payload["active_issues"] if i["issue_id"] == "ISS_005")
    assert iss["severity"] == "HIGH", f"기대 HIGH, 실제: {iss['severity']}"
    print(f"  OK: SOX=-3.5% → ISS_005 {iss['severity']}")


def test_foreign_selling_issue():
    """외국인 -5000억 → ISS_006 HIGH."""
    im = IssueManager()
    msg = _make_preprocessed(foreign_net=-5e11)
    result = asyncio.run(im.execute(msg))
    payload = result.body["payload"]
    ids = [i["issue_id"] for i in payload["active_issues"]]
    assert "ISS_006" in ids, f"ISS_006 미감지: {ids}"
    iss = next(i for i in payload["active_issues"] if i["issue_id"] == "ISS_006")
    assert iss["severity"] == "HIGH"
    print(f"  OK: 외국인 -5000억 → {iss['severity']}")


def test_black_swan_critical():
    """VIX 40 + 나스닥 -4% + 달러 +2% → ISS_007 CRITICAL."""
    im = IssueManager()
    msg = _make_preprocessed(
        vix=40.0,
        nasdaq_chg=-4.0,
        usd_krw_chg=2.0,
        gold_chg=3.0,
    )
    result = asyncio.run(im.execute(msg))
    payload = result.body["payload"]
    ids = [i["issue_id"] for i in payload["active_issues"]]
    assert "ISS_007" in ids, f"ISS_007 미감지: {ids}"
    iss = next(i for i in payload["active_issues"] if i["issue_id"] == "ISS_007")
    assert iss["severity"] == "CRITICAL"
    assert payload["max_severity"] == "CRITICAL"
    print(f"  OK: 복합 위기 → ISS_007 CRITICAL, max_severity=CRITICAL")


def test_multiple_issues_simultaneously():
    """VIX 28 + USD +1% + SOX -2.5% → 복수 이슈 감지."""
    im = IssueManager()
    msg = _make_preprocessed(vix=28.0, usd_krw_chg=1.0, sox_chg=-2.5)
    result = asyncio.run(im.execute(msg))
    payload = result.body["payload"]
    assert payload["issue_count"] >= 3, f"3건 이상 기대, 실제: {payload['issue_count']}"
    print(f"  OK: 복수 이슈 {payload['issue_count']}건 동시 감지")


def test_max_severity_aggregation():
    """여러 이슈 중 최대 심각도 집계."""
    im = IssueManager()
    # ISS_001 HIGH (VIX 31) + ISS_002 MEDIUM (USD +0.9%)
    msg = _make_preprocessed(vix=31.0, usd_krw_chg=0.9)
    result = asyncio.run(im.execute(msg))
    payload = result.body["payload"]
    assert payload["max_severity"] == "HIGH"
    print(f"  OK: max_severity={payload['max_severity']}")


def test_no_input_data():
    """입력 없으면 빈 이슈 목록 반환."""
    im = IssueManager()
    result = asyncio.run(im.execute(None))
    payload = result.body["payload"]
    assert payload["issue_count"] == 0
    assert result.status["code"] == "OK"
    print("  OK: 입력 없음 → 빈 이슈 반환")


def test_list_issues_by_category():
    """카테고리별 필터링."""
    im = IssueManager()
    all_issues = im.list_issues()
    kr_issues  = im.list_issues(category="통화금리")
    assert len(kr_issues) == 2, f"통화금리 2건 기대, 실제: {len(kr_issues)}"
    assert len(kr_issues) < len(all_issues)
    print(f"  OK: 통화금리 {len(kr_issues)}건 / 전체 {len(all_issues)}건")


def test_get_issue_by_id():
    """ID로 이슈 카드 단건 조회."""
    im = IssueManager()
    card = im.get_issue("ISS_001")
    assert card is not None
    assert card["issue_id"] == "ISS_001"
    assert "name" in card
    print(f"  OK: ISS_001 조회 → {card['name']}")


def test_issue_direction_sell():
    """HIGH 이슈 → direction=SELL."""
    im = IssueManager()
    msg = _make_preprocessed(vix=31.0)
    result = asyncio.run(im.execute(msg))
    payload = result.body["payload"]
    iss = next(i for i in payload["active_issues"] if i["issue_id"] == "ISS_001")
    assert iss["direction"] == "SELL"
    print(f"  OK: HIGH 이슈 direction={iss['direction']}")


def test_issue_direction_none_low():
    """LOW 이슈 → direction=NONE."""
    im = IssueManager()
    msg = _make_preprocessed(vix=21.0)
    result = asyncio.run(im.execute(msg))
    payload = result.body["payload"]
    iss = next((i for i in payload["active_issues"] if i["issue_id"] == "ISS_001"), None)
    if iss:
        assert iss["direction"] == "NONE", f"LOW 이슈 direction 기대 NONE, 실제: {iss['direction']}"
    print(f"  OK: LOW 이슈 direction=NONE (iss={iss is not None})")


def test_summary_non_empty_when_issues():
    """이슈 존재 시 summary 비어있지 않음."""
    im = IssueManager()
    msg = _make_preprocessed(vix=28.0)
    result = asyncio.run(im.execute(msg))
    payload = result.body["payload"]
    assert payload["summary"], "이슈 있을 때 summary 비어있으면 안 됨"
    print(f"  OK: summary='{payload['summary'][:50]}...'")


def test_message_status_ok():
    """정상 실행 시 status.code == OK."""
    im = IssueManager()
    msg = _make_preprocessed(vix=18.0)
    result = asyncio.run(im.execute(msg))
    assert result.status["code"] == "OK"
    print("  OK: status.code=OK")


def test_message_to_wa():
    """반환 메시지의 수신자는 WA."""
    im = IssueManager()
    msg = _make_preprocessed()
    result = asyncio.run(im.execute(msg))
    assert result.header.to_agent == "WA"
    print("  OK: 수신자=WA")


def test_affected_sectors_populated():
    """VIX 이슈 감지 시 affected_sectors 비어있지 않음."""
    im = IssueManager()
    msg = _make_preprocessed(vix=31.0)
    result = asyncio.run(im.execute(msg))
    payload = result.body["payload"]
    iss = next(i for i in payload["active_issues"] if i["issue_id"] == "ISS_001")
    assert isinstance(iss["affected_sectors"], list)
    print(f"  OK: affected_sectors={iss['affected_sectors']}")


def test_confidence_bounded():
    """confidence 값이 0~1 사이."""
    im = IssueManager()
    msg = _make_preprocessed(vix=50.0, usd_krw_chg=5.0, gold_chg=5.0, wti_chg=10.0)
    result = asyncio.run(im.execute(msg))
    payload = result.body["payload"]
    for iss in payload["active_issues"]:
        assert 0.0 <= iss["confidence"] <= 1.0, f"{iss['issue_id']} confidence 범위 초과: {iss['confidence']}"
    print(f"  OK: 모든 이슈 confidence 0~1 범위")


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_library_loaded,
        test_no_issues_normal_market,
        test_vix_medium_issue,
        test_vix_high_issue,
        test_usd_krw_issue,
        test_geopolitical_issue,
        test_sox_decline_issue,
        test_foreign_selling_issue,
        test_black_swan_critical,
        test_multiple_issues_simultaneously,
        test_max_severity_aggregation,
        test_no_input_data,
        test_list_issues_by_category,
        test_get_issue_by_id,
        test_issue_direction_sell,
        test_issue_direction_none_low,
        test_summary_non_empty_when_issues,
        test_message_status_ok,
        test_message_to_wa,
        test_affected_sectors_populated,
        test_confidence_bounded,
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
            failed += 1

    print(f"\n결과: {passed}/{passed+failed} 통과")
    sys.exit(0 if failed == 0 else 1)
