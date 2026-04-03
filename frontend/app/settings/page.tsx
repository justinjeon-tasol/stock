'use client'

import { useState, useEffect, useCallback } from 'react'
import { Save, RotateCcw, Settings2 } from 'lucide-react'
import { Card, CardHeader } from '@/components/ui/Card'

// ─── 타입 ────────────────────────────────────────────────────────────────────

interface PhaseWeight {
  aggressive: number
  defensive: number
  cash: number
}

interface Config {
  phase_weights: Record<string, PhaseWeight>
  risk_management: { max_stock_weight_pct: number }
  recommendation_rules: {
    max_stocks: number
    min_confidence: number
    futures_threshold_pct: number
  }
}

// ─── 헬퍼 ────────────────────────────────────────────────────────────────────

const PHASE_LABELS: Record<string, string> = {
  대상승장: '대상승장',
  상승장:   '상승장',
  일반장:   '일반장',
  변동폭큰: '변동폭큰',
  하락장:   '하락장',
  대폭락장: '대폭락장',
}

const PHASE_COLORS: Record<string, string> = {
  대상승장: '#4ade80',
  상승장:   '#86efac',
  일반장:   '#93c5fd',
  변동폭큰: '#fbbf24',
  하락장:   '#f87171',
  대폭락장: '#dc2626',
}

function pct(v: number) {
  return `${Math.round(v * 100)}%`
}

// ─── 슬라이더 행 컴포넌트 ────────────────────────────────────────────────────

function SliderRow({
  label,
  description,
  value,
  min,
  max,
  step,
  display,
  onChange,
}: {
  label: string
  description: string
  value: number
  min: number
  max: number
  step: number
  display: string
  onChange: (v: number) => void
}) {
  return (
    <div className="py-4 border-b border-[#1e1e2a] last:border-0">
      <div className="flex items-center justify-between mb-2">
        <div>
          <p className="text-sm font-medium text-[#f0f0f8]">{label}</p>
          <p className="text-xs text-[#555570] mt-0.5">{description}</p>
        </div>
        <span className="text-sm font-bold text-[#7c6af7] min-w-[60px] text-right">
          {display}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full h-1.5 rounded-full appearance-none cursor-pointer"
        style={{
          background: `linear-gradient(to right, #7c6af7 0%, #7c6af7 ${((value - min) / (max - min)) * 100}%, #2a2a38 ${((value - min) / (max - min)) * 100}%, #2a2a38 100%)`,
        }}
      />
      <div className="flex justify-between mt-1">
        <span className="text-xs text-[#333348]">{min}{typeof min === 'number' && min < 1 && min > 0 ? '' : ''}</span>
        <span className="text-xs text-[#333348]">{max}</span>
      </div>
    </div>
  )
}

// ─── 국면 가중치 행 ──────────────────────────────────────────────────────────

function PhaseWeightRow({
  phase,
  weights,
  onCashChange,
}: {
  phase: string
  weights: PhaseWeight
  onCashChange: (v: number) => void
}) {
  const color = PHASE_COLORS[phase] ?? '#8888a8'
  const cashPct = Math.round(weights.cash * 100)
  const aggrPct = Math.round(weights.aggressive * 100)

  return (
    <div className="py-3 border-b border-[#1e1e2a] last:border-0">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium" style={{ color }}>
          {PHASE_LABELS[phase]}
        </span>
        <div className="flex gap-3 text-xs">
          <span className="text-[#4ade80]">공격 {aggrPct}%</span>
          <span className="text-[#555570]">방어 {Math.round(weights.defensive * 100)}%</span>
          <span className="text-[#fbbf24]">현금 {cashPct}%</span>
        </div>
      </div>
      {/* 현금 비중 슬라이더 (공격 = 1 - 현금 - 방어 자동 계산) */}
      <input
        type="range"
        min={0}
        max={100}
        step={5}
        value={cashPct}
        onChange={(e) => onCashChange(Number(e.target.value) / 100)}
        className="w-full h-1.5 rounded-full appearance-none cursor-pointer"
        style={{
          background: `linear-gradient(to right, #fbbf24 0%, #fbbf24 ${cashPct}%, #2a2a38 ${cashPct}%, #2a2a38 100%)`,
        }}
      />
      {/* 바 시각화 */}
      <div className="flex h-2 rounded-full overflow-hidden mt-2 gap-0.5">
        <div className="h-full rounded-sm bg-[#4ade80]" style={{ width: `${aggrPct}%` }} />
        <div className="h-full rounded-sm bg-[#888]" style={{ width: `${Math.round(weights.defensive * 100)}%` }} />
        <div className="h-full rounded-sm bg-[#fbbf24]" style={{ width: `${cashPct}%` }} />
      </div>
    </div>
  )
}

