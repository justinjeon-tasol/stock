/**
 * KIS (Korea Investment Securities) API Client — Server-side only.
 * Ported from scripts/fetch_account_balance.py and agents/executor.py.
 */
import fs from 'fs'
import path from 'path'
import type {
  KISHoldingRaw,
  KISAccountSummaryRaw,
  KISPriceRaw,
  KISTradeExecutionRaw,
  KISHolding,
  KISAccountSummary,
  KISBalanceResponse,
  KISPrice,
  KISTradeExecution,
} from './kis-types'

// ─── Configuration ───

const KIS_APP_KEY = process.env.KIS_APP_KEY ?? ''
const KIS_APP_SECRET = process.env.KIS_APP_SECRET ?? ''
const KIS_ACCOUNT_NO = process.env.KIS_ACCOUNT_NO ?? ''
const KIS_IS_MOCK = (process.env.KIS_IS_MOCK ?? 'true') === 'true'

const MOCK_BASE = 'https://openapivts.koreainvestment.com:29443'
const REAL_BASE = 'https://openapi.koreainvestment.com:9443'
const BASE_URL = KIS_IS_MOCK ? MOCK_BASE : REAL_BASE
// 시세 조회는 항상 실서버 (position_manager.py:421 패턴)
const PRICE_BASE = REAL_BASE

const CANO = KIS_ACCOUNT_NO.slice(0, 8)
const ACNT_PRDT_CD = KIS_ACCOUNT_NO.slice(8)

const TOKEN_CACHE_PATH = path.resolve(process.cwd(), '..', 'logs', '.kis_token_cache.json')

// ─── In-memory token cache ───

let cachedToken: string | null = null
let cachedTokenExpiry: number = 0

function safeInt(v: string | undefined | null): number {
  return parseInt(v || '0', 10) || 0
}

function safeFloat(v: string | undefined | null): number {
  return parseFloat(v || '0') || 0
}

// ─── Token Management ───

function readTokenFromFile(): { token: string; expiresAt: number } | null {
  try {
    if (!fs.existsSync(TOKEN_CACHE_PATH)) return null
    const raw = fs.readFileSync(TOKEN_CACHE_PATH, 'utf-8')
    const cached = JSON.parse(raw)
    const expiresAt = new Date(cached.expires_at).getTime()
    if (Date.now() < expiresAt) {
      return { token: cached.access_token, expiresAt }
    }
  } catch {
    // ignore
  }
  return null
}

function writeTokenToFile(token: string, expiresAt: Date): void {
  try {
    const dir = path.dirname(TOKEN_CACHE_PATH)
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true })
    const tmpPath = TOKEN_CACHE_PATH + '.tmp'
    fs.writeFileSync(tmpPath, JSON.stringify({
      access_token: token,
      expires_at: expiresAt.toISOString(),
    }), 'utf-8')
    fs.renameSync(tmpPath, TOKEN_CACHE_PATH)
  } catch {
    // non-critical
  }
}

export async function getToken(): Promise<string> {
  // 1. In-memory cache
  if (cachedToken && Date.now() < cachedTokenExpiry) {
    return cachedToken
  }

  // 2. File cache (shared with Python agents)
  const fromFile = readTokenFromFile()
  if (fromFile) {
    cachedToken = fromFile.token
    cachedTokenExpiry = fromFile.expiresAt
    return fromFile.token
  }

  // 3. Request new token
  const resp = await fetch(`${BASE_URL}/oauth2/tokenP`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      grant_type: 'client_credentials',
      appkey: KIS_APP_KEY,
      appsecret: KIS_APP_SECRET,
    }),
  })

  if (!resp.ok) {
    throw new Error(`KIS token error: ${resp.status} ${resp.statusText}`)
  }

  const data = await resp.json()
  const token = data.access_token as string
  const expiresIn = (data.expires_in as number) || 86400
  const expiresAt = new Date(Date.now() + (expiresIn - 60) * 1000)

  cachedToken = token
  cachedTokenExpiry = expiresAt.getTime()
  writeTokenToFile(token, expiresAt)

  return token
}

