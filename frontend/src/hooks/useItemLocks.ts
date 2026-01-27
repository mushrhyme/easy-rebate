/**
 * 아이템 락 상태 WebSocket 훅
 */
import { useEffect, useRef, useState } from 'react'
import { getWebSocketUrl } from '@/utils/apiConfig'
import type { ReviewStatus } from '@/types'

interface LockMessage {
  type: 'lock_acquired' | 'lock_released' | 'connected' | 'ping' | 'pong' | 'review_status_updated'
  item_id?: number
  locked_by?: string
  pdf_filename?: string
  page_number?: number
  current_locks?: Array<{ item_id: number; locked_by: string }> // 초기 연결 시 현재 락 목록
  review_status?: {
    first_review?: { checked: boolean }
    second_review?: { checked: boolean }
  }
}

interface UseItemLocksOptions {
  pdfFilename: string | null
  pageNumber: number | null
  onLockUpdate?: (itemId: number, lockedBy: string | null) => void
  onReviewStatusUpdate?: (itemId: number, reviewStatus: ReviewStatus) => void
  enabled?: boolean
}

export const useItemLocks = ({
  pdfFilename,
  pageNumber,
  onLockUpdate,
  onReviewStatusUpdate,
  enabled = true,
}: UseItemLocksOptions) => {
  const [isConnected, setIsConnected] = useState(false)
  const [lockedItems, setLockedItems] = useState<Map<number, string>>(new Map()) // {itemId: sessionId}
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout>()

  useEffect(() => {
    if (!pdfFilename || !pageNumber || !enabled) {
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
      setIsConnected(false)
      return
    }

    const connect = () => {
      // 기존 연결이 있으면 먼저 정리
      if (wsRef.current) {
        try {
          wsRef.current.close()
        } catch (e) {
          // 이미 닫혀있을 수 있음
        }
        wsRef.current = null
      }
      
      const wsUrl = getWebSocketUrl('/ws/locks')
      console.log('🔵 [WebSocket] 연결 시도:', wsUrl)
      
      let ws: WebSocket
      try {
        ws = new WebSocket(wsUrl)
      } catch (error) {
        console.error('❌ [WebSocket] 연결 생성 실패:', error)
        // 연결 생성 실패 시 재시도
        if (enabled && pdfFilename && pageNumber) {
          reconnectTimeoutRef.current = setTimeout(() => {
            connect()
          }, 5000)
        }
        return
      }

      ws.onopen = () => {
        console.log('✅ [WebSocket] 연결 성공:', { pdfFilename, pageNumber })
        // 연결 후 첫 메시지로 구독 정보 전송
        const subscribeMessage = {
          type: 'subscribe',
          pdf_filename: pdfFilename,
          page_number: pageNumber,
        }
        console.log('🔵 [WebSocket] 구독 메시지 전송:', subscribeMessage)
        ws.send(JSON.stringify(subscribeMessage))
      }

      ws.onmessage = (event) => {
        try {
          const message: LockMessage = JSON.parse(event.data)
          console.log('🔵 [WebSocket] 메시지 수신:', message.type, message)

          if (message.type === 'connected') {
            setIsConnected(true)
            // 현재 활성 락 목록 초기화
            if (message.current_locks && message.current_locks.length > 0) {
              setLockedItems((prev) => {
                const next = new Map(prev)
                message.current_locks!.forEach(lock => {
                  next.set(lock.item_id, lock.locked_by)
                })
                return next
              })
            }
            return
          }

          if (message.type === 'error') {
            console.error('Lock WebSocket error:', message)
            return
          }

          if (message.type === 'lock_acquired' && message.item_id && message.locked_by) {
            setLockedItems((prev) => {
              const next = new Map(prev)
              next.set(message.item_id!, message.locked_by!)
              return next
            })
            onLockUpdate?.(message.item_id, message.locked_by)
          } else if (message.type === 'lock_released' && message.item_id) {
            setLockedItems((prev) => {
              const next = new Map(prev)
              next.delete(message.item_id!)
              return next
            })
            onLockUpdate?.(message.item_id, null)
          } else if (message.type === 'pong') {
            // 연결 유지 확인
          } else if (message.type === 'review_status_updated' && message.item_id && message.review_status) {
            console.log('🔵 [WebSocket] review_status_updated 수신:', {
              item_id: message.item_id,
              review_status: message.review_status,
            })
            onReviewStatusUpdate?.(message.item_id, message.review_status)
            console.log('✅ [WebSocket] onReviewStatusUpdate 콜백 호출 완료')
          }
        } catch (error) {
          console.error('Failed to parse lock message:', error)
        }
      }

      ws.onerror = (error) => {
        // WebSocket 에러는 일반적으로 연결 실패를 의미하지만,
        // onclose 이벤트에서 처리되므로 여기서는 조용히 로깅만 수행
        console.warn('⚠️ [WebSocket] 연결 에러 발생 (자동 재연결 시도):', {
          readyState: ws.readyState,
          url: wsUrl,
          error: error instanceof Error ? error.message : 'Unknown error'
        })
        // 에러는 치명적이지 않으므로 앱은 정상 작동 계속
      }

      ws.onclose = (event) => {
        const isNormalClose = event.code === 1000
        const isAbnormalClose = event.code === 1006 // Abnormal closure
        
        if (isAbnormalClose) {
          console.warn('⚠️ [WebSocket] 비정상 종료 (자동 재연결 시도):', {
            code: event.code,
            reason: event.reason || 'Connection closed abnormally',
            wasClean: event.wasClean,
          })
        } else {
          console.log('⚠️ [WebSocket] 연결 종료:', {
            code: event.code,
            reason: event.reason,
            wasClean: event.wasClean,
          })
        }
        
        setIsConnected(false)
        // 연결 끊김 시 락 상태 초기화 (재연결 시 다시 받음)
        setLockedItems(new Map())

        // 재연결 시도 (정상 종료가 아닌 경우에만)
        // 1000: Normal closure
        // 1001: Going away
        // 1006: Abnormal closure (네트워크 문제 등)
        if (!isNormalClose && enabled && pdfFilename && pageNumber) {
          const reconnectDelay = isAbnormalClose ? 3000 : 5000 // 비정상 종료는 더 빠르게 재연결
          console.log(`🔄 [WebSocket] 재연결 시도 중... (${reconnectDelay/1000}초 후)`)
          reconnectTimeoutRef.current = setTimeout(() => {
            if (enabled && pdfFilename && pageNumber) {
              connect()
            }
          }, reconnectDelay)
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
  }, [pdfFilename, pageNumber, enabled, onLockUpdate, onReviewStatusUpdate])

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

  return {
    isConnected,
    lockedItems,
    isItemLocked: (itemId: number) => lockedItems.has(itemId),
    getLockedBy: (itemId: number) => lockedItems.get(itemId) || null,
  }
}
