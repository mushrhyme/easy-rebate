/**
 * API 설정 유틸리티
 * 외부 접속 시에도 올바른 백엔드 URL을 동적으로 생성
 */

/**
 * API 기본 URL을 가져옵니다
 * - localhost/127.0.0.1: 백엔드 8000으로 직접 연결 (CORS 허용됨, 프록시 의존 제거)
 * - 외부 접속: 같은 호스트:8000
 */
export const getApiBaseUrl = (): string => {
  if (import.meta.env.VITE_API_BASE_URL) {
    console.log('🔵 [API Config] 환경 변수에서 API URL 사용:', import.meta.env.VITE_API_BASE_URL)
    return import.meta.env.VITE_API_BASE_URL
  }

  const host = window.location.hostname
  const url = `http://${host}:8000`
  console.log('🔵 [API Config] API URL:', url)
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
