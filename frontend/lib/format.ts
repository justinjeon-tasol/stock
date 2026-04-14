// 원 단위 → 억원 표시
export function formatAmount(won: number): string {
  const eok = won / 1e8
  return `${eok >= 0 ? '+' : ''}${eok.toFixed(0)}억원`
}

// 퍼센트 표시
export function formatPct(pct: number): string {
  const n = Number(pct)
  if (isNaN(n)) return '-'
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`
}

// 날짜 포맷 (YYYY-MM-DD HH:mm) — KST(UTC+9) 기준
export function formatDateTime(isoString: string | Date | null | undefined): string {
  if (!isoString) return '-'
  // Date 객체 또는 비문자열 처리 (Supabase realtime에서 Date 전달 가능)
  if (typeof isoString !== 'string') {
    const d = isoString instanceof Date ? isoString : new Date(String(isoString))
    if (isNaN(d.getTime())) return '-'
    const kst = new Date(d.getTime() + 9 * 60 * 60 * 1000)
    const pad = (n: number) => String(n).padStart(2, '0')
    return `${kst.getUTCFullYear()}-${pad(kst.getUTCMonth() + 1)}-${pad(kst.getUTCDate())} ${pad(kst.getUTCHours())}:${pad(kst.getUTCMinutes())}`
  }
  // Supabase에서 timezone 없이 저장된 경우 UTC로 간주
  const normalized = isoString.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(isoString)
    ? isoString
    : isoString + 'Z'
  const d = new Date(normalized)
  if (isNaN(d.getTime())) return '-'
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
  const n = Number(price)
  if (isNaN(n)) return '-'
  return n.toLocaleString('ko-KR') + '원'
}

// 원 단위 → 만원/억원 (상세 표시)
export function formatKRW(won: number): string {
  const abs = Math.abs(won)
  const sign = won < 0 ? '-' : ''
  if (abs >= 1e8) {
    const eok = abs / 1e8
    return `${sign}${eok.toFixed(eok >= 10 ? 0 : 1)}억원`
  }
  if (abs >= 1e4) {
    const man = abs / 1e4
    return `${sign}${man.toFixed(man >= 100 ? 0 : 1)}만원`
  }
  return `${sign}${abs.toLocaleString('ko-KR')}원`
}

// 주문 상태 표시
export function formatOrderStatus(status: string): string {
  const map: Record<string, string> = {
    '체결': '체결완료',
    '미체결': '미체결',
    '취소': '취소됨',
    '정정': '정정됨',
  }
  return map[status] || status
}

// 경과 시간 (N초 전 / N분 전 / N시간 전)
export function formatTimeAgo(isoString: string | Date | null | undefined): string {
  if (!isoString) return '-'
  const now = Date.now()
  const then = isoString instanceof Date ? isoString.getTime() : new Date(String(isoString)).getTime()
  if (isNaN(then)) return '-'
  const diffSec = Math.floor((now - then) / 1000)

  if (diffSec < 60) return `${diffSec}초 전`
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}분 전`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}시간 전`
  return `${Math.floor(diffSec / 86400)}일 전`
}
