import { NextResponse } from 'next/server'
import { createClient } from '@supabase/supabase-js'

export const dynamic = 'force-dynamic'

export async function GET() {
  const supabase = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  )

  const { data, error } = await supabase
    .from('positions')
    .select('*')
    .order('entry_time', { ascending: false })
    .limit(10)

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 })
  }

  const fieldTypes = data?.map((row: Record<string, unknown>) => {
    const types: Record<string, string> = {}
    for (const [key, val] of Object.entries(row)) {
      types[key] = val === null ? 'null' : typeof val === 'object' ? `object:${JSON.stringify(val).slice(0, 80)}` : typeof val
    }
    return { id: row.id, name: row.name, code: row.code, status: row.status, fieldTypes: types }
  })

  return NextResponse.json({ count: data?.length, fieldTypes, rawData: data })
}
