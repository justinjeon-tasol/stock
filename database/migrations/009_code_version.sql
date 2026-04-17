-- ============================================================
-- 009_code_version.sql
-- 매매/포지션 레코드에 "어느 코드 버전이 낸 신호인지" 기록하는 컬럼 추가.
-- 목적: 전략 수정 후 성과가 나빠지면 v0.1로 롤백 가능하게 하고,
--       버전별 성과 비교(SELECT code_version, AVG(result_pct) ...)를 가능하게 함.
--
-- 안전성:
--   - 모두 NULLable. 기존 레코드 = NULL (기록 시점 불명).
--   - 새 레코드 = services/version.py의 get_version() 결과 자동 주입.
--   - 이전 코드도 이 컬럼을 모르는 채로 INSERT 가능 (호환).
-- ============================================================

ALTER TABLE trades
  ADD COLUMN IF NOT EXISTS code_version TEXT;

ALTER TABLE positions
  ADD COLUMN IF NOT EXISTS code_version TEXT;

-- 인덱스: 버전별 집계/조회 성능
CREATE INDEX IF NOT EXISTS idx_trades_code_version
  ON trades(code_version)
  WHERE code_version IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_positions_code_version
  ON positions(code_version)
  WHERE code_version IS NOT NULL;

-- 참고: 버전별 평균 수익률 조회 예시
-- SELECT code_version,
--        COUNT(*) AS n,
--        AVG(result_pct) AS avg_return,
--        SUM(realized_pnl_amt) AS total_pnl
-- FROM trades
-- WHERE action = 'SELL' AND code_version IS NOT NULL
-- GROUP BY code_version
-- ORDER BY code_version DESC;
