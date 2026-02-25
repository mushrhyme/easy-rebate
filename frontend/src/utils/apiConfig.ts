/**
 * API 설정 유틸리티
 * 외부 접속 시에도 올바른 백엔드 URL을 동적으로 생성
 */

/**
 * API 기본 URL을 가져옵니다
 * - VITE_API_BASE_URL 있으면 사용
 * - localhost/127.0.0.1 + 포트 3002|5173 → 빈 문자열 (같은 origin, Vite proxy 사용)
 * - 그 외(192.168.x.x 등 IP 접속) → http://현재호스트:8000 (백엔드 직접 호출, CORS에 LOCAL_IP 필요)
 */
export const getApiBaseUrl = (): string => {
  if (import.meta.env.VITE_API_BASE_URL) {
    console.log('🔵 [API Config] 환경 변수에서 API URL 사용:', import.meta.env.VITE_API_BASE_URL)
    return import.meta.env.VITE_API_BASE_URL
  }

  const host = window.location.hostname
  const port = window.location.port
  const isLocalhost = host === 'localhost' || host === '127.0.0.1'
  if (isLocalhost && (port === '3002' || port === '5173')) {
    console.log('🔵 [API Config] localhost 개발 서버 - 프록시 사용 (baseURL: "")')
    return '' // same origin → Vite proxy /api → 127.0.0.1:8000
  }

  // IP(192.168.0.10 등)로 접속 시 프록시를 타지 않고 백엔드(8000) 직접 호출
  const apiHost = host === 'localhost' ? '127.0.0.1' : host
  const url = `http://${apiHost}:8000`
  console.log('🔵 [API Config] API URL (직접 호출):', url)
  return url
}

/**
 * WebSocket URL을 가져옵니다
 */
export const getWebSocketUrl = (path: string): string => {
  const apiBaseUrl = getApiBaseUrl()
  const wsBaseUrl = apiBaseUrl.replace(/^http/, 'ws')
  return `${wsBaseUrl}${path}`
}

/**
 * 페이지 이미지 표시용 절대 URL 생성.
 * API가 Windows 경로(백슬래시) 또는 앞에 / 없는 경로를 반환해도 항상 올바른 URL로 변환.
 */
export const getPageImageAbsoluteUrl = (imageUrl: string | null | undefined): string | null => {
  if (imageUrl == null || imageUrl === '') return null
  if (imageUrl.startsWith('http')) return imageUrl
  const normalized = imageUrl.replace(/\\/g, '/').replace(/^\/?/, '/')
  return `${getApiBaseUrl()}${normalized}`
}
