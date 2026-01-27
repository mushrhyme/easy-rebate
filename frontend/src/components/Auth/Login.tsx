/**
 * 로그인 컴포넌트
 */
import React, { useState } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import './Login.css'

const Login: React.FC = () => {
  const [username, setUsername] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const { login } = useAuth()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username.trim()) {
      setError('ユーザー名を入力してください')
      return
    }

    setIsLoading(true)
    setError('')

    try {
      const result = await login(username.trim())
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
          <div className="form-group">
            <label htmlFor="username" className="form-label">
              ユーザー名
            </label>
            <input
              type="text"
              id="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="form-input"
              placeholder="ユーザー名を入力してください"
              disabled={isLoading}
              autoComplete="username"
            />
          </div>

          {error && (
            <div className="error-message">
              {error}
            </div>
          )}

          <button
            type="submit"
            className="login-button"
            disabled={isLoading || !username.trim()}
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