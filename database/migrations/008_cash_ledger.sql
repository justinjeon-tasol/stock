-- ============================================================
-- 008_cash_ledger.sql
-- 현금 원장(Cash Ledger) 기반 잔액 관리 시스템
-- ============================================================

-- 1. cash_ledger 테이블: 모든 현금 이동을 추적하는 원장
CREATE TABLE IF NOT EXISTS cash_ledger (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  entry_type TEXT NOT NULL,          -- 'INITIAL', 'BUY', 'SELL', 'ADJUSTMENT'
  amount BIGINT NOT NULL,            -- +: 입금/매도수익, -: 매수지출
  balance_after BIGINT NOT NULL,     -- 이 거래 후 현금 잔액
  ref_trade_id UUID,                 -- trades.id 참조 (soft FK)
  ref_order_id TEXT,                 -- KIS 주문번호
  code TEXT,                         -- 종목코드
  name TEXT,                         -- 종목명
  quantity INT,                      -- 거래 수량
  price INT,                         -- 주당 가격
  note TEXT,                         -- 설명
  mode TEXT NOT NULL DEFAULT 'MOCK'  -- MOCK | REAL
);

CREATE INDEX IF NOT EXISTS idx_cash_ledger_created
  ON cash_ledger(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_cash_ledger_entry_type
  ON cash_ledger(entry_type);

-- RLS 비활성화 (서비스 키 사용)
ALTER TABLE cash_ledger ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow all for service role" ON cash_ledger
  FOR ALL USING (true) WITH CHECK (true);

-- 2. trades 테이블 컬럼 추가
ALTER TABLE trades ADD COLUMN IF NOT EXISTS realized_pnl_amt BIGINT;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS fill_amount BIGINT;

-- 3. account_summary 테이블 컬럼 추가
ALTER TABLE account_summary ADD COLUMN IF NOT EXISTS ledger_cash_amt BIGINT;
ALTER TABLE account_summary ADD COLUMN IF NOT EXISTS discrepancy_amt BIGINT DEFAULT 0;
ALTER TABLE account_summary ADD COLUMN IF NOT EXISTS reconciled BOOLEAN DEFAULT false;

-- 4. 원장 삽입 RPC 함수 (원자성 보장)
CREATE OR REPLACE FUNCTION append_cash_ledger(
  p_entry_type TEXT,
  p_amount BIGINT,
  p_ref_trade_id UUID DEFAULT NULL,
  p_ref_order_id TEXT DEFAULT NULL,
  p_code TEXT DEFAULT NULL,
  p_name TEXT DEFAULT NULL,
  p_quantity INT DEFAULT NULL,
  p_price INT DEFAULT NULL,
  p_note TEXT DEFAULT NULL,
  p_mode TEXT DEFAULT 'MOCK'
) RETURNS TABLE(id UUID, balance_after BIGINT) AS $$
DECLARE
  v_current BIGINT;
  v_new BIGINT;
  v_id UUID := gen_random_uuid();
BEGIN
  -- 가장 최근 잔액을 원자적으로 조회
  SELECT cl.balance_after INTO v_current
  FROM cash_ledger cl
  ORDER BY cl.created_at DESC
  LIMIT 1
  FOR UPDATE;  -- 행 잠금으로 동시성 보호

  IF NOT FOUND THEN
    v_current := 50000000;  -- 초기 자본금 fallback
  END IF;

  v_new := v_current + p_amount;

  INSERT INTO cash_ledger(
    id, entry_type, amount, balance_after,
    ref_trade_id, ref_order_id, code, name,
    quantity, price, note, mode
  ) VALUES (
    v_id, p_entry_type, p_amount, v_new,
    p_ref_trade_id, p_ref_order_id, p_code, p_name,
    p_quantity, p_price, p_note, p_mode
  );

  RETURN QUERY SELECT v_id, v_new;
END;
$$ LANGUAGE plpgsql;

-- 5. Supabase Realtime 활성화
ALTER PUBLICATION supabase_realtime ADD TABLE cash_ledger;
