/**
 * 검토 탭 등에서 렌더 오류 시 하얀 화면 대신 에러 메시지 표시
 */
import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  fallbackTitle?: string
}

interface State {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('[ErrorBoundary]', error, errorInfo)
  }

  render() {
    if (this.state.hasError && this.state.error) {
      return (
        <div
          className="error-boundary-fallback"
          style={{
            padding: '2rem',
            background: '#fef2f2',
            color: '#b91c1c',
            minHeight: '200px',
            overflow: 'auto',
          }}
        >
          <h3 style={{ margin: '0 0 0.75rem 0', fontSize: '1.1rem' }}>
            {this.props.fallbackTitle ?? '表示エラー'}
          </h3>
          <pre style={{ margin: 0, fontSize: '0.85rem', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
            {this.state.error.message}
          </pre>
        </div>
      )
    }
    return this.props.children
  }
}
