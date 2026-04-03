"""
디버깅 에이전트 단위 테스트.
모든 테스트는 독립적으로 실행 가능하며, 외부 API(Supabase, 텔레그램) 없이 동작한다.
"""

import asyncio
import sys
import os
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.debugger import Debugger, _MONITORED_AGENTS
from protocol.protocol import StandardMessage


class TestDebuggerInstantiation(unittest.TestCase):
    """테스트 1: 디버거 인스턴스 생성"""

    def test_instantiation(self):
        """Debugger 인스턴스가 정상적으로 생성되어야 한다."""
        debugger = Debugger()
        self.assertIsInstance(debugger, Debugger)
        self.assertEqual(debugger.agent_code, "DB")
        self.assertEqual(debugger.agent_name, "디버깅")


class TestHeartbeat(unittest.TestCase):
    """테스트 2-3: 하트비트 관련"""

    def setUp(self):
        self.debugger = Debugger()

    def test_receive_heartbeat_records_timestamp(self):
        """receive_heartbeat() 호출 시 타임스탬프가 기록되어야 한다."""
        before = datetime.now(timezone.utc)
        self.debugger.receive_heartbeat("DC")
        after = datetime.now(timezone.utc)

        self.assertIn("DC", self.debugger._heartbeats)
        recorded = self.debugger._heartbeats["DC"]
        self.assertGreaterEqual(recorded, before)
        self.assertLessEqual(recorded, after)

    def test_agent_no_heartbeat_returns_warning(self):
        """한 번도 하트비트를 받지 않은 에이전트는 WARNING 상태여야 한다."""
        # PP 에이전트에 하트비트를 보내지 않음
        health = self.debugger.get_agent_health()
        self.assertIn("PP", health)
        self.assertEqual(health["PP"]["status"], "WARNING")

    def test_agent_with_old_heartbeat_returns_warning(self):
        """30초 이상 경과한 하트비트는 WARNING 상태여야 한다."""
        # 31초 전 하트비트를 수동 설정
        old_time = datetime.now(timezone.utc) - timedelta(seconds=31)
        self.debugger._heartbeats["DC"] = old_time

        health = self.debugger.get_agent_health()
        self.assertIn(health["DC"]["status"], ["WARNING", "HIGH", "CRITICAL"])


class TestReceiveError(unittest.TestCase):
    """테스트 4-5: 오류 수신 관련"""

    def setUp(self):
        self.debugger = Debugger()

    def test_critical_error_sets_halt_trading(self):
        """CRITICAL 오류 수신 시 halt_trading이 True로 설정되어야 한다."""
        with patch.object(self.debugger, '_telegram_token', None):
            self.debugger.receive_error("DC", "CRITICAL", "심각한 오류 발생")
        self.assertTrue(self.debugger.halt_trading)

    def test_low_error_does_not_set_halt_trading(self):
        """LOW 오류 수신 시 halt_trading이 변경되지 않아야 한다."""
        self.debugger.receive_error("DC", "LOW", "사소한 오류")
        self.assertFalse(self.debugger.halt_trading)

    def test_medium_error_does_not_set_halt_trading(self):
        """MEDIUM 오류 수신 시 halt_trading이 변경되지 않아야 한다."""
        self.debugger.receive_error("PP", "MEDIUM", "중간 수준 오류")
        self.assertFalse(self.debugger.halt_trading)


class TestGetAgentHealth(unittest.TestCase):
    """테스트 6: get_agent_health() 반환 구조"""

    def setUp(self):
        self.debugger = Debugger()

    def test_get_agent_health_returns_correct_structure(self):
        """get_agent_health()가 올바른 구조를 반환해야 한다."""
        # 하나의 에이전트에 정상 하트비트 설정
        self.debugger.receive_heartbeat("DC")

        health = self.debugger.get_agent_health()

        # 반환값이 딕셔너리여야 함
        self.assertIsInstance(health, dict)

        # DC는 최근 하트비트로 ALIVE 상태여야 함
        self.assertIn("DC", health)
        dc_health = health["DC"]
        self.assertIn("status", dc_health)
        self.assertIn("last_seen_secs", dc_health)
        self.assertEqual(dc_health["status"], "ALIVE")
        self.assertGreaterEqual(dc_health["last_seen_secs"], 0)


class TestExecute(unittest.TestCase):
    """테스트 7-9, 11-12: execute() 관련"""

    def setUp(self):
        self.debugger = Debugger()

    def test_execute_returns_standard_message(self):
        """execute()가 StandardMessage를 반환해야 한다."""
        result = asyncio.run(self.debugger.execute())
        self.assertIsInstance(result, StandardMessage)

    def test_execute_sends_to_orchestrator(self):
        """execute()의 반환 메시지 수신자가 'OR'이어야 한다."""
        result = asyncio.run(self.debugger.execute())
        self.assertEqual(result.header.to_agent, "OR")

    def test_execute_clears_error_buffer(self):
        """execute() 호출 후 에러 버퍼가 비워져야 한다."""
        self.debugger.receive_error("DC", "HIGH", "테스트 오류")
        self.assertEqual(len(self.debugger._error_buffer), 1)

        asyncio.run(self.debugger.execute())

        self.assertEqual(len(self.debugger._error_buffer), 0)

    def test_multiple_errors_accumulate_before_execute(self):
        """execute() 호출 전 여러 오류가 버퍼에 누적되어야 한다."""
        self.debugger.receive_error("DC", "LOW", "오류 1")
        self.debugger.receive_error("PP", "MEDIUM", "오류 2")
        self.debugger.receive_error("MA", "HIGH", "오류 3")

        self.assertEqual(len(self.debugger._error_buffer), 3)

    def test_execute_payload_has_required_keys(self):
        """execute() 반환 페이로드에 필수 키가 모두 있어야 한다."""
        result = asyncio.run(self.debugger.execute())
        payload = result.body["payload"]

        required_keys = ["agent_health", "error_count", "halt_trading", "critical_errors", "summary"]
        for key in required_keys:
            self.assertIn(key, payload, f"페이로드에 '{key}' 키가 없음")

    def test_execute_data_type_is_debug_report(self):
        """execute() 반환 메시지의 data_type이 'DEBUG_REPORT'여야 한다."""
        result = asyncio.run(self.debugger.execute())
        self.assertEqual(result.body["data_type"], "DEBUG_REPORT")


