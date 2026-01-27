/**
 * 인증 컨텍스트
 */
import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react'
import { authApi } from '../api/client'

export interface User {
  user_id: number
  username: string
  display_name: string
  is_active: boolean
  last_login_at?: string
  login_count: number
}

interface AuthContextType {
  user: User | null
  sessionId: string | null
  isLoading: boolean
  login: (username: string) => Promise<{ success: boolean; message: string }>
  logout: () => Promise<void>
  checkAuth: () => Promise<boolean>
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

      if (data.valid) {
        setUser(data.user)
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

  const login = async (username: string): Promise<{ success: boolean; message: string }> => {
    try {
      setIsLoading(true)
      console.log('🔵 [로그인] 로그인 시도:', username)

      const data = await authApi.login(username)
      console.log('🔵 [로그인] API 응답:', data)

      if (data.success) {
        console.log('✅ [로그인] 로그인 성공:', {
          user_id: data.user_id,
          username: data.username,
          session_id: data.session_id?.substring(0, 20) + '...'
        })
        setUser({
          user_id: data.user_id,
          username: data.username,
          display_name: data.display_name,
          is_active: true,
          login_count: 0
        })
        setSessionId(data.session_id)
        localStorage.setItem('sessionId', data.session_id)
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
      const errorMessage = error?.response?.data?.detail || error?.message || '로그인 중 오류가 발생했습니다'
      return { success: false, message: errorMessage }
    } finally {
      setIsLoading(false)
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

  const value: AuthContextType = {
    user,
    sessionId,
    isLoading,
    login,
    logout,
    checkAuth
  }

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  )
}