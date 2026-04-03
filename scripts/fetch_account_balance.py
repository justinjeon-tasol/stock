"""
KIS 계좌잔고 실시간 조회 스크립트.
Next.js API 라우트에서 execSync로 호출하여 JSON 출력한다.

사용법: python scripts/fetch_account_balance.py
출력: JSON { summary: {...}, holdings: [...] }
"""

import json
import os
import sys

import requests
from dotenv import load_dotenv
from pathlib import Path

# .env 로드
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_KIS_BASE_URL = "https://openapivts.koreainvestment.com:29443"
_KIS_REAL_URL = "https://openapi.koreainvestment.com:9443"

APP_KEY = os.getenv("KIS_APP_KEY", "")
APP_SECRET = os.getenv("KIS_APP_SECRET", "")
ACCOUNT_NO = os.getenv("KIS_ACCOUNT_NO", "")


def get_token() -> str:
    """KIS 토큰 발급 (캐시 파일 우선)."""
    cache_path = Path(__file__).resolve().parent.parent / "logs" / ".kis_token_cache.json"
    if cache_path.exists():
        try:
            from datetime import datetime, timezone
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            expires = datetime.fromisoformat(cached["expires_at"])
            if datetime.now(timezone.utc) < expires:
                return cached["access_token"]
        except Exception:
            pass

    resp = requests.post(
        f"{_KIS_BASE_URL}/oauth2/tokenP",
        json={"grant_type": "client_credentials", "appkey": APP_KEY, "appsecret": APP_SECRET},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_balance(token: str) -> dict:
    """KIS 잔고 조회 API 호출."""
    cano = ACCOUNT_NO[:8]
    acnt_prdt_cd = ACCOUNT_NO[8:]

    headers = {
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": "VTTC8434R",
        "custtype": "P",
    }
    params = {
        "CANO": cano,
        "ACNT_PRDT_CD": acnt_prdt_cd,
        "AFHR_FLPR_YN": "N",
        "OFL_YN": "",
        "INQR_DVSN": "02",
        "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "00",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": "",
    }

    resp = requests.get(
        f"{_KIS_BASE_URL}/uapi/domestic-stock/v1/trading/inquire-balance",
        headers=headers, params=params, timeout=10,
    )
    data = resp.json()

    # output1: 보유 종목
    holdings = []
    for item in data.get("output1", []):
        qty = int(item.get("hldg_qty", 0))
        if qty <= 0:
            continue
        holdings.append({
            "name": item.get("prdt_name", ""),
            "code": item.get("pdno", ""),
            "quantity": qty,
            "avg_price": float(item.get("pchs_avg_pric", 0)),
            "current_price": int(item.get("prpr", 0)),
            "evlu_amt": int(item.get("evlu_amt", 0)),
            "evlu_pfls_amt": int(item.get("evlu_pfls_amt", 0)),
            "evlu_pfls_rt": float(item.get("evlu_pfls_rt", 0)),
        })

    # output2: 계좌 요약
    o2 = data.get("output2", [{}])[0] if data.get("output2") else {}

    summary = {
        "dnca_tot_amt": int(o2.get("dnca_tot_amt", 0) or 0),       # 예수금 총액
        "nxdy_excc_amt": int(o2.get("nxdy_excc_amt", 0) or 0),     # 익일정산액
        "prvs_rcdl_excc_amt": int(o2.get("prvs_rcdl_excc_amt", 0) or 0),  # D+2정산액
        "thdt_buy_amt": int(o2.get("thdt_buy_amt", 0) or 0),       # 금일매수액
        "thdt_sll_amt": int(o2.get("thdt_sll_amt", 0) or 0),       # 금일매도액
        "thdt_tlex_amt": int(o2.get("thdt_tlex_amt", 0) or 0),     # 금일제비용
        "scts_evlu_amt": int(o2.get("scts_evlu_amt", 0) or 0),     # 유가평가액
        "tot_evlu_amt": int(o2.get("tot_evlu_amt", 0) or 0),       # 총평가금액
        "pchs_amt_smtl_amt": int(o2.get("pchs_amt_smtl_amt", 0) or 0),  # 매입금액합계
        "evlu_pfls_smtl_amt": int(o2.get("evlu_pfls_smtl_amt", 0) or 0),  # 평가손익합계
        "nass_amt": int(o2.get("nass_amt", 0) or 0),               # 순자산
        "bfdy_buy_amt": int(o2.get("bfdy_buy_amt", 0) or 0),       # 전일매수액
        "bfdy_sll_amt": int(o2.get("bfdy_sll_amt", 0) or 0),       # 전일매도액
        "asst_icdc_amt": int(o2.get("asst_icdc_amt", 0) or 0),     # 자산증감액
        "asst_icdc_erng_rt": float(o2.get("asst_icdc_erng_rt", 0) or 0),  # 자산증감수익률
    }

    return {"summary": summary, "holdings": holdings}


if __name__ == "__main__":
    try:
        token = get_token()
        result = fetch_balance(token)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)