class TestHaltTrading(unittest.TestCase):
    """테스트 10: halt_trading 초기값"""

    def test_halt_trading_starts_false(self):
        """halt_trading 초기값이 False여야 한다."""
        debugger = Debugger()
        self.assertFalse(debugger.halt_trading)


class TestMonitoredAgents(unittest.TestCase):
    """테스트 13: 감시 대상 에이전트 코드 목록"""

    def test_all_known_agent_codes_in_monitoring_list(self):
        """CLAUDE.md에 정의된 모든 에이전트 코드가 감시 목록에 있어야 한다."""
        expected_codes = {"DC", "PP", "MA", "IM", "WA", "SR", "LA", "EX", "SM"}
        monitored_set = set(_MONITORED_AGENTS)

        for code in expected_codes:
            self.assertIn(code, monitored_set, f"에이전트 코드 '{code}'가 감시 목록에 없음")

    def test_monitored_agents_in_get_agent_health(self):
        """get_agent_health()가 모든 감시 대상 에이전트를 반환해야 한다."""
        debugger = Debugger()
        health = debugger.get_agent_health()

        for code in _MONITORED_AGENTS:
            self.assertIn(code, health, f"'{code}'가 health 결과에 없음")


class TestStartBackground(unittest.TestCase):
    """테스트 14: start_background() 반환 타입"""

    def test_start_background_returns_asyncio_task(self):
        """start_background()가 asyncio.Task를 반환해야 한다."""
        async def _run():
            debugger = Debugger()
            task = debugger.start_background(check_interval=1000)
            self.assertIsInstance(task, asyncio.Task)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(_run())


class TestPollDbErrors(unittest.TestCase):
    """테스트 15: _poll_db_errors() Supabase 미설정 시 빈 리스트 반환"""

    def test_poll_db_errors_returns_empty_when_supabase_not_configured(self):
        """Supabase 미설정 시 _poll_db_errors()가 빈 리스트를 반환해야 한다."""
        debugger = Debugger()

        # _get_client()가 None을 반환하도록 mock - Supabase 미설정 상황 시뮬레이션
        with patch("database.db._get_client", return_value=None):
            result = debugger._poll_db_errors("2026-01-01T00:00:00+00:00")

        self.assertEqual(result, [])
        self.assertIsInstance(result, list)


# ---------------------------------------------------------------------------
# 추가: 하트비트 타임아웃 세부 테스트
# ---------------------------------------------------------------------------

class TestHeartbeatTimeout(unittest.TestCase):
    """하트비트 타임아웃 임계값별 상태 변환 테스트"""

    def setUp(self):
        self.debugger = Debugger()

    def test_fresh_heartbeat_is_alive(self):
        """방금 수신한 하트비트는 ALIVE 상태여야 한다."""
        self.debugger.receive_heartbeat("DC")
        health = self.debugger.get_agent_health()
        self.assertEqual(health["DC"]["status"], "ALIVE")

    def test_60s_elapsed_heartbeat_is_high(self):
        """61초 경과한 하트비트는 HIGH 상태여야 한다."""
        old_time = datetime.now(timezone.utc) - timedelta(seconds=61)
        self.debugger._heartbeats["DC"] = old_time

        health = self.debugger.get_agent_health()
        self.assertIn(health["DC"]["status"], ["HIGH", "CRITICAL"])

    def test_90s_elapsed_heartbeat_is_critical(self):
        """91초 경과한 하트비트는 CRITICAL 상태여야 한다."""
        old_time = datetime.now(timezone.utc) - timedelta(seconds=91)
        self.debugger._heartbeats["DC"] = old_time

        health = self.debugger.get_agent_health()
        self.assertEqual(health["DC"]["status"], "CRITICAL")


if __name__ == "__main__":
    print("=" * 60)
    print("디버깅 에이전트 단위 테스트")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # 테스트 클래스 등록
    test_classes = [
        TestDebuggerInstantiation,
        TestHeartbeat,
        TestReceiveError,
        TestGetAgentHealth,
        TestExecute,
        TestHaltTrading,
        TestMonitoredAgents,
        TestStartBackground,
        TestPollDbErrors,
        TestHeartbeatTimeout,
    ]

    for cls in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 60)
    if result.wasSuccessful():
        print(f"모든 테스트 통과: {result.testsRun}개")
    else:
        print(f"실패: {len(result.failures)}개, 오류: {len(result.errors)}개")
        sys.exit(1)
