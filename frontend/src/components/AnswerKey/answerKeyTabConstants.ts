/**
 * 정답지 탭 공통: 타입, 상수, 유틸
 */
export interface GridRow {
  item_id: number
  page_number: number
  item_order: number
  version: number
  [key: string]: string | number | boolean | null | undefined
}

export const SYSTEM_ROW_KEYS = ['item_id', 'page_number', 'item_order', 'version']
export const HIDDEN_ROW_KEYS = new Set([...SYSTEM_ROW_KEYS, '_displayIndex'])

/** 解答作成タブで非表示（検討タブ frozen 由来・임베딩 불필요） */
export const ANSWER_KEY_HIDDEN_KEYS = new Set([
  '小売先コード', '小売先CD', '受注先コード', '受注先CD', '商品コード', '商品CD',
  'frozen_retail_code', 'frozen_dist_code', 'frozen_product_code',
])

export const KEY_LABELS: Record<string, string> = {
  page_number: 'p',
  item_order: '順番',
  得意先: '得意先',
  '商品名': '商品名',
  item_id: 'item_id',
  version: 'version',
}

export const TYPE_OPTIONS_BASE = [
  { value: '', label: '—' },
  { value: '条件', label: '条件' },
  { value: '販促費8%', label: '販促費8%' },
  { value: '販促費10%', label: '販促費10%' },
  { value: 'CF8%', label: 'CF8%' },
  { value: 'CF10%', label: 'CF10%' },
  { value: '非課税', label: '非課税' },
  { value: '消費税', label: '消費税' },
  { value: 'ロットアウト', label: 'ロットアウト' },
]

export interface InitialDocumentForAnswerKey {
  pdf_filename: string
  total_pages: number
  /** 検索タブで「解答作成」押下時の表示ページ → ブリッジではこの1ページのみ表示 */
  initialPage?: number
}

export interface AnswerKeyTabProps {
  initialDocument?: InitialDocumentForAnswerKey | null
  onConsumeInitialDocument?: () => void
  /** 検討タブに復帰 시 현재 편집 중인 문서·페이지 정보 전달 → 검토 탭에서 해당 문서·양식지·페이지로 복귀 */
  onRevokeSuccess?: (doc: { pdf_filename: string; form_type: string | null; initialPage?: number }) => void
}

export const CUSTOMER_KEYS = ['得意先名', '得意先様', '得意先', '取引先']
export const PRODUCT_NAME_KEYS = ['商品名']
export const PAGE_META_DELETE_SENTINEL = '__DELETE__'

export function pickFromGen(gen: Record<string, unknown>, keys: string[]): string | null {
  for (const k of keys) {
    const v = gen[k]
    if (v != null && typeof v === 'string' && v.trim() !== '') return v.trim()
  }
  return null
}
