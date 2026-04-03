"""
시스템관리 에이전트 단위 테스트.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.system_manager import SystemManager, _PATCHABLE_KEYS


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _make_logs(entries: list) -> list:
    """
    테스트용 agent_logs 레코드 생성.
    entries: [{"agent": str, "level": str, "message": str, "error_code": str}]
    """
    from datetime import datetime, timezone
    return [
        {
            "agent":      e.get("agent", "DC"),
            "level":      e.get("level", "INFO"),
            "message":    e.get("message", "test"),
            "error_code": e.get("error_code", ""),
            "timestamp":  datetime.now(timezone.utc).isoformat(),
        }
        for e in entries
    ]


# ---------------------------------------------------------------------------
# 테스트
# ---------------------------------------------------------------------------

def test_instantiation():
    """SystemManager 생성 확인."""
    sm = SystemManager()
    assert sm.agent_code == "SM"
    assert sm.agent_name == "시스템관리"
    print("  OK: 생성 확인")


def test_strategy_config_loaded():
    """strategy_config.json 로드 확인."""
    sm = SystemManager()
    cfg = sm.get_strategy_config()
    assert isinstance(cfg, dict)
    print(f"  OK: strategy_config 키={list(cfg.keys())[:3]}")


def test_patchable_keys_defined():
    """허용 패치 키 목록 존재."""
    sm = SystemManager()
    keys = sm.describe_patchable_keys()
    assert len(keys) > 0
    assert "stop_loss_pct" in keys
    assert "take_profit_pct" in keys
    print(f"  OK: 패치 가능 키 {len(keys)}개")


def test_analyze_logs_empty():
    """빈 로그 -> 빈 통계."""
    sm = SystemManager()
    stats = sm._analyze_logs([])
    assert stats == {}
    print("  OK: 빈 로그 -> 빈 통계")


def test_analyze_logs_no_errors():
    """오류 없는 로그 -> error_rate=0."""
    sm = SystemManager()
    logs = _make_logs([
        {"agent": "DC", "level": "INFO"},
        {"agent": "DC", "level": "INFO"},
        {"agent": "PP", "level": "INFO"},
    ])
    stats = sm._analyze_logs(logs)
    assert stats["DC"]["total"] == 2
    assert stats["DC"]["error_count"] == 0
    assert stats["DC"]["error_rate"] == 0.0
    print("  OK: 오류 없는 로그 처리")


def test_analyze_logs_with_errors():
    """오류 포함 로그 -> error_rate 정확히 계산."""
    sm = SystemManager()
    logs = _make_logs([
        {"agent": "EX", "level": "INFO"},
        {"agent": "EX", "level": "ERROR", "message": "KIS API 오류"},
        {"agent": "EX", "level": "ERROR", "message": "타임아웃"},
    ])
    stats = sm._analyze_logs(logs)
    assert stats["EX"]["total"] == 3
    assert stats["EX"]["error_count"] == 2
    assert abs(stats["EX"]["error_rate"] - 2/3) < 0.001
    print(f"  OK: 오류율={stats['EX']['error_rate']:.3f}")


def test_evaluate_health_good():
    """오류율 0% -> GOOD."""
    sm = SystemManager()
    stats = {"DC": {"error_rate": 0.0}, "PP": {"error_rate": 0.05}}
    health = sm._evaluate_health(stats)
    assert health == "GOOD"
    print("  OK: GOOD 판정")


def test_evaluate_health_warn():
    """오류율 25% -> WARN."""
    sm = SystemManager()
    stats = {"EX": {"error_rate": 0.25}}
    health = sm._evaluate_health(stats)
    assert health == "WARN"
    print("  OK: WARN 판정")


def test_evaluate_health_critical():
    """오류율 60% -> CRITICAL."""
    sm = SystemManager()
    stats = {"MA": {"error_rate": 0.60}}
    health = sm._evaluate_health(stats)
    assert health == "CRITICAL"
    print("  OK: CRITICAL 판정")


def test_evaluate_health_empty():
    """통계 없음 -> GOOD."""
    sm = SystemManager()
    health = sm._evaluate_health({})
    assert health == "GOOD"
    print("  OK: 빈 통계 -> GOOD")


def test_top_errors():
    """상위 오류 집계."""
    sm = SystemManager()
    logs = _make_logs([
        {"agent": "DC", "level": "ERROR", "message": "API 타임아웃", "error_code": "E001"},
        {"agent": "DC", "level": "ERROR", "message": "API 타임아웃", "error_code": "E001"},
        {"agent": "DC", "level": "ERROR", "message": "API 타임아웃", "error_code": "E001"},
        {"agent": "EX", "level": "ERROR", "message": "주문 실패", "error_code": "E002"},
        {"agent": "DC", "level": "INFO", "message": "정상"},
    ])
    top = sm._top_errors(logs, top_n=2)
    assert len(top) == 2
    assert top[0]["count"] == 3          # DC E001 가장 많음
    assert top[0]["agent"] == "DC"
    print(f"  OK: 상위 오류: {top[0]['error_code']} x{top[0]['count']}")


def test_top_errors_empty():
    """오류 없으면 빈 리스트."""
    sm = SystemManager()
    logs = _make_logs([{"agent": "DC", "level": "INFO"}])
    top = sm._top_errors(logs)
    assert top == []
    print("  OK: 오류 없음 -> 빈 리스트")


def test_recommendations_good():
    """GOOD 상태 -> 유지 권고."""
    sm = SystemManager()
    stats = {"DC": {"error_rate": 0.0, "issues": []}}
    recs = sm._build_recommendations(stats, "GOOD")
    assert len(recs) == 1
    assert "정상" in recs[0]
    print(f"  OK: GOOD 권고: '{recs[0][:40]}...'")


def test_recommendations_critical():
    """CRITICAL 상태 -> 중단 권고 포함."""
    sm = SystemManager()
    stats = {"EX": {"error_rate": 0.60, "issues": ["주문 실패"]}}
    recs = sm._build_recommendations(stats, "CRITICAL")
    assert any("CRITICAL" in r for r in recs)
    print(f"  OK: CRITICAL 권고 {len(recs)}건")


def test_patch_rejected_unknown_key():
    """허용 목록 외 키 패치 시도 -> 적용 안 됨."""
    sm = SystemManager()
    result = sm._apply_patches([
        {"key": "some_dangerous_key", "value": 999, "reason": "테스트"}
    ])
    assert result == []
    print("  OK: 알 수 없는 키 패치 거부")


def test_patch_no_requests():
    """패치 요청 없음 -> 빈 결과."""
    sm = SystemManager()
    result = sm._apply_patches([])
    assert result == []
    print("  OK: 패치 요청 없음")


def test_execute_returns_standard_message():
    """execute() -> StandardMessage 반환."""
    sm = SystemManager()
    result = asyncio.run(sm.execute(None))
    assert result is not None
    assert result.status["code"] == "OK"
    print("  OK: execute() StandardMessage 반환")


def test_execute_payload_keys():
    """execute() payload에 필수 키 존재."""
    sm = SystemManager()
    result = asyncio.run(sm.execute(None))
    payload = result.body["payload"]
    required_keys = {"health", "agent_stats", "top_errors", "patch_applied",
                     "recommendations", "report_period_hours", "generated_at"}
    missing = required_keys - payload.keys()
    assert not missing, f"누락 키: {missing}"
    print(f"  OK: payload 키 확인 ({len(payload)}개)")


def test_execute_to_or():
    """execute() 반환 메시지 수신자 = OR."""
    sm = SystemManager()
    result = asyncio.run(sm.execute(None))
    assert result.header.to_agent == "OR"
    print("  OK: 수신자=OR")


def test_execute_health_field():
    """execute() payload.health 가 유효한 값."""
    sm = SystemManager()
    result = asyncio.run(sm.execute(None))
    health = result.body["payload"]["health"]
    assert health in ("GOOD", "WARN", "CRITICAL")
    print(f"  OK: health={health}")


def test_get_system_summary():
    """get_system_summary() 기본 구조 확인."""
    sm = SystemManager()
    summary = sm.get_system_summary(hours=1)
    assert "health" in summary
    assert "error_count" in summary
    assert summary["period_hours"] == 1
    print(f"  OK: summary={summary}")


def test_fetch_logs_no_supabase():
    """Supabase 미설정 -> 빈 로그 반환."""
    sm = SystemManager()
    from datetime import datetime, timezone
    since = (datetime.now(timezone.utc)).isoformat()
    logs = sm._fetch_logs(since)
    assert isinstance(logs, list)
    print(f"  OK: Supabase 미설정 -> 로그 {len(logs)}건")


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_instantiation,
        test_strategy_config_loaded,
        test_patchable_keys_defined,
        test_analyze_logs_empty,
        test_analyze_logs_no_errors,
        test_analyze_logs_with_errors,
        test_evaluate_health_good,
        test_evaluate_health_warn,
        test_evaluate_health_critical,
        test_evaluate_health_empty,
        test_top_errors,
        test_top_errors_empty,
        test_recommendations_good,
        test_recommendations_critical,
        test_patch_rejected_unknown_key,
        test_patch_no_requests,
        test_execute_returns_standard_message,
        test_execute_payload_keys,
        test_execute_to_or,
        test_execute_health_field,
        test_get_system_summary,
        test_fetch_logs_no_supabase,
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
