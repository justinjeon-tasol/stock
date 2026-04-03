"""
리포트 생성 모듈
Recommender의 RecommendationPayload(dict)를 받아
사람이 읽기 좋은 리포트를 콘솔 출력 및 파일로 저장한다.
"""

import io
import os
import sys
from datetime import datetime
from pathlib import Path

# rich 라이브러리 선택적 임포트 (없으면 plain text fallback)
try:
    from rich.console import Console
    from rich.text import Text
    from rich.panel import Panel
    _RICH_AVAILABLE = True
except ImportError:
    _RICH_AVAILABLE = False


# 국면별 포트폴리오 비중 텍스트
_PHASE_WEIGHTS_TEXT = {
    "급등장":   "공격 100% | 방어 0% | 현금 0%",
    "안정화":   "공격 70% | 방어 0% | 현금 30%",
    "급락장":   "공격 0% | 방어 50% | 현금 50%",
    "변동폭큰": "공격 0% | 방어 20% | 현금 80%",
}

# 방향(direction) → 한국어 레이블 매핑
_DIRECTION_LABEL = {
    "BUY":   "매수 추천",
    "HOLD":  "관망",
    "AVOID": "회피",
}

# 구분선 길이
_LINE_WIDTH = 64


class ReportGenerator:
    """추천 결과를 사람이 읽기 쉬운 텍스트 리포트로 변환하는 클래스."""

    REPORTS_DIR = "reports"

    # ------------------------------------------------------------------
    # 공개 인터페이스
    # ------------------------------------------------------------------

    def generate(self, payload: dict, market_data: dict = None) -> str:
        """
        전체 리포트 텍스트를 생성하여 반환한다 (plain text).

        Args:
            payload:     RecommendationPayload를 dict로 변환한 것
            market_data: 시장 지표 dict (선택, 있으면 헤더에 출력)

        Returns:
            완성된 리포트 문자열
        """
        lines = []
        lines.append(self._format_header())
        lines.append("")
        lines.append(self._format_market_phase(payload))
        lines.append("")

        # 시장 요약
        summary = payload.get("market_summary", "")
        if summary:
            lines.append("[시장 요약]")
            lines.append(f"  {summary}")
            lines.append("")

        # 시장 지표 (market_data 있을 때만)
        if market_data:
            market_lines = self._format_market_indicators(market_data)
            if market_lines:
                lines.extend(market_lines)
                lines.append("")

        # 활성 신호
        active_signals = payload.get("active_signals", [])
        if active_signals:
            lines.append(self._format_active_signals(active_signals))
            lines.append("")

        # 추천 종목
        recommendations = payload.get("recommendations", [])
        lines.append("-" * _LINE_WIDTH)
        lines.append(f"  추천 종목 ({len(recommendations)}개)")
        lines.append("-" * _LINE_WIDTH)
        lines.append("")

        if recommendations:
            for idx, rec in enumerate(recommendations, start=1):
                lines.append(self._format_stock_card(idx, rec))
        else:
            lines.append("  현재 국면에서 추천 종목이 없습니다.")
            lines.append("  현금 비중을 유지하세요.")
            lines.append("")

        lines.append(self._format_footer(payload))

        return "\n".join(lines)

    def print_to_console(self, payload: dict, market_data: dict = None) -> None:
        """
        rich 라이브러리가 있으면 컬러 출력, 없으면 plain text로 fallback 출력.

        Args:
            payload:     RecommendationPayload dict
            market_data: 시장 지표 dict (선택)
        """
        report = self.generate(payload, market_data)

        if _RICH_AVAILABLE:
            # rich를 이용한 컬러 출력
            console = Console()
            console.print(report, highlight=False)
        else:
            # Windows CP949 환경에서 유니코드 안전 출력
            try:
                print(report)
            except UnicodeEncodeError:
                # 인코딩 불가 문자를 '?' 로 대체
                enc = sys.stdout.encoding or "utf-8"
                safe = report.encode(enc, errors="replace").decode(enc)
                print(safe)

    def save_to_file(self, report: str, filename: str = None) -> str:
        """
        reports/ 디렉토리에 리포트를 저장한다.

        Args:
            report:   저장할 리포트 텍스트
            filename: 파일명 (None이면 report_YYYYMMDD_HHMMSS.txt 자동 생성)

        Returns:
            저장된 파일의 절대 경로 문자열
        """
        # reports/ 디렉토리 없으면 자동 생성
        reports_path = Path(self.REPORTS_DIR)
        reports_path.mkdir(parents=True, exist_ok=True)

        # 파일명 결정
        if not filename:
            now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"report_{now_str}.txt"

        file_path = reports_path / filename
        file_path.write_text(report, encoding="utf-8")

        return str(file_path.resolve())

    # ------------------------------------------------------------------
    # 포맷 헬퍼
    # ------------------------------------------------------------------

    def _format_header(self) -> str:
        """리포트 상단 헤더를 생성한다."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        title = f"한국 주식 추천 리포트 | {now_str}"
        border = "=" * _LINE_WIDTH
        # 가운데 정렬 (양쪽 공백 패딩)
        inner_width = _LINE_WIDTH - 2  # border 양끝 제외
        centered = title.center(inner_width)
        return f"{border}\n {centered}\n{border}"

    def _format_market_phase(self, payload: dict) -> str:
        """시장 국면 및 신뢰도 줄을 생성한다."""
        phase      = payload.get("phase", "알 수 없음")
        confidence = payload.get("phase_confidence", 0.0)
        conf_pct   = int(round(confidence * 100))
        return f"[시장 국면] {phase}  (신뢰도: {conf_pct}%)"

    def _format_market_indicators(self, market_data: dict) -> list:
        """
        시장 지표 줄 목록을 생성한다.
        market_data 구조: {"us_market": {...}, "kr_market": {...}, ...}
        """
        lines = []
        us = market_data.get("us_market", {})
        kr = market_data.get("kr_market", {})

        # 미국 지표 줄
        us_parts = []
        nasdaq_chg = us.get("nasdaq", {}).get("change_pct")
        if nasdaq_chg is not None:
            us_parts.append(f"나스닥100 {nasdaq_chg:+.1f}%")
        sox_chg = us.get("sox", {}).get("change_pct")
        if sox_chg is not None:
            us_parts.append(f"SOX {sox_chg:+.1f}%")
        vix_val = us.get("vix", {}).get("value")
        if vix_val is not None:
            us_parts.append(f"VIX {vix_val:.1f}")
        if us_parts:
            lines.append("  " + "  |  ".join(us_parts))

        # 한국 지표 줄
        kr_parts = []
        kospi_chg = kr.get("kospi", {}).get("change_pct")
        if kospi_chg is not None:
            kr_parts.append(f"코스피 {kospi_chg:+.1f}%")
        kosdaq_chg = kr.get("kosdaq", {}).get("change_pct")
        if kosdaq_chg is not None:
            kr_parts.append(f"코스닥 {kosdaq_chg:+.1f}%")
        if kr_parts:
            lines.append("  " + "  |  ".join(kr_parts))

        return lines

    def _format_active_signals(self, active_signals: list) -> str:
        """활성 신호 목록을 형식화한다."""
        lines = ["[활성 신호]"]
        for sig in active_signals:
            direction   = sig.get("direction", "")
            description = sig.get("description", sig.get("signal_id", ""))
            value       = sig.get("value", 0.0)

            # 방향에 따른 아이콘 (plain text, CP949 호환)
            if direction == "BUY":
                icon = "[BUY]"
            elif direction == "AVOID":
                icon = "[SELL]"
            else:
                icon = "[HOLD]"

            # 값 표시 형식 결정
            signal_id = sig.get("signal_id", "")
            if signal_id == "vix_spike":
                # VIX는 절대값으로 표시
                val_str = f"({value:.1f})"
            else:
                val_str = f"({value:+.1f}%)"

            lines.append(f"  {icon} {description}  {val_str}")
        return "\n".join(lines)

    def _format_stock_card(self, idx: int, rec: dict) -> str:
        """개별 종목 추천 카드를 형식화한다."""
        name      = rec.get("name",      "알 수 없음")
        code      = rec.get("code",      "------")
        direction = rec.get("direction", "HOLD")
        weight    = rec.get("weight",    0.0)
        reasons   = rec.get("reasons",   [])
        risk_factors = rec.get("risk_factors", [])

        dir_label  = self._direction_label(direction)
        weight_pct = int(round(weight * 100))

        # 종목명 + 코드 줄 (방향 레이블 오른쪽 정렬 시도)
        left_part  = f"  [{idx}] {name} ({code})"
        right_part = f"[{dir_label}]"
        # 정렬: 전체 _LINE_WIDTH 기준으로 오른쪽 패딩
        gap = _LINE_WIDTH - len(left_part) - len(right_part)
        header_line = left_part + (" " * max(1, gap)) + right_part

        lines = [header_line]
        lines.append(f"      추천 비중: {weight_pct}%")

        # 추천 이유
        if reasons:
            lines.append("      추천 이유:")
            for r in reasons:
                lines.append(f"        - {r}")

        # 리스크
        if risk_factors:
            lines.append("      리스크:")
            for rf in risk_factors:
                lines.append(f"        - {rf}")

        lines.append("")
        return "\n".join(lines)

    def _format_footer(self, payload: dict) -> str:
        """리포트 하단 푸터(국면 비중 + 구분선)를 생성한다."""
        phase = payload.get("phase", "안정화")
        weights_text = self._phase_weights_text(phase)
        border = "=" * _LINE_WIDTH
        return f"-" * _LINE_WIDTH + f"\n  국면 비중: {weights_text}\n{border}"

    # ------------------------------------------------------------------
    # 텍스트 변환 헬퍼
    # ------------------------------------------------------------------

    def _direction_label(self, direction: str) -> str:
        """
        방향 코드를 한국어 레이블로 변환한다.
        BUY → 매수 추천, HOLD → 관망, AVOID → 회피
        """
        return _DIRECTION_LABEL.get(direction, direction)

    def _phase_weights_text(self, phase: str) -> str:
        """국면별 비중 텍스트를 반환한다."""
        return _PHASE_WEIGHTS_TEXT.get(phase, "공격 0% | 방어 0% | 현금 100%")
