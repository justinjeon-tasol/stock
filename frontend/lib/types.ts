// 시장 국면 타입
export type MarketPhaseType =
  | '대상승장'
  | '상승장'
  | '일반장'
  | '변동폭큰'
  | '하락장'
  | '대폭락장'

// 투자 기간 타입
export type HoldingPeriod = '초단기' | '단기' | '중기' | '장기'

// 포지션 상태
export type PositionStatus = 'OPEN' | 'CLOSED'

// 주문 방향
export type TradeAction = 'BUY' | 'SELL'

// 거래 모드
export type TradeMode = 'MOCK' | 'REAL'

// 에이전트 로그 레벨
export type LogLevel = 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL'

// 에이전트 상태
export type AgentStatus = 'NORMAL' | 'WARNING' | 'ERROR' | 'CRITICAL' | 'OFFLINE'

// 에이전트 코드 (7-agent 구조)
export type AgentCode =
  | 'OR'
  | 'DC'
  | 'MA'
  | 'WA'
  | 'SR'
  | 'EX'
  | 'DB'

// market_phases 테이블
export interface MarketPhase {
  id: string
  phase: MarketPhaseType
  confidence: number
  start_date: string
  end_date: string | null
  issue_id: string | null
  forecast_accuracy: number | null
  created_at?: string
}

// 시그널 출처 타입
export type SignalSource = 'backtest_signal' | 'sector_fallback'

// 시그널 신뢰도 타입
export type SignalConfidence = '★★★' | '★★' | '★'

// positions 테이블
export interface Position {
  id: string
  code: string
  name: string
  quantity: number
  avg_price: number
  buy_order_id: string | null
  buy_trade_id: string | null
  phase_at_buy: MarketPhaseType | null
  strategy_id: string | null
  mode: TradeMode
  holding_period: HoldingPeriod
  entry_time: string
  max_exit_date: string | null
  peak_price: number | null
  status: PositionStatus
  closed_at: string | null
  close_reason: string | null
  result_pct: number | null
  signal_source: SignalSource | null
  signal_confidence: SignalConfidence | null
  signal_trigger: string | null
  created_at?: string
}

// trades 테이블
export interface Trade {
  id: string
  order_id: string | null
  code: string
  name: string
  action: TradeAction
  quantity: number
  price: number
  strategy_id: string | null
  phase: MarketPhaseType | null
  result_pct: number | null
  mode: TradeMode
  signal_source: SignalSource | null
  signal_confidence: SignalConfidence | null
  signal_trigger: string | null
  backtest_win_rate: number | null
  backtest_expected_return: number | null
  created_at: string
}

// agent_logs 테이블
export interface AgentLog {
  id: string
  agent: AgentCode
  level: LogLevel
  message: string
  error_code: string | null
  timestamp: string
}

// 에이전트 메타데이터
export interface AgentMeta {
  code: AgentCode
  name: string
  file: string
  layer: '데이터' | '전략' | '운영' | '지휘'
  description: string
}

// 집계된 에이전트 상태 (useAgentLogs 반환값)
export interface AgentStatusInfo {
  code: AgentCode
  meta: AgentMeta
  status: AgentStatus
  lastLog: AgentLog | null
  lastSeen: string | null
}

// ForeignNetChart용 데이터 포인트
export interface ForeignNetDataPoint {
  date: string
  value: number
}

// 포지션 요약 카드용
export interface PositionSummary {
  openCount: number
  totalValue: number
  totalPnlPct: number
  winCount: number
  loseCount: number
}

// account_summary 테이블
export interface AccountSummary {
  id: number
  cash_amt: number
  stock_evlu_amt: number
  tot_evlu_amt: number
  pchs_amt: number
  evlu_pfls_amt: number
  erng_rt: number
  mode: TradeMode
  created_at: string
}

// position_analyses 테이블
export interface PositionAnalysis {
  id: string
  position_id: string
  code: string
  recommendation: 'HOLD' | 'CAUTION' | 'SELL'
  reason: string
  rsi: number | null
  price_change_5d: number | null
  above_ma20: boolean | null
  news_sentiment: 'POSITIVE' | 'NEUTRAL' | 'NEGATIVE' | null
  target_exit_price: number | null
  created_at: string
}

// 거래 필터 상태
export interface TradeFilter {
  action: TradeAction | 'ALL'
  mode: TradeMode | 'ALL'
  phase: MarketPhaseType | 'ALL'
  dateFrom: string
  dateTo: string
}
