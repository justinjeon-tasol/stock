'use client'

import { useState, useEffect } from 'react'
import { useKISTrades } from '@/hooks/useKISTrades'
import { DataSourceBadge } from './DataSourceBadge'
import { formatKRW, formatOrderStatus } from '@/lib/format'
import { RefreshCw } from 'lucide-react'

export function KISTradeHistory() {
  const { trades, loading, error, fetchedAt, hasMore, refetch } = useKISTrades()
  const [days, setDays] = useState(7)

  useEffect(() => {
    const end = new Date()
    const start = new Date(end.getTime() - days * 86400000)
    refetch(start.toISOString().slice(0, 10), end.toISOString().slice(0, 10))
  }, [days, refetch])

  return (
    <div className="space-y-3">
      {/* 헤더 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <DataSourceBadge source={error ? 'KIS_FALLBACK' : 'KIS'} fetchedAt={fetchedAt} />
          <div className="flex gap-1">
            {[7, 14, 30].map((d) => (
              <button
                key={d}
                onClick={() => setDays(d)}
                className={`px-2 py-0.5 text-xs rounded ${
                  days === d
                    ? 'bg-[#7c6af7] text-white'
                    : 'bg-[#1a1a24] text-[#8888a8] hover:bg-[#22222e]'
                }`}
              >
                {d}일
              </button>
            ))}
          </div>
        </div>
        <button
          onClick={() => {
            const end = new Date()
            const start = new Date(end.getTime() - days * 86400000)
            refetch(start.toISOString().slice(0, 10), end.toISOString().slice(0, 10))
          }}
          className="p-1.5 rounded hover:bg-[#1a1a24] text-[#8888a8]"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* 에러 */}
      {error && (
        <div className="text-xs text-yellow-400 bg-yellow-400/10 px-3 py-2 rounded">
          KIS 조회 실패: {error}
        </div>
      )}

      {/* 테이블 */}
      {loading && trades.length === 0 ? (
        <div className="text-center py-8 text-[#555570] text-sm">조회 중...</div>
      ) : trades.length === 0 ? (
        <div className="text-center py-8 text-[#555570] text-sm">체결 내역이 없습니다</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[#555570] text-xs border-b border-[#2a2a38]">
                <th className="text-left py-2 px-2">주문일시</th>
                <th className="text-center py-2 px-2">구분</th>
                <th className="text-left py-2 px-2">종목</th>
                <th className="text-right py-2 px-2">주문수량</th>
                <th className="text-right py-2 px-2">체결수량</th>
                <th className="text-right py-2 px-2">주문가</th>
                <th className="text-right py-2 px-2">체결가</th>
                <th className="text-center py-2 px-2">상태</th>
                <th className="text-right py-2 px-2">주문번호</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t, i) => {
                const isBuy = t.action === 'BUY'
                const actionColor = isBuy ? 'text-red-400' : 'text-blue-400'
                const isFilled = t.filledQty >= t.orderQty && t.orderQty > 0
                const statusColor = isFilled
                  ? 'text-emerald-400'
                  : t.filledQty > 0
                  ? 'text-yellow-400'
                  : 'text-[#555570]'

                return (
                  <tr key={`${t.orderNo}-${i}`} className="border-b border-[#1a1a24] hover:bg-[#1a1a24]/50">
                    <td className="py-2 px-2 text-[#8888a8]">
                      <div>{t.orderDate}</div>
                      <div className="text-xs text-[#555570]">{t.orderTime}</div>
                    </td>
                    <td className={`text-center py-2 px-2 font-semibold ${actionColor}`}>
                      {isBuy ? '매수' : '매도'}
                    </td>
                    <td className="py-2 px-2">
                      <div className="text-[#f0f0f8]">{t.name}</div>
                      <div className="text-xs text-[#555570]">{t.code}</div>
                    </td>
                    <td className="text-right py-2 px-2 text-[#f0f0f8]">{t.orderQty.toLocaleString('ko-KR')}</td>
                    <td className="text-right py-2 px-2 text-[#f0f0f8]">{t.filledQty.toLocaleString('ko-KR')}</td>
                    <td className="text-right py-2 px-2 text-[#8888a8]">{formatKRW(t.orderPrice)}</td>
                    <td className="text-right py-2 px-2 text-[#f0f0f8]">
                      {t.filledPrice > 0 ? formatKRW(t.filledPrice) : '-'}
                    </td>
                    <td className={`text-center py-2 px-2 text-xs ${statusColor}`}>
                      {formatOrderStatus(t.status)}
                    </td>
                    <td className="text-right py-2 px-2 text-xs text-[#555570]">{t.orderNo}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex items-center justify-between">
        <div className="text-xs text-[#555570]">
          총 {trades.length}건
        </div>
        {hasMore && (
          <div className="text-xs text-yellow-400 bg-yellow-400/10 px-3 py-1.5 rounded">
            이전 거래내역이 더 있을 수 있습니다. 조회 기간을 좁혀 주세요.
          </div>
        )}
      </div>
    </div>
  )
}
