/**
 * API 타입 정의
 */

export interface Document {
  pdf_filename: string
  total_pages: number
  form_type: string | null
  status: string
  created_at?: string  // 업로드 날짜 (ISO 형식)
  upload_date?: string  // 호환성을 위한 별칭
  data_year?: number  // 문서 데이터 연도 (請求年月에서 추출)
  data_month?: number  // 문서 데이터 월 (請求年月에서 추출)
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
  customer: string | null
  product_name: string | null
  item_data: Record<string, any>
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

export type FormType = '01' | '02' | '03' | '04' | '05'

export interface FormConfig {
  name: string
  color: string
  imagePath: string
}

// ReviewStatus 타입 정의 (WebSocket 메시지용)
export interface ReviewStatus {
  first_review?: { checked: boolean }
  second_review?: { checked: boolean }
}
