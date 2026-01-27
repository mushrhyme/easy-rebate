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

// 文書API
export const documentsApi = {
  /**
   * 文書アップロード
   */
  upload: async (
    formType: string,
    files: File[],
    year?: number,
    month?: number
  ): Promise<UploadResponse> => {
    const formData = new FormData()
    formData.append('form_type', formType)
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
      formType, 
      fileCount: files.length, 
      year, 
      month, 
      hasSessionId: !!sessionId 
    })
    // FormData 내용 확인 (디버깅용)
    console.log('🔵 [업로드] FormData 내용:', {
      form_type: formType,
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
   * 文書一覧取得
   */
  getList: async (formType?: string): Promise<DocumentListResponse> => {
    const params = formType ? { form_type: formType } : {}
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
   * 문서 삭제
   */
  delete: async (pdfFilename: string) => {
    const response = await client.delete(`/api/documents/${pdfFilename}`)
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
    console.log('🔵 [documentsApi.getPageMeta] 호출:', { pdfFilename, pageNumber, url })
    const response = await client.get<{ page_role: string | null; page_meta: Record<string, any> }>(url)
    console.log('✅ [documentsApi.getPageMeta] 응답:', response.data)
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
  ): Promise<{ items: Item[] }> => {
    // URL 인코딩
    const encodedFilename = encodeURIComponent(pdfFilename)
    const url = `/api/items/${encodedFilename}/pages/${pageNumber}`
    const response = await client.get<{ items: Item[] }>(url)
    return response.data
  },

  /**
   * 아이템 생성
   */
  create: async (
    pdfFilename: string,
    pageNumber: number,
    itemData: Record<string, any>,
    customer?: string,
    productName?: string,
    afterItemId?: number
  ): Promise<Item> => {
    const requestBody: Record<string, any> = {
      pdf_filename: pdfFilename,
      page_number: pageNumber,
      item_data: itemData,
    }
    
    // 선택적 필드 추가 (undefined가 아닐 때만)
    if (customer !== undefined) {
      requestBody.customer = customer
    }
    if (productName !== undefined) {
      requestBody.product_name = productName
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
  createUser: async (data: { username: string; display_name: string }) => {
    const response = await client.post('/api/auth/users', data)
    return response.data
  },

  /**
   * 사용자 정보 업데이트 (관리자용)
   */
  updateUser: async (userId: number, data: { display_name?: string; is_active?: boolean }) => {
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
}

export default client
