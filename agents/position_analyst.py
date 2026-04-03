"""
포지션 분석 에이전트 (PA)
보유 중인 OPEN 포지션에 대해 기술적 지표 + 뉴스 + Claude AI를 활용하여
HOLD / CAUTION / SELL 권고를 생성하고 DB에 저장한다.
"""

import json
import logging
import os
import re
from typing import Any, Optional

from agents.base_agent import BaseAgent
from protocol.protocol import StandardMessage
from database.db import save_position_analysis

logger = logging.getLogger(__name__)

# stock_classification.json 경로
_STOCK_CLASSIFICATION_PATH = os.path.join(
    os.path.dirname(__file__), "..", "config", "stock_classification.json"
)


def _load_stock_classification() -> dict:
    try:
        with open(_STOCK_CLASSIFICATION_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[PA] stock_classification.json 로드 실패: {e}")
        return {}


class PositionAnalyst(BaseAgent):
    """
    보유 포지션 AI 분석 에이전트.
    에이전트 코드: PA
    타임아웃: 60초 (Claude API 호출 포함)
    """

    def __init__(self) -> None:
        super().__init__(
            agent_code="PA",
            agent_name="포지션분석 에이전트",
            timeout=60,
            max_retries=2,
        )
        self._stock_cls = _load_stock_classification()

    # ------------------------------------------------------------------
    # execute
    # ------------------------------------------------------------------

    async def execute(self, input_data: Optional[Any] = None) -> StandardMessage:
        """
        input_data.body["payload"]["positions"] : OPEN 포지션 목록 (list[dict])
        input_data.body["payload"]["news"]      : 뉴스 헤드라인 목록 (list[str], 선택)
        """
        positions: list = []
        news_list: list = []

        if input_data is not None:
            payload = input_data.body.get("payload", {})
            positions = payload.get("positions", [])
            news_list = payload.get("news", [])

        if not positions:
            self.log("info", "분석할 OPEN 포지션 없음")
            return self.create_message(
                to="OR",
                data_type="POSITION_ANALYSIS",
                payload={"analyses": [], "count": 0},
            )

        self.log("info", f"포지션 분석 시작: {len(positions)}건")
        analyses = []

        for pos in positions:
            try:
                analysis = await self._analyze_position(pos, news_list)
                if analysis:
                    analyses.append(analysis)
                    # DB 저장
                    try:
                        save_position_analysis(
                            position_id=pos.get("id"),
                            code=analysis["code"],
                            name=analysis["name"],
                            recommendation=analysis["recommendation"],
                            reason=analysis["reason"],
                            rsi=analysis.get("rsi"),
                            price_change_5d=analysis.get("price_change_5d"),
                            above_ma20=analysis.get("above_ma20"),
                            news_sentiment=analysis.get("news_sentiment"),
                            target_exit_price=analysis.get("target_exit_price"),
                        )
                    except Exception as db_exc:
                        self.log("warning", f"DB 저장 실패 ({analysis['code']}): {db_exc}")
            except Exception as exc:
                self.log("warning", f"포지션 분석 실패 ({pos.get('code', '?')}): {exc}")

        self.log("info", f"포지션 분석 완료: {len(analyses)}건")
        self._db_log("INFO", f"포지션 분석 완료: {len(analyses)}건")

        return self.create_message(
            to="OR",
            data_type="POSITION_ANALYSIS",
            payload={"analyses": analyses, "count": len(analyses)},
        )

    # ------------------------------------------------------------------
    # _analyze_position
    # ------------------------------------------------------------------

    async def _analyze_position(self, pos: dict, news_list: list) -> Optional[dict]:
        """
        단일 포지션 분석.

        Returns dict with keys:
          code, name, recommendation, reason, rsi, price_change_5d,
          above_ma20, news_sentiment, target_exit_price
        """
        code = pos.get("code", "")
        name = pos.get("name", "")
        avg_price = float(pos.get("avg_price", 0))
        current_price_db = float(pos.get("current_price") or pos.get("avg_price") or avg_price)
        holding_period = pos.get("holding_period", "단기")
        phase_at_buy = pos.get("phase_at_buy", "일반장")

        # ----------------------------------------------------------
        # Step 1: yfinance 기술적 지표
        # ----------------------------------------------------------
        rsi: Optional[float] = None
        price_change_5d: Optional[float] = None
        above_ma20: Optional[bool] = None
        current_price: float = current_price_db

        try:
            import yfinance as yf
            import pandas as pd

            # 마켓 결정 (.KS = KOSPI, .KQ = KOSDAQ)
            stock_info = self._stock_cls.get("stocks", {}).get(code, {})
            market = stock_info.get("market", "KOSPI")
            suffix = ".KS" if market == "KOSPI" else ".KQ"
            ticker_sym = code + suffix

            hist = yf.Ticker(ticker_sym).history(period="1mo")
            if hist.empty:
                raise ValueError(f"yfinance 데이터 없음: {ticker_sym}")

            closes = hist["Close"]

            # 현재가 (최신 종가)
            current_price = float(closes.iloc[-1])

            # RSI(14) 계산
            if len(closes) >= 15:
                delta = closes.diff()
                gain = delta.clip(lower=0)
                loss = -delta.clip(upper=0)
                avg_gain = gain.rolling(window=14).mean()
                avg_loss = loss.rolling(window=14).mean()
                rs = avg_gain / avg_loss.replace(0, float("nan"))
                rsi_series = 100 - (100 / (1 + rs))
                rsi = float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else None

            # 5일 변동률
            if len(closes) >= 6:
                price_5d_ago = float(closes.iloc[-6])
                if price_5d_ago > 0:
                    price_change_5d = ((current_price - price_5d_ago) / price_5d_ago) * 100

            # 20일 이동평균 대비
            if len(closes) >= 20:
                ma20 = float(closes.rolling(window=20).mean().iloc[-1])
                above_ma20 = current_price > ma20

        except Exception as yf_exc:
            self.log("warning", f"yfinance 조회 실패 ({code}), 기술적 분석 없이 진행: {yf_exc}")
            current_price = current_price_db

        # 수익률 계산
        pnl = ((current_price - avg_price) / avg_price * 100) if avg_price > 0 else 0.0

        # ----------------------------------------------------------
        # Step 2: 관련 뉴스 필터링
        # ----------------------------------------------------------
        stock_info = self._stock_cls.get("stocks", {}).get(code, {})
        sectors = stock_info.get("sector", [])
        themes = stock_info.get("themes", [])
        keywords = [name, code] + sectors + themes

        related_news = [
            headline for headline in news_list
            if any(kw.lower() in headline.lower() for kw in keywords if kw)
        ][:3]

        # ----------------------------------------------------------
        # Step 3: Claude API 호출
        # ----------------------------------------------------------
        news_text = (
            "\n".join(f"- {h}" for h in related_news)
            if related_news
            else "관련 뉴스 없음"
        )

        above_ma20_text = "위" if above_ma20 else ("아래" if above_ma20 is not None else "데이터 없음")
        rsi_text = f"{rsi:.1f}" if rsi is not None else "데이터 없음"
        pch5d_text = f"{price_change_5d:+.2f}%" if price_change_5d is not None else "데이터 없음"

        prompt = f"""당신은 한국 주식 매도 타이밍 전문가입니다.

[보유 포지션]
- 종목: {name}({code})
- 매수가: {avg_price:,.0f}원
- 현재가: {current_price:,.0f}원
- 수익률: {pnl:+.2f}%
- 보유기간 설정: {holding_period}
- 매수 시 국면: {phase_at_buy}

[기술적 지표]
- RSI(14): {rsi_text}
- 5일 수익률: {pch5d_text}
- 20일 이동평균 대비: {above_ma20_text}

[관련 뉴스] (최근 3건)
{news_text}

위 정보를 바탕으로 다음을 JSON으로 답하세요:
{{
  "recommendation": "HOLD or CAUTION or SELL",
  "reason": "2-3문장으로 핵심 근거",
  "target_exit_price": 매도 목표가(숫자, 없으면 null),
  "news_sentiment": "POSITIVE or NEUTRAL or NEGATIVE"
}}"""

        try:
            from anthropic import Anthropic
            api_key = os.getenv("ANTHROPIC_API_KEY", "")
            client_ai = Anthropic(api_key=api_key)

            response = client_ai.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            raw_text = response.content[0].text.strip()

            # 코드블록 제거 후 JSON 파싱
            raw_text = re.sub(r"```(?:json)?", "", raw_text).strip().rstrip("`").strip()
            parsed = json.loads(raw_text)

            recommendation = parsed.get("recommendation", "HOLD")
            reason = parsed.get("reason", "")
            target_exit_price = parsed.get("target_exit_price")
            news_sentiment = parsed.get("news_sentiment", "NEUTRAL")

            # 유효성 보정
            if recommendation not in ("HOLD", "CAUTION", "SELL"):
                recommendation = "HOLD"
            if news_sentiment not in ("POSITIVE", "NEUTRAL", "NEGATIVE"):
                news_sentiment = "NEUTRAL"
            if target_exit_price is not None:
                try:
                    target_exit_price = float(target_exit_price)
                except (TypeError, ValueError):
                    target_exit_price = None

        except Exception as claude_exc:
            self.log("warning", f"Claude API 실패 ({code}), 규칙 기반 fallback 사용: {claude_exc}")
            recommendation, reason, target_exit_price, news_sentiment = (
                self._fallback_recommendation(rsi, price_change_5d)
            )

        return {
            "code": code,
            "name": name,
            "recommendation": recommendation,
            "reason": reason,
            "rsi": rsi,
            "price_change_5d": price_change_5d,
            "above_ma20": above_ma20,
            "news_sentiment": news_sentiment,
            "target_exit_price": target_exit_price,
        }

    # ------------------------------------------------------------------
    # _fallback_recommendation
    # ------------------------------------------------------------------

    @staticmethod
    def _fallback_recommendation(
        rsi: Optional[float],
        price_change_5d: Optional[float],
    ) -> tuple:
        """
        Claude API 실패 시 규칙 기반으로 권고를 생성한다.

        Returns (recommendation, reason, target_exit_price, news_sentiment)
        """
        if rsi is not None and rsi > 80:
            return (
                "SELL",
                f"RSI {rsi:.1f}로 극과매수 구간. 단기 조정 가능성이 높아 매도를 권고합니다.",
                None,
                "NEUTRAL",
            )
        if price_change_5d is not None and price_change_5d <= -3.0:
            return (
                "SELL",
                f"5일 수익률 {price_change_5d:.2f}%로 하락 추세 지속. 추가 하락 방어를 위해 매도를 권고합니다.",
                None,
                "NEGATIVE",
            )
        if rsi is not None and rsi > 75:
            return (
                "CAUTION",
                f"RSI {rsi:.1f}로 과매수 구간 진입. 상승 모멘텀 둔화 가능성에 주의가 필요합니다.",
                None,
                "NEUTRAL",
            )
        return (
            "HOLD",
            "기술적 지표상 특이 신호 없음. 현재 포지션 유지를 권고합니다.",
            None,
            "NEUTRAL",
        )
