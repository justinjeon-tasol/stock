'use client'

import { useState } from 'react'
import { PositionTable } from '@/components/positions/PositionTable'
import { Card } from '@/components/ui/Card'
import { cn } from '@/lib/cn'
import type { PositionStatus } from '@/lib/types'

const TABS: { label: string; value: PositionStatus }[] = [
  { label: 'OPEN (보유중)', value: 'OPEN' },
  { label: 'CLOSED (청산)', value: 'CLOSED' },
]

export default function PositionsPage() {
  const [activeTab, setActiveTab] = useState<PositionStatus>('OPEN')

  return (
    <div className="space-y-6 animate-slide-in">
      <div>
        <h1 className="text-xl font-bold text-[#f0f0f8]">포지션</h1>
        <p className="text-xs text-[#555570] mt-0.5">보유 종목 및 청산 이력</p>
      </div>

      <Card padding="none">
        {/* 탭 헤더 */}
        <div className="flex border-b border-[#2a2a38] px-4">
          {TABS.map((tab) => (
            <button
              key={tab.value}
              onClick={() => setActiveTab(tab.value)}
              className={cn(
                'py-3 px-4 text-sm font-medium border-b-2 transition-colors duration-150 -mb-px',
                activeTab === tab.value
                  ? 'border-[#7c6af7] text-[#7c6af7]'
                  : 'border-transparent text-[#8888a8] hover:text-[#f0f0f8]'
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* 테이블 */}
        <div className="p-4">
          <PositionTable status={activeTab} />
        </div>
      </Card>
    </div>
  )
}
