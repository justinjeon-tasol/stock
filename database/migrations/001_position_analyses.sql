CREATE TABLE IF NOT EXISTS position_analyses (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  position_id uuid REFERENCES positions(id),
  code text NOT NULL,
  name text NOT NULL,
  recommendation text NOT NULL,  -- HOLD | CAUTION | SELL
  reason text NOT NULL,
  rsi numeric,
  price_change_5d numeric,
  above_ma20 boolean,
  news_sentiment text,  -- POSITIVE | NEUTRAL | NEGATIVE
  target_exit_price numeric,
  created_at timestamptz DEFAULT now()
);
