CREATE TABLE IF NOT EXISTS financial_indicators (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    fetched_date DATE NOT NULL DEFAULT CURRENT_DATE,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- 투자지표 (FHKST66430300)
    per FLOAT,
    pbr FLOAT,
    eps FLOAT,
    bps FLOAT,
    dividend_yield FLOAT,
    market_cap FLOAT,

    -- 재무비율 (CTPF1002R)
    roe FLOAT,
    roa FLOAT,
    debt_ratio FLOAT,
    operating_margin FLOAT,

    -- 계산 필드
    fair_value_pbr FLOAT,
    price_to_fair FLOAT,

    UNIQUE(symbol, fetched_date)
);

CREATE INDEX IF NOT EXISTS idx_fi_symbol ON financial_indicators(symbol);
CREATE INDEX IF NOT EXISTS idx_fi_fetched ON financial_indicators(fetched_at DESC);
