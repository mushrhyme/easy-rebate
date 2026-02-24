/**
 * 그리드용 유틸: 날짜 포맷, 숫자 파싱
 */

/** 증빙 툴팁용: ISO 일시 → 짧은 표시 (예: 2025-02-22 14:30) */
export function formatReviewDate(iso: string | null | undefined): string {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    const y = d.getFullYear()
    const m = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    const h = String(d.getHours()).padStart(2, '0')
    const min = String(d.getMinutes()).padStart(2, '0')
    return `${y}-${m}-${day} ${h}:${min}`
  } catch {
    return iso
  }
}

/** 셀 값 → 숫자 (콤마 제거). NET/本部長 비교용 */
export function parseCellNum(v: unknown): number | null {
  if (v == null) return null
  if (typeof v === 'number' && !Number.isNaN(v)) return v
  const s = String(v).replace(/,/g, '').trim()
  if (!s) return null
  const n = Number(s)
  return Number.isNaN(n) ? null : n
}