// ─── 메인 페이지 ─────────────────────────────────────────────────────────────

export default function SettingsPage() {
  const [config, setConfig] = useState<Config | null>(null)
  const [original, setOriginal] = useState<Config | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saveStatus, setSaveStatus] = useState<'idle' | 'ok' | 'error'>('idle')

  const fetchConfig = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/config')
      const data: Config = await res.json()
      setConfig(structuredClone(data))
      setOriginal(structuredClone(data))
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchConfig() }, [fetchConfig])

  const handleSave = async () => {
    if (!config || !original) return
    setSaving(true)
    setSaveStatus('idle')

    // 변경된 값만 추출
    const updates: Record<string, unknown> = {}

    const riskNew = config.risk_management.max_stock_weight_pct
    if (riskNew !== original.risk_management.max_stock_weight_pct) {
      updates['risk_management.max_stock_weight_pct'] = riskNew
    }

    const rrNew = config.recommendation_rules
    const rrOld = original.recommendation_rules
    if (rrNew.max_stocks !== rrOld.max_stocks)
      updates['recommendation_rules.max_stocks'] = rrNew.max_stocks
    if (rrNew.min_confidence !== rrOld.min_confidence)
      updates['recommendation_rules.min_confidence'] = rrNew.min_confidence
    if (rrNew.futures_threshold_pct !== rrOld.futures_threshold_pct)
      updates['recommendation_rules.futures_threshold_pct'] = rrNew.futures_threshold_pct

    for (const phase of Object.keys(config.phase_weights)) {
      const newCash = config.phase_weights[phase].cash
      if (newCash !== original.phase_weights[phase].cash) {
        updates[`phase_weights.${phase}.cash`] = newCash
      }
    }

    if (Object.keys(updates).length === 0) {
      setSaving(false)
      return
    }

    try {
      const res = await fetch('/api/config', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      })
      if (res.ok) {
        const { config: saved } = await res.json()
        setConfig(structuredClone(saved))
        setOriginal(structuredClone(saved))
        setSaveStatus('ok')
        setTimeout(() => setSaveStatus('idle'), 2500)
      } else {
        setSaveStatus('error')
      }
    } catch {
      setSaveStatus('error')
    } finally {
      setSaving(false)
    }
  }

  const handleReset = () => {
    if (original) setConfig(structuredClone(original))
    setSaveStatus('idle')
  }

  if (loading || !config) {
    return (
      <div className="space-y-4 animate-pulse">
        <div className="h-8 w-48 bg-[#1e1e2a] rounded" />
        <div className="h-64 bg-[#1e1e2a] rounded-xl" />
        <div className="h-64 bg-[#1e1e2a] rounded-xl" />
      </div>
    )
  }

  const isDirty = JSON.stringify(config) !== JSON.stringify(original)

  return (
    <div className="space-y-6 animate-slide-in max-w-2xl">
      {/* 헤더 */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-[#f0f0f8]">설정</h1>
          <p className="text-xs text-[#555570] mt-0.5">매매 전략 파라미터 조정</p>
        </div>
        <div className="flex items-center gap-2">
          {isDirty && (
            <button
              onClick={handleReset}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md text-[#8888a8] hover:text-[#f0f0f8] hover:bg-[#1e1e2a] transition-colors"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              되돌리기
            </button>
          )}
          <button
            onClick={handleSave}
            disabled={saving || !isDirty}
            className="flex items-center gap-1.5 text-sm px-4 py-1.5 rounded-md font-medium transition-colors disabled:opacity-40
              bg-[#7c6af7] hover:bg-[#6a58e0] text-white disabled:cursor-not-allowed"
          >
            <Save className="w-3.5 h-3.5" />
            {saving ? '저장 중...' : saveStatus === 'ok' ? '저장됨 ✓' : '저장'}
          </button>
        </div>
      </div>

      {saveStatus === 'error' && (
        <p className="text-xs text-[#f87171] bg-[#f87171]/10 px-3 py-2 rounded-md">
          저장 실패 — 파일 접근 권한을 확인하세요.
        </p>
      )}

      {/* 리스크 관리 */}
      <Card>
        <CardHeader title="리스크 관리" action={<Settings2 className="w-4 h-4 text-[#555570]" />} />
        <SliderRow
          label="단일 종목 최대 비중"
          description="한 종목에 투자할 수 있는 최대 금액 (총자산 대비 %)"
          value={Math.round(config.risk_management.max_stock_weight_pct * 100)}
          min={5}
          max={50}
          step={5}
          display={`${Math.round(config.risk_management.max_stock_weight_pct * 100)}%`}
          onChange={(v) =>
            setConfig((c) => c && { ...c, risk_management: { ...c.risk_management, max_stock_weight_pct: v / 100 } })
          }
        />
      </Card>

      {/* 매수 규칙 */}
      <Card>
        <CardHeader title="매수 규칙" />
        <SliderRow
          label="최대 동시 보유 종목 수"
          description="한 번에 보유할 수 있는 최대 종목 수"
          value={config.recommendation_rules.max_stocks}
          min={1}
          max={10}
          step={1}
          display={`${config.recommendation_rules.max_stocks}종목`}
          onChange={(v) =>
            setConfig((c) => c && { ...c, recommendation_rules: { ...c.recommendation_rules, max_stocks: v } })
          }
        />
        <SliderRow
          label="최소 신호 신뢰도"
          description="이 값 미만의 신뢰도를 가진 매수 신호는 무시"
          value={Math.round(config.recommendation_rules.min_confidence * 100)}
          min={10}
          max={90}
          step={5}
          display={`${Math.round(config.recommendation_rules.min_confidence * 100)}%`}
          onChange={(v) =>
            setConfig((c) => c && { ...c, recommendation_rules: { ...c.recommendation_rules, min_confidence: v / 100 } })
          }
        />
        <SliderRow
          label="선물 임계값"
          description="선물 방향 신호로 인정하는 최소 변동률"
          value={config.recommendation_rules.futures_threshold_pct}
          min={0.1}
          max={1.0}
          step={0.1}
          display={`${config.recommendation_rules.futures_threshold_pct.toFixed(1)}%`}
          onChange={(v) =>
            setConfig((c) => c && { ...c, recommendation_rules: { ...c.recommendation_rules, futures_threshold_pct: v } })
          }
        />
      </Card>

      {/* 국면별 현금 비중 */}
      <Card>
        <CardHeader title="국면별 현금 비중" />
        <p className="text-xs text-[#555570] mb-4">
          슬라이더로 현금 비중을 조정하면 공격 비중이 자동으로 재계산됩니다.
        </p>
        {Object.keys(PHASE_LABELS).map((phase) => (
          <PhaseWeightRow
            key={phase}
            phase={phase}
            weights={config.phase_weights[phase]}
            onCashChange={(v) =>
              setConfig((c) => {
                if (!c) return c
                const pw = { ...c.phase_weights[phase] }
                pw.cash = v
                pw.aggressive = Math.max(0, Math.round((1 - v - pw.defensive) * 100) / 100)
                return { ...c, phase_weights: { ...c.phase_weights, [phase]: pw } }
              })
            }
          />
        ))}
      </Card>
    </div>
  )
}