// ─── Common Headers ───

function authHeaders(token: string, trId: string): Record<string, string> {
  return {
    'Content-Type': 'application/json; charset=utf-8',
    authorization: `Bearer ${token}`,
    appkey: KIS_APP_KEY,
    appsecret: KIS_APP_SECRET,
    tr_id: trId,
    custtype: 'P',
  }
}

// ─── Balance Inquiry (VTTC8434R) ───

export async function fetchBalance(): Promise<KISBalanceResponse> {
  const token = await getToken()
  const trId = KIS_IS_MOCK ? 'VTTC8434R' : 'TTTC8434R'

  const params = new URLSearchParams({
    CANO,
    ACNT_PRDT_CD,
    AFHR_FLPR_YN: 'N',
    OFL_YN: '',
    INQR_DVSN: '02',
    UNPR_DVSN: '01',
    FUND_STTL_ICLD_YN: 'N',
    FNCG_AMT_AUTO_RDPT_YN: 'N',
    PRCS_DVSN: '00',
    CTX_AREA_FK100: '',
    CTX_AREA_NK100: '',
  })

  const resp = await fetch(
    `${BASE_URL}/uapi/domestic-stock/v1/trading/inquire-balance?${params}`,
    { headers: authHeaders(token, trId) },
  )

  if (!resp.ok) {
    throw new Error(`KIS balance error: ${resp.status}`)
  }

  const data = await resp.json()

  // output1: 보유종목
  const holdings: KISHolding[] = (data.output1 || [])
    .filter((item: KISHoldingRaw) => safeInt(item.hldg_qty) > 0)
    .map((item: KISHoldingRaw): KISHolding => ({
      code: item.pdno,
      name: item.prdt_name,
      quantity: safeInt(item.hldg_qty),
      avgPrice: safeFloat(item.pchs_avg_pric),
      currentPrice: safeInt(item.prpr),
      evluAmt: safeInt(item.evlu_amt),
      evluPflsAmt: safeInt(item.evlu_pfls_amt),
      evluPflsRt: safeFloat(item.evlu_pfls_rt),
      dayChange: safeInt(item.bfdy_cprs_icdc),
      dayChangeRt: safeFloat(item.fltt_rt),
    }))

  // output2: 계좌 요약
  const o2: KISAccountSummaryRaw = (data.output2 || [{}])[0] || {}
  const pchsAmt = safeInt(o2.pchs_amt_smtl_amt)
  const evluPflsAmt = safeInt(o2.evlu_pfls_smtl_amt)

  const summary: KISAccountSummary = {
    cashAmt: safeInt(o2.dnca_tot_amt),
    stockEvluAmt: safeInt(o2.scts_evlu_amt),
    totEvluAmt: safeInt(o2.tot_evlu_amt),
    pchsAmt,
    evluPflsAmt,
    nassAmt: safeInt(o2.nass_amt),
    thdtBuyAmt: safeInt(o2.thdt_buy_amt),
    thdtSllAmt: safeInt(o2.thdt_sll_amt),
    thdtTlexAmt: safeInt(o2.thdt_tlex_amt),
    asstIcdcAmt: safeInt(o2.asst_icdc_amt),
    asstIcdcErngRt: safeFloat(o2.asst_icdc_erng_rt),
    erngRt: pchsAmt > 0 ? (evluPflsAmt / pchsAmt) * 100 : null,
  }

  return {
    summary,
    holdings,
    fetchedAt: new Date().toISOString(),
  }
}

// ─── Stock Price (FHKST01010100) ───

