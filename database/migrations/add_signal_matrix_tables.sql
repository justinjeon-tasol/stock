-- ============================================================================
-- 백테스팅 시그널 매트릭스 통합 마이그레이션
-- 실행: Supabase SQL Editor에서 직접 실행
-- 날짜: 2026-04-05
-- ============================================================================

-- 1. 신규 테이블: indicator_stock_correlations
CREATE TABLE IF NOT EXISTS indicator_stock_correlations (
    id BIGSERIAL PRIMARY KEY,

    -- 시그널 식별
    indicator_id TEXT NOT NULL,           -- "wti", "sox", "nasdaq" 등
    event_direction TEXT NOT NULL,        -- "up" (급등), "down" (급락)
    stock_code TEXT NOT NULL,             -- "010950" (S-Oil)
    stock_name TEXT NOT NULL,             -- "S-Oil"
    sector TEXT,                          -- "정유"

    -- 분석 결과
    lag_days INTEGER NOT NULL,            -- 1, 2, 3, 5, 10, 20
    signal_direction TEXT,                -- "buy", "sell", "neutral"
    mean_excess_return FLOAT,            -- 평균 초과수익률 (%)
    median_excess_return FLOAT,          -- 중앙값 초과수익률 (%)
    win_rate FLOAT,                      -- 승률 (0~1)
    sample_count INTEGER,                -- 이벤트 발생 횟수
    t_statistic FLOAT,                   -- t-검정 통계량
    p_value FLOAT,                       -- p-value
    confidence TEXT,                      -- "★★★", "★★", "★"

    -- 메타
    analysis_start TEXT,                  -- "2015-01-01"
    analysis_end TEXT,                    -- "2025-12-31"
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- 복합 유니크 키 (동일 조합 upsert용)
    UNIQUE(indicator_id, event_direction, stock_code, lag_days)
);

-- 조회 성능용 인덱스
CREATE INDEX IF NOT EXISTS idx_isc_indicator ON indicator_stock_correlations(indicator_id, event_direction);
CREATE INDEX IF NOT EXISTS idx_isc_stock ON indicator_stock_correlations(stock_code);
CREATE INDEX IF NOT EXISTS idx_isc_confidence ON indicator_stock_correlations(confidence);
CREATE INDEX IF NOT EXISTS idx_isc_signal ON indicator_stock_correlations(signal_direction);

-- 2. trades 테이블 컬럼 추가 (기존 행에 NULL, 안전)
ALTER TABLE trades ADD COLUMN IF NOT EXISTS signal_source TEXT;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS signal_confidence TEXT;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS signal_trigger TEXT;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS backtest_win_rate FLOAT;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS backtest_expected_return FLOAT;

-- 3. positions 테이블 컬럼 추가 (기존 행에 NULL, 안전)
ALTER TABLE positions ADD COLUMN IF NOT EXISTS signal_source TEXT;
ALTER TABLE positions ADD COLUMN IF NOT EXISTS signal_confidence TEXT;
ALTER TABLE positions ADD COLUMN IF NOT EXISTS signal_trigger TEXT;
