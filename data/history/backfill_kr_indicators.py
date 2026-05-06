#!/usr/bin/env python3
"""
BT-A Phase B — 한국 시장 외국인/기관 순매수 1년치 백필 (KIS API).

배경:
  pykrx KRX endpoint가 LOGOUT 응답으로 차단됨 (2026-05-06 확인).
  KIS Open API의 시장 단위 시계열 endpoint로 대체.

사용 endpoint:
  FHPTJ04040000  /uapi/domestic-stock/v1/quotations/inquire-investor-daily-by-market
  단일 호출 = ~300 거래일 (약 15개월) 응답.

산출:
  data/history/extended/kr_market/foreign_net_market.csv      # date, foreign_net
  data/history/extended/kr_market/institution_net_market.csv  # date, institution_net

종목별 백필(_by_ticker.csv 2개)은 본 스크립트에서 다루지 않는다.
BT-A Phase E에서 FHPTJ04160001 + DATE_1 shift 9~10회 패턴으로 별도 진행.

read-only(시세 조회). 실거래 환경(.env KIS_IS_MOCK=false) 필수.

사용:
  python3 data/history/backfill_kr_indicators.py             # 365일
  python3 data/history/backfill_kr_indicators.py --days 730  # 2년 (다회 호출 자동)
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "data" / "history" / "extended" / "kr_market"

KIS_BASE = "https://openapi.koreainvestment.com:9443"
KIS_PATH = "/uapi/domestic-stock/v1/quotations/inquire-investor-daily-by-market"
KIS_TR_ID = "FHPTJ04040000"


def get_token(app_key: str, app_secret: str) -> str:
    r = requests.post(
        f"{KIS_BASE}/oauth2/tokenP",
        json={
            "grant_type": "client_credentials",
            "appkey": app_key,
            "appsecret": app_secret,
        },
        timeout=10,
    )
    r.raise_for_status()
    j = r.json()
    if "access_token" not in j:
        raise RuntimeError(f"token issuance failed: {j}")
    return j["access_token"]


def fetch_market_series(
    token: str, app_key: str, app_secret: str, start: str, end: str
) -> pd.DataFrame:
    headers = {
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": KIS_TR_ID,
        "custtype": "P",
        "Content-Type": "application/json; charset=utf-8",
    }
    params = {
        "FID_COND_MRKT_DIV_CODE": "U",
        "FID_INPUT_ISCD": "0001",
        "FID_INPUT_DATE_1": start,
        "FID_INPUT_ISCD_1": "KSP",
        "FID_INPUT_DATE_2": end,
        "FID_INPUT_ISCD_2": "0001",
    }
    r = requests.get(f"{KIS_BASE}{KIS_PATH}", headers=headers, params=params, timeout=15)
    r.raise_for_status()
    j = r.json()
    if j.get("rt_cd") != "0":
        raise RuntimeError(
            f"KIS rt_cd={j.get('rt_cd')} msg_cd={j.get('msg_cd')} msg={j.get('msg1')}"
        )
    rows = j.get("output") or []
    if not rows:
        raise RuntimeError("KIS returned empty output")
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=365)
    args = parser.parse_args()

    load_dotenv()
    app_key = os.getenv("KIS_APP_KEY")
    app_secret = os.getenv("KIS_APP_SECRET")
    is_mock = os.getenv("KIS_IS_MOCK", "true").lower() == "true"

    if not app_key or not app_secret:
        print("[error] KIS_APP_KEY/SECRET not set in .env")
        return 2
    if is_mock:
        print("[error] KIS_IS_MOCK=true. FHPTJ04040000 requires live domain.")
        print("        실행 시 환경변수 override: KIS_IS_MOCK=false python3 ...")
        return 3

    today = datetime.now()
    today_yyyymmdd = today.strftime("%Y%m%d")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[info] target: 최근 {args.days}일 ({(today - timedelta(days=args.days)).strftime('%Y-%m-%d')} ~ {today.strftime('%Y-%m-%d')})")
    print(f"[info] 출력: {OUT_DIR}")
    print(f"[info] endpoint: {KIS_TR_ID} {KIS_PATH}")
    print(f"[info] 호출 spec: DATE_1=DATE_2={today_yyyymmdd} → KIS는 그 시점 기준 ~300 거래일(약 15개월) 응답")

    print("\n[1/3] 토큰 발급")
    t0 = time.time()
    token = get_token(app_key, app_secret)
    print(f"  ok ({time.time()-t0:.2f}s)")

    print("\n[2/3] 시장 시계열 조회 (단일 호출)")
    t0 = time.time()
    df = fetch_market_series(token, app_key, app_secret, today_yyyymmdd, today_yyyymmdd)
    print(f"  rows received: {len(df)}  ({(time.time()-t0)*1000:.0f}ms)")
    print(f"  KIS columns: {list(df.columns)[:14]}")

    if "stck_bsop_date" not in df.columns:
        print(f"[error] response missing 'stck_bsop_date'. cols={list(df.columns)}")
        return 4

    print("\n[3/3] CSV 저장")
    df["date"] = pd.to_datetime(df["stck_bsop_date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
    df["foreign_net"] = pd.to_numeric(df.get("frgn_ntby_qty"), errors="coerce")
    df["institution_net"] = pd.to_numeric(df.get("orgn_ntby_qty"), errors="coerce")

    cutoff = (today - timedelta(days=args.days)).strftime("%Y-%m-%d")
    df_cut = df[df["date"] >= cutoff].sort_values("date").reset_index(drop=True)

    # cumsum: 누적 합. BT 엔진(load_close)은 csv 마지막 column 자동 사용 → cumsum이 indicator 시계열로 입력됨.
    df_cut["foreign_net_cumsum"] = df_cut["foreign_net"].cumsum()
    df_cut["institution_net_cumsum"] = df_cut["institution_net"].cumsum()

    fpath = OUT_DIR / "foreign_net_market.csv"
    ipath = OUT_DIR / "institution_net_market.csv"
    df_cut[["date", "foreign_net", "foreign_net_cumsum"]].to_csv(fpath, index=False, encoding="utf-8")
    df_cut[["date", "institution_net", "institution_net_cumsum"]].to_csv(ipath, index=False, encoding="utf-8")

    print(f"  {fpath.name}: rows={len(df_cut)}")
    print(f"  {ipath.name}: rows={len(df_cut)}")
    if len(df_cut):
        print(f"  date range: {df_cut['date'].min()} ~ {df_cut['date'].max()}")
        print(f"  foreign_net cumsum 끝값: {df_cut['foreign_net_cumsum'].iloc[-1]:,}")
        print(f"  institution_net cumsum 끝값: {df_cut['institution_net_cumsum'].iloc[-1]:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
