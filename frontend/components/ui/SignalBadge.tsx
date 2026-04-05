'use client'

import type { SignalSource, SignalConfidence } from '@/lib/types'

interface SignalBadgeProps {
  source: SignalSource | null
  confidence: SignalConfidence | null
  trigger?: string | null
  size?: 'sm' | 'md'
}

const CONFIDENCE_STYLES: Record<string, { bg: string; text: string; border: string }> = {
  '★★★': { bg: '#052e16', text: '#4ade80', border: '#166534' },
  '★★':  { bg: '#422006', text: '#fbbf24', border: '#854d0e' },
  '★':   { bg: '#1e1e2a', text: '#555570', border: '#2a2a38' },
}

const FALLBACK_STYLE = { bg: '#1e1e2a', text: '#555570', border: '#2a2a38' }

export function SignalBadge({ source, confidence, trigger, size = 'sm' }: SignalBadgeProps) {
  if (!source) return null

  const isFallback = source === 'sector_fallback'
  const style = isFallback
    ? FALLBACK_STYLE
    : CONFIDENCE_STYLES[confidence ?? ''] ?? FALLBACK_STYLE

  const label = isFallback
    ? '섹터'
    : confidence ?? '?'

  const fontSize = size === 'sm' ? '10px' : '11px'
  const padding = size === 'sm' ? '1px 5px' : '2px 7px'

  return (
    <span
      title={trigger ? `트리거: ${trigger}` : undefined}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '2px',
        fontSize,
        padding,
        borderRadius: '4px',
        border: `1px solid ${style.border}`,
        backgroundColor: style.bg,
        color: style.text,
        whiteSpace: 'nowrap',
        lineHeight: 1.4,
      }}
    >
      {label}
    </span>
  )
}
