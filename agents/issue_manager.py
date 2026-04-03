"""
이슈관리 에이전트 모듈.
전처리된 시장 데이터에서 이슈를 감지하고 이슈 라이브러리와 매핑한다.
뉴스 RSS는 추후 연동 예정 — 현재는 시장 지표 기반 룰로 이슈 감지.

파이프라인 위치: Preprocessor(PP) → IssueManager(IM) → WeightAdjuster(WA)
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from agents.base_agent import BaseAgent
from protocol.protocol import StandardMessage

logger = logging.getLogger(__name__)

# 뉴스 키워드 → 이슈 매핑 룰
_NEWS_KEYWORD_RULES = [
    {
        "issue_id": "ISS_002",
        "keywords": ["달러 강세", "원화 약세", "환율 급등", "환율 상승", "달러 급등", "달러 강세"],
        "base_confidence": 0.45,
        "severity": "MEDIUM",
    },
    {
        "issue_id": "ISS_003",
        "keywords": ["전쟁", "지정학", "무역분쟁", "제재", "관세 폭탄", "무역전쟁", "지정학적 리스크"],
        "base_confidence": 0.50,
        "severity": "MEDIUM",
    },
    {
        "issue_id": "ISS_004",
        "keywords": ["인플레이션", "CPI 쇼크", "물가 급등", "금리 인상", "테이퍼링", "긴축"],
        "base_confidence": 0.50,
        "severity": "MEDIUM",
    },
    {
        "issue_id": "ISS_005",
        "keywords": ["반도체 수요 감소", "메모리 가격 하락", "반도체 공급 과잉", "D램 하락", "낸드 가격"],
        "base_confidence": 0.45,
        "severity": "MEDIUM",
    },
    {
        "issue_id": "ISS_006",
        "keywords": ["외국인 순매도", "외국인 대량 매도", "외국인 이탈", "외인 매도"],
        "base_confidence": 0.50,
        "severity": "MEDIUM",
    },
    {
        "issue_id": "ISS_007",
        "keywords": ["금융위기", "뱅크런", "파산", "서킷브레이커", "시장 붕괴", "패닉셀", "블랙스완"],
        "base_confidence": 0.55,
        "severity": "HIGH",
    },
]

# 이슈 라이브러리 루트 경로
_ISSUE_LIBRARY_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "issue_library",
)

# 히스토리 로더 (옵션 — 없으면 룰 기반만 사용)
try:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from data.history.history_loader import get_loader as _get_history_loader
    _HISTORY_AVAILABLE = True
except Exception:
    _HISTORY_AVAILABLE = False


class IssueManager(BaseAgent):
    """
    시장 지표로 이슈를 감지하고 이슈 라이브러리에 매핑하는 에이전트.
    PREPROCESSED_DATA → ISSUE_ANALYSIS
    """

    def __init__(self) -> None:
        super().__init__("IM", "이슈관리", timeout=3, max_retries=3)
        self._library: dict[str, dict] = {}
        self._load_library()

    # ------------------------------------------------------------------
    # 라이브러리 로드
    # ------------------------------------------------------------------

    def _load_library(self) -> None:
        """data/issue_library/ 하위 JSON 파일 전체를 메모리에 로드."""
        if not os.path.isdir(_ISSUE_LIBRARY_ROOT):
            logger.warning("[이슈관리] 이슈 라이브러리 폴더 없음: %s", _ISSUE_LIBRARY_ROOT)
            return

        count = 0
        for root, _, files in os.walk(_ISSUE_LIBRARY_ROOT):
            for fname in files:
                if not fname.endswith(".json"):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, encoding="utf-8") as f:
                        card = json.load(f)
                    issue_id = card.get("issue_id", "")
                    if issue_id:
                        self._library[issue_id] = card
                        count += 1
                except Exception as exc:
                    logger.warning("[이슈관리] %s 로드 실패: %s", fname, exc)

        logger.info("[이슈관리] 이슈 라이브러리 %d건 로드 완료", count)

    # ------------------------------------------------------------------
    # BaseAgent 구현
    # ------------------------------------------------------------------

    async def execute(self, input_data: Optional[StandardMessage] = None) -> StandardMessage:
        """
        PREPROCESSED_DATA를 받아 활성 이슈 목록을 반환한다.

        반환 payload (ISSUE_ANALYSIS):
        {
            "active_issues": [
                {
                    "issue_id":          str,
                    "name":              str,
                    "category":          str,
                    "severity":          "LOW|MEDIUM|HIGH|CRITICAL",
                    "confidence":        float,
                    "affected_sectors":  list[str],
                    "strategy_override": bool,   # True이면 WeightAdjuster가 전략 강제 교체
                    "direction":         "SELL|HOLD|NONE",  # 이슈가 요구하는 방향성
                    "source":            str,    # 감지 근거
                }
            ],
            "issue_count":  int,
            "max_severity": str,   # 현재 가장 심각한 등급
            "summary":      str,
        }
        """
        self.log("info", "이슈 감지 시작")

        if input_data is None:
            return self._empty_response("입력 데이터 없음")

        payload = input_data.body.get("payload", {})
        us      = payload.get("us_market", {})
        kr      = payload.get("kr_market", {})
        comm    = payload.get("commodities", {})
        news    = payload.get("news", [])

        # 이슈 감지: 시장 지표 룰 + 뉴스 키워드
        detected_map: dict[str, dict] = {
            i["issue_id"]: i for i in self._detect_issues(us, kr, comm)
        }
        for issue in self._detect_issues_from_news(news):
            iid = issue["issue_id"]
            if iid not in detected_map:
                detected_map[iid] = issue
            else:
                # 이미 감지된 이슈면 confidence만 높임
                existing = detected_map[iid]
                existing["confidence"] = round(
                    min(0.95, existing["confidence"] + issue["confidence"] * 0.3), 3
                )
                existing["source"] += f" + 뉴스({issue['news_count']}건)"
        detected = list(detected_map.values())

        # 심각도 집계
        severity_rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
        max_severity  = "LOW"
        for issue in detected:
            if severity_rank.get(issue["severity"], 0) > severity_rank.get(max_severity, 0):
                max_severity = issue["severity"]

        summary = self._build_summary(detected, max_severity)
        self.log("info", f"이슈 감지 완료: {len(detected)}건 (최대 등급: {max_severity})")

        # 히스토리 컨텍스트 (선택적)
        hist_ctx = self._build_history_context(us, comm) if _HISTORY_AVAILABLE else {}

        result_payload = {
            "active_issues":     detected,
            "issue_count":       len(detected),
            "max_severity":      max_severity,
            "summary":           summary,
            "history_context":   hist_ctx,
        }

        msg = self.create_message(
            to="WA",
            data_type="ISSUE_ANALYSIS",
            payload=result_payload,
        )
        msg.status = {"code": "OK", "message": f"이슈 {len(detected)}건 감지"}
        return msg

    # ------------------------------------------------------------------
    # 이슈 감지 (룰 기반)
    # ------------------------------------------------------------------

    def _detect_issues(self, us: dict, kr: dict, comm: dict) -> list:
        """
        시장 지표에서 룰 기반으로 이슈를 감지한다.
        각 룰은 독립적으로 평가 — 중복 이슈는 ID로 중복 제거.
        """
        detected: dict[str, dict] = {}  # issue_id → issue_dict

        vix_val       = us.get("vix", {}).get("value", 0.0)
        usd_krw_chg   = us.get("usd_krw", {}).get("change_pct", 0.0)
        gold_chg      = comm.get("gold", {}).get("change_pct", 0.0)
        wti_chg       = comm.get("wti", {}).get("change_pct", 0.0)
        copper_chg    = comm.get("copper", {}).get("change_pct", 0.0)
        sox_chg       = us.get("sox", {}).get("change_pct", 0.0)
        nasdaq_chg    = us.get("nasdaq", {}).get("change_pct", 0.0)
        foreign_net   = kr.get("foreign_net", 0)

        # ---- ISS_001: VIX 급등 ----
        if vix_val >= 20.0:
            issue = self._make_issue_entry(
                issue_id   = "ISS_001",
                severity   = self._vix_severity(vix_val),
                confidence = min(0.95, 0.6 + (vix_val - 20) * 0.02),
                source     = f"VIX={vix_val:.1f}",
            )
            detected["ISS_001"] = issue

        # ---- ISS_002: 달러 강세 ----
        if usd_krw_chg >= 0.8:
            issue = self._make_issue_entry(
                issue_id   = "ISS_002",
                severity   = self._threshold_severity(
                    usd_krw_chg,
                    {"LOW": 0.5, "MEDIUM": 0.8, "HIGH": 1.2, "CRITICAL": 2.0},
                ),
                confidence = min(0.90, 0.5 + usd_krw_chg * 0.2),
                source     = f"USD/KRW 변화율={usd_krw_chg:+.2f}%",
            )
            detected["ISS_002"] = issue

        # ---- ISS_003: 지정학 리스크 (금 + 유가 동반 급등) ----
        if gold_chg >= 1.5 and wti_chg >= 2.0:
            issue = self._make_issue_entry(
                issue_id   = "ISS_003",
                severity   = self._threshold_severity(
                    gold_chg + wti_chg,
                    {"LOW": 3.0, "MEDIUM": 5.0, "HIGH": 8.0, "CRITICAL": 12.0},
                ),
                confidence = min(0.75, 0.4 + (gold_chg + wti_chg) * 0.05),
                source     = f"금={gold_chg:+.2f}% + WTI={wti_chg:+.2f}% 동반 급등",
            )
            detected["ISS_003"] = issue

        # ---- ISS_004: 인플레이션 충격 (유가 급등 + VIX 상승) ----
        if wti_chg >= 3.0 and vix_val >= 22.0:
            issue = self._make_issue_entry(
                issue_id   = "ISS_004",
                severity   = self._threshold_severity(
                    wti_chg,
                    {"LOW": 2.0, "MEDIUM": 3.0, "HIGH": 5.0, "CRITICAL": 8.0},
                ),
                confidence = 0.60,
                source     = f"WTI={wti_chg:+.2f}% + VIX={vix_val:.1f}",
            )
            detected["ISS_004"] = issue

        # ---- ISS_005: 반도체 다운사이클 (SOX 약세) ----
        if sox_chg <= -2.0:
            issue = self._make_issue_entry(
                issue_id   = "ISS_005",
                severity   = self._threshold_severity(
                    abs(sox_chg),
                    {"LOW": 1.0, "MEDIUM": 2.0, "HIGH": 3.5, "CRITICAL": 5.0},
                ),
                confidence = min(0.80, 0.5 + abs(sox_chg) * 0.08),
                source     = f"SOX={sox_chg:+.2f}%",
            )
            detected["ISS_005"] = issue

        # ---- ISS_006: 외국인 대량 순매도 ----
        if foreign_net <= -3e11:  # -3000억
            issue = self._make_issue_entry(
                issue_id   = "ISS_006",
                severity   = self._threshold_severity(
                    abs(foreign_net),
                    {"LOW": 1e11, "MEDIUM": 3e11, "HIGH": 5e11, "CRITICAL": 8e11},
                ),
                confidence = min(0.85, 0.5 + abs(foreign_net) / 1e12 * 0.3),
                source     = f"외국인 순매도={foreign_net/1e8:.0f}억",
            )
            detected["ISS_006"] = issue

        # ---- ISS_007: 블랙스완 (VIX 35 이상 + 복합 약세) ----
        negative_count = sum([
            1 if vix_val >= 35 else 0,
            1 if nasdaq_chg <= -3.0 else 0,
            1 if sox_chg <= -3.0 else 0,
            1 if usd_krw_chg >= 1.5 else 0,
            1 if gold_chg >= 2.0 else 0,
        ])
        if negative_count >= 3:
            issue = self._make_issue_entry(
                issue_id   = "ISS_007",
                severity   = "CRITICAL",
                confidence = min(0.95, 0.5 + negative_count * 0.1),
                source     = f"복합 위기 신호 {negative_count}개 동시 발생",
            )
            detected["ISS_007"] = issue

        return list(detected.values())

    # ------------------------------------------------------------------
    # 뉴스 기반 이슈 감지
    # ------------------------------------------------------------------

    def _detect_issues_from_news(self, news: list) -> list:
        """
        뉴스 헤드라인 키워드 매칭으로 이슈를 감지한다.
        동일 issue_id는 매칭 수에 따라 confidence를 높인다.
        """
        if not news:
            return []

        # 제목 전체를 이어붙인 텍스트로 한 번에 검색
        titles = [item.get("title", "") for item in news]

        detected: dict[str, dict] = {}
        for rule in _NEWS_KEYWORD_RULES:
            issue_id = rule["issue_id"]
            matches = sum(
                1 for t in titles
                if any(kw in t for kw in rule["keywords"])
            )
            if matches == 0:
                continue

            confidence = round(
                min(0.85, rule["base_confidence"] + matches * 0.05), 3
            )
            issue = self._make_issue_entry(
                issue_id   = issue_id,
                severity   = rule["severity"],
                confidence = confidence,
                source     = f"뉴스 키워드 매칭 {matches}건",
            )
            issue["news_count"] = matches
            detected[issue_id] = issue

        if detected:
            self.log("info", f"뉴스 기반 이슈 감지: {len(detected)}건 ({', '.join(detected.keys())})")
        return list(detected.values())

    # ------------------------------------------------------------------
    # 이슈 엔트리 생성
    # ------------------------------------------------------------------

    def _make_issue_entry(
        self,
        issue_id: str,
        severity: str,
        confidence: float,
        source: str,
    ) -> dict:
        """
        라이브러리 카드를 기반으로 활성 이슈 dict를 생성한다.
        라이브러리에 없으면 기본값으로 생성.
        """
        card = self._library.get(issue_id, {})

        name     = card.get("name", f"미분류 이슈 ({issue_id})")
        category = card.get("category", "기타")

        # 피해 섹터
        affected_sectors: list[str] = []
        market_impact = card.get("시장영향", {})
        sector_impact = market_impact.get("섹터영향", {})
        affected_sectors = sector_impact.get("가장큰피해", [])

        # strategy_override: HIGH 이상이면 WeightAdjuster가 전략 강제 검토
        strategy_override = severity in ("HIGH", "CRITICAL")

        # direction: CRITICAL/HIGH → SELL, MEDIUM → HOLD, LOW → NONE
        direction_map = {"CRITICAL": "SELL", "HIGH": "SELL", "MEDIUM": "HOLD", "LOW": "NONE"}
        direction = direction_map.get(severity, "NONE")

        return {
            "issue_id":          issue_id,
            "name":              name,
            "category":          category,
            "severity":          severity,
            "confidence":        round(confidence, 3),
            "affected_sectors":  affected_sectors,
            "strategy_override": strategy_override,
            "direction":         direction,
            "source":            source,
        }

    # ------------------------------------------------------------------
    # 심각도 유틸리티
    # ------------------------------------------------------------------

    def _vix_severity(self, vix: float) -> str:
        if vix >= 35:
            return "CRITICAL"
        if vix >= 30:
            return "HIGH"
        if vix >= 25:
            return "MEDIUM"
        return "LOW"

    def _threshold_severity(self, value: float, thresholds: dict) -> str:
        """
        thresholds = {"LOW": t1, "MEDIUM": t2, "HIGH": t3, "CRITICAL": t4}
        value가 임계값 이상인 최대 등급을 반환.
        """
        rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
        result = "LOW"
        for level, threshold in thresholds.items():
            if value >= threshold and rank.get(level, 0) >= rank.get(result, 0):
                result = level
        return result

    # ------------------------------------------------------------------
    # 히스토리 컨텍스트 (선택적)
    # ------------------------------------------------------------------

    def _build_history_context(self, us: dict, comm: dict) -> dict:
        """
        히스토리 데이터와 비교한 현재 시장 맥락.
        VIX/USD/KRW/Gold의 역사적 백분위를 계산해 이슈 판단에 참고 정보 제공.
        """
        ctx = {}
        try:
            hl = _get_history_loader()
            vix_val      = us.get("vix", {}).get("value", 0.0) or 0.0
            usd_krw_val  = us.get("usd_krw", {}).get("value", 0.0) or 0.0
            gold_chg     = comm.get("gold", {}).get("change_pct", 0.0) or 0.0

            if vix_val > 0:
                pct = hl.percentile("vix", vix_val)
                ctx["vix_percentile"] = pct  # 역사적 1년 대비 백분위
                ctx["vix_extreme"]    = (pct or 0) >= 90

            if usd_krw_val > 0:
                pct = hl.percentile("usd_krw", usd_krw_val)
                ctx["usdkrw_percentile"] = pct
                ctx["usdkrw_high"]       = (pct or 0) >= 80

            if gold_chg != 0:
                z = hl.z_score("gold", gold_chg)
                ctx["gold_zscore"] = z   # 오늘 금 등락률이 몇 시그마인지
        except Exception as e:
            logger.debug("[이슈관리] 히스토리 컨텍스트 실패 (무시): %s", e)

        return ctx

    # ------------------------------------------------------------------
    # 요약 생성
    # ------------------------------------------------------------------

    def _build_summary(self, issues: list, max_severity: str) -> str:
        if not issues:
            return "감지된 이슈 없음 - 정상 시장 상태"

        names = [i["name"] for i in issues]
        return f"[{max_severity}] 활성 이슈 {len(issues)}건: " + ", ".join(names[:3]) + (
            f" 외 {len(names)-3}건" if len(names) > 3 else ""
        )

    # ------------------------------------------------------------------
    # 빈 응답
    # ------------------------------------------------------------------

    def _empty_response(self, reason: str = "") -> StandardMessage:
        msg = self.create_message(
            to="WA",
            data_type="ISSUE_ANALYSIS",
            payload={
                "active_issues": [],
                "issue_count":   0,
                "max_severity":  "LOW",
                "summary":       reason or "이슈 없음",
            },
        )
        msg.status = {"code": "OK", "message": reason or "no issues"}
        return msg

    # ------------------------------------------------------------------
    # 라이브러리 관리 (공개 API)
    # ------------------------------------------------------------------

    def list_issues(self, category: Optional[str] = None) -> list:
        """
        이슈 라이브러리 목록 반환.
        category 지정 시 해당 카테고리만 필터링.
        """
        cards = list(self._library.values())
        if category:
            cards = [c for c in cards if c.get("category") == category]
        return sorted(cards, key=lambda c: c.get("issue_id", ""))

    def get_issue(self, issue_id: str) -> Optional[dict]:
        """이슈 카드 단건 조회."""
        return self._library.get(issue_id)

    def save_new_issue(self, card: dict) -> Optional[str]:
        """
        신규 이슈 카드를 라이브러리에 저장한다.
        issue_id가 없으면 자동 생성.
        반환: issue_id 또는 None (실패 시).
        """
        try:
            if not card.get("issue_id"):
                card["issue_id"] = f"ISS_{str(uuid.uuid4())[:8].upper()}"

            category = card.get("category", "기타")
            card["updated_at"] = datetime.now(timezone.utc).date().isoformat()

            # 폴더 생성
            category_dir = os.path.join(_ISSUE_LIBRARY_ROOT, category)
            os.makedirs(category_dir, exist_ok=True)

            # 파일 저장
            safe_name = card.get("name", card["issue_id"]).replace("/", "_").replace(" ", "_")
            fpath = os.path.join(category_dir, f"{card['issue_id']}_{safe_name}.json")
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(card, f, ensure_ascii=False, indent=2)

            self._library[card["issue_id"]] = card
            logger.info("[이슈관리] 신규 이슈 저장: %s (%s)", card["issue_id"], card.get("name"))
            return card["issue_id"]

        except Exception as exc:
            logger.warning("[이슈관리] save_new_issue 실패: %s", exc)
            return None
