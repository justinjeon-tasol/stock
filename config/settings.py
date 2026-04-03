"""
설정 관리 모듈
.env 파일을 로딩하여 전역 설정 객체를 제공한다.
싱글톤 패턴으로 모듈 임포트 시 한 번만 로드된다.
"""

import os
from dataclasses import dataclass, field
from typing import Optional
from dotenv import load_dotenv


@dataclass
class Settings:
    """애플리케이션 전역 설정 클래스"""

    # Anthropic Claude API
    ANTHROPIC_API_KEY: str

    # Supabase DB 연결
    SUPABASE_URL: str
    SUPABASE_KEY: str

    # 한국투자증권 API (선택)
    KIS_APP_KEY: Optional[str]
    KIS_APP_SECRET: Optional[str]
    KIS_ACCOUNT_NO: Optional[str]
    KIS_IS_MOCK: bool  # True = 모의투자, False = 실거래

    # 텔레그램 알림 (선택)
    TELEGRAM_BOT_TOKEN: Optional[str]
    TELEGRAM_CHAT_ID: Optional[str]

    # 로깅 레벨
    LOG_LEVEL: str

    @classmethod
    def load(cls) -> "Settings":
        """
        .env 파일을 로딩하여 Settings 인스턴스를 반환한다.
        필수 키가 없으면 명확한 에러 메시지와 함께 ValueError를 발생시킨다.
        """
        # 프로젝트 루트의 .env 파일 우선 로딩
        load_dotenv(override=True)

        # 필수 키 목록 (없으면 시스템 동작 불가)
        required_keys = ["ANTHROPIC_API_KEY", "SUPABASE_URL", "SUPABASE_KEY"]
        missing = [key for key in required_keys if not os.getenv(key)]
        if missing:
            raise ValueError(
                f"[Settings] 필수 환경 변수가 설정되지 않았습니다: {missing}\n"
                f".env 파일 또는 시스템 환경 변수를 확인하세요. (.env.example 참고)"
            )

        # KIS_IS_MOCK: 문자열 "true"/"false" → bool 변환
        kis_is_mock_raw = os.getenv("KIS_IS_MOCK", "true").lower()
        kis_is_mock = kis_is_mock_raw not in ("false", "0", "no")

        return cls(
            ANTHROPIC_API_KEY=os.getenv("ANTHROPIC_API_KEY", ""),
            SUPABASE_URL=os.getenv("SUPABASE_URL", ""),
            SUPABASE_KEY=os.getenv("SUPABASE_KEY", ""),
            KIS_APP_KEY=os.getenv("KIS_APP_KEY") or None,
            KIS_APP_SECRET=os.getenv("KIS_APP_SECRET") or None,
            KIS_ACCOUNT_NO=os.getenv("KIS_ACCOUNT_NO") or None,
            KIS_IS_MOCK=kis_is_mock,
            TELEGRAM_BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN") or None,
            TELEGRAM_CHAT_ID=os.getenv("TELEGRAM_CHAT_ID") or None,
            LOG_LEVEL=os.getenv("LOG_LEVEL", "INFO"),
        )


# 싱글톤: 모듈 임포트 시 한 번만 로딩
# 테스트 환경 등에서 .env가 없을 경우 None으로 설정하고 필요 시 load() 직접 호출
try:
    settings = Settings.load()
except ValueError:
    # .env 파일이 없는 개발/테스트 초기 환경에서도 임포트 가능하게 허용
    settings = None  # type: ignore
