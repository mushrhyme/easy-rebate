/**
 * 인증 컨텍스트
 */
import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react'
import { authApi } from '../api/client'

export interface User {
  user_id: number
  username: string
  display_name: string
  display_name_ja?: string
  is_active: boolean
  is_admin?: boolean
  last_login_at?: string
  login_count: number
  must_change_password?: boolean
}

interface AuthContextType {
  user: User | null
  sessionId: string | null
  isLoading: boolean
  mustChangePassword: boolean
  login: (username: string, password: string) => Promise<{ success: boolean; message: string }>
  logout: () => Promise<void>
  checkAuth: () => Promise<boolean>
  changePassword: (currentPassword: string, newPassword: string) => Promise<{ success: boolean; message: string }>
  clearMustChangePassword: () => void
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export const useAuth = () => {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}

interface AuthProviderProps {
  children: ReactNode
}

export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [mustChangePassword, setMustChangePassword] = useState(false)

  // 세션 ID를 로컬 스토리지에서 불러오기
  useEffect(() => {
    const storedSessionId = localStorage.getItem('sessionId')
    if (storedSessionId) {
      setSessionId(storedSessionId)
      checkAuthStatus(storedSessionId)
    } else {
      setIsLoading(false)
    }
  }, [])

  const checkAuthStatus = async (sid: string): Promise<boolean> => {
    try {
      // 임시로 세션 ID를 로컬 스토리지에 설정 (API 호출용)
      const originalSessionId = localStorage.getItem('sessionId')
      localStorage.setItem('sessionId', sid)

      const data = await authApi.validateSession()

      if (data.valid && data.user) {
        setUser({
          ...data.user,
          is_active: true,
          is_admin: (data.user as { is_admin?: boolean }).is_admin ?? false,
          login_count: 0,
          must_change_password: (data as { must_change_password?: boolean }).must_change_password ?? false,
        })
        setMustChangePassword((data as { must_change_password?: boolean }).must_change_password ?? false)
        return true
      }

      // 유효하지 않은 세션
      localStorage.removeItem('sessionId')
      setSessionId(null)
      setUser(null)
      return false
    } catch (error) {
      console.error('Auth check failed:', error)
      localStorage.removeItem('sessionId')
      setSessionId(null)
      setUser(null)
      return false
    } finally {
      setIsLoading(false)
    }
  }

  const login = async (username: string, password: string): Promise<{ success: boolean; message: string }> => {
    try {
      // 전역 isLoading은 세션 체크용만 사용. 로그인 시도 시 바꾸지 않아 로그인 화면이 유지되고 에러 메시지가 보이도록 함.
      console.log('🔵 [로그인] 로그인 시도:', username)

      const data = await authApi.login(username, password)
      console.log('🔵 [로그인] API 응답:', data)

      if (data.success) {
        const mustChange = data.must_change_password ?? false
        console.log('✅ [로그인] 로그인 성공:', {
          user_id: data.user_id,
          username: data.username,
          session_id: data.session_id?.substring(0, 20) + '...',
          must_change_password: mustChange,
        })
        setUser({
          user_id: data.user_id!,
          username: data.username!,
          display_name: data.display_name!,
          display_name_ja: data.display_name_ja,
          is_active: true,
          login_count: 0,
          must_change_password: mustChange,
        })
        setMustChangePassword(mustChange)
        setSessionId(data.session_id ?? null)
        if (data.session_id) localStorage.setItem('sessionId', data.session_id)
        return { success: true, message: data.message }
      } else {
        console.warn('⚠️ [로그인] 로그인 실패:', data.message)
        return { success: false, message: data.message }
      }
    } catch (error: any) {
      console.error('❌ [로그인] 예외 발생:', {
        error,
        message: error?.message,
        response: error?.response?.data,
        status: error?.response?.status
      })
      const isNetworkError = error?.code === 'ERR_NETWORK' || error?.message === 'Network Error'
      const errorMessage = isNetworkError
        ? 'サーバーに接続できません。バックエンド(ポート8000)が起動しているか確認してください。'
        : (error?.response?.data?.detail || error?.message || 'ログイン中にエラーが発生しました')
      return { success: false, message: errorMessage }
    }
  }

  const logout = async (): Promise<void> => {
    try {
      if (sessionId) {
        await authApi.logout()
      }
    } catch (error) {
      console.error('Logout error:', error)
    } finally {
      setUser(null)
      setSessionId(null)
      localStorage.removeItem('sessionId')
      setIsLoading(false)
    }
  }

  const checkAuth = async (): Promise<boolean> => {
    if (!sessionId) return false
    return await checkAuthStatus(sessionId)
  }

  const changePassword = async (
    currentPassword: string,
    newPassword: string
  ): Promise<{ success: boolean; message: string }> => {
    try {
      const data = await authApi.changePassword(currentPassword, newPassword)
      if (data.success) {
        setMustChangePassword(false)
        setUser((prev) => (prev ? { ...prev, must_change_password: false } : null))
      }
      return data
    } catch (error: any) {
      const message = error?.response?.data?.detail || error?.message || '비밀번호 변경에 실패했습니다'
      return { success: false, message: typeof message === 'string' ? message : JSON.stringify(message) }
    }
  }

  const clearMustChangePassword = () => {
    setMustChangePassword(false)
    setUser((prev) => (prev ? { ...prev, must_change_password: false } : null))
  }

  const value: AuthContextType = {
    user,
    sessionId,
    isLoading,
    mustChangePassword,
    login,
    logout,
    checkAuth,
    changePassword,
    clearMustChangePassword,
  }

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  )
}