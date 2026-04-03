// 간단한 className 병합 유틸 (clsx 대체)
export function cn(...classes: (string | undefined | null | false)[]): string {
  return classes.filter(Boolean).join(' ')
}
