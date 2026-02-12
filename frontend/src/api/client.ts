/**
 * APIクライアント
 */
import axios from 'axios'
import type {
  DocumentListResponse,
  Item,
  ItemUpdateRequest,
  SearchResult,
  PageImageResponse,
  UploadResponse,
} from '@/types'
import { getApiBaseUrl } from '@/utils/apiConfig'

const API_BASE_URL = getApiBaseUrl()

console.log('🔵 [API Client] 初期化 - baseURL:', API_BASE_URL)

const client = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

// リクエストインターセプター: セッションヘッダー追加およびログ
client.interceptors.request.use(
  (config) => {
    // FormData인 경우 Content-Type 헤더 제거 (axios가 자동으로 multipart/form-data 설정)
    if (config.data instanceof FormData) {
      if (config.headers) {
        if ('delete' in config.headers && typeof config.headers.delete === 'function') {
          // AxiosHeaders 인스턴스
          config.headers.delete('Content-Type')
        } else if (typeof config.headers === 'object') {
          // 일반 객체
          delete (config.headers as Record<string, string>)['Content-Type']
        }
      }
    }
    
    // セッションIDをヘッダーに追加
    const sessionId = localStorage.getItem('sessionId')
    if (sessionId) {
      // headers를 안전하게 설정
      if (!config.headers) {
        config.headers = {} as any
      }
      // AxiosHeaders 또는 일반 객체 모두 처리
      if (config.headers && typeof config.headers === 'object') {
        if ('set' in config.headers && typeof config.headers.set === 'function') {
          // AxiosHeaders 인스턴스
          config.headers.set('X-Session-ID', sessionId)
        } else {
          // 일반 객체
          (config.headers as Record<string, string>)['X-Session-ID'] = sessionId
        }
      }
    }

    console.log('🔵 [API Request]', config.method?.toUpperCase(), config.baseURL + config.url, {
      params: config.params,
      hasSessionId: !!sessionId,
      isFormData: config.data instanceof FormData,
    })
    return config
  },
  (error) => {
    console.error('❌ [API Request Error]', error)
    return Promise.reject(error)
  }
)

// レスポンスインターセプター: エラーログ
client.interceptors.response.use(
  (response) => {
    console.log('✅ [API Response]', response.config.method?.toUpperCase(), response.config.url, response.status)
    return response
  },
  (error) => {
    const errorInfo = {
      url: error.config?.url,
      method: error.config?.method,
      status: error.response?.status,
      statusText: error.response?.statusText,
      data: error.response?.data,
      message: error.message,
      code: error.code,
    }
    console.error('❌ [API Response Error]', errorInfo)
    
    // 세션 만료 에러 처리
    const errorDetail = error.response?.data?.detail || error.response?.data?.message || ''
    if (
      error.response?.status === 401 ||
      (error.response?.status === 409 && typeof errorDetail === 'string' && 
       (errorDetail.includes('Session expired') || errorDetail.includes('세션') || errorDetail.includes('Session expired or invalid')))
    ) {
      console.warn('⚠️ [세션 에러] 세션이 유효하지 않습니다. localStorage에서 세션 제거:', {
        status: error.response?.status,
        detail: errorDetail,
        url: error.config?.url
      })
      localStorage.removeItem('sessionId')
    }
    
    // 500 에러인 경우 상세 정보 출력
    if (error.response?.status === 500) {
      console.error('❌ [500 Error Detail]', {
        detail: error.response?.data?.detail,
        fullData: error.response?.data,
      })
    }
    return Promise.reject(error)
  }
)

