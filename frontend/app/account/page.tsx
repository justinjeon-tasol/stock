'use client'

import { useState, useEffect, useCallback } from 'react'
import { RefreshCw, ChevronDown, ChevronRight } from 'lucide-react'
import { supabase } from '@/lib/supabase'
import { useAccountSummary } from '@/hooks/useAccountSummary'
import { useKISBalance } from '@/hooks/useKISBalance'
import { DataSourceBadge } from '@/components/account/DataSourceBadge'
import { KISBalanceSummary } from '@/components/account/KISBalanceSummary'
import { KISHoldingsTable } from '@/components/account/KISHoldingsTable'
import { KISTradeHistory } from '@/components/account/KISTradeHistory'
import { InvestmentAnalysis } from '@/components/account/InvestmentAnalysis'
import { formatKRW } from '@/lib/format'
import type { Trade } from '@/lib/types'
import type { DataSource } from '@/lib/kis-types'

type TabType = 'balance' | 'history' | 'analysis'
type HistoryView = 'kis' | 'daily'

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
  const [historyView, setHistoryView] = useState<HistoryView>('kis')

  // KIS 실시간 (primary)
  const { data: kisData, loading: kisLoading, error: kisError, refetch: refetchKIS } = useKISBalance()
  // Supabase 폴백
  const { summary: sbSummary, loading: sbLoading, refetch: refetchSB } = useAccountSummary()

  // 데이터 소스 결정
  const hasKIS = !!kisData && !kisError
  const dataSource: DataSource = hasKIS ? 'KIS' : sbSummary ? 'KIS_FALLBACK' : 'SUPABASE'

  // History tab (일별 요약)
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

  useEffect(() => {
    if (tab === 'history' && historyView === 'daily') fetchHistory()
  }, [tab, historyView, days, fetchHistory])

  const handleRefresh = useCallback(() => {
    refetchKIS()
    refetchSB()
    if (tab === 'history' && historyView === 'daily') fetchHistory()
  }, [refetchKIS, refetchSB, tab, historyView, fetchHistory])

  const loading = kisLoading || sbLoading

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold text-[#f0f0f8]">계좌내역</h1>
          <DataSourceBadge source={dataSource} fetchedAt={kisData?.fetchedAt} />
        </div>
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
          { key: 'analysis' as TabType, label: '수익분석' },
        ]).map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-5 py-2.5 text-sm font-medium transition-colors relative ${
              tab === t.key ? 'text-[#f0f0f8]' : 'text-[#555570] hover:text-[#8888a8]'
            }`}
          >
            {t.label}
            {tab === t.key && <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-[#7c6af7]" />}
          </button>
        ))}
      </div>

      {/* ─── 계좌잔고 탭 ─── */}
      {tab === 'balance' && (
        <>
          {kisError && !sbSummary && (
            <p className="text-xs text-yellow-400 bg-yellow-400/10 px-3 py-2 rounded">
              KIS 조회 실패: {kisError}
            </p>
          )}

          {/* KIS 실시간 잔고 요약 */}
          {hasKIS ? (
            <div className="bg-[#13131a] border border-[#2a2a38] rounded-lg p-4">
              <KISBalanceSummary summary={kisData.summary} />
            </div>
          ) : sbSummary ? (
            /* Supabase 폴백 */
            <div className="bg-[#13131a] border border-[#2a2a38] rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <tbody>
                  <tr className="border-b border-[#2a2a38]">
                    <SummaryCell label="예수금(현금)" value={formatKRW(sbSummary.cash_amt)} />
                    <SummaryCell label="유가평가액" value={formatKRW(sbSummary.stock_evlu_amt)} />
                    <SummaryCell label="총평가금액" value={formatKRW(sbSummary.tot_evlu_amt)} highlight />
                  </tr>
                  <tr>
                    <SummaryCell label="매입금액" value={formatKRW(sbSummary.pchs_amt)} />
                    <SummaryCell label="평가손익" value={formatKRW(sbSummary.evlu_pfls_amt)} colored={sbSummary.evlu_pfls_amt} />
                    <SummaryCell label="수익률" value={`${sbSummary.erng_rt >= 0 ? '+' : ''}${sbSummary.erng_rt.toFixed(2)}%`} colored={sbSummary.erng_rt} />
                  </tr>
                </tbody>
              </table>
            </div>
          ) : loading ? (
            <div className="text-center py-8 text-[#555570] text-sm">로드 중...</div>
          ) : null}

          {/* 보유종목 테이블 */}
          <div className="bg-[#13131a] border border-[#2a2a38] rounded-lg p-4">
            <h3 className="text-sm font-semibold text-[#8888a8] uppercase tracking-wider mb-3">보유 종목</h3>
            {hasKIS ? (
              <KISHoldingsTable holdings={kisData.holdings} summary={kisData.summary} />
            ) : (
              <div className="text-center py-8 text-[#555570] text-sm">
                {loading ? '로드 중...' : 'KIS 연결 대기 중'}
              </div>
            )}
          </div>
        </>
      )}

      {/* ─── 거래내역 탭 ─── */}
      {tab === 'history' && (
        <>
          {/* 뷰 토글 */}
          <div className="flex gap-2">
            <button
              onClick={() => setHistoryView('kis')}
              className={`text-xs px-3 py-1.5 rounded-md transition-colors ${
                historyView === 'kis' ? 'bg-[#7c6af7] text-white' : 'bg-[#1e1e2a] text-[#555570] hover:text-[#8888a8]'
              }`}
            >
              KIS 체결내역
            </button>
            <button
              onClick={() => setHistoryView('daily')}
              className={`text-xs px-3 py-1.5 rounded-md transition-colors ${
                historyView === 'daily' ? 'bg-[#7c6af7] text-white' : 'bg-[#1e1e2a] text-[#555570] hover:text-[#8888a8]'
              }`}
            >
              일별 요약
            </button>
          </div>

          {historyView === 'kis' ? (
            <KISTradeHistory />
          ) : (
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
        </>
      )}

      {/* ─── 수익분석 탭 ─── */}
      {tab === 'analysis' && (
        <InvestmentAnalysis kisSummary={hasKIS ? kisData.summary : null} />
      )}
    </div>
  )
}

// ─── Helper Components ───

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
        <td className="py-3 px-3 font-mono text-[#f0f0f8] text-xs">{formatKRW(row.tot_evlu_amt)}</td>
        <td className="py-3 px-3 font-mono text-xs text-[#8888a8]">{formatKRW(row.cash_amt)}</td>
        <td className="py-3 px-3 font-mono text-xs text-[#8888a8]">{formatKRW(row.stock_evlu_amt)}</td>
        <td className="py-3 px-3 font-mono text-xs text-[#8888a8]">{row.daily_buy_amt > 0 ? formatKRW(row.daily_buy_amt) : '-'}</td>
        <td className="py-3 px-3 font-mono text-xs text-[#8888a8]">{row.daily_sell_amt > 0 ? formatKRW(row.daily_sell_amt) : '-'}</td>
        <td className="py-3 px-3 text-xs font-medium" style={{ color: row.daily_realized_pnl === 0 ? '#555570' : dayPnlPos ? '#4ade80' : '#f87171' }}>
          {row.daily_realized_pnl !== 0 ? `${dayPnlPos ? '+' : ''}${formatKRW(Math.abs(row.daily_realized_pnl))}` : '-'}
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
                      <td className="py-1.5 px-2 font-mono text-[#8888a8]">{formatKRW(t.price)}</td>
                      <td className="py-1.5 px-2 font-mono text-[#8888a8]">{formatKRW(t.price * t.quantity)}</td>
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
