'use client'

import { useState, useEffect, useCallback } from 'react'
import { RefreshCw, ChevronDown, ChevronRight } from 'lucide-react'
import { supabase } from '@/lib/supabase'
import { useAccountSummary } from '@/hooks/useAccountSummary'
import { usePositions } from '@/hooks/usePositions'
import type { Trade } from '@/lib/types'

function fmt(n: number): string {
  return Math.round(n).toLocaleString('ko-KR')
}

function fmtDecimal(n: number, digits = 2): string {
  return n.toLocaleString('ko-KR', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

type TabType = 'balance' | 'history'

interface AccountHistory {
  id: string
  recorded_date: string
  tot_evlu_amt: number
  cash_amt: number
  stock_evlu_amt: number
  daily_buy_amt: number
  daily_sell_amt: number
  daily_realized_pnl: number
  daily_trade_count: number
}

export default function AccountPage() {
  const [tab, setTab] = useState<TabType>('balance')

  // Supabase 훅으로 교체 (기존 execSync → Python 제거)
  const { summary, loading, error, refetch: refetchSummary } = useAccountSummary()
  const { positions: holdings, loading: holdingsLoading, refetch: refetchHoldings } = usePositions({ status: 'OPEN' })

  // History tab
  const [history, setHistory] = useState<AccountHistory[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [days, setDays] = useState(30)
  const [expandedDate, setExpandedDate] = useState<string | null>(null)
  const [tradeDetails, setTradeDetails] = useState<Record<string, Trade[]>>({})

  const fetchHistory = useCallback(async () => {
    setHistoryLoading(true)
    try {
      const res = await fetch(`/api/account-history?days=${days}`)
      const data = await res.json()
      setHistory(Array.isArray(data) ? data : [])
    } catch { setHistory([]) }
    setHistoryLoading(false)
  }, [days])

  const fetchDateDetail = async (date: string) => {
    if (tradeDetails[date] !== undefined) {
      setExpandedDate(expandedDate === date ? null : date)
      return
    }
    const res = await fetch(`/api/account-history?date=${date}`)
    const data = await res.json()
    setTradeDetails((prev) => ({ ...prev, [date]: data.trades ?? [] }))
    setExpandedDate(date)
  }

  useEffect(() => { if (tab === 'history') fetchHistory() }, [tab, days, fetchHistory])

  const handleRefresh = useCallback(() => {
    refetchSummary()
    refetchHoldings()
    if (tab === 'history') fetchHistory()
  }, [refetchSummary, refetchHoldings, tab, fetchHistory])

  const s = summary

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-[#f0f0f8]">계좌잔고내역</h1>
        <button
          onClick={handleRefresh}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md bg-[#1e1e2a] text-[#8888a8] hover:text-[#f0f0f8] hover:bg-[#2a2a38] transition-colors"
        >
          <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
          새로고침
        </button>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-[#2a2a38]">
        {([
          { key: 'balance' as TabType, label: '계좌잔고' },
          { key: 'history' as TabType, label: '거래내역' },
        ]).map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-5 py-2.5 text-sm font-medium transition-colors relative ${
              tab === t.key ? 'text-[#f0f0f8]' : 'text-[#555570] hover:text-[#8888a8]'
            }`}
          >
            {t.label}
            {tab === t.key && <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-[#60a5fa]" />}
          </button>
        ))}
      </div>

      {tab === 'balance' ? (
        <>
          {error && <p className="text-xs text-[#f87171]">{error}</p>}

          {s && (
            <p className="text-xs text-[#555570] text-right">
              최종 갱신: {new Date(s.created_at).toLocaleString('ko-KR', {
                month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
              })} — Supabase
            </p>
          )}

          {/* Summary Grid */}
          {s && (
            <div className="bg-[#13131a] border border-[#2a2a38] rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <tbody>
                  <tr className="border-b border-[#2a2a38]">
                    <SummaryCell label="예수금(현금)" value={fmt(s.cash_amt)} />
                    <SummaryCell label="유가평가액" value={fmt(s.stock_evlu_amt)} />
                    <SummaryCell label="총평가금액" value={fmt(s.tot_evlu_amt)} highlight />
                  </tr>
                  <tr>
                    <SummaryCell label="매입금액" value={fmt(s.pchs_amt)} />
                    <SummaryCell label="평가손익" value={fmt(s.evlu_pfls_amt)} colored={s.evlu_pfls_amt} />
                    <SummaryCell label="수익률" value={`${s.erng_rt >= 0 ? '+' : ''}${s.erng_rt.toFixed(2)}%`} colored={s.erng_rt} />
                  </tr>
                </tbody>
              </table>
            </div>
          )}

          {/* Holdings Table */}
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#2a2a38] bg-[#13131a]">
                  {['종목명', '수량', '매입평균', '현재가', '평가금액', '평가손익', '수익률'].map((h) => (
                    <th key={h} className="text-center text-xs text-[#555570] font-medium py-3 px-3">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(loading || holdingsLoading) && holdings.length === 0 ? (
                  <tr><td colSpan={7} className="text-center text-xs text-[#555570] py-8">로드 중...</td></tr>
                ) : holdings.length === 0 ? (
                  <tr><td colSpan={7} className="text-center text-xs text-[#555570] py-8">보유 종목 없음</td></tr>
                ) : (
                  holdings.map((h) => {
                    const pnlPct = h.result_pct ?? 0
                    const currentPrice = h.avg_price > 0 ? Math.round(h.avg_price * (1 + pnlPct / 100)) : 0
                    const evluAmt = currentPrice * h.quantity
                    const evluPflsAmt = evluAmt - (h.avg_price * h.quantity)

                    return (
                      <tr key={h.id} className="border-b border-[#1e1e2a] hover:bg-[#1a1a24] transition-colors">
                        <td className="py-3.5 px-3 text-center text-[#f0f0f8]">{h.name}</td>
                        <td className="py-3.5 px-3 text-center font-mono text-[#8888a8]">{h.quantity}</td>
                        <td className="py-3.5 px-3 text-center font-mono text-[#8888a8]">{fmtDecimal(h.avg_price)}</td>
                        <td className="py-3.5 px-3 text-center font-mono text-[#8888a8]">{fmt(currentPrice)}</td>
                        <td className="py-3.5 px-3 text-center font-mono text-[#8888a8]">{fmt(evluAmt)}</td>
                        <td
                          className="py-3.5 px-3 text-center font-mono font-medium"
                          style={{ color: evluPflsAmt > 0 ? '#f87171' : evluPflsAmt < 0 ? '#60a5fa' : '#8888a8' }}
                        >
                          {fmt(evluPflsAmt)}
                        </td>
                        <td
                          className="py-3.5 px-3 text-center font-mono font-medium"
                          style={{ color: pnlPct > 0 ? '#f87171' : pnlPct < 0 ? '#60a5fa' : '#8888a8' }}
                        >
                          {pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%
                        </td>
                      </tr>
                    )
                  })
                )}
                {/* Holdings total row */}
                {holdings.length > 0 && s && (
                  <tr className="bg-[#13131a] border-t border-[#2a2a38]">
                    <td className="py-3 px-3 text-center text-xs text-[#555570] font-medium">합계</td>
                    <td className="py-3 px-3 text-center font-mono text-xs text-[#8888a8]">
                      {holdings.reduce((sum, h) => sum + h.quantity, 0)}
                    </td>
                    <td className="py-3 px-3" />
                    <td className="py-3 px-3" />
                    <td className="py-3 px-3 text-center font-mono text-xs text-[#f0f0f8] font-medium">
                      {fmt(s.stock_evlu_amt)}
                    </td>
                    <td
                      className="py-3 px-3 text-center font-mono text-xs font-medium"
                      style={{ color: s.evlu_pfls_amt > 0 ? '#f87171' : s.evlu_pfls_amt < 0 ? '#60a5fa' : '#8888a8' }}
                    >
                      {fmt(s.evlu_pfls_amt)}
                    </td>
                    <td className="py-3 px-3" />
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        /* 거래내역 Tab */
        <>
          <div className="flex gap-2">
            {[7, 30, 90].map((d) => (
              <button
                key={d}
                onClick={() => setDays(d)}
                className={`text-xs px-3 py-1.5 rounded-md transition-colors ${
                  days === d ? 'bg-[#2a2a38] text-[#f0f0f8]' : 'text-[#555570] hover:text-[#8888a8]'
                }`}
              >
                {d}일
              </button>
            ))}
          </div>

          {historyLoading ? (
            <p className="text-xs text-[#555570] py-8 text-center">로드 중...</p>
          ) : history.length === 0 ? (
            <p className="text-xs text-[#555570] py-8 text-center">데이터 없음</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[#2a2a38]">
                    {['날짜', '총자산', '현금', '주식평가', '매수', '매도', '당일손익', '건수', ''].map((h) => (
                      <th key={h} className="text-left text-xs text-[#555570] font-medium py-2 px-3 whitespace-nowrap">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {history.map((row) => {
                    const isExpanded = expandedDate === row.recorded_date
                    const dayPnlPos = row.daily_realized_pnl >= 0
                    return (
                      <HistoryRow
                        key={row.recorded_date}
                        row={row}
                        isExpanded={isExpanded}
                        dayPnlPos={dayPnlPos}
                        trades={tradeDetails[row.recorded_date]}
                        onClick={() => fetchDateDetail(row.recorded_date)}
                      />
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function SummaryCell({ label, value, colored, highlight }: {
  label: string; value: string; colored?: number; highlight?: boolean
}) {
  let valueColor = '#f0f0f8'
  if (colored !== undefined) {
    valueColor = colored > 0 ? '#f87171' : colored < 0 ? '#60a5fa' : '#f0f0f8'
  }
  if (highlight) valueColor = '#fbbf24'

  return (
    <td className="py-3.5 px-4 w-1/3">
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs text-[#555570] whitespace-nowrap">{label}</span>
        <span className="font-mono text-sm" style={{ color: valueColor }}>{value}</span>
      </div>
    </td>
  )
}

function HistoryRow({ row, isExpanded, dayPnlPos, trades, onClick }: {
  row: AccountHistory; isExpanded: boolean; dayPnlPos: boolean; trades?: Trade[]; onClick: () => void
}) {
  return (
    <>
      <tr className="border-b border-[#2a2a38] hover:bg-[#1a1a24] transition-colors cursor-pointer" onClick={onClick}>
        <td className="py-3 px-3 text-xs text-[#8888a8] whitespace-nowrap">{row.recorded_date}</td>
        <td className="py-3 px-3 font-mono text-[#f0f0f8] text-xs">{fmt(row.tot_evlu_amt)}원</td>
        <td className="py-3 px-3 font-mono text-xs text-[#8888a8]">{fmt(row.cash_amt)}원</td>
        <td className="py-3 px-3 font-mono text-xs text-[#8888a8]">{fmt(row.stock_evlu_amt)}원</td>
        <td className="py-3 px-3 font-mono text-xs text-[#8888a8]">{row.daily_buy_amt > 0 ? `${fmt(row.daily_buy_amt)}원` : '-'}</td>
        <td className="py-3 px-3 font-mono text-xs text-[#8888a8]">{row.daily_sell_amt > 0 ? `${fmt(row.daily_sell_amt)}원` : '-'}</td>
        <td className="py-3 px-3 text-xs font-medium" style={{ color: row.daily_realized_pnl === 0 ? '#555570' : dayPnlPos ? '#4ade80' : '#f87171' }}>
          {row.daily_realized_pnl !== 0 ? `${dayPnlPos ? '+' : ''}${fmt(Math.abs(row.daily_realized_pnl))}원` : '-'}
        </td>
        <td className="py-3 px-3 text-xs text-[#555570]">{row.daily_trade_count > 0 ? `${row.daily_trade_count}건` : '-'}</td>
        <td className="py-3 px-3">{isExpanded ? <ChevronDown className="w-3.5 h-3.5 text-[#555570]" /> : <ChevronRight className="w-3.5 h-3.5 text-[#555570]" />}</td>
      </tr>
      {isExpanded && (
        <tr className="bg-[#0f0f18]">
          <td colSpan={9} className="px-6 py-3">
            {(trades ?? []).length === 0 ? (
              <p className="text-xs text-[#555570]">해당 날짜 거래 내역 없음</p>
            ) : (
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-[#2a2a38]">
                    {['시각', '구분', '종목', '수량', '체결가', '금액', '손익률'].map((h) => (
                      <th key={h} className="text-left text-[#555570] font-medium py-1.5 px-2">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(trades ?? []).map((t) => (
                    <tr key={t.id} className="border-b border-[#1e1e2a]">
                      <td className="py-1.5 px-2 text-[#555570]">{t.created_at.slice(11, 16)}</td>
                      <td className="py-1.5 px-2 font-medium" style={{ color: t.action === 'BUY' ? '#60a5fa' : '#f87171' }}>
                        {t.action === 'BUY' ? '매수' : '매도'}
                      </td>
                      <td className="py-1.5 px-2 text-[#f0f0f8]">{t.name}({t.code})</td>
                      <td className="py-1.5 px-2 text-[#8888a8]">{t.quantity}주</td>
                      <td className="py-1.5 px-2 font-mono text-[#8888a8]">{fmt(t.price)}원</td>
                      <td className="py-1.5 px-2 font-mono text-[#8888a8]">{fmt(t.price * t.quantity)}원</td>
                      <td className="py-1.5 px-2 font-medium" style={{ color: (t.result_pct ?? 0) >= 0 ? '#4ade80' : '#f87171' }}>
                        {t.result_pct != null ? `${t.result_pct >= 0 ? '+' : ''}${t.result_pct.toFixed(2)}%` : '-'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </td>
        </tr>
      )}
    </>
  )
}
