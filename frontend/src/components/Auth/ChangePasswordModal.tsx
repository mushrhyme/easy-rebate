/**
 * 초기 비밀번호(ID와 동일)일 때 강제로 띄우는 비밀번호 변경
 * - standalone: 로그인 직후 전용 풀페이지(다음 화면 전환 전)
 * - 그 외: 모달 오버레이 (레거시)
 */
import React, { useState } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import './ChangePasswordModal.css'
import './Login.css'

interface ChangePasswordModalProps {
  /** true면 로그인 직후 풀페이지로 표시(메인 화면 전에만 보임) */
  standalone?: boolean
}

const EyeIcon = () => (
  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 5c-5 0-8 4-10 7 2 3 5 7 10 7s8-4 10-7c-2-3-5-7-10-7z" />
    <circle cx="12" cy="12" r="2.5" />
  </svg>
)
const EyeOffIcon = () => (
  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M3.98 8.88A12 12 0 0 1 12 6c4.92 0 8.24 2.51 9.58 5.12a12 12 0 0 1-2.4 3.24" />
    <path d="M14 14.5a2.5 2.5 0 1 1-3.5-3.5" />
    <path d="M4 4l16 16" />
  </svg>
)

const ChangePasswordModal: React.FC<ChangePasswordModalProps> = ({ standalone = false }) => {
  const { changePassword } = useAuth()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [newPasswordConfirm, setNewPasswordConfirm] = useState('')
  const [showCurrent, setShowCurrent] = useState(false)
  const [showNew, setShowNew] = useState(false)
  const [showNewConfirm, setShowNewConfirm] = useState(false)
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (!currentPassword.trim()) {
      setError('現在のパスワードを入力してください')
      return
    }
    if (!newPassword.trim()) {
      setError('新しいパスワードを入力してください')
      return
    }
    if (newPassword.length < 1) {
      setError('新しいパスワードを入力してください')
      return
    }
    if (newPassword !== newPasswordConfirm) {
      setError('新しいパスワードが一致しません')
      return
    }

    setIsLoading(true)
    try {
      const result = await changePassword(currentPassword, newPassword)
      if (result.success) {
        setCurrentPassword('')
        setNewPassword('')
        setNewPasswordConfirm('')
      } else {
        setError(result.message)
      }
    } catch (err) {
      setError('パスワード変更中にエラーが発生しました')
    } finally {
      setIsLoading(false)
    }
  }

  const formOnly = (
    <form onSubmit={handleSubmit} className="change-password-form">
        <div className="form-group">
          <label htmlFor="current-password" className="form-label">現在のパスワード（初期パスワード＝IDと同じ）</label>
          <div className="password-input-wrap">
            <input
              type={showCurrent ? 'text' : 'password'}
              id="current-password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              className="form-input"
              placeholder="現在のパスワード"
              disabled={isLoading}
              autoComplete="current-password"
            />
            <button type="button" className="password-toggle-btn" onClick={() => setShowCurrent((v) => !v)} tabIndex={-1} aria-label={showCurrent ? 'パスワードを隠す' : 'パスワードを表示'} title={showCurrent ? '隠す' : '表示'}>
              {showCurrent ? <EyeOffIcon /> : <EyeIcon />}
            </button>
          </div>
        </div>
        <div className="form-group">
          <label htmlFor="new-password" className="form-label">新しいパスワード</label>
          <div className="password-input-wrap">
            <input
              type={showNew ? 'text' : 'password'}
              id="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className="form-input"
              placeholder="新しいパスワード"
              disabled={isLoading}
              autoComplete="new-password"
            />
            <button type="button" className="password-toggle-btn" onClick={() => setShowNew((v) => !v)} tabIndex={-1} aria-label={showNew ? 'パスワードを隠す' : 'パスワードを表示'} title={showNew ? '隠す' : '表示'}>
              {showNew ? <EyeOffIcon /> : <EyeIcon />}
            </button>
          </div>
        </div>
        <div className="form-group">
          <label htmlFor="new-password-confirm" className="form-label">新しいパスワード（確認）</label>
          <div className="password-input-wrap">
            <input
              type={showNewConfirm ? 'text' : 'password'}
              id="new-password-confirm"
              value={newPasswordConfirm}
              onChange={(e) => setNewPasswordConfirm(e.target.value)}
              className="form-input"
              placeholder="もう一度入力"
              disabled={isLoading}
              autoComplete="new-password"
            />
            <button type="button" className="password-toggle-btn" onClick={() => setShowNewConfirm((v) => !v)} tabIndex={-1} aria-label={showNewConfirm ? 'パスワードを隠す' : 'パスワードを表示'} title={showNewConfirm ? '隠す' : '表示'}>
              {showNewConfirm ? <EyeOffIcon /> : <EyeIcon />}
            </button>
          </div>
        </div>
        {error && <div className="change-password-error">{error}</div>}
        <button type="submit" className="change-password-submit" disabled={isLoading}>
          {isLoading ? '変更中...' : 'パスワードを変更'}
        </button>
    </form>
  )

  if (standalone) {
    return (
      <div className="login-container" role="dialog" aria-modal="true" aria-labelledby="change-password-title">
        <div className="login-card change-password-standalone-card">
          <div className="login-header">
            <div className="login-logo">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M9 12L11 14L15 10M21 12C21 16.9706 16.9706 21 12 21C7.02944 21 3 16.9706 3 12C3 7.02944 7.02944 3 12 3C16.9706 3 21 7.02944 21 12Z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </div>
            <h1 id="change-password-title" className="login-title">
              <span className="login-title-main">初回パスワードの変更</span>
              <span className="login-title-sub">Change initial password</span>
            </h1>
            <p className="login-subtitle">
              セキュリティのため、新しいパスワードを設定してください。
            </p>
          </div>
          {formOnly}
        </div>
      </div>
    )
  }

  return (
    <div className="change-password-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="change-password-title">
      <div className="change-password-modal">
        <h2 id="change-password-title" className="change-password-modal-title">
          初回パスワードの変更
        </h2>
        <p className="change-password-modal-desc">
          セキュリティのため、初回ログイン時はパスワードの変更が必要です。新しいパスワードを設定してください。
        </p>
        {formOnly}
      </div>
    </div>
  )
}

export default ChangePasswordModal