// 様式(form_type) 목록 API (DB에서 동적 조회)
export const formTypesApi = {
  getList: async (): Promise<{ form_types: Array<{ value: string; label: string }> }> => {
    const response = await client.get('/api/form-types')
    return response.data
  },

  /** 様式コードの表示名を更新（基準管理） */
  updateLabel: async (formCode: string, displayName: string): Promise<{ form_code: string; display_name: string; message: string }> => {
    const response = await client.patch(`/api/form-types/${encodeURIComponent(formCode)}/label`, {
      display_name: displayName,
    })
    return response.data
  },

  /**
   * 新規様式作成。
   * display_name のみ渡すと次のコードを自動採番（01,02...の次）。form_code を渡すとそのコードで作成。
   */
  create: async (params: {
    form_code?: string
    display_name?: string
  }): Promise<{ form_code: string; display_name: string; message: string }> => {
    const response = await client.post('/api/form-types', params)
    return response.data
  },

  /** 양식지 미리보기 이미지 저장 (문서 1페이지 이미지를 form_XX.png로 저장) */
  savePreviewImage: async (formCode: string, pdfFilename: string): Promise<{ form_code: string; preview_path: string }> => {
    const response = await client.post(`/api/form-types/${encodeURIComponent(formCode)}/preview-image`, {
      pdf_filename: pdfFilename,
    })
    return response.data
  },
}

