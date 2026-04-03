CREATE TABLE IF NOT EXISTS account_history (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  recorded_date date NOT NULL,
  recorded_at timestamptz DEFAULT now(),

  -- 자산 현황
  initial_capital numeric NOT NULL DEFAULT 50000000,
  cash_amt numeric NOT NULL DEFAULT 0,
  stock_evlu_amt numeric NOT NULL DEFAULT 0,
  tot_evlu_amt numeric NOT NULL DEFAULT 0,
  pchs_amt numeric NOT NULL DEFAULT 0,
  evlu_pfls_amt numeric NOT NULL DEFAULT 0,
  erng_rt numeric NOT NULL DEFAULT 0,

  -- 당일 거래 요약
  daily_buy_amt numeric NOT NULL DEFAULT 0,
  daily_sell_amt numeric NOT NULL DEFAULT 0,
  daily_realized_pnl numeric NOT NULL DEFAULT 0,
  daily_trade_count int NOT NULL DEFAULT 0,

  -- 누적
  total_realized_pnl numeric NOT NULL DEFAULT 0,

  mode text NOT NULL DEFAULT 'MOCK',
  note text
);

CREATE INDEX IF NOT EXISTS idx_account_history_date ON account_history(recorded_date DESC);
