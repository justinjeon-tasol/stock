CREATE TABLE IF NOT EXISTS prediction_log (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    predicted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    horizon_days INT NOT NULL,
    predicted_price FLOAT NOT NULL,
    predicted_return_pct FLOAT NOT NULL,
    components JSONB,
    actual_price FLOAT,
    actual_return_pct FLOAT,
    filled_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_predlog_symbol ON prediction_log(symbol);
CREATE INDEX IF NOT EXISTS idx_predlog_predicted_at ON prediction_log(predicted_at DESC);
