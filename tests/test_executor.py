"""
Executor 에이전트 테스트 모듈

KIS API, 텔레그램 API는 모두 mock 처리하여 실제 HTTP 요청 없이 동작한다.
.env 파일 없이도 실행 가능하다.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, AsyncMock

from protocol.protocol import StandardMessage


# ---------------------------------------------------------------------------
# 헬퍼 함수: 테스트용 StandardMessage 생성
# ---------------------------------------------------------------------------

def make_signal_msg(direction="BUY", phase="급등장", targets=None):
    """테스트용 SIGNAL 메시지를 생성한다."""
    if targets is None:
        targets = [{"code": "000660", "name": "SK하이닉스", "weight": 0.3}]
    payload = {
        "signal_id": "WA_TEST_0001",
        "direction": direction,
        "confidence": 0.8,
        "phase": phase,
        "issue_factor": None,
        "targets": targets,
        "weight_config": {"aggressive_pct": 1.0, "defensive_pct": 0.0, "cash_pct": 0.0},
        "reason": "테스트 신호",
    }
    return StandardMessage.create(
        from_agent="WA",
        to_agent="EX",
        data_type="SIGNAL",
        payload=payload,
    )


# ---------------------------------------------------------------------------
# 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture
def executor():
    """
    Executor 인스턴스를 반환한다.
    _load_kis_config를 patch하여 .env 없이도 생성 가능하도록 한다.
    """
    # executor.py가 아직 없을 수도 있으므로, import를 픽스처 안에서 수행한다.
    from agents.executor import Executor

    with patch.object(Executor, "_load_kis_config"):
        ex = Executor()
        ex._app_key = "test_key"
        ex._app_secret = "test_secret"
        ex._account_no = "0000000001"
        ex._is_mock = True
        ex._token = None
        ex._token_expires_at = None
        return ex


# ---------------------------------------------------------------------------
# TestGetToken — 토큰 발급
# ---------------------------------------------------------------------------

class TestGetToken:
    """_get_token() 메서드 테스트"""

    @pytest.mark.asyncio
    async def test_get_token_성공(self, executor):
        """requests.post mock → 200 OK → access_token 반환"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "test_access_token_abc",
            "token_type": "Bearer",
            "expires_in": 86400,
        }

        with patch("requests.post", return_value=mock_resp):
            token = await executor._get_token()

        assert token == "test_access_token_abc", f"토큰 불일치: {token}"

    @pytest.mark.asyncio
    async def test_get_token_캐시_재사용(self, executor):
        """유효한 토큰이 캐시되어 있으면 HTTP 요청을 추가로 하지 않는다."""
        executor._token = "cached_token_xyz"
        executor._token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        with patch("requests.post") as mock_post:
            token = await executor._get_token()
            mock_post.assert_not_called()

        assert token == "cached_token_xyz", f"캐시된 토큰을 반환해야 함: {token}"

    @pytest.mark.asyncio
    async def test_get_token_만료_시_재발급(self, executor):
        """토큰 만료 시각이 과거이면 재발급을 시도한다."""
        executor._token = "old_token"
        executor._token_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "new_token_after_expiry",
            "token_type": "Bearer",
            "expires_in": 86400,
        }

        with patch("requests.post", return_value=mock_resp) as mock_post:
            token = await executor._get_token()
            mock_post.assert_called_once()

        assert token == "new_token_after_expiry", f"재발급 토큰 불일치: {token}"

    @pytest.mark.asyncio
    async def test_get_token_실패_예외(self, executor):
        """requests.post → 400 응답 → 예외 발생"""
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {"error": "invalid_client"}

        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(Exception):
                await executor._get_token()


# ---------------------------------------------------------------------------
# TestPlaceOrder — 주문 실행
# ---------------------------------------------------------------------------

