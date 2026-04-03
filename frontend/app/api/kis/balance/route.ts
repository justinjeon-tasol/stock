import { NextResponse } from 'next/server'
import { fetchBalance } from '@/lib/kis-client'

export const dynamic = 'force-dynamic'

export async function GET() {
  try {
    const result = await fetchBalance()
    return NextResponse.json(result)
  } catch (err) {
    const message = err instanceof Error ? err.message : 'KIS balance fetch failed'
    return NextResponse.json({ error: message }, { status: 502 })
  }
}
