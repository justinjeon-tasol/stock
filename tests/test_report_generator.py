"""
ReportGenerator 단위 테스트
"""

import os
import tempfile
import pytest

# 테스트 대상 모듈 임포트
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from report_generator import ReportGenerator


# ---------------------------------------------------------------------------
# 테스트용 픽스처 데이터
# ---------------------------------------------------------------------------

def _make_payload(
    phase="급등장",
    confidence=0.82,
    recommendations=None,
    market_summary="미국 반도체 지수(SOX)가 +3.8% 급등하며 기술주 강세를 이끌었습니다.",
    active_signals=None,
):
    """테스트용 RecommendationPayload dict를 반환한다."""
    if recommendations is None:
        recommendations = [
            {
                "code":      "000660",
                "name":      "SK하이닉스",
                "direction": "BUY",
                "weight":    0.30,
                "reasons":   [
                    "SOX 급등 → 반도체 수혜 (변동률: +3.8%)",
                    "현재 국면(급등장)에서 반도체 섹터 공격 비중 100% 적용",
                ],
                "leading_indicators": ["sox_surge: +3.8%"],
                "risk_factors":       ["VIX 상승 중 주의"],
            },
            {
                "code":      "005930",
                "name":      "삼성전자",
                "direction": "BUY",
                "weight":    0.25,
                "reasons":   ["SOX 급등 → 반도체 수혜 (변동률: +3.8%)"],
                "leading_indicators": [],
                "risk_factors":       [],
            },
        ]
    if active_signals is None:
        active_signals = [
            {
                "signal_id":   "sox_surge",
                "direction":   "BUY",
                "kr_sectors":  ["반도체"],
                "description": "SOX 급등 → 반도체 수혜",
                "strength":    1.9,
                "value":       3.8,
            },
            {
                "signal_id":   "vix_spike",
                "direction":   "AVOID",
                "kr_sectors":  [],
                "description": "VIX 30 돌파 → 외국인 대량 매도 예고",
                "strength":    1.07,
                "value":       32.0,
            },
        ]
    return {
        "phase":            phase,
        "phase_confidence": confidence,
        "recommendations":  recommendations,
        "market_summary":   market_summary,
        "active_signals":   active_signals,
        "generated_at":     "2026-03-28T09:30:00+00:00",
    }


def _make_market_data():
    """테스트용 시장 지표 dict를 반환한다."""
    return {
        "us_market": {
            "nasdaq": {"value": 19500.0, "change_pct": 2.1,  "volume_ratio": 1.3},
            "sox":    {"value": 5200.0,  "change_pct": 3.8,  "volume_ratio": 1.8},
            "sp500":  {"value": 5800.0,  "change_pct": 1.2,  "volume_ratio": 1.1},
            "vix":    {"value": 18.2,    "change_pct": -5.0},
            "usd_krw": {"value": 1330.0, "change_pct": -0.2},
            "futures": {"value": 19550.0, "direction": "UP"},
            "individual": {
                "NVDA": {"value": 800.0, "change_pct": 5.2},
                "AMD":  {"value": 160.0, "change_pct": 2.1},
                "TSLA": {"value": 250.0, "change_pct": 1.0},
            },
        },
        "kr_market": {
            "kospi":  {"value": 2750.0, "change_pct": 0.8,  "volume_ratio": 1.1},
            "kosdaq": {"value": 880.0,  "change_pct": 1.2,  "volume_ratio": 1.2},
            "foreign_net":     500,
            "institution_net": 200,
            "stocks": {},
        },
        "commodities": {
            "wti":     {"value": 80.0, "change_pct": 1.0},
            "gold":    {"value": 2000.0, "change_pct": 0.5},
            "copper":  {"value": 4.2,  "change_pct": 0.8},
            "lithium": {"value": 20.0, "change_pct": 0.3},
        },
    }


# ---------------------------------------------------------------------------
# 테스트 케이스
# ---------------------------------------------------------------------------

