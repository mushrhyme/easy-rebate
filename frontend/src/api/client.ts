/**
 * APIクライアント (도메인별 래퍼)
 * - HTTP 설정 및 인터셉터는 `httpClient.ts`에서 관리
 * - 여기서는 도메인별 API 객체만 정의한다.
 */
import client from './httpClient'
import type {
  DocumentListResponse,
  Item,
  ItemUpdateRequest,
  SearchResult,
  PageImageResponse,
  UploadResponse,
} from '@/types'

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

  /** 양식지 종류 삭제. 사용 중인 문서가 있으면 409 */
  delete: async (formCode: string): Promise<{ form_code: string; message: string }> => {
    const response = await client.delete(`/api/form-types/${encodeURIComponent(formCode)}`)
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
   * 文書一覧取得
   * @param uploadChannel チャネルで絞り込み（省略可）
   * @param options is_answer_key_document: 解答対象のみ / exclude_answer_key: 検討タブ用に正解表対象を除外 / form_type: 様式で絞り込み
   */
  getList: async (
    uploadChannel?: string,
    options?: { is_answer_key_document?: boolean; exclude_answer_key?: boolean; form_type?: string }
  ): Promise<DocumentListResponse> => {
    const params: Record<string, string | boolean> = {}
    if (uploadChannel) params.upload_channel = uploadChannel
    if (options?.is_answer_key_document === true) params.is_answer_key_document = true
    if (options?.exclude_answer_key === true) params.exclude_answer_key = true
    if (options?.form_type) params.form_type = options.form_type
    const response = await client.get<DocumentListResponse>('/api/documents', { params })
    return response.data
  },

  /**
   * 解答作成タブ用の文書一覧（管理者は全件、一般は自分が指定した文書のみ）
   */
  getListForAnswerKeyTab: async (): Promise<DocumentListResponse> => {
    const response = await client.get<DocumentListResponse>('/api/documents/for-answer-key-tab')
    return response.data
  },

  /**
   * 文書の解答 answer.json 一式取得（様式別「既存解答」参照用・DB由来）
   */
  getDocumentAnswerJson: async (
    pdfFilename: string
  ): Promise<{
    pdf_filename: string
    form_type: string | null
    total_pages: number
    pages: Array<Record<string, any>>
  }> => {
    const encoded = encodeURIComponent(pdfFilename)
    const response = await client.get(
      `/api/documents/${encoded}/answer-json`
    )
    return response.data
  },

  /**
   * 現在状態を answer-json として DB に一括保存（行ごとの PUT なし・高速、ベクターDBなし）
   */
  saveAnswerJson: async (
    pdfFilename: string,
    body: { pages: Array<{ page_number: number; page_role?: string; page_meta?: Record<string, unknown>; items: Array<Record<string, unknown>> }> }
  ): Promise<{ success: boolean; message: string; pages_count: number }> => {
    const encoded = encodeURIComponent(pdfFilename)
    const response = await client.put(`/api/documents/${encoded}/answer-json`, body)
    return response.data
  },

  /**
   * RAG DB ソース: img フォルダ内の解答一覧（form_type 別）
   * 戻り: { by_form_type: { "01": [ { pdf_name, relative_path, total_pages }, ... ], ... } }
   */
  getAnswerKeysFromImg: async (): Promise<{
    by_form_type: Record<string, Array<{ pdf_name: string; relative_path: string | null; total_pages: number }>>
  }> => {
    const response = await client.get('/api/documents/answer-keys-from-img')
    return response.data
  },

  /**
   * img フォルダ内の解答フォルダ（relative_path）の answer.json 一式取得
   */
  getAnswerJsonFromImg: async (
    relativePath: string
  ): Promise<{
    pdf_filename: string
    form_type: string | null
    total_pages: number
    pages: Array<Record<string, any>>
  }> => {
    const response = await client.get('/api/documents/answer-json-from-img', {
      params: { relative_path: relativePath },
    })
    return response.data
  },

  /**
   * img 폴더의 Page*_answer.json에만 저장 (DB 미사용). RAG 문서는 여기서 읽어오므로 여기 저장해야 null 덮어쓰기 없음.
   */
  saveAnswerJsonFromImg: async (
    relativePath: string,
    body: { pages: Array<{ page_number: number; page_role?: string; page_meta?: Record<string, unknown>; items: Array<Record<string, unknown>> }> }
  ): Promise<{ success: boolean; message: string; pages_count: number }> => {
    const response = await client.put('/api/documents/answer-json-from-img', {
      relative_path: relativePath,
      pages: body.pages,
    })
    return response.data
  },

  /** img 폴더 정답지 페이지 이미지 URL (RAG 문서 뷰용). GET으로 이미지 반환 */
  getImgPageImageUrl: (relativePath: string, pageNumber: number): string => {
    const base = client.defaults.baseURL ?? ''
    const sep = base.includes('?') ? '&' : '?'
    return `${base}/api/documents/img-page-image${sep}relative_path=${encodeURIComponent(relativePath)}&page_number=${pageNumber}`
  },

  /**
   * 現在のRAGベクトルインデックスに含まれる文書(pdf_filename)一覧。アップロード一覧のハイライト用。
   */
  getInVectorIndex: async (): Promise<{ pdf_filenames: string[] }> => {
    const response = await client.get<{ pdf_filenames: string[] }>('/api/documents/in-vector-index')
    return response.data
  },

  /**
   * 文書一覧＋様式マッピング＋ページ役割(Cover/Detail/Summary/Reply)件数
   */
  getOverview: async (answerKeyOnly?: boolean): Promise<{
    page_role_totals: Record<string, number>
    documents: Array<{
      pdf_filename: string
      form_type: string | null
      total_pages: number
      is_answer_key_document: boolean
      cover: number
      detail: number
      summary: number
      reply: number
    }>
  }> => {
    const params = answerKeyOnly === true ? { answer_key_only: 'true' } : {}
    const response = await client.get('/api/documents/overview', { params })
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
   * ページ画像が未生成の文書について、PDFから画像を生成して保存する。
   * PDFはセッションtempまたはimg学習フォルダから検索。見つからない場合は再アップロードが必要。
   */
  generatePageImages: async (
    pdfFilename: string
  ): Promise<{ success: boolean; message: string; pages: number }> => {
    const encoded = encodeURIComponent(pdfFilename)
    const response = await client.post<{ success: boolean; message: string; pages: number }>(
      `/api/documents/${encoded}/generate-page-images`
    )
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
   * Azure OCR(표 복원) + RAG+LLM으로 페이지 정답지 생성. 표 구조 보존.
   */
  generateAnswerWithRag: async (
    pdfFilename: string,
    pageNumber: number
  ): Promise<{ success: boolean; page_number: number; page_role: string; page_meta?: Record<string, any> | null; items: Array<Record<string, any>>; provider?: string }> => {
    const encoded = encodeURIComponent(pdfFilename)
    const response = await client.post(
      `/api/documents/${encoded}/pages/${pageNumber}/generate-answer-rag`
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
   * 첫 행(템플릿)으로 나머지 행 LLM 생성 후 페이지 items 전체 교체. provider는 상단 드롭다운 선택과 동일.
   */
  generateItemsFromTemplate: async (
    pdfFilename: string,
    pageNumber: number,
    templateItem: Record<string, any>,
    provider: 'gemini' | 'gpt-5.2' = 'gpt-5.2'
  ): Promise<{ success: boolean; page_number: number; items_count: number; items: Array<Record<string, any>> }> => {
    const encoded = encodeURIComponent(pdfFilename)
    const response = await client.post(
      `/api/documents/${encoded}/pages/${pageNumber}/generate-items-from-template`,
      { template_item: templateItem, provider }
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
   * page_meta 업데이트 (정답지 생성 탭에서 편집 저장용). page_role 지정 시 함께 저장.
   */
  updatePageMeta: async (
    pdfFilename: string,
    pageNumber: number,
    pageMeta: Record<string, any>,
    pageRole?: string
  ): Promise<{ success: boolean; message: string }> => {
    const encodedFilename = encodeURIComponent(pdfFilename)
    const body: { page_meta: Record<string, any>; page_role?: string } = { page_meta: pageMeta }
    if (pageRole != null && pageRole !== '') body.page_role = pageRole
    const response = await client.patch<{ success: boolean; message: string }>(
      `/api/documents/${encodedFilename}/pages/${pageNumber}/meta`,
      body
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
   * 現況フィルタ用。請求年月が設定されている文書の distinct 一覧。
   * 返却: { year_months: [{ year, month }, ...] }
   */
  getAvailableYearMonths: async (): Promise<{
    year_months: Array<{ year: number; month: number }>
  }> => {
    const response = await client.get('/api/items/stats/available-year-months')
    return response.data
  },

  /**
   * 検討状況（アイテム数基準・detail・得意先ありのみ）。year/month で請求年月絞り込み可。
   */
  getReviewStatsByItems: async (params?: { year?: number; month?: number }): Promise<{
    total_item_count: number
    total_document_count: number
    first_checked_count: number
    first_not_checked_count: number
    second_checked_count: number
    second_not_checked_count: number
  }> => {
    const q = params && params.year != null && params.month != null ? { year: params.year, month: params.month } : {}
    const response = await client.get('/api/items/stats/review-by-items', { params: q })
    return response.data
  },

  /**
   * 検討チェックを誰が何件したか。year/month で請求年月絞り込み可。
   */
  getReviewStatsByUser: async (params?: { year?: number; month?: number }): Promise<{
    by_user: Array<{
      user_id: number
      display_name: string
      first_checked_count: number
      second_checked_count: number
    }>
  }> => {
    const q = params && params.year != null && params.month != null ? { year: params.year, month: params.month } : {}
    const response = await client.get('/api/items/stats/review-by-user', { params: q })
    return response.data
  },

  /**
   * detail ページ・得意先ありのみのアイテム数集計。year/month で請求年月絞り込み可。
   */
  getDetailSummary: async (params?: { year?: number; month?: number }): Promise<{
    total_item_count: number
    total_document_count: number
    by_channel: Array<{ channel: string; item_count: number }>
    by_form_type: Array<{ form_type: string; item_count: number }>
    by_year_month: Array<{ year: number; month: number; item_count: number }>
    by_year_month_by_form: Array<{ year: number; month: number; form_type: string; item_count: number }>
  }> => {
    const q = params && params.year != null && params.month != null ? { year: params.year, month: params.month } : {}
    const response = await client.get('/api/items/stats/detail-summary', { params: q })
    return response.data
  },

  /**
   * 得意先別統計。year/month で請求年月絞り込み可。
   */
  getCustomerStats: async (
    limit?: number,
    params?: { year?: number; month?: number }
  ): Promise<{
    customers: Array<{
      customer_name: string
      document_count: number
      page_count: number
      item_count: number
    }>
  }> => {
    const q: Record<string, number> = {}
    if (limit != null) q.limit = limit
    if (params && params.year != null && params.month != null) {
      q.year = params.year
      q.month = params.month
    }
    const response = await client.get('/api/items/stats/by-customer', { params: q })
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
}

// 검색 API
export const searchApi = {
  /**
   * 거래처명으로 검색
   * mySupersOnly: true면 로그인 사용자 담당 슈퍼만 (유사도 90% 이상)
   */
  byCustomer: async (
    customerName: string,
    exactMatch: boolean = false,
    formType?: string,
    mySupersOnly: boolean = false
  ): Promise<SearchResult> => {
    const params: Record<string, any> = {
      customer_name: customerName,
      exact_match: exactMatch,
      my_supers_only: mySupersOnly,
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
   * 로그인 사용자 담당 거래처(슈퍼) 목록 (retail_user.csv 기준)
   */
  getMySupers: async (): Promise<{ super_names: string[] }> => {
    const response = await client.get<{ super_names: string[] }>('/api/search/my-supers')
    return response.data
  },

  /**
   * retail_user.csv 대표슈퍼명 전체. 거래처↔담당 매핑 시 notepad와 동일하게 전체 풀에서 최적 매칭용.
   */
  getAllSuperNames: async (): Promise<{ super_names: string[] }> => {
    const response = await client.get<{ super_names: string[] }>('/api/search/all-super-names')
    return response.data
  },

  /**
   * 검토 탭 전체 거래처 목록 (정답지·벡터 제외, items의 得意先/customer 중복 제거)
   */
  getReviewTabCustomers: async (year?: number, month?: number): Promise<{ customer_names: string[] }> => {
    const params: Record<string, number> = {}
    if (year != null) params.year = year
    if (month != null) params.month = month
    const response = await client.get<{ customer_names: string[] }>('/api/search/review-tab-customers', { params })
    return response.data
  },

  /**
   * 로그인 사용자 담당 슈퍼에 해당하는 페이지 목록 (검토 탭 "내 담당만" 필터용, 유사도 90% 이상)
   */
  getMySuperPages: async (formType?: string): Promise<{ pages: Array<{ pdf_filename: string; page_number: number; form_type?: string | null }> }> => {
    const params: Record<string, any> = {}
    if (formType) params.form_type = formType
    const response = await client.get<{ pages: Array<{ pdf_filename: string; page_number: number; form_type?: string | null }> }>(
      '/api/search/my-super-pages',
      { params }
    )
    return response.data
  },

  /**
   * 거래처(왼쪽) vs 담당(오른쪽) 유사도 매핑. notepad와 동일한 difflib 기준.
   */
  getCustomerSimilarityMapping: async (
    customerNames: string[],
    superNames: string[]
  ): Promise<{ mapped: Array<{ left: string; right: string; score: number }>; unmapped_rights: string[] }> => {
    const response = await client.post('/api/search/customer-similarity-mapping', {
      customer_names: customerNames,
      super_names: superNames,
    })
    return response.data
  },

  /**
   * 선택한 customer명 목록으로 해당 페이지 목록 조회 (확인 후 필터 적용용)
   */
  postPagesByCustomers: async (
    customerNames: string[],
    formType?: string
  ): Promise<{ pages: Array<{ pdf_filename: string; page_number: number; form_type?: string | null }> }> => {
    const response = await client.post('/api/search/pages-by-customers', {
      customer_names: customerNames,
      form_type: formType ?? null,
    })
    return response.data
  },

  /**
   * 商品名으로 단가 매칭 (제품명·용량 분리 후 unit_price 유사도 조회 → 시키리/본부장 반환)
   */
  getUnitPriceByProduct: async (
    productName: string,
    options?: { topK?: number; minSimilarity?: number; subMinSimilarity?: number }
  ): Promise<{
    base_name: string
    capacity: string | null
    product_name_input: string
    matches: Array<{
      제품코드?: string | number
      제품명?: string
      제품용량?: number | string
      시키리?: number
      본부장?: number
      JANCD?: string | number
      제품명_similarity?: number
      제품용량_similarity?: number
      similarity?: number
    }>
  }> => {
    const params: Record<string, any> = { product_name: productName }
    if (options?.topK != null) params.top_k = options.topK
    if (options?.minSimilarity != null) params.min_similarity = options.minSimilarity
    if (options?.subMinSimilarity != null) params.sub_min_similarity = options.subMinSimilarity
    const response = await client.get('/api/search/unit-price-by-product', { params })
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

  /**
   * 현재 페이지 OCR 다시 인식 (Azure 또는 Upstage) — 결과를 debug2에 저장 후 반환
   * Azure 시 azure_model: prebuilt-read | prebuilt-layout | prebuilt-document
   */
  /** 정답지 탭: OCR 재인식 (Azure 전용). 결과는 debug2에 저장됨 */
  rerunPageOcr: async (
    pdfFilename: string,
    pageNumber: number,
    azureModel?: string
  ): Promise<{ ocr_text: string }> => {
    const encodedFilename = encodeURIComponent(pdfFilename)
    const url = `/api/search/${encodedFilename}/pages/${pageNumber}/ocr-rerun`
    const body = { provider: 'azure', azure_model: azureModel ?? 'prebuilt-layout' }
    const response = await client.post<{ ocr_text: string }>(url, body)
    return response.data
  },
}

/**
 * 인증 관련 API
 */
export interface LoginResponse {
  success: boolean
  message: string
  user_id?: number
  username?: string
  display_name?: string
  display_name_ja?: string
  session_id?: string
  must_change_password?: boolean
}

/** 사용자 생성 (관리자용). users 테이블 키값 전체 입력 가능 */
export type CreateUserPayload = {
  username: string
  display_name: string
  display_name_ja?: string
  department_ko?: string
  department_ja?: string
  role?: string
  category?: string
}

/** 사용자 정보 업데이트 (관리자용) */
export type UpdateUserPayload = {
  display_name?: string
  display_name_ja?: string
  department_ko?: string
  department_ja?: string
  role?: string
  category?: string
  is_active?: boolean
  is_admin?: boolean
  /** 관리자 설정용. 전달 시 해당 비밀번호로 설정, 빈 문자열이면 로그인ID로 초기화 */
  password?: string
}

export const authApi = {
  /**
   * 로그인 (사용자명 + 비밀번호)
   */
  login: async (username: string, password: string): Promise<LoginResponse> => {
    console.log('🔵 [authApi.login] 요청:', { username, url: '/api/auth/login' })
    try {
      const response = await client.post<LoginResponse>('/api/auth/login', { username, password })
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
   * 비밀번호 변경 (로그인 후, 초기 비밀번호 변경 시)
   */
  changePassword: async (currentPassword: string, newPassword: string): Promise<{ success: boolean; message: string }> => {
    const response = await client.post<{ success: boolean; message: string }>('/api/auth/change-password', {
      current_password: currentPassword,
      new_password: newPassword,
    })
    return response.data
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
   * 사용자 생성 (관리자용). users 테이블 키값 전체 입력 가능
   */
  createUser: async (data: CreateUserPayload) => {
    const response = await client.post('/api/auth/users', data)
    return response.data
  },

  /**
   * 사용자 정보 업데이트 (관리자용)
   */
  updateUser: async (userId: number, data: UpdateUserPayload) => {
    const response = await client.put(`/api/auth/users/${userId}`, data)
    return response.data
  },

  /**
   * 사용자 삭제 (관리자용 - DB 행 삭제)
   */
  deleteUser: async (userId: number) => {
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
    answer_key_pages_total: number
    answer_key_pages_this_month: number
    answer_key_pages_last_month: number
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
   * retail_user.csv をそのまま取得（管理マスタタブで CSV 内容を表示）
   */
  getRetailUserCsv: async (): Promise<{
    rows: Array<{
      super_code: string
      super_name: string
      person_id: string
      person_name: string
      username: string
    }>
  }> => {
    const response = await client.get('/api/rag-admin/retail-user-csv')
    return response.data
  },

  /** retail_user.csv を全体上書き保存 */
  putRetailUserCsv: async (rows: Array<{
    super_code: string
    super_name: string
    person_id: string
    person_name: string
    username: string
  }>): Promise<{ message: string; rows_count: number }> => {
    const response = await client.put('/api/rag-admin/retail-user-csv', { rows })
    return response.data
  },

  /** dist_retail.csv をそのまま取得（管理マスタタブで CSV 内容を表示） */
  getDistRetailCsv: async (): Promise<{
    rows: Array<{
      dist_code: string
      dist_name: string
      super_code: string
      super_name: string
      person_id: string
      person_name: string
    }>
  }> => {
    const response = await client.get('/api/rag-admin/dist-retail-csv')
    return response.data
  },

  /** dist_retail.csv を全体上書き保存 */
  putDistRetailCsv: async (rows: Array<{
    dist_code: string
    dist_name: string
    super_code: string
    super_name: string
    person_id: string
    person_name: string
  }>): Promise<{ message: string; rows_count: number }> => {
    const response = await client.put('/api/rag-admin/dist-retail-csv', { rows })
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
