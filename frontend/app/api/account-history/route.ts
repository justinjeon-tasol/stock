import { createClient } from '@supabase/supabase-js'
import { NextResponse } from 'next/server'

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
)

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const days = parseInt(searchParams.get('days') ?? '30')
  const date = searchParams.get('date')

  if (date) {
    // 특정 날짜 상세
    const [histRes, tradesRes] = await Promise.all([
      supabase.from('account_history').select('*').eq('recorded_date', date).limit(1),
      supabase.from('trades')
        .select('*')
        .gte('created_at', `${date}T00:00:00+00:00`)
        .lte('created_at', `${date}T23:59:59+00:00`)
        .order('created_at'),
    ])
    return NextResponse.json({
      history: histRes.data?.[0] ?? null,
      trades: tradesRes.data ?? [],
    })
  }

  // 목록
  const start = new Date()
  start.setDate(start.getDate() - days)
  const { data, error } = await supabase
    .from('account_history')
    .select('*')
    .gte('recorded_date', start.toISOString().split('T')[0])
    .order('recorded_date', { ascending: false })

  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  return NextResponse.json(data ?? [])
}
