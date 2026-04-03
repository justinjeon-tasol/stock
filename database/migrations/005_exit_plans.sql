CREATE TABLE IF NOT EXISTS exit_plans (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    position_id uuid NOT NULL REFERENCES positions(id),
    code text NOT NULL,
    name text NOT NULL,

    -- 가격 예측
    forecast_target_1w numeric,
    forecast_target_1m numeric,
    forecast_confidence numeric,
    forecast_trend text,
    forecast_components jsonb,

    -- 분할 매도 단계 (JSONB 배열)
    exit_stages jsonb NOT NULL DEFAULT '[]',

    -- 동적 손절
    dynamic_sl jsonb NOT NULL DEFAULT '{}',

    -- 시간 조정
    time_adjustments jsonb DEFAULT '{}',

    -- 메타데이터
    plan_version int DEFAULT 1,
    last_phase text,
    current_price numeric,
    avg_price numeric,
    quantity int,
    holding_period text,

    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now(),

    CONSTRAINT uq_exit_plan_position UNIQUE (position_id)
);

CREATE INDEX IF NOT EXISTS idx_exit_plans_position ON exit_plans(position_id);
CREATE INDEX IF NOT EXISTS idx_exit_plans_code ON exit_plans(code);
