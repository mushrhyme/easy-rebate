/**
 * 메인 App 컴포넌트
 */
import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FormUploadSection } from './components/Upload/FormUploadSection'
import { CustomerSearch } from './components/Search/CustomerSearch'
import { SAPUpload } from './components/SAPUpload/SAPUpload'
import { RagAdminPanel } from './components/Admin/RagAdminPanel'
import { OcrTestTab } from './components/OcrTest/OcrTestTab'
import { documentsApi } from './api/client'
import { FORM_TYPES } from './config/formConfig'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import Login from './components/Auth/Login'
import './App.css'

type Tab = 'upload' | 'search' | 'sap_upload' | 'ocr_test' | 'rag_admin'

// 문서 인터페이스
interface Document {
  pdf_filename: string
  form_type: string | null
  total_pages: number
  upload_date?: string
  created_at?: string
  data_year?: number
  data_month?: number
}

// 년월별 그룹화된 데이터
interface YearMonthGroup {
  year: number
  month: number
  documents: Document[]
  totalFiles: number
  totalPages: number
}


function AppContent() {
  const { user, logout } = useAuth()
  const [activeTab, setActiveTab] = useState<Tab>('upload')
  const [sidebarOpen, setSidebarOpen] = useState(false) // 사이드바는 기본적으로 닫혀있음

  // 모든 문서 조회 (드롭다운 표시를 위해)
  const { data: documentsData } = useQuery({
    queryKey: ['documents', 'all'],
    queryFn: () => documentsApi.getList(),
    refetchInterval: 30000,
  })

  // 문서를 년월별로 그룹화
  const groupedData: YearMonthGroup[] = useMemo(() => {
    if (!documentsData?.documents) return []

    const documentsWithYearMonth = documentsData.documents.map((doc: Document) => {
      // 백엔드에서 data_year, data_month가 제공되면 우선 사용
      // 없으면 created_at으로 폴백
      let data_year = doc.data_year
      let data_month = doc.data_month
      
      // data_year, data_month가 없거나 유효하지 않은 경우에만 폴백
      if (!data_year || !data_month || data_year <= 0 || data_month <= 0 || data_month > 12) {
        const dateString = doc.created_at || doc.upload_date
        let uploadDate: Date
        
        if (dateString) {
          uploadDate = new Date(dateString)
          if (isNaN(uploadDate.getTime())) {
            uploadDate = new Date()
          }
        } else {
          uploadDate = new Date()
        }
        
        data_year = data_year || uploadDate.getFullYear()
        data_month = data_month || uploadDate.getMonth() + 1
      }
      
      return {
        ...doc,
        data_year,
        data_month,
      }
    })

    const groups: Record<string, YearMonthGroup> = {}

    documentsWithYearMonth.forEach((doc: Document) => {
      const year = doc.data_year || new Date().getFullYear()
      const month = doc.data_month || new Date().getMonth() + 1
      const key = `${year}-${month}`
      if (!groups[key]) {
        groups[key] = {
          year,
          month,
          documents: [],
          totalFiles: 0,
          totalPages: 0,
        }
      }
      groups[key].documents.push(doc)
      groups[key].totalFiles++
      groups[key].totalPages += doc.total_pages
    })

    // 년월 기준으로 정렬 (최신순)
    return Object.values(groups).sort((a, b) => {
      if (a.year !== b.year) return b.year - a.year
      return (b.month || 0) - (a.month || 0)
    })
  }, [documentsData])

  const isAdmin = user?.username === 'admin'

  return (
    <div className="app">
      <aside
        className={`app-sidebar ${sidebarOpen ? 'open' : ''}`}
        onMouseEnter={() => setSidebarOpen(true)}
        onMouseLeave={() => setSidebarOpen(false)}
      >
        <div className="sidebar-toggle-area">
          {sidebarOpen ? (
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              className="sidebar-arrow-icon"
            >
              <path
                d="M15 18L9 12L15 6"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          ) : (
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              className="sidebar-arrow-icon"
            >
              <path
                d="M9 18L15 12L9 6"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          )}
        </div>

        <div className="sidebar-content">
          <div className="sidebar-user-info">
            <div className="user-avatar">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M20 21V19C20 17.9391 19.5786 16.9217 18.8284 16.1716C18.0783 15.4214 17.0609 15 16 15H8C6.93913 15 5.92172 15.4214 5.17157 16.1716C4.42143 16.9217 4 17.9391 4 19V21M16 7C16 9.20914 14.2091 11 12 11C9.79086 11 8 9.20914 8 7C8 4.79086 9.79086 3 12 3C14.2091 3 16 4.79086 16 7Z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </div>
            <div className="user-details">
              <div className="user-name">{user?.display_name || user?.username}</div>
              <button className="logout-button" onClick={logout}>
                ログアウト
              </button>
            </div>
          </div>

          <div className="sidebar-menu">
            <button
              className={`sidebar-button ${activeTab === 'upload' ? 'active' : ''}`}
              onClick={() => {
                setActiveTab('upload')
              }}
            >
              アップロード
            </button>
            <button
              className={`sidebar-button ${activeTab === 'search' ? 'active' : ''}`}
              onClick={() => {
                setActiveTab('search')
              }}
            >
              請求
            </button>
            <button
              className={`sidebar-button ${activeTab === 'sap_upload' ? 'active' : ''}`}
              onClick={() => {
                setActiveTab('sap_upload')
              }}
            >
              SAPアップロード
            </button>
            {isAdmin && (
              <button
                className={`sidebar-button ${activeTab === 'ocr_test' ? 'active' : ''}`}
                onClick={() => setActiveTab('ocr_test')}
              >
                OCRテスト
              </button>
            )}
            {isAdmin && (
              <button
                className={`sidebar-button ${activeTab === 'rag_admin' ? 'active' : ''}`}
                onClick={() => {
                  setActiveTab('rag_admin')
                }}
              >
                ベクターDB管理
              </button>
            )}
          </div>
        </div>
      </aside>

      <main className="app-main">
        {activeTab === 'upload' && (
          <div className="upload-tab">
            <div className="upload-header">
              <div className="upload-title-container">
                <div className="upload-title-icon">
                  <svg width="32" height="32" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M9 12L11 14L15 10M21 12C21 16.9706 16.9706 21 12 21C7.02944 21 3 16.9706 3 12C3 7.02944 7.02944 3 12 3C16.9706 3 21 7.02944 21 12Z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </div>
                <h1 className="upload-title">
                  <span className="upload-title-main">リベート管理システム</span>
                  <span className="upload-title-sub">Rebate Management System</span>
                </h1>
              </div>
            </div>
            <div className="upload-sections">
              {FORM_TYPES.map((formType) => (
                <FormUploadSection key={formType} formType={formType} />
              ))}
            </div>
          </div>
        )}

        {activeTab === 'search' && (
          <div className="search-tab">
            <CustomerSearch />
          </div>
        )}

        {activeTab === 'sap_upload' && (
          <div className="sap-upload-tab-wrapper">
            <SAPUpload />
          </div>
        )}

        {isAdmin && activeTab === 'ocr_test' && (
          <div className="ocr-test-tab-wrapper">
            <OcrTestTab />
          </div>
        )}

        {activeTab === 'rag_admin' && (
          <div className="sap-upload-tab-wrapper">
            <RagAdminPanel />
          </div>
        )}
      </main>
    </div>
  )
}

function App() {
  return (
    <AuthProvider>
      <AppWithAuth />
    </AuthProvider>
  )
}

function AppWithAuth() {
  const { user, isLoading } = useAuth()

  if (isLoading) {
    return (
      <div className="loading-container">
        <div className="loading-spinner">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M12 2V6M12 18V22M4.93 4.93L7.76 7.76M16.24 16.24L19.07 19.07M2 12H6M18 12H22M4.93 19.07L7.76 16.24M16.24 7.76L19.07 4.93" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </div>
        <p>読み込み中...</p>
      </div>
    )
  }

  if (!user) {
    return <Login />
  }

  return <AppContent />
}

export default App