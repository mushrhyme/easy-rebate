/**
 * 공용 Axios 클라이언트
 * - baseURL 및 공통 헤더 설정
 * - 요청/응답 인터셉터 (세션 헤더, 로깅, 에러 처리)
 *
 * 도메인별 API 모듈은 이 클라이언트를 import 해서 사용한다.
 */
import axios from 'axios'
import { getApiBaseUrl } from '@/utils/apiConfig'

const API_BASE_URL = getApiBaseUrl()

console.log('🔵 [API Client] 초기화 - baseURL:', API_BASE_URL)

const client = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 리퀘스트 인터셉터: 세션 헤더 추가 및 로깅
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

    // セッションIDをヘッダーに追加 (config에 이미 있으면 덮어쓰지 않음 — 학습 요청 등에서 클릭 시점 세션 고정용)
    const existingSession =
      config.headers &&
      (typeof (config.headers as { get?: (k: string) => string }).get === 'function'
        ? (config.headers as { get: (k: string) => string }).get('X-Session-ID')
        : (config.headers as Record<string, string>)['X-Session-ID'])
    const sessionId = existingSession ?? localStorage.getItem('sessionId')
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

    console.log('🔵 [API Request]', config.method?.toUpperCase(), (config.baseURL ?? '') + (config.url ?? ''), {
      params: config.params,
      hasSessionId: !!sessionId,
      isFormData: config.data instanceof FormData,
    })
    return config
  },
  (error) => {
    console.error('❌ [API Request Error]', error)
    return Promise.reject(error)
  },
)

// 레스폰스 인터셉터: 에러 로깅 및 세션 만료 처리
client.interceptors.response.use(
  (response) => {
    console.log('✅ [API Response]', response.config.method?.toUpperCase(), response.config.url, response.status)
    return response
  },
  (error) => {
    const status = error.response?.status
    const url = error.config?.url ?? ''
    const method = (error.config?.method ?? '').toLowerCase()
    // 문서 존재 여부 확인용 GET 404는 정상 동작 → 에러 로그 생략
    const isDocumentCheck404 = status === 404 && method === 'get' && typeof url === 'string' && url.includes('/documents/')
    if (!isDocumentCheck404) {
      const errorInfo = {
        url,
        method: error.config?.method,
        status,
        statusText: error.response?.statusText,
        data: error.response?.data,
        message: error.message,
        code: error.code,
      }
      console.error('❌ [API Response Error]', errorInfo)
    }

    // 세션 만료 에러 처리
    const errorDetail = error.response?.data?.detail || error.response?.data?.message || ''
    if (
      error.response?.status === 401 ||
      (error.response?.status === 409 &&
        typeof errorDetail === 'string' &&
        (errorDetail.includes('Session expired') ||
          errorDetail.includes('세션') ||
          errorDetail.includes('Session expired or invalid')))
    ) {
      console.warn('⚠️ [세션 에러] 세션이 유효하지 않습니다. localStorage에서 세션 제거:', {
        status: error.response?.status,
        detail: errorDetail,
        url: error.config?.url,
      })
      localStorage.removeItem('sessionId')
      window.dispatchEvent(new CustomEvent('app:session-invalid'))
    }

    // 500 에러인 경우 상세 정보 출력
    if (error.response?.status === 500) {
      console.error('❌ [500 Error Detail]', {
        detail: error.response?.data?.detail,
        fullData: error.response?.data,
      })
    }
    return Promise.reject(error)
  },
)

export default client

