/**
 * 문서(또는 연월 정보가 있는 객체)에서 유효한 데이터 연/월을 계산한다.
 * - 우선 data_year/data_month 사용
 * - 없거나 잘못된 값이면 created_at 또는 upload_date 기준으로 보정
 * - 그래도 없으면 현재 날짜 기준
 */
export function getDocumentYearMonth(doc: {
  data_year?: number
  data_month?: number
  created_at?: string
  upload_date?: string
}): { year: number; month: number } {
  let { data_year, data_month } = doc

  const isValidYear = (y?: number) => typeof y === 'number' && y > 0
  const isValidMonth = (m?: number) => typeof m === 'number' && m >= 1 && m <= 12

  if (!isValidYear(data_year) || !isValidMonth(data_month)) {
    const now = new Date()
    const dateString = doc.created_at || doc.upload_date
    let baseDate = now

    if (dateString) {
      const d = new Date(dateString)
      if (!isNaN(d.getTime())) {
        baseDate = d
      }
    }

    if (!isValidYear(data_year)) {
      data_year = baseDate.getFullYear()
    }
    if (!isValidMonth(data_month)) {
      data_month = baseDate.getMonth() + 1
    }
  }

  return {
    year: data_year as number,
    month: data_month as number,
  }
}

/**
 * 업로드 문서용 날짜 라벨 (리스트 표시용)
 * - data_year/data_month가 있으면 "YYYY年MM月"
 * - 없으면 created_at 기준으로 "YYYY年MM月DD日"
 * - 둘 다 없으면 "—"
 */
export function formatDocumentDateLabel(doc: {
  data_year?: number
  data_month?: number
  created_at?: string
}): string {
  if (doc.data_year && doc.data_month) {
    return `${doc.data_year}年${String(doc.data_month).padStart(2, '0')}月`
  }

  if (doc.created_at) {
    const d = new Date(doc.created_at)
    if (!isNaN(d.getTime())) {
      return `${d.getFullYear()}年${String(d.getMonth() + 1).padStart(2, '0')}月${String(
        d.getDate(),
      ).padStart(2, '0')}日`
    }
  }

  return '—'
}

