import { NextResponse } from 'next/server'
import { createClient } from '@supabase/supabase-js'

export const dynamic = 'force-dynamic'

export async function GET() {
  try {
    const url = process.env.NEXT_PUBLIC_SUPABASE_URL
    const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
    if (!url || !key) {
      return NextResponse.json({})
    }

    const supabase = createClient(url, key)

    // 최근 market_snapshots에서 칼만 신호 조회
    const { data } = await supabase
      .from('market_snapshots')
      .select('data')
      .order('created_at', { ascending: false })
      .limit(1)
      .single()

    if (!data?.data) {
      return NextResponse.json({})
    }

    // market_snapshots.data에 kalman_signals가 포함되어 있으면 사용
    const kalman = data.data.kalman_signals || {}
    const trends: Record<string, string> = {}
    for (const [code, sig] of Object.entries(kalman)) {
      const s = sig as { trend?: string }
      if (s.trend) trends[code] = s.trend
    }

    return NextResponse.json(trends)
  } catch {
    return NextResponse.json({})
  }
}
