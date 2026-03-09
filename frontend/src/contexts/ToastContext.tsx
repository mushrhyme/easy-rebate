/**
 * 전역 토스트 알림 (성공/에러 메시지)
 * 학습 리クエ스트 등 작업 완료 시 사용자에게 명확한 피드백 제공
 */
import { createContext, useCallback, useContext, useState, useRef, useEffect } from 'react'

type ToastType = 'success' | 'error'

interface ToastState {
  message: string
  type: ToastType
}

interface ToastContextValue {
  showToast: (message: string, type?: ToastType) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

const TOAST_DURATION_MS = 5000

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toast, setToast] = useState<ToastState | null>(null)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clearToast = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current)
      timeoutRef.current = null
    }
    setToast(null)
  }, [])

  const showToast = useCallback(
    (message: string, type: ToastType = 'success') => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current)
      setToast({ message, type })
      timeoutRef.current = setTimeout(clearToast, TOAST_DURATION_MS)
    },
    [clearToast]
  )

  useEffect(() => () => { if (timeoutRef.current) clearTimeout(timeoutRef.current) }, [])

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      {toast && (
        <div
          className={`app-toast app-toast-${toast.type}`}
          role="alert"
          aria-live="polite"
        >
          {toast.type === 'success' && (
            <span className="app-toast-icon" aria-hidden>✓</span>
          )}
          {toast.type === 'error' && (
            <span className="app-toast-icon app-toast-icon-error" aria-hidden>!</span>
          )}
          <span className="app-toast-message">{toast.message}</span>
          <button
            type="button"
            className="app-toast-close"
            onClick={clearToast}
            aria-label="닫기"
          >
            ×
          </button>
        </div>
      )}
    </ToastContext.Provider>
  )
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within ToastProvider')
  return ctx
}
