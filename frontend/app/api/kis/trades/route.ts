import { NextResponse } from 'next/server'
import { fetchTradeHistory } from '@/lib/kis-client'

export const dynamic = 'force-dynamic'

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  // 기본: 오늘부터 7일 전
  const now = new Date()
  const defaultEnd = now.toISOString().slice(0, 10).replace(/-/g, '')
  const weekAgo = new Date(now.getTime() - 7 * 86400000)
  const defaultStart = weekAgo.toISOString().slice(0, 10).replace(/-/g, '')

  const startDate = searchParams.get('startDate') || defaultStart
  const endDate = searchParams.get('endDate') || defaultEnd

  try {
    const { trades, hasMore } = await fetchTradeHistory(startDate, endDate)
    return NextResponse.json({ trades, hasMore, fetchedAt: new Date().toISOString() })
  } catch (err) {
    const message = err instanceof Error ? err.message : 'KIS trades fetch failed'
    return NextResponse.json({ error: message }, { status: 502 })
  }
}