// 文書API
export const documentsApi = {
  /**
   * 文書アップロード (upload_channel: finet | mail)
   */
  upload: async (
    uploadChannel: string,
    files: File[],
    year?: number,
    month?: number
  ): Promise<UploadResponse> => {
    const formData = new FormData()
    formData.append('upload_channel', uploadChannel)
    // year와 month가 유효한 숫자일 때만 FormData에 추가
    // undefined, null, NaN, 0 이 아닌 유효한 숫자만 전송
    if (year !== undefined && year !== null && !isNaN(year) && year > 0) {
      formData.append('year', year.toString())
    }
    if (month !== undefined && month !== null && !isNaN(month) && month > 0 && month <= 12) {
      formData.append('month', month.toString())
    }
    files.forEach((file) => {
      formData.append('files', file)
    })

    // 세션 ID를 localStorage에서 직접 가져와서 헤더에 명시적으로 추가
    const sessionId = localStorage.getItem('sessionId')
    const headers: Record<string, string> = {}
    if (sessionId) {
      headers['X-Session-ID'] = sessionId
      console.log('🔵 [업로드] 세션 ID 헤더 추가:', sessionId.substring(0, 20) + '...')
    } else {
      console.warn('⚠️ [업로드] 세션 ID가 없습니다! localStorage에서 확인 필요')
    }

    // FormData를 보낼 때는 Content-Type을 명시하지 않음
    // axios가 자동으로 multipart/form-data와 boundary를 설정함
    // 기본 헤더의 Content-Type: application/json을 제거해야 함
    console.log('🔵 [업로드] 요청 전송:', { 
      uploadChannel, 
      fileCount: files.length, 
      year, 
      month, 
      hasSessionId: !!sessionId 
    })
    console.log('🔵 [업로드] FormData 내용:', {
      upload_channel: uploadChannel,
      year: year?.toString(),
      month: month?.toString(),
      files: files.map(f => f.name)
    })
    const response = await client.post<UploadResponse>(
      '/api/documents/upload',
      formData,
      {
        headers, // 인터셉터에서 FormData 감지 시 Content-Type 자동 제거
      }
    )
    console.log('✅ [업로드] 응답 수신:', response.status)
    return response.data
  },

  /**
   * 文書アップロード（座標付き解析・mailチャネルでUpstage単語座標＋LLM _word_indices→_bbox付与）
   */
  uploadWithBbox: async (
    uploadChannel: string,
    files: File[],
    year?: number,
    month?: number
  ): Promise<UploadResponse> => {
    const formData = new FormData()
    formData.append('upload_channel', uploadChannel)
    if (year !== undefined && year !== null && !isNaN(year) && year > 0) {
      formData.append('year', year.toString())
    }
    if (month !== undefined && month !== null && !isNaN(month) && month > 0 && month <= 12) {
      formData.append('month', month.toString())
    }
    files.forEach((file) => formData.append('files', file))
    const sessionId = localStorage.getItem('sessionId')
    const headers: Record<string, string> = {}
    if (sessionId) headers['X-Session-ID'] = sessionId
    const response = await client.post<UploadResponse>(
      '/api/documents/upload-with-bbox',
      formData,
      { headers }
    )
    return response.data
  },

  /**
   * 文書一覧取得
   */
  getList: async (uploadChannel?: string): Promise<DocumentListResponse> => {
    const params = uploadChannel ? { upload_channel: uploadChannel } : {}
    const response = await client.get<DocumentListResponse>(
      '/api/documents',
      { params }
    )
    return response.data
  },

  /**
   * 特定文書取得
   */
  get: async (pdfFilename: string) => {
    const response = await client.get(`/api/documents/${pdfFilename}`)
    return response.data
  },

  /**
   * 文書を정답지 생성 대상に指定（検索タブでは非表示、정답지 생성タブでのみ表示）
   */
  setAnswerKeyDocument: async (pdfFilename: string): Promise<{ success: boolean; message: string }> => {
    const encoded = encodeURIComponent(pdfFilename)
    const response = await client.post<{ success: boolean; message: string }>(
      `/api/documents/${encoded}/answer-key-designate`
    )
    return response.data
  },

  /**
   * Gemini 생성 결과로 페이지에 items 신규 생성 (기존 항목 없을 때)
   */
  createItemsFromAnswer: async (
    pdfFilename: string,
    pageNumber: number,
    items: Array<Record<string, any>>,
    pageRole?: string,
    pageMeta?: Record<string, any> | null
  ): Promise<{ success: boolean; created_count: number }> => {
    const encoded = encodeURIComponent(pdfFilename)
    const body: Record<string, any> = { items, page_role: pageRole ?? 'detail' }
    if (pageMeta != null && Object.keys(pageMeta).length > 0) {
      body.page_meta = pageMeta
    }
    const response = await client.post(
      `/api/documents/${encoded}/pages/${pageNumber}/create-items-from-answer`,
      body
    )
    return response.data
  },

  /**
   * Gemini zero-shot으로 페이지 정답지 생성 (동일 프롬프트)
   */
  generateAnswerWithGemini: async (
    pdfFilename: string,
    pageNumber: number
  ): Promise<{ success: boolean; page_number: number; page_role: string; page_meta?: Record<string, any> | null; items: Array<Record<string, any>> }> => {
    const encoded = encodeURIComponent(pdfFilename)
    const response = await client.post(
      `/api/documents/${encoded}/pages/${pageNumber}/generate-answer`
    )
    return response.data
  },

  /**
   * 동일 프롬프트(prompt_v3.txt)로 GPT Vision으로 페이지 정답지 생성 (테스트용)
   */
  generateAnswerWithGpt: async (
    pdfFilename: string,
    pageNumber: number,
    model: string = 'gpt-5.2-2025-12-11'
  ): Promise<{ success: boolean; page_number: number; page_role: string; page_meta?: Record<string, any> | null; items: Array<Record<string, any>>; provider?: string; model?: string }> => {
    const encoded = encodeURIComponent(pdfFilename)
    const response = await client.post(
      `/api/documents/${encoded}/pages/${pageNumber}/generate-answer-gpt`,
      null,
      { params: { model } }
    )
    return response.data
  },

  /**
   * 첫 행(템플릿)으로 나머지 행 LLM 생성 후 페이지 items 전체 교체
   */
  generateItemsFromTemplate: async (
    pdfFilename: string,
    pageNumber: number,
    templateItem: Record<string, any>
  ): Promise<{ success: boolean; page_number: number; items_count: number; items: Array<Record<string, any>> }> => {
    const encoded = encodeURIComponent(pdfFilename)
    const response = await client.post(
      `/api/documents/${encoded}/pages/${pageNumber}/generate-items-from-template`,
      { template_item: templateItem }
    )
    return response.data
  },

  /**
   * 문서의 정답지 생성 대상 지정 해제
   */
  revokeAnswerKeyDocument: async (pdfFilename: string): Promise<{ success: boolean; message: string }> => {
    const encoded = encodeURIComponent(pdfFilename)
    const response = await client.post<{ success: boolean; message: string }>(
      `/api/documents/${encoded}/answer-key-revoke`
    )
    return response.data
  },

  /**
   * 문서 양식지 타입(form_type) 변경
   */
  updateFormType: async (pdfFilename: string, formType: string) => {
    const encodedFilename = encodeURIComponent(pdfFilename)
    const response = await client.patch(`/api/documents/${encodedFilename}/form-type`, {
      form_type: formType,
    })
    return response.data
  },

  /**
   * 문서 삭제 (파일명에 한글/공백 등 포함 시 URL 인코딩 필요)
   */
  delete: async (pdfFilename: string) => {
    const encoded = encodeURIComponent(pdfFilename)
    const response = await client.delete(`/api/documents/${encoded}`)
    return response.data
  },

  /**
   * 문서의 페이지 목록 조회
   */
  getPages: async (pdfFilename: string) => {
    const response = await client.get(`/api/documents/${pdfFilename}/pages`)
    return response.data
  },

  /**
   * 페이지 메타데이터 조회 (page_meta)
   */
  getPageMeta: async (
    pdfFilename: string,
    pageNumber: number
  ): Promise<{ page_role: string | null; page_meta: Record<string, any> }> => {
    const encodedFilename = encodeURIComponent(pdfFilename)
    const url = `/api/documents/${encodedFilename}/pages/${pageNumber}/meta`
    const response = await client.get<{ page_role: string | null; page_meta: Record<string, any> }>(url)
    return response.data
  },

  /**
   * page_meta 업데이트 (정답지 생성 탭에서 편집 저장용)
   */
  updatePageMeta: async (
    pdfFilename: string,
    pageNumber: number,
    pageMeta: Record<string, any>
  ): Promise<{ success: boolean; message: string }> => {
    const encodedFilename = encodeURIComponent(pdfFilename)
    const response = await client.patch<{ success: boolean; message: string }>(
      `/api/documents/${encodedFilename}/pages/${pageNumber}/meta`,
      { page_meta: pageMeta }
    )
    return response.data
  },
}

