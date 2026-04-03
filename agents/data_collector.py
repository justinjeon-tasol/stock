"""
데이터 수집 에이전트 모듈
yfinance(미국/원자재)와 pykrx(한국) 에서 시장 데이터를 수집하여 raw dict를 반환한다.
"""

import asyncio
import math
import os
from datetime import datetime, timedelta

from agents.base_agent import BaseAgent
from agents.classification_loader import ClassificationLoader
from protocol.protocol import StandardMessage


class DataCollector(BaseAgent):
    """미국/한국/원자재 시장 데이터를 수집하는 에이전트."""

    # 선물 방향성 판단 기준 (0.3% 이상/이하면 UP/DOWN, 그 사이면 FLAT)
    FUTURES_THRESHOLD = 0.3

    def __init__(self):
        super().__init__("DC", "데이터수집", timeout=30, max_retries=3)

        # 분류 체계 로더
        _CLASSIFICATION_PATH = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "stock_classification.json"
        )
        self._classification = ClassificationLoader(_CLASSIFICATION_PATH)

    # ------------------------------------------------------------------
    # 공개 인터페이스
    # ------------------------------------------------------------------

    async def execute(self, input_data=None) -> StandardMessage:
        """
        미국/한국/원자재 데이터를 수집하여 단일 StandardMessage로 반환한다.
        body.data_type = "RAW_MARKET_DATA"
        body.payload = {
            "us_market": {...},
            "kr_market": {...},
            "commodities": {...}
        }
        """
        self.log("info", "시장 데이터 수집 시작")

        us, kr, comm, news = await asyncio.gather(
            self._collect_us_market(),
            self._collect_kr_market(),
            self._collect_commodities(),
            self._collect_news(),
            return_exceptions=True,
        )

        if isinstance(us, Exception):
            self.log("error", f"미국 시장 수집 실패: {us}")
            us = self._default_us_market()
        if isinstance(kr, Exception):
            self.log("error", f"한국 시장 수집 실패: {kr}")
            kr = self._default_kr_market()
        if isinstance(comm, Exception):
            self.log("error", f"원자재 수집 실패: {comm}")
            comm = self._default_commodities()
        if isinstance(news, Exception):
            self.log("warning", f"뉴스 수집 실패: {news}")
            news = []

        payload = {
            "us_market":   us,
            "kr_market":   kr,
            "commodities": comm,
            "news":        news,
        }

        self.log("info", "시장 데이터 수집 완료")
        return self.create_message(
            to="PP",
            data_type="RAW_MARKET_DATA",
            payload=payload,
        )

    # ------------------------------------------------------------------
    # 미국 시장 수집
    # ------------------------------------------------------------------

    async def _collect_us_market(self) -> dict:
        """yfinance 동기 수집을 executor에서 비동기로 실행한다."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._collect_us_market_sync)

    def _collect_us_market_sync(self) -> dict:
        """
        yfinance로 나스닥100, S&P500, SOX, VIX, USD/KRW, 나스닥 선물,
        NVDA/AMD/TSLA 개별 종목 데이터를 수집한다.

        반환 형식:
        {
            "nasdaq":     {"value": float, "change_pct": float, "volume_ratio": float},
            "sox":        {"value": float, "change_pct": float, "volume_ratio": float},
            "sp500":      {"value": float, "change_pct": float, "volume_ratio": float},
            "vix":        {"value": float, "change_pct": float},
            "usd_krw":    {"value": float, "change_pct": float},
            "futures":    {"value": float, "direction": "UP|DOWN|FLAT"},
            "individual": {
                "NVDA": {"value": float, "change_pct": float},
                "AMD":  {"value": float, "change_pct": float},
                "TSLA": {"value": float, "change_pct": float},
            }
        }
        """
        try:
            import yfinance as yf

            # 지수 티커 매핑
            index_tickers = {
                "nasdaq": "^NDX",
                "sp500":  "^GSPC",
                "sox":    "^SOX",
            }
            result = {}

            # --- 지수 수집 (volume_ratio 포함) ---
            for key, ticker in index_tickers.items():
                try:
                    hist = yf.Ticker(ticker).history(period="1mo")
                    if hist.empty or len(hist) < 2:
                        result[key] = {"value": 0.0, "change_pct": 0.0, "volume_ratio": 1.0}
                        continue
                    closes  = hist["Close"].tolist()
                    volumes = hist["Volume"].tolist()
                    value      = round(closes[-1], 2)
                    change_pct = self._safe_change_pct(closes[-1], closes[-2])
                    vol_ratio  = self._safe_volume_ratio(volumes)
                    result[key] = {
                        "value":        value,
                        "change_pct":   change_pct,
                        "volume_ratio": vol_ratio,
                    }
                except Exception as exc:
                    self.log("warning", f"지수 수집 실패 [{ticker}]: {exc}")
                    result[key] = {"value": 0.0, "change_pct": 0.0, "volume_ratio": 1.0}

            # --- VIX ---
            try:
                hist = yf.Ticker("^VIX").history(period="1mo")
                if hist.empty or len(hist) < 2:
                    result["vix"] = {"value": 0.0, "change_pct": 0.0}
                else:
                    closes = hist["Close"].tolist()
                    result["vix"] = {
                        "value":      round(closes[-1], 2),
                        "change_pct": self._safe_change_pct(closes[-1], closes[-2]),
                    }
            except Exception as exc:
                self.log("warning", f"VIX 수집 실패: {exc}")
                result["vix"] = {"value": 0.0, "change_pct": 0.0}

            # --- USD/KRW 환율 ---
            try:
                hist = yf.Ticker("KRW=X").history(period="1mo")
                if hist.empty or len(hist) < 2:
                    result["usd_krw"] = {"value": 0.0, "change_pct": 0.0}
                else:
                    closes = hist["Close"].tolist()
                    result["usd_krw"] = {
                        "value":      round(closes[-1], 2),
                        "change_pct": self._safe_change_pct(closes[-1], closes[-2]),
                    }
            except Exception as exc:
                self.log("warning", f"USD/KRW 수집 실패: {exc}")
                result["usd_krw"] = {"value": 0.0, "change_pct": 0.0}

            # --- 나스닥 선물 ---
            try:
                hist = yf.Ticker("NQ=F").history(period="1mo")
                if hist.empty or len(hist) < 2:
                    result["futures"] = {"value": 0.0, "direction": "FLAT"}
                else:
                    closes     = hist["Close"].tolist()
                    value      = round(closes[-1], 2)
                    change_pct = self._safe_change_pct(closes[-1], closes[-2])
                    if change_pct > self.FUTURES_THRESHOLD:
                        direction = "UP"
                    elif change_pct < -self.FUTURES_THRESHOLD:
                        direction = "DOWN"
                    else:
                        direction = "FLAT"
                    result["futures"] = {"value": value, "direction": direction}
            except Exception as exc:
                self.log("warning", f"나스닥 선물 수집 실패: {exc}")
                result["futures"] = {"value": 0.0, "direction": "FLAT"}

            # --- 개별 종목 (classification proxy 티커 + 최소 보장 티커) ---
            _BASE_TICKERS = {"NVDA", "AMD", "TSLA"}  # 최소 보장 티커
            proxy_set = self._classification.get_all_proxy_tickers()
            all_tickers = sorted(proxy_set | _BASE_TICKERS)
            self.log("info", f"개별 종목 수집 대상: {all_tickers}")
            individual = {}
            for ticker in all_tickers:
                try:
                    hist = yf.Ticker(ticker).history(period="1mo")
                    if hist.empty or len(hist) < 2:
                        individual[ticker] = {"value": 0.0, "change_pct": 0.0}
                        continue
                    closes = hist["Close"].tolist()
                    individual[ticker] = {
                        "value":      round(closes[-1], 2),
                        "change_pct": self._safe_change_pct(closes[-1], closes[-2]),
                    }
                except Exception as exc:
                    self.log("warning", f"개별 종목 수집 실패 [{ticker}]: {exc}")
                    individual[ticker] = {"value": 0.0, "change_pct": 0.0}
            result["individual"] = individual

            return result

        except Exception as exc:
            # yfinance 임포트 실패 또는 최상위 예외
            self.log("error", f"미국 시장 수집 전체 실패: {exc}")
            return self._default_us_market()

    # ------------------------------------------------------------------
    # 한국 시장 수집
    # ------------------------------------------------------------------

    async def _collect_kr_market(self) -> dict:
        """pykrx 동기 수집을 executor에서 비동기로 실행한다."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._collect_kr_market_sync)

    # 종목코드 → history_loader 심볼 매핑 (yfinance도 실패 시 최후 수단)
    _CODE_TO_HISTORY = {
        "005930": "samsung",
        "000660": "sk_hynix",
        "373220": "lg_energy",
        "006400": "samsung_sdi",
        "042700": "hanmi_semi",
        "096770": "sk_inno",
    }

    def _build_stock_universe(self) -> dict:
        """
        stock_classification.json 에서 전체 종목 목록을 읽어 반환한다.
        반환: {"종목코드": "종목명", ...}
        코드 추가/삭제는 stock_classification.json 에서만 관리한다.
        """
        stocks = self._classification.get_all_stocks()  # {code: {...}}
        return {code: info.get("name", code) for code, info in stocks.items()}

    def _build_code_to_yf(self) -> dict:
        """
        stock_classification.json 의 market 필드로 yfinance 티커 자동 생성.
        KOSPI → code.KS / KOSDAQ → code.KQ / 나머지 → code.KS (기본)
        """
        stocks = self._classification.get_all_stocks()
        result = {}
        for code, info in stocks.items():
            market = info.get("market", "KOSPI")
            suffix = ".KQ" if market == "KOSDAQ" else ".KS"
            result[code] = f"{code}{suffix}"
        return result

    def _collect_kr_market_sync(self) -> dict:
        """
        한국 시장 데이터를 3단계 우선순위로 수집한다.
          1순위: pykrx (KRX 공식 데이터)
          2순위: yfinance (^KS11, ^KQ11, 종목코드.KS)
          3순위: 로컬 history CSV (최후 수단 — 전일 종가)

        반환 형식:
        {
            "kospi":   {"value": float, "change_pct": float, "volume_ratio": float},
            "kosdaq":  {"value": float, "change_pct": float, "volume_ratio": float},
            "foreign_net":     0,
            "institution_net": 0,
            "stocks": {
                "005930": {"name": "삼성전자", "price": int, "change_pct": float},
                ...
            }
        }
        """
        try:
            import logging as _logging
            from pykrx import stock

            today = self._get_recent_trading_date()
            # 최근 21 거래일 범위 계산 (volume_ratio 계산을 위해 21일치 필요)
            from_date = (datetime.strptime(today, "%Y%m%d") - timedelta(days=45)).strftime("%Y%m%d")
            # pykrx 내부 로깅 버그(logging.info(args,kwargs)) 노이즈 억제
            _logging.raiseExceptions = False

            result = {
                "foreign_net":     0,
                "institution_net": 0,
            }

            # --- 지수 수집 (pykrx → yfinance → history) ---
            index_map = {"kospi": "1001", "kosdaq": "2001"}
            for key, ticker in index_map.items():
                try:
                    df = stock.get_index_ohlcv_by_date(from_date, today, ticker)
                    if df is None or df.empty or len(df) < 2:
                        raise ValueError("빈 데이터")
                    closes  = df["종가"].tolist()
                    volumes = df["거래량"].tolist()
                    result[key] = {
                        "value":        round(closes[-1], 2),
                        "change_pct":   self._safe_change_pct(closes[-1], closes[-2]),
                        "volume_ratio": self._safe_volume_ratio(volumes),
                    }
                except Exception as exc:
                    self.log("warning", f"pykrx 지수 실패 [{ticker}]: {exc} → yfinance 시도")
                    result[key] = self._kr_index_from_yfinance(key)

            # --- 개별 종목 (pykrx → yfinance → history) ---
            # stock_classification.json 에서 동적으로 종목 목록 로드
            stock_list = self._build_stock_universe()
            code_to_yf = self._build_code_to_yf()
            self.log("info", f"종목 수집 대상: {len(stock_list)}개 ({', '.join(stock_list.values())})")
            stocks = {}
            for code, name in stock_list.items():
                try:
                    df = stock.get_market_ohlcv_by_date(from_date, today, code)
                    if df is None or df.empty or len(df) < 2:
                        raise ValueError("빈 데이터")
                    closes = df["종가"].tolist()
                    stocks[code] = {
                        "name":       name,
                        "price":      int(closes[-1]),
                        "change_pct": self._safe_change_pct(closes[-1], closes[-2]),
                    }
                except Exception as exc:
                    self.log("warning", f"pykrx 종목 실패 [{code}]: {exc} → yfinance 시도")
                    stocks[code] = self._kr_stock_from_yfinance(code, name, code_to_yf)
            result["stocks"] = stocks

            # --- 종목별 외국인+기관 순매수 (C안) ---
            _frgn, _inst = self._collect_kr_foreign_net_sync(today)
            result["stock_foreign_net"] = _frgn
            result["stock_institution_net"] = _inst

            return result

        except Exception as exc:
            self.log("error", f"한국 시장 수집 전체 실패: {exc}")
            return self._default_kr_market()

    def _collect_kr_foreign_net_sync(self, today: str) -> tuple:
        """
        종목별 외국인+기관 순매수 수집 (KIS API 우선 → pykrx 폴백).
        반환: (foreign_dict, institution_dict)
        """
        _TRACKED = [
            "005930", "000660", "042700", "373220", "006400", "068270",
        ]
        foreign, institution = self._foreign_net_from_kis(today, _TRACKED)
        if foreign:
            return foreign, institution
        # KIS 실패 시 pykrx 폴백 (기관은 빈 dict)
        return self._foreign_net_from_pykrx(today, set(_TRACKED)), {}

    @staticmethod
    def _safe_int(value, default=0):
        """KIS API 문자열을 안전하게 int로 변환."""
        try:
            return int(float(str(value).replace(",", "").strip()))
        except (ValueError, TypeError):
            return default

    def _foreign_net_from_kis(self, today: str, codes: list) -> tuple:
        """
        KIS API FHKST01010900으로 종목별 외국인+기관 순매수 거래대금 수집.
        오늘 데이터가 비어있으면 전일 데이터 사용.
        단위: 원 (frgn_ntby_tr_pbmn 백만원 × 1,000,000)

        반환: (foreign_dict, institution_dict)
          foreign_dict:     {code: 외국인순매수(원)}
          institution_dict: {code: 기관순매수(원)}
        """
        import os, requests as _req
        from dotenv import load_dotenv
        load_dotenv()

        app_key    = os.getenv("KIS_APP_KEY")
        app_secret = os.getenv("KIS_APP_SECRET")
        is_mock    = os.getenv("KIS_IS_MOCK", "true").lower() == "true"

        if not app_key or not app_secret:
            return {}, {}

        base = "https://openapivts.koreainvestment.com:29443" if is_mock else "https://openapi.koreainvestment.com:9443"

        try:
            r = _req.post(f"{base}/oauth2/tokenP", json={
                "grant_type": "client_credentials",
                "appkey": app_key,
                "appsecret": app_secret,
            }, timeout=8)
            if r.status_code != 200:
                return {}, {}
            token = r.json().get("access_token", "")
            if not token:
                return {}, {}
        except Exception:
            return {}, {}

        headers = {
            "authorization": f"Bearer {token}",
            "appkey": app_key,
            "appsecret": app_secret,
            "tr_id": "FHKST01010900",
            "Content-Type": "application/json; charset=utf-8",
        }

        from_dt = (datetime.strptime(today, "%Y%m%d") - timedelta(days=5)).strftime("%Y%m%d")

        foreign_result = {}
        institution_result = {}
        for code in codes:
            try:
                params = {
                    "FID_COND_MRKT_DIV_CODE": "J",
                    "FID_INPUT_ISCD": code,
                    "FID_PERIOD_DIV_CODE": "D",
                    "FID_INPUT_DATE_1": from_dt,
                    "FID_INPUT_DATE_2": today,
                }
                r2 = _req.get(f"{base}/uapi/domestic-stock/v1/quotations/inquire-investor",
                              headers=headers, params=params, timeout=8)
                if r2.status_code != 200:
                    continue
                rows = r2.json().get("output", [])
                for row in rows:
                    frgn_str = row.get("frgn_ntby_tr_pbmn", "")
                    if frgn_str and frgn_str.strip():
                        foreign_result[code] = self._safe_int(frgn_str) * 1_000_000
                        # 같은 row에서 기관 데이터도 추출
                        orgn_str = row.get("orgn_ntby_tr_pbmn", "")
                        institution_result[code] = (
                            self._safe_int(orgn_str) * 1_000_000 if orgn_str and orgn_str.strip() else 0
                        )
                        break
            except Exception:
                continue

        if foreign_result:
            self.log("info", f"투자자 순매수 KIS 수집: {len(foreign_result)}종목 "
                             f"(외국인+기관, 전일 기준)")
        return foreign_result, institution_result

    def _foreign_net_from_pykrx(self, today: str, codes: set) -> dict:
        """pykrx 폴백. 실패 시 빈 dict 반환."""
        try:
            import logging as _logging
            from pykrx import stock
            _prev_raise = _logging.raiseExceptions
            _logging.raiseExceptions = False
            try:
                df = stock.get_market_net_purchases_of_equities_by_ticker(today, today, "KOSPI", "외국인")
            finally:
                _logging.raiseExceptions = _prev_raise
            if df is None or df.empty:
                return {}
            result = {}
            for code in codes:
                if code not in df.index:
                    continue
                row = df.loc[code]
                for col in df.columns:
                    if "순매수" in str(col) and "거래대금" in str(col):
                        try:
                            result[code] = int(row[col])
                        except (TypeError, ValueError):
                            pass
                        break
            return result
        except Exception as exc:
            self.log("warning", f"외국인 순매수 pykrx 폴백 실패: {exc}")
            return {}

    def _kr_index_from_yfinance(self, key: str) -> dict:
        """2순위: yfinance로 KOSPI/KOSDAQ 지수 수집. 실패 시 history CSV 폴백."""
        import yfinance as yf
        yf_ticker_map = {"kospi": "^KS11", "kosdaq": "^KQ11"}
        yf_ticker = yf_ticker_map.get(key)
        try:
            hist = yf.Ticker(yf_ticker).history(period="1mo")
            if hist.empty or len(hist) < 2:
                raise ValueError("빈 데이터")
            closes  = hist["Close"].tolist()
            volumes = hist["Volume"].tolist()
            self.log("info", f"{key.upper()} yfinance 수집 성공: {closes[-1]:.2f}")
            return {
                "value":        round(closes[-1], 2),
                "change_pct":   self._safe_change_pct(closes[-1], closes[-2]),
                "volume_ratio": self._safe_volume_ratio(volumes),
            }
        except Exception as exc:
            self.log("warning", f"yfinance 지수 실패 [{yf_ticker}]: {exc} → history 폴백(전일)")
            return self._kr_index_from_history(key)

    def _kr_stock_from_yfinance(self, code: str, name: str, code_to_yf: dict = None) -> dict:
        """2순위: yfinance로 한국 개별 종목 수집. 실패 시 history CSV 폴백."""
        import yfinance as yf
        mapping = code_to_yf if code_to_yf is not None else self._build_code_to_yf()
        yf_ticker = mapping.get(code)
        if yf_ticker is None:
            return self._kr_stock_from_history(code, name)
        try:
            hist = yf.Ticker(yf_ticker).history(period="1mo")
            if hist.empty or len(hist) < 2:
                raise ValueError("빈 데이터")
            closes = hist["Close"].tolist()
            self.log("info", f"{name} yfinance 수집 성공: {int(closes[-1])}")
            return {
                "name":       name,
                "price":      int(closes[-1]),
                "change_pct": self._safe_change_pct(closes[-1], closes[-2]),
            }
        except Exception as exc:
            self.log("warning", f"yfinance 종목 실패 [{yf_ticker}]: {exc} → history 폴백(전일)")
            return self._kr_stock_from_history(code, name)

    def _kr_index_from_history(self, key: str) -> dict:
        """3순위(최후 수단): 로컬 history CSV의 최신 종가. 전일 데이터임을 로그에 명시."""
        from data.history.history_loader import get_loader
        symbol_map = {"kospi": "KOSPI", "kosdaq": "KOSDAQ"}
        symbol = symbol_map.get(key)
        if symbol is None:
            return {"value": 0.0, "change_pct": 0.0, "volume_ratio": 1.0}
        loader = get_loader()
        close = loader._load_close(symbol)
        if close is None or len(close) < 2:
            return {"value": 0.0, "change_pct": 0.0, "volume_ratio": 1.0}
        closes = close.tolist()
        self.log("warning", f"{key.upper()} history 폴백(전일): {closes[-1]:.2f} ({close.index[-1].date()})")
        return {
            "value":        round(closes[-1], 2),
            "change_pct":   self._safe_change_pct(closes[-1], closes[-2]),
            "volume_ratio": 1.0,
        }

    def _kr_stock_from_history(self, code: str, name: str) -> dict:
        """3순위(최후 수단): 로컬 history CSV의 최신 종가."""
        from data.history.history_loader import get_loader
        symbol = self._CODE_TO_HISTORY.get(code)
        if symbol is None:
            return {"name": name, "price": 0, "change_pct": 0.0}
        loader = get_loader()
        close = loader._load_close(symbol)
        if close is None or len(close) < 2:
            return {"name": name, "price": 0, "change_pct": 0.0}
        closes = close.tolist()
        return {
            "name":       name,
            "price":      int(closes[-1]),
            "change_pct": self._safe_change_pct(closes[-1], closes[-2]),
        }

    # ------------------------------------------------------------------
    # 원자재 수집
    # ------------------------------------------------------------------

    async def _collect_commodities(self) -> dict:
        """yfinance 동기 수집을 executor에서 비동기로 실행한다."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._collect_commodities_sync)

    def _collect_commodities_sync(self) -> dict:
        """
        yfinance로 WTI 원유, 금, 구리, 리튬 ETF 데이터를 수집한다.

        반환 형식:
        {
            "wti":     {"value": float, "change_pct": float},
            "gold":    {"value": float, "change_pct": float},
            "copper":  {"value": float, "change_pct": float},
            "lithium": {"value": float, "change_pct": float},
        }
        """
        try:
            import yfinance as yf

            commodity_map = {
                "wti":     "CL=F",
                "gold":    "GC=F",
                "copper":  "HG=F",
                "lithium": "LIT",
            }
            result = {}
            for key, ticker in commodity_map.items():
                try:
                    hist = yf.Ticker(ticker).history(period="1mo")
                    if hist.empty or len(hist) < 2:
                        result[key] = {"value": 0.0, "change_pct": 0.0}
                        continue
                    closes = hist["Close"].tolist()
                    result[key] = {
                        "value":      round(closes[-1], 2),
                        "change_pct": self._safe_change_pct(closes[-1], closes[-2]),
                    }
                except Exception as exc:
                    self.log("warning", f"원자재 수집 실패 [{ticker}]: {exc}")
                    result[key] = {"value": 0.0, "change_pct": 0.0}
            return result

        except Exception as exc:
            self.log("error", f"원자재 수집 전체 실패: {exc}")
            return self._default_commodities()

    # ------------------------------------------------------------------
    # 뉴스 RSS 수집
    # ------------------------------------------------------------------

    async def _collect_news(self) -> list:
        """RSS 동기 수집을 executor에서 비동기로 실행한다."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._collect_news_sync)

    def _collect_news_sync(self) -> list:
        """
        한국 경제 뉴스 RSS 피드 3종에서 최신 헤드라인을 수집한다.

        반환 형식: [{"title": str, "source": str}, ...]
        """
        import urllib.request
        import xml.etree.ElementTree as ET

        _RSS_FEEDS = [
            ("연합뉴스",  "https://www.yna.co.kr/rss/economy.xml"),
            ("한국경제",  "https://www.hankyung.com/feed/economy"),
            ("매일경제",  "https://www.mk.co.kr/rss/40300001/"),
        ]

        headlines = []
        for source, url in _RSS_FEEDS:
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; stock-agent/1.0)"},
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    content = resp.read()

                root = ET.fromstring(content)
                # RSS 2.0: .//item / Atom: .//entry
                items = root.findall(".//item")
                if not items:
                    items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

                count = 0
                for item in items[:30]:
                    title_el = item.find("title")
                    if title_el is None:
                        title_el = item.find("{http://www.w3.org/2005/Atom}title")
                    title = (title_el.text or "").strip() if title_el is not None else ""
                    # CDATA 벗기기
                    if title.startswith("<![CDATA["):
                        title = title[9:-3].strip()
                    if title:
                        headlines.append({"title": title, "source": source})
                        count += 1

                self.log("info", f"뉴스 RSS 수집 [{source}]: {count}건")
            except Exception as exc:
                self.log("warning", f"뉴스 RSS 실패 [{source}]: {exc}")

        self.log("info", f"뉴스 수집 완료: {len(headlines)}건")
        return headlines

    # ------------------------------------------------------------------
    # 유틸리티
    # ------------------------------------------------------------------

    def _get_recent_trading_date(self) -> str:
        """
        오늘이 주말이면 가장 최근 금요일 날짜를 YYYYMMDD 형식으로 반환한다.
        pykrx는 주말/공휴일에 데이터가 없으므로 날짜를 조정한다.
        """
        today = datetime.now()
        # 토요일(5) → 금요일(-1일), 일요일(6) → 금요일(-2일)
        offset = {5: 1, 6: 2}
        days_back = offset.get(today.weekday(), 0)
        trading_day = today - timedelta(days=days_back)
        return trading_day.strftime("%Y%m%d")

    def _safe_change_pct(self, current: float, previous: float) -> float:
        """0 나누기 방지. previous가 0이면 0.0을 반환한다."""
        if previous == 0 or previous is None:
            return 0.0
        try:
            return round((current - previous) / previous * 100, 2)
        except Exception:
            return 0.0

    def _safe_volume_ratio(self, recent_volumes: list, avg_period: int = 20) -> float:
        """
        당일 거래량 / 20일 평균 거래량을 계산한다.
        데이터가 부족하거나 평균이 0이면 1.0을 반환한다.
        """
        if not recent_volumes or len(recent_volumes) < 2:
            return 1.0
        # 마지막 값이 당일 거래량
        today_vol = recent_volumes[-1]
        # 평균 계산 대상: 당일 제외한 최근 avg_period개
        hist_vols = recent_volumes[-(avg_period + 1):-1]
        if not hist_vols:
            return 1.0
        avg_vol = sum(hist_vols) / len(hist_vols)
        if avg_vol == 0:
            return 1.0
        return round(today_vol / avg_vol, 2)

    # ------------------------------------------------------------------
    # 기본값 반환 (전체 실패 시)
    # ------------------------------------------------------------------

    def _default_us_market(self) -> dict:
        """미국 시장 수집 전체 실패 시 반환하는 기본값 dict."""
        return {
            "nasdaq":   {"value": 0.0, "change_pct": 0.0, "volume_ratio": 1.0},
            "sox":      {"value": 0.0, "change_pct": 0.0, "volume_ratio": 1.0},
            "sp500":    {"value": 0.0, "change_pct": 0.0, "volume_ratio": 1.0},
            "vix":      {"value": 0.0, "change_pct": 0.0},
            "usd_krw":  {"value": 0.0, "change_pct": 0.0},
            "futures":  {"value": 0.0, "direction": "FLAT"},
            "individual": {
                "NVDA": {"value": 0.0, "change_pct": 0.0},
                "AMD":  {"value": 0.0, "change_pct": 0.0},
                "TSLA": {"value": 0.0, "change_pct": 0.0},
            },
        }

    def _default_kr_market(self) -> dict:
        """한국 시장 수집 전체 실패 시 반환하는 기본값 dict."""
        return {
            "kospi":           {"value": 0.0, "change_pct": 0.0, "volume_ratio": 1.0},
            "kosdaq":          {"value": 0.0, "change_pct": 0.0, "volume_ratio": 1.0},
            "foreign_net":     0,
            "institution_net": 0,
            "stocks":          {},
        }

    def _default_commodities(self) -> dict:
        """원자재 수집 전체 실패 시 반환하는 기본값 dict."""
        return {
            "wti":     {"value": 0.0, "change_pct": 0.0},
            "gold":    {"value": 0.0, "change_pct": 0.0},
            "copper":  {"value": 0.0, "change_pct": 0.0},
            "lithium": {"value": 0.0, "change_pct": 0.0},
        }

    # ------------------------------------------------------------------
    # KIS 재무지표 수집
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_float(value, default: float = 0.0) -> float:
        """문자열을 안전하게 float로 변환. KIS API는 숫자를 문자열로 반환."""
        try:
            return float(str(value).replace(",", "")) or default
        except (ValueError, TypeError, AttributeError):
            return default

    def _get_kis_token(self):
        """KIS API 토큰 발급 (재무지표 조회용). 세션 내 캐시 + 만료 체크."""
        import requests as _req
        import time as _time
        from dotenv import load_dotenv
        load_dotenv(override=True)

        # 캐시된 토큰이 있고, 발급 후 23시간 이내면 재사용
        if (hasattr(self, "_kis_fin_token") and self._kis_fin_token
                and hasattr(self, "_kis_fin_token_ts")
                and (_time.time() - self._kis_fin_token_ts) < 82800):
            return self._kis_fin_token

        app_key    = os.getenv("KIS_APP_KEY", "")
        app_secret = os.getenv("KIS_APP_SECRET", "")
        if not app_key or not app_secret:
            return None, None, None
        base = "https://openapi.koreainvestment.com:9443"
        for attempt in range(3):
            try:
                r = _req.post(f"{base}/oauth2/tokenP", json={
                    "grant_type": "client_credentials",
                    "appkey": app_key, "appsecret": app_secret,
                }, timeout=8)
                if r.status_code == 200:
                    token = r.json().get("access_token", "")
                    if token:
                        self._kis_fin_token = (token, app_key, app_secret)
                        self._kis_fin_token_ts = _time.time()
                        return self._kis_fin_token
                elif r.status_code == 403 and "EGW00133" in r.text:
                    # 토큰 발급 1분 제한 — 대기 후 재시도
                    self.log("info", f"[KIS토큰] 1분 제한, {65}초 대기 ({attempt+1}/3)")
                    _time.sleep(65)
                    continue
                else:
                    self.log("warning", f"[KIS토큰] HTTP {r.status_code}")
                    return None, None, None
            except Exception as exc:
                self.log("warning", f"[KIS토큰] 발급 실패: {exc}")
                return None, None, None
        return None, None, None

    def fetch_financial_indicators(self, symbol: str) -> dict:
        """
        KIS 주식현재가 시세 API (FHKST01010100) 로 투자지표 조회.
        PER, PBR, EPS, BPS, 배당수익률, 시가총액.
        실전 서버에서 조회 (모의투자 앱키로도 시세는 조회 가능).
        """
        import requests as _req
        token, app_key, app_secret = self._get_kis_token()
        if not token:
            return None

        base = "https://openapi.koreainvestment.com:9443"
        headers = {
            "authorization": f"Bearer {token}",
            "appkey": app_key, "appsecret": app_secret,
            "tr_id": "FHKST01010100",
            "custtype": "P",
        }
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol,
        }

        try:
            r = _req.get(
                f"{base}/uapi/domestic-stock/v1/quotations/inquire-price",
                headers=headers, params=params, timeout=8,
            )
            if r.status_code != 200:
                self.log("warning", f"[재무지표] {symbol} HTTP {r.status_code}")
                # 토큰 만료 시 캐시 초기화
                if r.status_code in (401, 403):
                    self._kis_fin_token = None
                return None
            data = r.json()
            if data.get("rt_cd") != "0":
                self.log("warning", f"[재무지표] {symbol} rt_cd={data.get('rt_cd')}: {data.get('msg1', '')}")
                if "token" in data.get("msg1", "").lower():
                    self._kis_fin_token = None
                return None
            output = data.get("output", {})
            if not output:
                return None

            return {
                "symbol":         symbol,
                "per":            self._safe_float(output.get("per")),
                "pbr":            self._safe_float(output.get("pbr")),
                "eps":            self._safe_float(output.get("eps")),
                "bps":            self._safe_float(output.get("bps")),
                "dividend_yield": self._safe_float(output.get("stck_divi_rate")),
                "market_cap":     self._safe_float(output.get("hts_avls")),
                "fetched_at":     datetime.now().isoformat(),
            }
        except Exception as exc:
            self.log("warning", f"[재무지표] {symbol} 조회 실패: {exc}")
            return None

    def fetch_financial_ratios(self, symbol: str) -> dict:
        """
        KIS 재무비율 API (FHKST66430300) 조회.
        ROE, ROA, 부채비율, 영업이익률.
        API 미지원 시 None 반환 (graceful fail).
        """
        import requests as _req
        token, app_key, app_secret = self._get_kis_token()
        if not token:
            return None

        base = "https://openapi.koreainvestment.com:9443"
        headers = {
            "authorization": f"Bearer {token}",
            "appkey": app_key, "appsecret": app_secret,
            "tr_id": "FHKST66430300",
            "custtype": "P",
        }
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol,
        }

        try:
            r = _req.get(
                f"{base}/uapi/domestic-stock/v1/quotations/inquire-invest-opinion",
                headers=headers, params=params, timeout=8,
            )
            if r.status_code != 200:
                return None
            data = r.json()
            if data.get("rt_cd") != "0":
                return None
            output = data.get("output", {})
            if isinstance(output, list) and output:
                output = output[0]
            if not output:
                return None

            return {
                "symbol":           symbol,
                "roe":              self._safe_float(output.get("roe_val")),
                "roa":              self._safe_float(output.get("roa_val")),
                "debt_ratio":       self._safe_float(output.get("lblt_rate")),
                "operating_margin": self._safe_float(output.get("bsop_prfi_rate")),
                "fetched_at":       datetime.now().isoformat(),
            }
        except Exception as exc:
            self.log("debug", f"[재무비율] {symbol} 조회 실패 (무시): {exc}")
            return None

    def fetch_financial_data_batch(self, symbols: list) -> dict:
        """
        여러 종목의 재무 데이터를 일괄 조회.
        KIS API 속도제한(초당 20건) 고려하여 간격을 둔다.
        """
        import time
        results = {}
        for i, symbol in enumerate(symbols):
            if i > 0 and i % 18 == 0:
                time.sleep(1.1)

            indicator = self.fetch_financial_indicators(symbol)
            if indicator:
                ratios = self.fetch_financial_ratios(symbol)
                if ratios:
                    indicator.update({k: v for k, v in ratios.items()
                                      if k != "symbol" and k != "fetched_at"})
                results[symbol] = indicator

        self.log("info", f"[재무데이터] {len(results)}/{len(symbols)}개 종목 조회 완료")
        return results
