/**
 * ItemsGridRdg 관련 타입·상수
 */

/** 조건금액 컬럼 후보 (양식지별로 単価|条件|対象数量又は金額 중 하나 사용) */
export const CONDITION_AMOUNT_KEYS = ['条件', '対象数量又は金額'] as const

export interface ItemsGridRdgProps {
  pdfFilename: string
  pageNumber: number
  formType: string | null
  /** 현재 페이지 1次/2次 전부 체크·일부 체크 상태 변경 시 호출 (체크박스 표시용) */
  onBulkCheckStateChange?: (state: BulkCheckState) => void
}

export interface ItemsGridRdgHandle {
  save: () => void
  checkAllFirst: () => Promise<void>
  checkAllSecond: () => Promise<void>
  uncheckAllFirst: () => Promise<void>
  uncheckAllSecond: () => Promise<void>
}

export interface BulkCheckState {
  allFirstChecked: boolean
  allSecondChecked: boolean
  someFirstChecked: boolean
  someSecondChecked: boolean
}

export interface GridRow {
  item_id: number
  item_order: number
  first_review_checked: boolean
  second_review_checked: boolean
  first_review_reviewed_at?: string | null
  first_review_reviewed_by?: string | null
  second_review_reviewed_at?: string | null
  second_review_reviewed_by?: string | null
  [key: string]: string | number | boolean | null | undefined
}