// 아이템 API
export const itemsApi = {
  /**
   * 페이지의 아이템 목록 조회
   */
  getByPage: async (
    pdfFilename: string,
    pageNumber: number
  ): Promise<{ items: Item[]; item_data_keys?: string[] | null }> => {
    // URL 인코딩
    const encodedFilename = encodeURIComponent(pdfFilename)
    const url = `/api/items/${encodedFilename}/pages/${pageNumber}`
    const response = await client.get<{ items: Item[]; item_data_keys?: string[] | null }>(url)
    return response.data
  },

  /**
   * 아이템 생성
   */
  create: async (
    pdfFilename: string,
    pageNumber: number,
    itemData: Record<string, any>,
    afterItemId?: number
  ): Promise<Item> => {
    const requestBody: Record<string, any> = {
      pdf_filename: pdfFilename,
      page_number: pageNumber,
      item_data: itemData,
    }
    
    if (afterItemId !== undefined) {
      requestBody.after_item_id = afterItemId
    }
    
    const response = await client.post<Item>('/api/items/', requestBody)
    return response.data
  },

  /**
   * 아이템 업데이트
   */
  update: async (
    itemId: number,
    request: ItemUpdateRequest
  ): Promise<{ message: string; item_id: number }> => {
    console.log('🔵 [itemsApi.update] 호출:', {
      itemId,
      review_status: request.review_status,
      expected_version: request.expected_version,
    })
    try {
      const response = await client.put(
        `/api/items/${itemId}`,
        request
      )
      console.log('✅ [itemsApi.update] 성공:', response.data)
      return response.data
    } catch (error: unknown) {
      const axiosError = error as { response?: { status?: number; data?: { detail?: string } } }
      console.error('❌ [itemsApi.update] 에러:', {
        itemId,
        status: axiosError?.response?.status,
        detail: axiosError?.response?.data?.detail,
        error: error,
      })
      throw error
    }
  },

  /**
   * 아이템 삭제
   */
  delete: async (itemId: number): Promise<{ message: string; item_id: number }> => {
    console.log('🔵 [itemsApi.delete] 호출:', { itemId, url: `/api/items/${itemId}` })
    try {
      const response = await client.delete(`/api/items/${itemId}`)
      console.log('✅ [itemsApi.delete] 성공:', response.data)
      return response.data
    } catch (error: unknown) {
      const axiosError = error as { response?: { status?: number; statusText?: string; data?: { detail?: string } } }
      console.error('❌ [itemsApi.delete] 에러:', {
        itemId,
        url: `/api/items/${itemId}`,
        status: axiosError?.response?.status,
        statusText: axiosError?.response?.statusText,
        detail: axiosError?.response?.data?.detail,
        error: error,
      })
      throw error
    }
  },

  /**
   * 아이템 락 획득
   */
  acquireLock: async (
    itemId: number,
    sessionId: string
  ): Promise<{ message: string; item_id: number }> => {
    const response = await client.post(`/api/items/${itemId}/lock`, {
      session_id: sessionId,
    })
    return response.data
  },

  /**
   * 검토 상태 통계 조회
   */
  getReviewStats: async (): Promise<{
    first_reviewed_count: number
    first_not_reviewed_count: number
    second_reviewed_count: number
    second_not_reviewed_count: number
    total_pages: number
    page_stats: Array<{
      pdf_filename: string
      page_number: number
      first_reviewed: boolean
      second_reviewed: boolean
      first_review_rate: number
      second_review_rate: number
      total_items: number
      first_checked_count: number
      second_checked_count: number
    }>
  }> => {
    const response = await client.get('/api/items/stats/review')
    return response.data
  },

  /**
   * 아이템 락 해제
   */
  releaseLock: async (
    itemId: number,
    sessionId: string
  ): Promise<{ message: string; item_id: number }> => {
    const response = await client.delete(`/api/items/${itemId}/lock`, {
      data: { session_id: sessionId },
    })
    return response.data
  },

  /**
   * 세션 ID로 잠긴 모든 락 해제 (페이지 언로드 시 사용)
   */
  releaseAllLocks: async (
    sessionId: string
  ): Promise<{ message: string; released_count: number }> => {
    // beforeunload에서는 비동기 요청이 완료되지 않을 수 있으므로
    // navigator.sendBeacon을 사용하거나 동기 요청을 사용해야 함
    // 하지만 DELETE 요청은 sendBeacon으로 보낼 수 없으므로
    // XMLHttpRequest를 동기 모드로 사용
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('DELETE', `${API_BASE_URL}/api/items/locks/session`, false) // 동기 모드
      xhr.setRequestHeader('Content-Type', 'application/json')
      xhr.send(JSON.stringify({ session_id: sessionId }))
      
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const data = JSON.parse(xhr.responseText)
          resolve(data)
        } catch (e) {
          resolve({ message: 'Locks released', released_count: 0 })
        }
      } else {
        reject(new Error(`Failed to release locks: ${xhr.status}`))
      }
    })
  },
}

