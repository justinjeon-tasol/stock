// 원 단위 → 억원 표시
export function formatAmount(won: number): string {
  const eok = won / 1e8
  return `${eok >= 0 ? '+' : ''}${eok.toFixed(0)}억원`
}

// 퍼센트 표시
export function formatPct(pct: number): string {
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`
}

// 날짜 포맷 (YYYY-MM-DD HH:mm) — KST(UTC+9) 기준
export function formatDateTime(isoString: string): string {
  if (!isoString) return '-'
  // Supabase에서 timezone 없이 저장된 경우 UTC로 간주
  const normalized = isoString.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(isoString)
    ? isoString
    : isoString + 'Z'
  const d = new Date(normalized)
  const kst = new Date(d.getTime() + 9 * 60 * 60 * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${kst.getUTCFullYear()}-${pad(kst.getUTCMonth() + 1)}-${pad(kst.getUTCDate())} ${pad(kst.getUTCHours())}:${pad(kst.getUTCMinutes())}`
}

// 날짜만 (YYYY-MM-DD)
export function formatDate(isoString: string): string {
  return new Date(isoString).toLocaleDateString('ko-KR', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
}

// 가격 포맷 (천 단위 콤마)
export function formatPrice(price: number): string {
  return price.toLocaleString('ko-KR') + '원'
}

// 경과 시간 (N초 전 / N분 전 / N시간 전)
export function formatTimeAgo(isoString: string): string {
  const now = Date.now()
  const then = new Date(isoString).getTime()
  const diffSec = Math.floor((now - then) / 1000)

  if (diffSec < 60) return `${diffSec}초 전`
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}분 전`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}시간 전`
  return `${Math.floor(diffSec / 86400)}일 전`
}
