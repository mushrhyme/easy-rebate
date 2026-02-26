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

/** 셀 값 → 숫자. NET/本部長 비교용. 전각 마침표(．)·중간점(·)은 소수점으로, 콤마는 제거 후 파싱 */
export function parseCellNum(v: unknown): number | null {
  if (v == null) return null
  if (typeof v === 'number' && !Number.isNaN(v)) return v
  let s = String(v).trim()
  if (!s) return null
  // 소수점 문자 정규화: ．(U+FF0E), ·(U+00B7) → .
  s = s.replace(/[\uFF0E\u00B7]/g, '.')
  // 콤마가 소수점인 경우(예: "39,2"): 콤마 하나이고 뒤가 1~3자리 숫자면 소수점으로 처리
  if (!/\./.test(s) && /^\d+,\d{1,3}$/.test(s)) {
    s = s.replace(',', '.')
  }
  // 천단위 콤마 제거
  s = s.replace(/,/g, '')
  let n = Number(s)
  if (!Number.isNaN(n)) return n
  // OCR 공백: "39 2" → 39.2 시도 후 공백 제거 시도
  const withDot = s.replace(/\s+/g, '.')
  n = Number(withDot)
  if (!Number.isNaN(n)) return n
  n = Number(s.replace(/\s+/g, ''))
  return Number.isNaN(n) ? null : n
}