// 검색 API
export const searchApi = {
  /**
   * 거래처명으로 검색
   */
  byCustomer: async (
    customerName: string,
    exactMatch: boolean = false,
    formType?: string
  ): Promise<SearchResult> => {
    const params: Record<string, any> = {
      customer_name: customerName,
      exact_match: exactMatch,
    }
    if (formType) {
      params.form_type = formType
    }
    const response = await client.get<SearchResult>('/api/search/customer', {
      params,
    })
    return response.data
  },

  /**
   * 페이지 이미지 조회
   */
  getPageImage: async (
    pdfFilename: string,
    pageNumber: number
  ): Promise<PageImageResponse> => {
    // URL 인코딩
    const encodedFilename = encodeURIComponent(pdfFilename)
    const url = `/api/search/${encodedFilename}/pages/${pageNumber}/image`
    const response = await client.get<PageImageResponse>(url)
    return response.data
  },

  /**
   * 페이지 OCR 텍스트 조회 (정답지 생성 탭 이미지 아래 표시용)
   */
  getPageOcrText: async (
    pdfFilename: string,
    pageNumber: number
  ): Promise<{ ocr_text: string }> => {
    const encodedFilename = encodeURIComponent(pdfFilename)
    const url = `/api/search/${encodedFilename}/pages/${pageNumber}/ocr-text`
    const response = await client.get<{ ocr_text: string }>(url)
    return response.data
  },
}

