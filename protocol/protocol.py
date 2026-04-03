"""
에이전트 간 통신 프로토콜 정의 모듈
모든 에이전트는 StandardMessage를 통해 데이터를 주고받는다.
"""

import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# 순번 관리 (thread-safe)
# ---------------------------------------------------------------------------
_counter_lock = threading.Lock()
_counter: int = 0


def _next_counter() -> int:
    """전역 순번을 thread-safe하게 증가시키고 반환한다."""
    global _counter
    with _counter_lock:
        _counter += 1
        return _counter


# ---------------------------------------------------------------------------
# 헬퍼 함수
# ---------------------------------------------------------------------------

def dataclass_to_dict(obj: Any) -> Any:
    """
    중첩된 dataclass를 재귀적으로 dict로 변환한다.
    list, tuple, dict 내부의 dataclass도 처리한다.
    """
    if hasattr(obj, "__dataclass_fields__"):
        return {k: dataclass_to_dict(v) for k, v in asdict(obj).items()}
    elif isinstance(obj, dict):
        return {k: dataclass_to_dict(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [dataclass_to_dict(item) for item in obj]
    return obj


# ---------------------------------------------------------------------------
# 메시지 헤더
# ---------------------------------------------------------------------------

@dataclass
class MessageHeader:
    """
    StandardMessage의 메타 정보를 담는 헤더.
    msg_id는 {agent_code}_{YYYYMMDD}_{HHMMSS}_{순번:04d} 형식으로 자동 생성된다.
    """

    from_agent: str
    to_agent: str
    priority: str   # CRITICAL | HIGH | NORMAL | LOW
    msg_type: str   # DATA | SIGNAL | ORDER | RESPONSE | ERROR | HEARTBEAT | COMMAND | ALERT
    msg_id: str = field(default="")
    version: str = field(default="1.0")
    timestamp: str = field(default="")

    def __post_init__(self) -> None:
        """인스턴스 생성 직후 msg_id와 timestamp를 자동으로 채운다."""
        now = datetime.now(timezone.utc)
        seq = _next_counter()

        if not self.msg_id:
            date_str = now.strftime("%Y%m%d")
            time_str = now.strftime("%H%M%S")
            self.msg_id = f"{self.from_agent}_{date_str}_{time_str}_{seq:04d}"

        if not self.timestamp:
            self.timestamp = now.isoformat()

    # 우선순위 유효값
    VALID_PRIORITIES = {"CRITICAL", "HIGH", "NORMAL", "LOW"}
    # 메시지 타입 유효값
    VALID_MSG_TYPES = {"DATA", "SIGNAL", "ORDER", "RESPONSE", "ERROR", "HEARTBEAT", "COMMAND", "ALERT"}


# ---------------------------------------------------------------------------
# 표준 메시지
# ---------------------------------------------------------------------------

@dataclass
class StandardMessage:
    """
    에이전트 간 통신의 기본 단위.
    header: 라우팅/메타 정보
    body:   실제 데이터 (data_type + payload)
    status: 처리 결과 코드 및 메시지
    """

    header: MessageHeader
    body: dict   # {"data_type": str, "payload": dict}
    status: dict  # {"code": str, "message": str}

    # ------------------------------------------------------------------ #
    # 팩토리 메서드
    # ------------------------------------------------------------------ #
    @staticmethod
    def create(
        from_agent: str,
        to_agent: str,
        data_type: str,
        payload: Any,
        priority: str = "NORMAL",
        msg_type: str = "DATA",
    ) -> "StandardMessage":
        """
        StandardMessage를 편리하게 생성하는 정적 팩토리 메서드.

        Args:
            from_agent: 발신 에이전트 코드 (예: "US_COLLECTOR")
            to_agent:   수신 에이전트 코드 (예: "KR_ANALYZER")
            data_type:  페이로드 타입 식별자 (예: "US_MARKET_DATA")
            payload:    실제 데이터 (dict 또는 dataclass)
            priority:   CRITICAL | HIGH | NORMAL | LOW
            msg_type:   DATA | SIGNAL | ORDER | RESPONSE | ERROR | HEARTBEAT | COMMAND | ALERT

        Returns:
            StandardMessage 인스턴스
        """
        # dataclass 페이로드는 dict로 직렬화
        if hasattr(payload, "__dataclass_fields__"):
            payload_dict = dataclass_to_dict(payload)
        elif isinstance(payload, dict):
            payload_dict = payload
        else:
            payload_dict = {"value": payload}

        header = MessageHeader(
            from_agent=from_agent,
            to_agent=to_agent,
            priority=priority,
            msg_type=msg_type,
        )

        return StandardMessage(
            header=header,
            body={"data_type": data_type, "payload": payload_dict},
            status={"code": "OK", "message": "정상 처리"},
        )

    # ------------------------------------------------------------------ #
    # 직렬화 / 역직렬화
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict:
        """StandardMessage 전체를 dict로 직렬화한다."""
        return {
            "header": dataclass_to_dict(self.header),
            "body": self.body,
            "status": self.status,
        }

    @staticmethod
    def from_dict(data: dict) -> "StandardMessage":
        """
        dict에서 StandardMessage를 복원한다.
        header 필드는 MessageHeader 인스턴스로 변환한다.
        """
        try:
            h = data["header"]
            header = MessageHeader(
                from_agent=h["from_agent"],
                to_agent=h["to_agent"],
                priority=h["priority"],
                msg_type=h["msg_type"],
                msg_id=h.get("msg_id", ""),
                version=h.get("version", "1.0"),
                timestamp=h.get("timestamp", ""),
            )
            # from_dict로 복원 시 msg_id/timestamp는 원본 값을 그대로 사용
            # __post_init__이 다시 덮어쓰지 않도록 원본 값을 재적용
            header.msg_id = h.get("msg_id", header.msg_id)
            header.timestamp = h.get("timestamp", header.timestamp)

            return StandardMessage(
                header=header,
                body=data["body"],
                status=data["status"],
            )
        except KeyError as e:
            raise ValueError(f"StandardMessage.from_dict() 실패: 필수 필드 누락 - {e}") from e
        except Exception as e:
            raise ValueError(f"StandardMessage.from_dict() 실패: {e}") from e


# ---------------------------------------------------------------------------
# 페이로드 dataclass들
# ---------------------------------------------------------------------------

@dataclass
class USMarketPayload:
    """미국 시장 데이터 페이로드"""
    nasdaq: dict       # {"value": 0.0, "change_pct": 0.0, "volume_ratio": 0.0}
    sox: dict          # 반도체 지수
    sp500: dict
    vix: dict          # {"value": 0.0, "change_pct": 0.0}
    usd_krw: dict      # 환율
    futures: dict      # {"value": 0.0, "direction": "UP|DOWN|FLAT"}
    individual: dict = field(default_factory=dict)  # NVDA, AMD, TSLA 등 개별 종목


@dataclass
class KRMarketPayload:
    """한국 시장 데이터 페이로드"""
    kospi: dict
    kosdaq: dict
    foreign_net: int = 0        # 외국인 순매수 (억원)
    institution_net: int = 0    # 기관 순매수 (억원)
    stocks: dict = field(default_factory=dict)  # 개별 종목 데이터
    stock_foreign_net: dict = field(default_factory=dict)  # 종목별 외국인 순매수 (원, C안)


@dataclass
class CommodityPayload:
    """원자재 시장 데이터 페이로드"""
    wti: dict       # 원유
    gold: dict      # 금
    copper: dict    # 구리 (경기 선행 지표)
    lithium: dict   # 리튬 (2차전지 관련)


@dataclass
class MarketPhasePayload:
    """시장 국면 분석 페이로드"""
    phase: str          # 안정화 | 급등장 | 급락장 | 변동폭큰
    confidence: float   # 국면 판단 신뢰도 (0.0~1.0)
    elapsed_days: int = 0
    forecast: dict = field(default_factory=dict)             # 향후 전망
    strategy_timeline: dict = field(default_factory=dict)    # 전략 타임라인


@dataclass
class StockRecommendation:
    """개별 종목 추천 데이터"""
    code: str               # 종목 코드 (예: "005930")
    name: str               # 종목명 (예: "삼성전자")
    direction: str          # BUY | HOLD | AVOID
    weight: float           # 포트폴리오 비중 (0.0~1.0)
    reasons: list = field(default_factory=list)              # 추천 이유 목록
    leading_indicators: list = field(default_factory=list)   # 선행 지표
    risk_factors: list = field(default_factory=list)         # 리스크 요인


@dataclass
class RecommendationPayload:
    """종목 추천 결과 페이로드"""
    phase: str                    # 현재 시장 국면
    phase_confidence: float       # 국면 신뢰도
    recommendations: list         # List[StockRecommendation]
    market_summary: str           # 시장 요약 텍스트
    generated_at: str             # 생성 시각 (ISO 8601)


@dataclass
class ErrorPayload:
    """에러 정보 페이로드"""
    error_id: str
    level: str          # LOW | MEDIUM | HIGH | CRITICAL
    from_agent: str     # 에러 발생 에이전트
    error_code: str     # 에러 코드 (예: "NETWORK_TIMEOUT")
    message: str        # 상세 에러 메시지
    retry_count: int = 0
    auto_fix: bool = False
    action: str = ""    # 권장 조치 (예: "재시도", "관리자 알림")
