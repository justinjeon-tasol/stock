// ─── KIS API Raw Response Types ───

/** VTTC8434R output1: 보유종목 */
export interface KISHoldingRaw {
  pdno: string            // 종목코드
  prdt_name: string       // 종목명
  hldg_qty: string        // 보유수량
  pchs_avg_pric: string   // 매입평균가
  prpr: string            // 현재가
  evlu_amt: string        // 평가금액
  evlu_pfls_amt: string   // 평가손익
  evlu_pfls_rt: string    // 평가수익률
  bfdy_cprs_icdc: string  // 전일대비증감
  fltt_rt: string         // 등락률
}

/** VTTC8434R output2: 계좌 요약 */
export interface KISAccountSummaryRaw {
  dnca_tot_amt: string         // 예수금 총액
  nxdy_excc_amt: string        // 익일정산액
  prvs_rcdl_excc_amt: string   // D+2 정산액
  thdt_buy_amt: string         // 금일매수액
  thdt_sll_amt: string         // 금일매도액
  thdt_tlex_amt: string        // 금일제비용
  scts_evlu_amt: string        // 유가평가액
  tot_evlu_amt: string         // 총평가금액
  pchs_amt_smtl_amt: string    // 매입금액합계
  evlu_pfls_smtl_amt: string   // 평가손익합계
  nass_amt: string             // 순자산
  bfdy_buy_amt: string         // 전일매수액
  bfdy_sll_amt: string         // 전일매도액
  asst_icdc_amt: string        // 자산증감액
  asst_icdc_erng_rt: string    // 자산증감수익률
}

/** FHKST01010100: 주식현재가 시세 */
export interface KISPriceRaw {
  stck_prpr: string       // 현재가
  prdy_vrss: string       // 전일대비
  prdy_ctrt: string       // 전일대비율
  acml_vol: string        // 누적거래량
  acml_tr_pbmn: string    // 누적거래대금
  stck_oprc: string       // 시가
  stck_hgpr: string       // 고가
  stck_lwpr: string       // 저가
  prdy_vrss_sign: string  // 전일대비부호 (1:상한,2:상승,3:보합,4:하한,5:하락)
  per: string             // PER
  pbr: string             // PBR
}

/** VTTC8001R / TTTC8001R: 일별주문체결조회 */
export interface KISTradeExecutionRaw {
  ord_dt: string          // 주문일자
  ord_tmd: string         // 주문시각
  odno: string            // 주문번호
  sll_buy_dvsn_cd: string // 매도매수구분 (01:매도, 02:매수)
  pdno: string            // 종목코드
  prdt_name: string       // 종목명
  ord_qty: string         // 주문수량
  tot_ccld_qty: string    // 총체결수량
  ord_unpr: string        // 주문단가
  avg_prvs: string        // 체결평균가
  ccld_cndt_name: string  // 주문상태명
  ord_dvsn_name: string   // 주문구분명
}

// ─── Normalized Frontend Types ───

export interface KISHolding {
  code: string
  name: string
  quantity: number
  avgPrice: number
  currentPrice: number
  evluAmt: number
  evluPflsAmt: number
  evluPflsRt: number
  dayChange: number       // 전일대비
  dayChangeRt: number     // 등락률
}

export interface KISAccountSummary {
  cashAmt: number           // 예수금
  stockEvluAmt: number      // 유가평가액
  totEvluAmt: number        // 총평가금액
  pchsAmt: number           // 매입금액합계
  evluPflsAmt: number       // 평가손익합계
  nassAmt: number           // 순자산
  thdtBuyAmt: number        // 금일매수액
  thdtSllAmt: number        // 금일매도액
  thdtTlexAmt: number       // 금일제비용
  asstIcdcAmt: number       // 자산증감액
  asstIcdcErngRt: number    // 자산증감수익률
  erngRt: number | null      // 수익률 (계산, 매입금액 0이면 null)
}

export interface KISBalanceResponse {
  summary: KISAccountSummary
  holdings: KISHolding[]
  fetchedAt: string
}

export interface KISTradeHistoryResponse {
  trades: KISTradeExecution[]
  hasMore: boolean
  fetchedAt: string
}

export interface KISPrice {
  code: string
  price: number
  dayChange: number
  dayChangeRt: number
  volume: number
  open: number
  high: number
  low: number
  sign: string  // 상한/상승/보합/하한/하락
  per: number
  pbr: number
}

export interface KISTradeExecution {
  orderDate: string       // YYYY-MM-DD
  orderTime: string       // HH:mm:ss
  orderNo: string
  action: 'BUY' | 'SELL'
  code: string
  name: string
  orderQty: number
  filledQty: number
  orderPrice: number
  filledPrice: number
  status: string          // 체결완료/미체결/취소 등
  orderType: string       // 지정가/시장가 등
}

export type DataSource = 'KIS' | 'SUPABASE' | 'KIS_FALLBACK'

/** 수익률 분석 — 월별 수익률 */
export interface PeriodReturn {
  period: string   // "2026-01", "2026-02" 등
  returnPct: number
  tradeCount: number
  winCount: number
}

/** 수익률 분석 — 종목별 손익 */
export interface StockReturn {
  code: string
  name: string
  totalPnl: number        // 총 실현 손익 (원)
  totalPnlPct: number     // 총 수익률
  tradeCount: number
  winCount: number
  winRate: number
}

/** 수익률 분석 — 통계 요약 */
export interface WinLossStatsData {
  totalTrades: number
  winRate: number
  avgWinPct: number
  avgLossPct: number
  profitFactor: number
  maxConsecutiveWins: number
  maxConsecutiveLosses: number
  totalRealizedPnl: number
}
