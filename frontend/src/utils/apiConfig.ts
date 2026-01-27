/**
 * API 설정 유틸리티
 * 외부 접속 시에도 올바른 백엔드 URL을 동적으로 생성
 */

/**
 * API 기본 URL을 가져옵니다
 * 환경 변수가 있으면 사용하고, 없으면 현재 호스트 기반으로 생성
 */
export const getApiBaseUrl = (): string => {
  if (import.meta.env.VITE_API_BASE_URL) {
    console.log('🔵 [API Config] 환경 변수에서 API URL 사용:', import.meta.env.VITE_API_BASE_URL)
    return import.meta.env.VITE_API_BASE_URL
  }
  
  // 개발 환경에서 현재 호스트 기반으로 API URL 생성
  // 외부 접속 시에도 같은 호스트의 백엔드에 연결
  const host = window.location.hostname
  const port = '8000'
  
  // localhost나 127.0.0.1이면 그대로 사용
  if (host === 'localhost' || host === '127.0.0.1') {
    const url = `http://${host}:${port}`
    console.log('🔵 [API Config] 로컬호스트 API URL:', url)
    return url
  }
  
  // 외부 IP 접속 시 같은 IP의 백엔드에 연결
  const url = `http://${host}:${port}`
  console.log('🔵 [API Config] 외부 IP API URL:', url, '(현재 호스트:', host, ')')
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
