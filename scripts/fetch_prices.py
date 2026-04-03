"""
현재가 조회 스크립트 (Next.js API 라우트에서 호출)
사용법: python fetch_prices.py 005930,000660,229200
출력: {"005930": 58000, "000660": 195000, ...}
"""
import sys
import json
import os

def main():
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print("{}")
        return

    codes = [c.strip() for c in sys.argv[1].split(',') if c.strip()]
    if not codes:
        print("{}")
        return

    # stock_classification.json으로 KOSPI/KOSDAQ 판단
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    classification_path = os.path.join(project_root, 'config', 'stock_classification.json')

    stocks_info = {}
    try:
        with open(classification_path, encoding='utf-8') as f:
            data = json.load(f)
            stocks_info = data.get('stocks', {})
    except Exception:
        pass

    import yfinance as yf

    result = {}
    for code in codes:
        market = stocks_info.get(code, {}).get('market', 'KOSPI')
        suffix = '.KS' if market == 'KOSPI' else '.KQ'
        ticker_sym = code + suffix
        try:
            ticker = yf.Ticker(ticker_sym)
            fast = ticker.fast_info
            price = fast.last_price
            if price and float(price) > 0:
                result[code] = int(round(float(price)))
        except Exception:
            pass

    print(json.dumps(result))


if __name__ == '__main__':
    main()