/**
 * 인증 관련 API
 */
export const authApi = {
  /**
   * 로그인
   */
  login: async (username: string) => {
    console.log('🔵 [authApi.login] 요청:', { username, url: '/api/auth/login' })
    try {
      const response = await client.post('/api/auth/login', { username })
      console.log('✅ [authApi.login] 응답:', response.status, response.data)
      return response.data
    } catch (error: any) {
      console.error('❌ [authApi.login] 에러:', {
        status: error?.response?.status,
        statusText: error?.response?.statusText,
        data: error?.response?.data,
        message: error?.message
      })
      throw error
    }
  },

  /**
   * 로그아웃
   */
  logout: async () => {
    const response = await client.post('/api/auth/logout')
    return response.data
  },

  /**
   * 현재 사용자 정보 조회
   */
  getCurrentUser: async () => {
    const response = await client.get('/api/auth/me')
    return response.data
  },

  /**
   * 세션 유효성 검증
   */
  validateSession: async () => {
    const response = await client.get('/api/auth/validate-session')
    return response.data
  },

  /**
   * 사용자 목록 조회 (관리자용)
   */
  getUsers: async () => {
    const response = await client.get('/api/auth/users')
    return response.data
  },

  /**
   * 사용자 생성 (관리자용)
   */
  createUser: async (data: { username: string; display_name: string; display_name_ja?: string }) => {
    const response = await client.post('/api/auth/users', data)
    return response.data
  },

  /**
   * 사용자 정보 업데이트 (관리자용)
   */
  updateUser: async (userId: number, data: { display_name?: string; display_name_ja?: string; is_active?: boolean }) => {
    const response = await client.put(`/api/auth/users/${userId}`, data)
    return response.data
  },

  /**
   * 사용자 비활성화 (관리자용)
   */
  deactivateUser: async (userId: number) => {
    const response = await client.delete(`/api/auth/users/${userId}`)
    return response.data
  },
}

/**
 * SAP 업로드 API
 */
export const sapUploadApi = {
  /**
   * SAP 엑셀 파일 미리보기
   */
  preview: async (): Promise<{
    total_items: number
    preview_rows: Array<Record<string, any>>
    column_names: string[]
    message: string
  }> => {
    const response = await client.get('/api/sap-upload/preview')
    return response.data
  },

  /**
   * SAP 엑셀 파일 다운로드
   */
  download: async (): Promise<Blob> => {
    const response = await client.get('/api/sap-upload/download', {
      responseType: 'blob',
    })
    return response.data
  },

  /**
   * SAP 템플릿 컬럼명 목록 (1행 기준)
   */
  getColumnNames: async (): Promise<{ column_names: string[] }> => {
    const response = await client.get('/api/sap-upload/column-names')
    return response.data
  },

  /**
   * SAP 산식 설정 조회 (양식지별)
   */
  getFormulas: async (): Promise<import('@/types').SapFormulasConfig> => {
    const response = await client.get('/api/sap-upload/formulas')
    return response.data
  },

  /**
   * SAP 산식 설정 저장 (양식지별 편집)
   */
  putFormulas: async (body: import('@/types').SapFormulasConfig): Promise<{ ok: boolean }> => {
    const response = await client.put('/api/sap-upload/formulas', body)
    return response.data
  },
}