class TestPlaceOrder:
    """_place_order() 메서드 테스트"""

    @pytest.mark.asyncio
    async def test_place_order_매수_성공(self, executor):
        """rt_cd="0" 응답 → status="OK" 반환"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "rt_cd": "0",
            "msg1": "정상처리",
            "output": {"ODNO": "12345"},
        }

        with patch("requests.post", return_value=mock_resp):
            result = await executor._place_order(
                token="fake_token",
                code="000660",
                name="SK하이닉스",
                action="BUY",
            )

        assert result.get("status") == "OK", f"status 불일치: {result}"

    @pytest.mark.asyncio
    async def test_place_order_실패_응답(self, executor):
        """rt_cd="1" (잔고부족) → status="ERROR" 반환"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "rt_cd": "1",
            "msg1": "잔고부족",
            "output": {},
        }

        with patch("requests.post", return_value=mock_resp):
            result = await executor._place_order(
                token="fake_token",
                code="000660",
                name="SK하이닉스",
                action="BUY",
            )

        assert result.get("status") == "ERROR", f"status 불일치: {result}"

    @pytest.mark.asyncio
    async def test_place_order_헤더_tr_id_매수(self, executor):
        """매수 주문 시 요청 헤더에 'VTTC0802U'가 포함되어야 한다."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "rt_cd": "0",
            "msg1": "정상처리",
            "output": {"ODNO": "99999"},
        }

        with patch("requests.post", return_value=mock_resp) as mock_post:
            await executor._place_order(
                token="fake_token",
                code="005930",
                name="삼성전자",
                action="BUY",
            )

        assert mock_post.called, "requests.post가 호출되지 않음"
        call_kwargs = mock_post.call_args
        # headers는 kwargs 또는 positional args에 있을 수 있다
        headers = None
        if call_kwargs.kwargs.get("headers"):
            headers = call_kwargs.kwargs["headers"]
        elif len(call_kwargs.args) > 1 and isinstance(call_kwargs.args[1], dict):
            headers = call_kwargs.args[1]
        else:
            # json body에 tr_id가 있을 수 있으므로 전체 call 확인
            all_args = str(call_kwargs)
            assert "VTTC0802U" in all_args, f"VTTC0802U가 요청에 포함되지 않음. call: {all_args}"
            return

        assert headers is not None, "headers를 찾을 수 없음"
        assert "VTTC0802U" in str(headers), \
            f"헤더에 VTTC0802U 없음. headers: {headers}"


# ---------------------------------------------------------------------------
# TestSendTelegram — 텔레그램 알림
# ---------------------------------------------------------------------------

class TestSendTelegram:
    """_send_telegram() 메서드 테스트"""

    @pytest.mark.asyncio
    async def test_telegram_토큰_없으면_False(self, executor):
        """TELEGRAM_BOT_TOKEN이 없으면 False를 반환하고 예외가 없어야 한다."""
        executor._telegram_token = None
        executor._telegram_chat_id = None

        result = await executor._send_telegram("테스트 메시지")
        assert result is False, f"토큰 없을 때 False 반환 필요: {result}"

    @pytest.mark.asyncio
    async def test_telegram_성공(self, executor):
        """requests.post → 200 OK → True 반환"""
        executor._telegram_token = "bot_token_123"
        executor._telegram_chat_id = "chat_id_456"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}

        with patch("requests.post", return_value=mock_resp):
            result = await executor._send_telegram("주문 체결: SK하이닉스 매수")

        assert result is True, f"성공 시 True 반환 필요: {result}"

    @pytest.mark.asyncio
    async def test_telegram_실패해도_예외없음(self, executor):
        """requests.post → 예외 발생 → False 반환 (예외 전파 없음)"""
        executor._telegram_token = "bot_token_123"
        executor._telegram_chat_id = "chat_id_456"

        with patch("requests.post", side_effect=Exception("Connection refused")):
            result = await executor._send_telegram("테스트 메시지")

        assert result is False, f"예외 발생 시 False 반환 필요: {result}"


# ---------------------------------------------------------------------------
# TestExecute — 통합 테스트
# ---------------------------------------------------------------------------

class TestExecute:
    """execute() 메서드 통합 테스트"""

    @pytest.mark.asyncio
    async def test_execute_HOLD_즉시_SKIP(self, executor):
        """direction=HOLD → action=SKIP, KIS API 미호출"""
        msg = make_signal_msg(direction="HOLD")

        with patch.object(executor, "_get_token", new_callable=AsyncMock) as mock_token:
            with patch.object(executor, "_place_order", new_callable=AsyncMock) as mock_order:
                result = await executor.execute(msg)

        mock_token.assert_not_called()
        mock_order.assert_not_called()
        payload = result.body.get("payload", {})
        assert payload.get("action") == "SKIP", \
            f"HOLD 신호에서 action이 SKIP이어야 함: {payload.get('action')}"

    @pytest.mark.asyncio
    async def test_execute_BUY_주문실행(self, executor):
        """direction=BUY, 종목 1개 → _place_order 1회 호출"""
        msg = make_signal_msg(direction="BUY", targets=[
            {"code": "000660", "name": "SK하이닉스", "weight": 0.3}
        ])

        order_result = {
            "status": "OK",
            "order_no": "12345",
            "code": "000660",
            "name": "SK하이닉스",
            "action": "BUY",
        }

        with patch.object(executor, "_get_token", new_callable=AsyncMock, return_value="fake_token"):
            with patch.object(executor, "_place_order", new_callable=AsyncMock, return_value=order_result) as mock_order:
                with patch.object(executor, "_send_telegram", new_callable=AsyncMock, return_value=True):
                    await executor.execute(msg)

        assert mock_order.call_count == 1, \
            f"_place_order가 1회 호출되어야 함: {mock_order.call_count}회"

    @pytest.mark.asyncio
    async def test_execute_returns_standard_message(self, executor):
        """execute()는 항상 StandardMessage를 반환해야 한다."""
        msg = make_signal_msg(direction="BUY")

        with patch.object(executor, "_get_token", new_callable=AsyncMock, return_value="fake_token"):
            with patch.object(executor, "_place_order", new_callable=AsyncMock, return_value={"status": "OK", "order_no": "1"}):
                with patch.object(executor, "_send_telegram", new_callable=AsyncMock, return_value=True):
                    result = await executor.execute(msg)

        assert isinstance(result, StandardMessage), \
            f"반환 타입이 StandardMessage여야 함: {type(result)}"

    @pytest.mark.asyncio
    async def test_execute_data_type_ORDER(self, executor):
        """body['data_type'] == 'ORDER'"""
        msg = make_signal_msg(direction="BUY")

        with patch.object(executor, "_get_token", new_callable=AsyncMock, return_value="fake_token"):
            with patch.object(executor, "_place_order", new_callable=AsyncMock, return_value={"status": "OK", "order_no": "1"}):
                with patch.object(executor, "_send_telegram", new_callable=AsyncMock, return_value=True):
                    result = await executor.execute(msg)

        assert result.body.get("data_type") == "ORDER", \
            f"data_type이 'ORDER'여야 함: {result.body.get('data_type')}"

    @pytest.mark.asyncio
    async def test_execute_to_OR(self, executor):
        """header.to_agent == 'OR'"""
        msg = make_signal_msg(direction="BUY")

        with patch.object(executor, "_get_token", new_callable=AsyncMock, return_value="fake_token"):
            with patch.object(executor, "_place_order", new_callable=AsyncMock, return_value={"status": "OK", "order_no": "1"}):
                with patch.object(executor, "_send_telegram", new_callable=AsyncMock, return_value=True):
                    result = await executor.execute(msg)

        assert result.header.to_agent == "OR", \
            f"to_agent가 'OR'이어야 함: {result.header.to_agent}"

    @pytest.mark.asyncio
    async def test_execute_payload_필수키(self, executor):
        """payload에 order_id, signal_id, action, results, mode가 모두 포함되어야 한다."""
        msg = make_signal_msg(direction="BUY")

        with patch.object(executor, "_get_token", new_callable=AsyncMock, return_value="fake_token"):
            with patch.object(executor, "_place_order", new_callable=AsyncMock, return_value={"status": "OK", "order_no": "1"}):
                with patch.object(executor, "_send_telegram", new_callable=AsyncMock, return_value=True):
                    result = await executor.execute(msg)

        payload = result.body.get("payload", {})
        required_keys = ["order_id", "signal_id", "action", "results", "mode"]
        for key in required_keys:
            assert key in payload, \
                f"payload에 '{key}' 키 없음. 실제 키: {list(payload.keys())}"

    @pytest.mark.asyncio
    async def test_execute_BUY_여러종목(self, executor):
        """targets 2개 → _place_order 2회 호출"""
        targets = [
            {"code": "000660", "name": "SK하이닉스", "weight": 0.2},
            {"code": "005930", "name": "삼성전자",   "weight": 0.2},
        ]
        msg = make_signal_msg(direction="BUY", targets=targets)

        with patch.object(executor, "_get_token", new_callable=AsyncMock, return_value="fake_token"):
            with patch.object(executor, "_place_order", new_callable=AsyncMock, return_value={"status": "OK", "order_no": "1"}) as mock_order:
                with patch.object(executor, "_send_telegram", new_callable=AsyncMock, return_value=True):
                    await executor.execute(msg)

        assert mock_order.call_count == 2, \
            f"_place_order가 2회 호출되어야 함: {mock_order.call_count}회"

    @pytest.mark.asyncio
    async def test_execute_mode_MOCK(self, executor):
        """payload['mode'] == 'MOCK'"""
        msg = make_signal_msg(direction="BUY")
        executor._is_mock = True

        with patch.object(executor, "_get_token", new_callable=AsyncMock, return_value="fake_token"):
            with patch.object(executor, "_place_order", new_callable=AsyncMock, return_value={"status": "OK", "order_no": "1"}):
                with patch.object(executor, "_send_telegram", new_callable=AsyncMock, return_value=True):
                    result = await executor.execute(msg)

        payload = result.body.get("payload", {})
        assert payload.get("mode") == "MOCK", \
            f"mode가 'MOCK'이어야 함: {payload.get('mode')}"

    @pytest.mark.asyncio
    async def test_execute_SELL_SKIP처리(self, executor):
        """direction=SELL → MVP 미구현으로 action=SKIP 처리"""
        msg = make_signal_msg(direction="SELL")

        with patch.object(executor, "_get_token", new_callable=AsyncMock) as mock_token:
            with patch.object(executor, "_place_order", new_callable=AsyncMock) as mock_order:
                result = await executor.execute(msg)

        mock_order.assert_not_called()
        payload = result.body.get("payload", {})
        assert payload.get("action") == "SKIP", \
            f"SELL 신호에서 action이 SKIP이어야 함: {payload.get('action')}"

    @pytest.mark.asyncio
    async def test_execute_주문실패해도_ORDER반환(self, executor):
        """_place_order → ERROR 결과여도 ORDER 타입 StandardMessage를 반환한다."""
        msg = make_signal_msg(direction="BUY")

        with patch.object(executor, "_get_token", new_callable=AsyncMock, return_value="fake_token"):
            with patch.object(executor, "_place_order", new_callable=AsyncMock, return_value={"status": "ERROR", "message": "잔고부족"}):
                with patch.object(executor, "_send_telegram", new_callable=AsyncMock, return_value=True):
                    result = await executor.execute(msg)

        assert isinstance(result, StandardMessage), \
            f"주문 실패 후에도 StandardMessage 반환 필요: {type(result)}"
        assert result.body.get("data_type") == "ORDER", \
            f"주문 실패 후에도 data_type='ORDER'이어야 함: {result.body.get('data_type')}"
