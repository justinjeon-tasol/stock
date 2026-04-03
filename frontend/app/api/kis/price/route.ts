import { NextResponse } from 'next/server'
import { fetchPrice } from '@/lib/kis-client'

export const dynamic = 'force-dynamic'

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const code = searchParams.get('code')

  if (!code) {
    return NextResponse.json({ error: 'code parameter required' }, { status: 400 })
  }

  try {
    const result = await fetchPrice(code)
    return NextResponse.json(result)
  } catch (err) {
    const message = err instanceof Error ? err.message : 'KIS price fetch failed'
    return NextResponse.json({ error: message }, { status: 502 })
  }
}