export async function fetchPrice(code: string): Promise<KISPrice> {
  const token = await getToken()

  const params = new URLSearchParams({
    FID_COND_MRKT_DIV_CODE: 'J',
    FID_INPUT_ISCD: code,
  })

  const resp = await fetch(
    `${PRICE_BASE}/uapi/domestic-stock/v1/quotations/inquire-price?${params}`,
    { headers: authHeaders(token, 'FHKST01010100') },
  )

  if (!resp.ok) {
    throw new Error(`KIS price error: ${resp.status}`)
  }

  const data = await resp.json()
  const o: KISPriceRaw = data.output || {}

  const signMap: Record<string, string> = {
    '1': '상한', '2': '상승', '3': '보합', '4': '하한', '5': '하락',
  }

  return {
    code,
    price: safeInt(o.stck_prpr),
    dayChange: safeInt(o.prdy_vrss),
    dayChangeRt: safeFloat(o.prdy_ctrt),
    volume: safeInt(o.acml_vol),
    open: safeInt(o.stck_oprc),
    high: safeInt(o.stck_hgpr),
    low: safeInt(o.stck_lwpr),
    sign: signMap[o.prdy_vrss_sign] || '보합',
    per: safeFloat(o.per),
    pbr: safeFloat(o.pbr),
  }
}

// ─── Trade History (VTTC8001R / TTTC8001R) ───

export async function fetchTradeHistory(
  startDate: string,  // YYYYMMDD
  endDate: string,    // YYYYMMDD
): Promise<{ trades: KISTradeExecution[]; hasMore: boolean }> {
  const token = await getToken()
  const trId = KIS_IS_MOCK ? 'VTTC8001R' : 'TTTC8001R'

  const allTrades: KISTradeExecution[] = []
  let ctxAreaFK100 = ''
  let ctxAreaNK100 = ''
  let hasMore = false
  const MAX_PAGES = 10

  // 페이지네이션 루프
  for (let page = 0; page < MAX_PAGES; page++) {
    const params = new URLSearchParams({
      CANO,
      ACNT_PRDT_CD,
      INQR_STRT_DT: startDate,
      INQR_END_DT: endDate,
      SLL_BUY_DVSN_CD: '00',   // 전체 (매도+매수)
      INQR_DVSN: '00',         // 역순
      PDNO: '',
      CCLD_DVSN: '00',         // 전체
      ORD_GNO_BRNO: '',
      ODNO: '',
      INQR_DVSN_3: '00',
      INQR_DVSN_1: '',
      CTX_AREA_FK100: ctxAreaFK100,
      CTX_AREA_NK100: ctxAreaNK100,
    })

    const resp = await fetch(
      `${BASE_URL}/uapi/domestic-stock/v1/trading/inquire-daily-ccld?${params}`,
      { headers: authHeaders(token, trId) },
    )

    if (!resp.ok) {
      throw new Error(`KIS trades error: ${resp.status}`)
    }

    const data = await resp.json()
    const items: KISTradeExecutionRaw[] = data.output1 || []

    for (const item of items) {
      if (!item.odno) continue
      const dt = item.ord_dt || ''
      const tm = item.ord_tmd || ''
      allTrades.push({
        orderDate: dt ? `${dt.slice(0, 4)}-${dt.slice(4, 6)}-${dt.slice(6, 8)}` : '',
        orderTime: tm ? `${tm.slice(0, 2)}:${tm.slice(2, 4)}:${tm.slice(4, 6)}` : '',
        orderNo: item.odno,
        action: item.sll_buy_dvsn_cd === '01' ? 'SELL' : 'BUY',
        code: item.pdno,
        name: item.prdt_name,
        orderQty: safeInt(item.ord_qty),
        filledQty: safeInt(item.tot_ccld_qty),
        orderPrice: safeFloat(item.ord_unpr),
        filledPrice: safeFloat(item.avg_prvs),
        status: item.ccld_cndt_name || '알수없음',
        orderType: item.ord_dvsn_name || '',
      })
    }

    // 연속조회 확인
    ctxAreaFK100 = data.ctx_area_fk100 || ''
    ctxAreaNK100 = data.ctx_area_nk100 || ''
    if (!ctxAreaFK100 && !ctxAreaNK100) break
    if (items.length === 0) break

    // 마지막 페이지에서 아직 더 있으면 hasMore 플래그 설정
    if (page === MAX_PAGES - 1 && (ctxAreaFK100 || ctxAreaNK100)) {
      hasMore = true
    }
  }

  return { trades: allTrades, hasMore }
}
