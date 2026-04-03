'use client'

import { useState } from 'react'
import { TradeFilterBar } from '@/components/trades/TradeFilterBar'
import { TradeTable } from '@/components/trades/TradeTable'
import { Card } from '@/components/ui/Card'
import { useTrades } from '@/hooks/useTrades'
import type { TradeFilter } from '@/lib/types'

const DEFAULT_FILTER: TradeFilter = {
  action: 'ALL',
  mode: 'ALL',
  phase: 'ALL',
  dateFrom: '',
  dateTo: '',
}

export default function TradesPage() {
  const [filter, setFilter] = useState<TradeFilter>(DEFAULT_FILTER)
  const { trades, loading, error } = useTrades(filter)

  return (
    <div className="space-y-4 animate-slide-in">
      <div>
        <h1 className="text-xl font-bold text-[#f0f0f8]">매매이력</h1>
        <p className="text-xs text-[#555570] mt-0.5">
          전체 거래 기록 ({trades.length}건)
        </p>
      </div>

      <TradeFilterBar filter={filter} onChange={setFilter} />

      <Card padding="none">
        <div className="p-4">
          <TradeTable trades={trades} loading={loading} error={error} />
        </div>
      </Card>
    </div>
  )
}
