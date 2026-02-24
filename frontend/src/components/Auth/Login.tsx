/**
 * 로그인 컴포넌트
 */
import React, { useState } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import './Login.css'

const Login: React.FC = () => {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const { login } = useAuth()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username.trim()) {
      setError('ログインIDを入力してください')
      return
    }
    if (!password) {
      setError('パスワードを入力してください')
      return
    }

    setIsLoading(true)
    setError('')

    try {
      const result = await login(username.trim(), password)
      if (!result.success) {
        setError(result.message)
      }
    } catch (err) {
      setError('ログイン中にエラーが発生しました')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="login-container">
      <div className="login-card">
        <div className="login-header">
          <div className="login-logo">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M9 12L11 14L15 10M21 12C21 16.9706 16.9706 21 12 21C7.02944 21 3 16.9706 3 12C3 7.02944 7.02944 3 12 3C16.9706 3 21 7.02944 21 12Z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </div>
          <h1 className="login-title">
            <span className="login-title-main">リベート管理システム</span>
            <span className="login-title-sub">Rebate Management System</span>
          </h1>
          <p className="login-subtitle">ログインしてシステムをご利用ください</p>
        </div>

        <form className="login-form" onSubmit={handleSubmit}>
          <div className="login-id-password-group">
            <p className="login-group-label">ユーザーID／パスワード</p>
            <div className="form-group">
              <input
                type="text"
                id="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="form-input"
                placeholder="イントラネットIDを入力してください"
                disabled={isLoading}
                autoComplete="username"
                aria-label="ログインID"
              />
            </div>
            <div className="form-group">
              <div className="password-input-wrap">
              <input
                type={showPassword ? 'text' : 'password'}
                id="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="form-input"
                placeholder="初期パスワードはIDと同一です"
                disabled={isLoading}
                autoComplete="current-password"
                aria-label="パスワード"
              />
              <button
                type="button"
                className="password-toggle-btn"
                onClick={() => setShowPassword((v) => !v)}
                tabIndex={-1}
                aria-label={showPassword ? 'パスワードを隠す' : 'パスワードを表示'}
                title={showPassword ? 'パスワードを隠す' : 'パスワードを表示'}
              >
                {showPassword ? (
                  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M3.98 8.88A12 12 0 0 1 12 6c4.92 0 8.24 2.51 9.58 5.12a12 12 0 0 1-2.4 3.24" />
                    <path d="M14 14.5a2.5 2.5 0 1 1-3.5-3.5" />
                    <path d="M4 4l16 16" />
                  </svg>
                ) : (
                  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 5c-5 0-8 4-10 7 2 3 5 7 10 7s8-4 10-7c-2-3-5-7-10-7z" />
                    <circle cx="12" cy="12" r="2.5" />
                  </svg>
                )}
              </button>
            </div>
            </div>
          </div>

          {error && (
            <div className="login-error-wrap">
              <div className="error-message">{error}</div>
              <p className="login-error-hint">パスワードを忘れた場合は管理者にご連絡ください。</p>
            </div>
          )}

          <button
            type="submit"
            className="login-button"
            disabled={isLoading || !username.trim() || !password}
          >
            {isLoading ? 'ログイン中...' : 'ログイン'}
          </button>
        </form>

        <div className="login-footer">
          <p className="login-info">
            ※ 管理者承認が必要なユーザーのみがログイン可能です
          </p>
        </div>
      </div>
    </div>
  )
}

export default Login