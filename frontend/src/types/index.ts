/**
 * API 타입 정의
 */

export interface Document {
  pdf_filename: string
  total_pages: number
  form_type: string | null
  upload_channel: string | null
  status: string
  created_at?: string  // 업로드 날짜 (ISO 형식)
  upload_date?: string  // 호환성을 위한 별칭
  data_year?: number  // 문서 데이터 연도 (請求年月에서 추출)
  data_month?: number  // 문서 데이터 월 (請求年月에서 추출)
  is_answer_key_document?: boolean  // 정답지 생성 대상 여부 (true면 검토 탭에서 제외)
}

export interface DocumentListResponse {
  documents: Document[]
  total: number
}

export interface Item {
  item_id: number
  pdf_filename: string
  page_number: number
  item_order: number
  item_data: Record<string, any>  // 공식 키는 일본어(예: 請求番号, 得意先, 備考, 税額, 商品名 등)
  review_status: {
    first_review: { checked: boolean }
    second_review: { checked: boolean }
  }
  version: number
}

export interface ItemUpdateRequest {
  item_data: Record<string, any>
  review_status?: {
    first_review?: { checked: boolean }
    second_review?: { checked: boolean }
  }
  expected_version: number
  session_id: string
}

export interface UploadResponse {
  message: string
  results: Array<{
    filename: string
    status: 'pending' | 'exists' | 'error'
    pdf_name?: string
    pages?: number
    error?: string
  }>
  session_id: string
}

export interface SearchResult {
  query: string
  total_items: number
  total_pages: number
  pages: Array<{
    pdf_filename: string
    page_number: number
    items: Item[]
    form_type: string | null
  }>
}

export interface PageImageResponse {
  image_url: string // static file URL
  format: string
  page_role?: string // 'cover', 'detail', 'summary', 'reply' 등
}

export interface WebSocketMessage {
  type: 'connected' | 'start' | 'progress' | 'complete' | 'error' | 'ping' | 'pong'
  task_id?: string
  file_name?: string
  current_page?: number
  total_pages?: number
  message?: string
  progress?: number
  pages?: number
  elapsed_time?: number
  error?: string
}

/** 양식지 코드 (DB에서 동적 조회, 01, 02, 07 등) */
export type FormType = string

export type UploadChannel = 'finet' | 'mail'

export interface FormConfig {
  name: string
  color: string
  imagePath: string
}

export interface UploadChannelConfig {
  name: string
  label: string
  color: string
  imagePath: string
}

// ReviewStatus 타입 정의 (WebSocket 메시지용)
export interface ReviewStatus {
  first_review?: { checked: boolean }
  second_review?: { checked: boolean }
}

/** SAP 산식 설정: 양식지별 데이터 입력 (DB에서 동적, 01, 02, 07 등) */
export type FormTypeKey = string

/** 데이터 입력 규칙 (백엔드 해석용) */
export type DataInputRule =
  | { field: string }
  | { field_digits: string }
  | { cond: Array<{ if_field: string; if_eq: string; then_field?: string; then_expr?: string }> }
  | { expr: string }

/** byForm 값: 설명 문자열 또는 { description, rule } (rule은 백엔드 실행용) */
export type ByFormValue = string | { description?: string; rule?: DataInputRule }

export interface SapDataInputColumn {
  column: string
  byForm: Record<string, ByFormValue>
}

export interface SapExcelFormulaColumn {
  column: string
  formula: string
  description?: string
}

export interface SapFormulasConfig {
  dataInputColumns: SapDataInputColumn[]
  excelFormulaColumns: SapExcelFormulaColumn[]
}