/**
 * RAG / 벡터 DB 관리자 API
 */
export const ragAdminApi = {
  /**
   * 벡터 DB 상태 조회
   */
  getStatus: async (): Promise<{
    total_vectors: number
    per_form_type: Array<{ form_type: string | null; vector_count: number }>
  }> => {
    const response = await client.get('/api/rag-admin/status')
    return response.data
  },

  /**
   * img 폴ダからのベクターDB生成/再構築トリガー
   */
  build: async (formType?: string): Promise<{
    success: boolean
    message: string
    total_vectors: number
    per_form_type: Array<{ form_type: string | null; vector_count: number }>
  }> => {
    const payload: { form_type?: string } = {}
    if (formType) {
      payload.form_type = formType
    }
    const response = await client.post('/api/rag-admin/build', payload)
    return response.data
  },

  /**
   * 특정 페이지의 벡터DB 학습 플래그 조회
   */
  getLearningFlag: async (
    pdfFilename: string,
    pageNumber: number,
  ): Promise<{ selected: boolean }> => {
    const response = await client.get('/api/rag-admin/learning-flag', {
      params: { pdf_filename: pdfFilename, page_number: pageNumber },
    })
    return response.data
  },

  /**
   * 특정 페이지의 벡터DB 학습 플래그 설정
   */
  setLearningFlag: async (params: {
    pdf_filename: string
    page_number: number
    selected: boolean
  }): Promise<{ success: boolean }> => {
    const response = await client.post('/api/rag-admin/learning-flag', params)
    return response.data
  },

  /**
   * 현재 학습 대상으로 체크된 페이지 목록 조회
   */
  getLearningPages: async (): Promise<{
    count: number
    pages: Array<{ pdf_filename: string; page_number: number }>
  }> => {
    const response = await client.get('/api/rag-admin/learning-pages')
    return response.data
  },

  /**
   * 학습 대상으로 체크된 페이지들로부터 벡터 생성
   */
  buildFromLearningPages: async (formType?: string): Promise<{
    success: boolean
    message: string
    processed_pages: number
    total_vectors: number
    per_form_type: Array<{ form_type: string | null; vector_count: number }>
  }> => {
    const payload: { form_type?: string } = {}
    if (formType) {
      payload.form_type = formType
    }
    const response = await client.post('/api/rag-admin/build-from-learning-pages', payload)
    return response.data
  },

  /**
   * 基準管理 master_code.xlsx 一覧取得
   */
  getMasterCode: async (): Promise<{
    headers: string[]
    rows: Array<{ a: string; b: string; c: string; d: string; e: string; f: string }>
  }> => {
    const response = await client.get('/api/rag-admin/master-code')
    return response.data
  },

  /**
   * 基準管理 master_code.xlsx 保存
   */
  saveMasterCode: async (params: {
    headers?: string[]
    rows: Array<{ a: string; b: string; c: string; d: string; e: string; f: string }>
  }): Promise<{ success: boolean; message: string }> => {
    const response = await client.put('/api/rag-admin/master-code', params)
    return response.data
  },
}

/** OCR 테스트: 구조화(좌표付き) 요청 - DB 저장 없이 일회성 */
export type OcrStructureRequest = {
  ocr_text: string
  words: OcrWord[]
  page_width: number
  page_height: number
  form_type?: string
}

/** Upstage OCR 테스트용 API (bbox 포함 전체 응답) */
export type OcrWord = {
  id: number
  text: string
  confidence?: number
  boundingBox?: {
    vertices: Array< { x: number; y: number } >
  }
}