class TestReportGenerator:
    """ReportGenerator 테스트 스위트."""

    def setup_method(self):
        """각 테스트 전에 ReportGenerator 인스턴스를 초기화한다."""
        self.rg = ReportGenerator()

    # 1. generate() 결과가 str 타입인지 확인
    def test_generate_returns_string(self):
        """generate() 반환값이 str 이어야 한다."""
        payload = _make_payload()
        result  = self.rg.generate(payload)
        assert isinstance(result, str), "generate() 반환값은 str이어야 한다"
        assert len(result) > 0, "리포트 텍스트가 비어있으면 안 된다"

    # 2. 국면명 포함 여부
    def test_report_contains_phase(self):
        """리포트 텍스트에 국면명(급등장)이 포함되어야 한다."""
        payload = _make_payload(phase="급등장")
        report  = self.rg.generate(payload)
        assert "급등장" in report, "리포트에 국면명 '급등장'이 포함되어야 한다"

    def test_report_contains_phase_confidence(self):
        """리포트 텍스트에 신뢰도(82%)가 포함되어야 한다."""
        payload = _make_payload(phase="급등장", confidence=0.82)
        report  = self.rg.generate(payload)
        assert "82%" in report, "리포트에 신뢰도 '82%'가 포함되어야 한다"

    # 3. 추천 종목명 포함 여부
    def test_report_contains_stock_name(self):
        """리포트 텍스트에 추천 종목명이 포함되어야 한다."""
        payload = _make_payload()
        report  = self.rg.generate(payload)
        assert "SK하이닉스" in report, "리포트에 'SK하이닉스'가 포함되어야 한다"
        assert "삼성전자" in report,   "리포트에 '삼성전자'가 포함되어야 한다"

    # 4. 추천 이유 포함 여부
    def test_report_contains_reasons(self):
        """리포트 텍스트에 추천 이유가 포함되어야 한다."""
        payload = _make_payload()
        report  = self.rg.generate(payload)
        assert "SOX 급등" in report, "리포트에 추천 이유 'SOX 급등'이 포함되어야 한다"

    # 5. 추천 없을 때 (급락장) 정상 처리
    def test_report_empty_recommendations(self):
        """추천 종목이 없을 때(급락장) 오류 없이 처리되어야 한다."""
        payload = _make_payload(
            phase="급락장",
            confidence=0.75,
            recommendations=[],
            active_signals=[],
            market_summary="시장이 급락 중입니다.",
        )
        report = self.rg.generate(payload)
        assert isinstance(report, str), "급락장 리포트도 str이어야 한다"
        assert "급락장" in report,          "급락장 국면명이 포함되어야 한다"
        assert "추천 종목 (0개)" in report,  "추천 종목 0개가 표시되어야 한다"

    # 6. save_to_file() 파일 실제 생성 확인
    def test_save_to_file_creates_file(self):
        """save_to_file()이 실제 파일을 생성하고 경로를 반환해야 한다."""
        payload     = _make_payload()
        report_text = self.rg.generate(payload)

        # tmp 디렉토리를 reports 경로로 임시 변경
        original_dir = self.rg.REPORTS_DIR
        with tempfile.TemporaryDirectory() as tmpdir:
            self.rg.REPORTS_DIR = tmpdir
            saved_path = self.rg.save_to_file(report_text, "test_report.txt")
            self.rg.REPORTS_DIR = original_dir  # 복원

            assert os.path.isfile(saved_path), f"파일이 생성되어야 한다: {saved_path}"
            content = open(saved_path, encoding="utf-8").read()
            assert len(content) > 0, "저장된 파일 내용이 비어있으면 안 된다"

    def test_save_to_file_auto_filename(self):
        """filename을 지정하지 않으면 report_YYYYMMDD_HHMMSS.txt 형식으로 자동 생성된다."""
        payload     = _make_payload()
        report_text = self.rg.generate(payload)

        original_dir = self.rg.REPORTS_DIR
        with tempfile.TemporaryDirectory() as tmpdir:
            self.rg.REPORTS_DIR = tmpdir
            saved_path = self.rg.save_to_file(report_text)  # filename 미지정
            self.rg.REPORTS_DIR = original_dir

            basename = os.path.basename(saved_path)
            assert basename.startswith("report_"), "자동 생성 파일명은 'report_'로 시작해야 한다"
            assert basename.endswith(".txt"),       "자동 생성 파일명은 '.txt'로 끝나야 한다"

    # 7. _direction_label() — BUY/HOLD/AVOID 변환
    def test_direction_label_buy(self):
        """BUY → '매수 추천'으로 변환되어야 한다."""
        assert self.rg._direction_label("BUY") == "매수 추천"

    def test_direction_label_hold(self):
        """HOLD → '관망'으로 변환되어야 한다."""
        assert self.rg._direction_label("HOLD") == "관망"

    def test_direction_label_avoid(self):
        """AVOID → '회피'로 변환되어야 한다."""
        assert self.rg._direction_label("AVOID") == "회피"

    def test_direction_label_unknown(self):
        """알 수 없는 방향은 원본 문자열을 반환해야 한다."""
        assert self.rg._direction_label("UNKNOWN") == "UNKNOWN"

    # 8. _phase_weights_text() — 국면별 비중 텍스트
    def test_phase_weights_text_surge(self):
        """급등장 비중 텍스트가 '공격 100%'를 포함해야 한다."""
        text = self.rg._phase_weights_text("급등장")
        assert "공격 100%" in text, f"급등장 비중 텍스트 오류: {text}"

    def test_phase_weights_text_stable(self):
        """안정화 비중 텍스트가 '공격 70%'를 포함해야 한다."""
        text = self.rg._phase_weights_text("안정화")
        assert "공격 70%" in text, f"안정화 비중 텍스트 오류: {text}"

    def test_phase_weights_text_crash(self):
        """급락장 비중 텍스트가 '현금 50%'를 포함해야 한다."""
        text = self.rg._phase_weights_text("급락장")
        assert "현금 50%" in text, f"급락장 비중 텍스트 오류: {text}"

    def test_phase_weights_text_volatile(self):
        """변동폭큰 비중 텍스트가 '현금 80%'를 포함해야 한다."""
        text = self.rg._phase_weights_text("변동폭큰")
        assert "현금 80%" in text, f"변동폭큰 비중 텍스트 오류: {text}"

    def test_phase_weights_text_unknown(self):
        """알 수 없는 국면은 '현금 100%' fallback을 반환해야 한다."""
        text = self.rg._phase_weights_text("알수없음")
        assert "현금 100%" in text, f"알 수 없는 국면 fallback 오류: {text}"

    # 추가: market_data가 있을 때 지표가 리포트에 포함되는지 확인
    def test_report_with_market_data_contains_indicators(self):
        """market_data가 있으면 코스피, 나스닥100 지표가 리포트에 포함되어야 한다."""
        payload     = _make_payload()
        market_data = _make_market_data()
        report      = self.rg.generate(payload, market_data=market_data)
        assert "나스닥100" in report, "시장 지표에 '나스닥100'이 포함되어야 한다"
        assert "코스피"    in report, "시장 지표에 '코스피'가 포함되어야 한다"

    # 추가: market_data 없을 때 정상 처리
    def test_report_without_market_data(self):
        """market_data가 None이어도 오류 없이 리포트를 생성해야 한다."""
        payload = _make_payload()
        report  = self.rg.generate(payload, market_data=None)
        assert isinstance(report, str) and len(report) > 0
