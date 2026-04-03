'use client'

import { Filter, RotateCcw } from 'lucide-react'
import type { TradeFilter, TradeAction, TradeMode, MarketPhaseType } from '@/lib/types'

const PHASE_OPTIONS: (MarketPhaseType | 'ALL')[] = [
  'ALL', '대상승장', '상승장', '일반장', '변동폭큰', '하락장', '대폭락장',
]

interface TradeFilterBarProps {
  filter: TradeFilter
  onChange: (filter: TradeFilter) => void
}

const LABEL_CLASSES =
  'text-xs text-[#555570] mb-1 block'

const SELECT_CLASSES =
  'bg-[#1a1a24] border border-[#3a3a4e] text-[#f0f0f8] text-xs rounded-lg px-2 py-1.5 focus:outline-none focus:border-[#7c6af7] transition-colors'

const INPUT_CLASSES =
  'bg-[#1a1a24] border border-[#3a3a4e] text-[#f0f0f8] text-xs rounded-lg px-2 py-1.5 focus:outline-none focus:border-[#7c6af7] transition-colors'

const DEFAULT_FILTER: TradeFilter = {
  action: 'ALL',
  mode: 'ALL',
  phase: 'ALL',
  dateFrom: '',
  dateTo: '',
}

export function TradeFilterBar({ filter, onChange }: TradeFilterBarProps) {
  const set = <K extends keyof TradeFilter>(key: K, value: TradeFilter[K]) => {
    onChange({ ...filter, [key]: value })
  }

  const reset = () => onChange(DEFAULT_FILTER)

  return (
    <div className="flex flex-wrap items-end gap-4 p-4 bg-[#111118] border border-[#2a2a38] rounded-xl">
      <div className="flex items-center gap-1.5 text-[#8888a8] shrink-0">
        <Filter className="w-3.5 h-3.5" />
        <span className="text-xs font-medium">필터</span>
      </div>

      {/* 매수/매도 */}
      <div>
        <label className={LABEL_CLASSES}>구분</label>
        <select
          className={SELECT_CLASSES}
          value={filter.action}
          onChange={(e) => set('action', e.target.value as TradeAction | 'ALL')}
        >
          <option value="ALL">전체</option>
          <option value="BUY">매수</option>
          <option value="SELL">매도</option>
        </select>
      </div>

      {/* 모드 */}
      <div>
        <label className={LABEL_CLASSES}>모드</label>
        <select
          className={SELECT_CLASSES}
          value={filter.mode}
          onChange={(e) => set('mode', e.target.value as TradeMode | 'ALL')}
        >
          <option value="ALL">전체</option>
          <option value="MOCK">모의</option>
          <option value="REAL">실전</option>
        </select>
      </div>

      {/* 국면 */}
      <div>
        <label className={LABEL_CLASSES}>국면</label>
        <select
          className={SELECT_CLASSES}
          value={filter.phase}
          onChange={(e) => set('phase', e.target.value as MarketPhaseType | 'ALL')}
        >
          {PHASE_OPTIONS.map((p) => (
            <option key={p} value={p}>
              {p === 'ALL' ? '전체' : p}
            </option>
          ))}
        </select>
      </div>

      {/* 날짜 범위 */}
      <div>
        <label className={LABEL_CLASSES}>시작일</label>
        <input
          type="date"
          className={INPUT_CLASSES}
          value={filter.dateFrom}
          onChange={(e) => set('dateFrom', e.target.value)}
        />
      </div>
      <div>
        <label className={LABEL_CLASSES}>종료일</label>
        <input
          type="date"
          className={INPUT_CLASSES}
          value={filter.dateTo}
          onChange={(e) => set('dateTo', e.target.value)}
        />
      </div>

      {/* 초기화 */}
      <button
        onClick={reset}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-[#8888a8] hover:text-[#f0f0f8] hover:bg-[#1a1a24] border border-[#3a3a4e] transition-colors mb-0.5"
      >
        <RotateCcw className="w-3 h-3" />
        초기화
      </button>
    </div>
  )
}