export type OcrTestPage = {
  id: number
  text: string
  width: number
  height: number
  confidence?: number
  words?: OcrWord[]
}

export type OcrTestResponse = {
  text?: string
  pages?: OcrTestPage[]
  metadata?: { pages?: Array<{ page: number; width: number; height: number }> }
}

/** キーイン保存リクエスト */
export type OcrKeyinSaveRequest = {
  keyed_values: Record<string, string>
  image_filename?: string
}

/** PDF 업로드 응답 */
export type OcrUploadPdfResponse = {
  upload_id: string
  num_pages: number
}

/** master_code.xlsx 1行（A~F列） */
export type OcrSuggestRow = {
  a: string
  b: string
  c: string
  d: string
  e: string
  f: string
}

export const ocrTestApi = {
  /** PDF 업로드 → upload_id, num_pages 반환 */
  uploadPdf: async (file: File): Promise<OcrUploadPdfResponse> => {
    const formData = new FormData()
    formData.append('file', file)
    const response = await client.post<OcrUploadPdfResponse>('/api/ocr-test/upload-pdf', formData)
    return response.data
  },

  /** 指定ページの画像URL（img src 用） */
  getPdfPageImageUrl: (uploadId: string, page: number): string => {
    const base = client.defaults.baseURL ?? ''
    const sep = base.includes('?') ? '&' : '?'
    return `${base}/api/ocr-test/pdf-page-image${sep}upload_id=${encodeURIComponent(uploadId)}&page=${page}`
  },

  /** 指定PDFページでOCR実行 → OcrTestResponse */
  ocrPdfPage: async (uploadId: string, page: number): Promise<OcrTestResponse> => {
    const response = await client.post<OcrTestResponse>('/api/ocr-test/ocr-pdf-page', {
      upload_id: uploadId,
      page,
    })
    return response.data
  },

  /** 이미지 1장 업로드 → Upstage OCR 전체 응답 (bbox 포함) */
  ocrImage: async (file: File): Promise<OcrTestResponse> => {
    const formData = new FormData()
    formData.append('file', file)
    const response = await client.post<OcrTestResponse>('/api/ocr-test/ocr', formData)
    return response.data
  },

  /** OCR 결과로 구조화(좌표付き) - LLM _word_indices → _bbox, DB 저장 없음 */
  structure: async (body: OcrStructureRequest): Promise<OcrTestResponse & Record<string, unknown>> => {
    const response = await client.post<Record<string, unknown>>('/api/ocr-test/structure', body)
    return response.data as OcrTestResponse & Record<string, unknown>
  },

  /** キーイン結果を保存 */
  saveKeyin: async (body: OcrKeyinSaveRequest): Promise<{ success: boolean }> => {
    const response = await client.post<{ success: boolean }>('/api/ocr-test/keyin', body)
    return response.data
  },

  /** master_code.xlsx: 受注先はB列、スーパーはD列基準で類似3件をA~F列付きで取得 */
  suggestCodes: async (value: string, field?: string): Promise<{ suggestions: OcrSuggestRow[] }> => {
    const response = await client.post<{ suggestions: OcrSuggestRow[] }>('/api/ocr-test/suggest-codes', {
      value: value || '',
      field: field || undefined,
    })
    return response.data
  },
}

/** 分析(기본 RAG) LLM: gemini | gpt5.2 */
export type RagProvider = 'gemini' | 'gpt5.2'

export const settingsApi = {
  getRagProvider: async (): Promise<{ provider: RagProvider }> => {
    const response = await client.get<{ provider: RagProvider }>('/api/settings/rag-provider')
    return response.data
  },
  setRagProvider: async (provider: RagProvider): Promise<{ provider: RagProvider }> => {
    const response = await client.put<{ provider: RagProvider }>('/api/settings/rag-provider', { provider })
    return response.data
  },
}

export default client
