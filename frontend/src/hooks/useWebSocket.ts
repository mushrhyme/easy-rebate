/**
 * WebSocket 훅
 */
import { useEffect, useRef, useState } from 'react'
import type { WebSocketMessage } from '@/types'
import { getWebSocketUrl } from '@/utils/apiConfig'

interface UseWebSocketOptions {
  taskId: string | null
  onMessage?: (message: WebSocketMessage) => void
  onError?: (error: Event) => void
  onClose?: () => void
  enabled?: boolean
}

export const useWebSocket = ({
  taskId,
  onMessage,
  onError,
  onClose,
  enabled = true,
}: UseWebSocketOptions) => {
  const [isConnected, setIsConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout>()
  
  // 콜백을 ref로 저장하여 의존성 배열 문제 해결
  const onMessageRef = useRef(onMessage)
  const onErrorRef = useRef(onError)
  const onCloseRef = useRef(onClose)
  
  useEffect(() => {
    onMessageRef.current = onMessage
    onErrorRef.current = onError
    onCloseRef.current = onClose
  }, [onMessage, onError, onClose])

  useEffect(() => {
    if (!taskId || !enabled) {
      // taskId가 없거나 비활성화되면 연결 종료
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
      setIsConnected(false)
      return
    }

    const connect = () => {
      const wsUrl = getWebSocketUrl(`/ws/processing/${taskId}`)
      console.log('WebSocket 연결 시도:', wsUrl)
      const ws = new WebSocket(wsUrl)

      ws.onopen = () => {
        setIsConnected(true)
        console.log('WebSocket connected:', taskId)
      }

      ws.onmessage = (event) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data)
          onMessageRef.current?.(message) // ref를 통해 최신 콜백 호출
        } catch (error) {
          console.error('Failed to parse WebSocket message:', error)
        }
      }

      ws.onerror = (error) => {
        // WebSocket 에러는 일반적으로 연결 실패를 의미하지만,
        // onclose 이벤트에서 처리되므로 여기서는 조용히 로깅만 수행
        console.warn('⚠️ [WebSocket] 연결 에러 발생 (자동 재연결 시도):', {
          taskId,
          url: wsUrl,
          readyState: ws.readyState, // 0: CONNECTING, 1: OPEN, 2: CLOSING, 3: CLOSED
          error: error instanceof Error ? error.message : 'Unknown error'
        })
        onErrorRef.current?.(error) // ref를 통해 최신 콜백 호출
      }

      ws.onclose = (event) => {
        setIsConnected(false)
        console.log('WebSocket closed:', taskId, {
          code: event.code,
          reason: event.reason,
          wasClean: event.wasClean,
        })
        onCloseRef.current?.() // ref를 통해 최신 콜백 호출

        // 정상 종료가 아니고, 재연결이 활성화되어 있으면 재연결 시도
        if (event.code !== 1000 && enabled && taskId) {
          console.log('WebSocket 재연결 시도 중... (5초 후)')
          reconnectTimeoutRef.current = setTimeout(() => {
            connect()
          }, 5000)
        }
      }

      wsRef.current = ws
    }

    connect()

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [taskId, enabled]) // taskId와 enabled만 의존성으로 사용

  // ping 전송 (연결 유지)
  useEffect(() => {
    if (!isConnected || !wsRef.current) return

    const pingInterval = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send('ping')
      }
    }, 30000) // 30초마다

    return () => clearInterval(pingInterval)
  }, [isConnected])

  return { isConnected }
}
