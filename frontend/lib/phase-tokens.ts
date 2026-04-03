import type { MarketPhaseType } from './types'

export interface PhaseToken {
  bg: string
  text: string
  border: string
  glow: string
  label: string
  emoji: string
}

export const PHASE_TOKENS: Record<MarketPhaseType, PhaseToken> = {
  대상승장: {
    bg: '#064e3b',
    text: '#34d399',
    border: '#059669',
    glow: '#10b98140',
    label: '대상승장',
    emoji: '🚀',
  },
  상승장: {
    bg: '#14532d',
    text: '#4ade80',
    border: '#16a34a',
    glow: '#22c55e40',
    label: '상승장',
    emoji: '📈',
  },
  일반장: {
    bg: '#1e3a5f',
    text: '#60a5fa',
    border: '#2563eb',
    glow: '#3b82f640',
    label: '일반장',
    emoji: '📊',
  },
  변동폭큰: {
    bg: '#713f12',
    text: '#fbbf24',
    border: '#d97706',
    glow: '#f59e0b40',
    label: '변동폭 큰',
    emoji: '⚡',
  },
  하락장: {
    bg: '#7c2d12',
    text: '#fb923c',
    border: '#ea580c',
    glow: '#f9731640',
    label: '하락장',
    emoji: '📉',
  },
  대폭락장: {
    bg: '#7f1d1d',
    text: '#f87171',
    border: '#dc2626',
    glow: '#ef444440',
    label: '대폭락장',
    emoji: '🔴',
  },
}

export function getPhaseToken(phase: MarketPhaseType | null | undefined): PhaseToken {
  if (!phase) return PHASE_TOKENS['일반장']
  return PHASE_TOKENS[phase] ?? PHASE_TOKENS['일반장']
}
