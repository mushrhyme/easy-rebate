/**
 * 메인 App 컴포넌트
 */
import { useState, useMemo, useRef, useCallback, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FormUploadSection } from './components/Upload/FormUploadSection'
import { UploadedFilesList } from './components/Upload/UploadedFilesList'
import { UploadPagePreview } from './components/Upload/UploadPagePreview'
import { UploadProgressList } from './components/Upload/UploadProgressList'
import type { UploadProgressPayload } from './components/Upload/FormUploadSection'
import { CustomerSearch } from './components/Search/CustomerSearch'
import { SAPUpload } from './components/SAPUpload/SAPUpload'
import { RagAdminPanel } from './components/Admin/RagAdminPanel'
import { AnswerKeyTab } from './components/AnswerKey/AnswerKeyTab'
import { Dashboard } from './components/Dashboard/Dashboard'
import { documentsApi } from './api/client'
import { UPLOAD_CHANNELS } from './config/formConfig'
import type { UploadChannel } from './types'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import Login from './components/Auth/Login'
import ChangePasswordModal from './components/Auth/ChangePasswordModal'
import { getDocumentYearMonth } from './utils/documentDate'
import './App.css'

type Tab = 'dashboard' | 'upload' | 'search' | 'sap_upload' | 'ocr_test' | 'rag_admin'

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
  const isAdmin = user?.is_admin === true || user?.username === 'admin'
  const [activeTab, setActiveTab] = useState<Tab>('upload')

  // 비관리자가 관리자(기준정보) 탭이 선택된 상태면 업로드 탭으로 전환. 현황 탭은 모든 사용자 허용
  useEffect(() => {
    if (!isAdmin && activeTab === 'rag_admin') {
      setActiveTab('upload')
    }
  }, [isAdmin, activeTab])

  /** 정답지 탭으로 이동 시 선택할 문서. RAG에서 오면 relative_path 있음 → img 기반 뷰 */
  const [initialDocumentForAnswerKey, setInitialDocumentForAnswerKey] = useState<{
    pdf_filename: string
    total_pages: number
    relative_path: string | null
  } | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(false) // 사이드바는 기본적으로 닫혀있음
  const [selectedUploadChannel, setSelectedUploadChannel] = useState<UploadChannel | null>(UPLOAD_CHANNELS[0] ?? null)
  const [selectedDocumentForPreview, setSelectedDocumentForPreview] = useState<{ pdfFilename: string; totalPages: number } | null>(null)
  const [uploadProgressByChannel, setUploadProgressByChannel] = useState<Partial<Record<UploadChannel, UploadProgressPayload>>>({})
  const removeFileByChannelRef = useRef<Partial<Record<UploadChannel, (fileName: string) => void>>>({})

  /** 채널별 날짜 필터 (업로드 블록 + 업로드 완료 목록 연동) */
  const [dateFilterByChannel, setDateFilterByChannel] = useState<Partial<Record<UploadChannel, { year: number | null; month: number | null }>>>({})
  const setChannelDateFilter = useCallback((channel: UploadChannel, year: number | null, month: number | null) => {
    setDateFilterByChannel((prev) => ({ ...prev, [channel]: { year, month } }))
  }, [])

  const isSidebarOpen = sidebarOpen

  // 모든 문서 조회 (드롭다운 표시용, 업로드/검토와 동일하게 img 시드 문서 제외)
  const { data: documentsData } = useQuery({
    queryKey: ['documents', 'all'],
    queryFn: () => documentsApi.getList(undefined, { exclude_img_seed: true }),
    refetchInterval: 30000,
  })

  // 문서를 년월별로 그룹화
  const groupedData: YearMonthGroup[] = useMemo(() => {
    if (!documentsData?.documents) return []

    const groups: Record<string, YearMonthGroup> = {}

    documentsData.documents.forEach((doc: Document) => {
      const { year, month } = getDocumentYearMonth(doc)
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
      return b.month - a.month
    })
  }, [documentsData])

  return (
    <div className="app">
      <aside
        className={`app-sidebar ${isSidebarOpen ? 'open' : ''}`}
        onMouseEnter={() => setSidebarOpen(true)}
        onMouseLeave={() => setSidebarOpen(false)}
      >
        <div className="sidebar-toggle-area">
          {isSidebarOpen ? (
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
          <div className="sidebar-menu">
            <button
              className={`sidebar-button ${activeTab === 'dashboard' ? 'active' : ''}`}
              onClick={() => setActiveTab('dashboard')}
            >
              現況
            </button>
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
            <button
              className={`sidebar-button ${activeTab === 'ocr_test' ? 'active' : ''}`}
              onClick={() => setActiveTab('ocr_test')}
            >
              解答作成
            </button>
            {isAdmin && (
              <button
                className={`sidebar-button ${activeTab === 'rag_admin' ? 'active' : ''}`}
                onClick={() => {
                  setActiveTab('rag_admin')
                }}
              >
                管理者画面
              </button>
            )}
          </div>
        </div>
      </aside>

      <main className="app-main">
        {activeTab === 'dashboard' && (
          <div className="dashboard-tab-wrapper">
            <Dashboard
              onOpenAnswerKeyWithDocument={(payload) => {
                setInitialDocumentForAnswerKey(payload)
                setActiveTab('ocr_test')
              }}
            />
          </div>
        )}
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
              <div className="header-user-info">
                <div className="header-user-avatar">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M20 21V19C20 17.9391 19.5786 16.9217 18.8284 16.1716C18.0783 15.4214 17.0609 15 16 15H8C6.93913 15 5.92172 15.4214 5.17157 16.1716C4.42143 16.9217 4 17.9391 4 19V21M16 7C16 9.20914 14.2091 11 12 11C9.79086 11 8 9.20914 8 7C8 4.79086 9.79086 3 12 3C14.2091 3 16 4.79086 16 7Z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </div>
                <span className="header-user-name">
                  {user?.display_name_ja || user?.display_name || user?.username}
                </span>
                <button type="button" className="header-logout-button" onClick={logout}>
                  ログアウト
                </button>
              </div>
            </div>
            <div className="upload-body">
              <div className="upload-body-left">
                <div className="upload-body-cards">
                  {UPLOAD_CHANNELS.map((channel) => (
                    <FormUploadSection
                      key={channel}
                      uploadChannel={channel}
                      selectedYear={dateFilterByChannel[channel]?.year ?? null}
                      selectedMonth={dateFilterByChannel[channel]?.month ?? null}
                      onYearMonthChange={(y, m) => setChannelDateFilter(channel, y, m)}
                      onShowFileList={(ch) => {
                        setSelectedUploadChannel(ch)
                        setSelectedDocumentForPreview(null)
                      }}
                      isListSelected={selectedUploadChannel === channel}
                      onUploadProgressChange={(ch, payload) => {
                        setUploadProgressByChannel((prev) => ({ ...prev, [ch]: payload }))
                      }}
                      onRegisterRemove={(ch, removeFn) => {
                        const next = { ...removeFileByChannelRef.current }
                        if (removeFn == null) delete next[ch]
                        else next[ch] = removeFn
                        removeFileByChannelRef.current = next
                      }}
                    />
                  ))}
                </div>
                <div className="upload-body-preview">
                  <UploadPagePreview pdfFilename={selectedDocumentForPreview?.pdfFilename ?? null} />
                </div>
              </div>
              <div className="upload-body-list">
                {selectedUploadChannel ? (
                  <>
                    {uploadProgressByChannel[selectedUploadChannel]?.fileNames?.length ? (
                      <UploadProgressList
                        channel={selectedUploadChannel}
                        fileNames={uploadProgressByChannel[selectedUploadChannel].fileNames}
                        progress={uploadProgressByChannel[selectedUploadChannel].progress}
                        isUploading={uploadProgressByChannel[selectedUploadChannel].isUploading}
                        onRemove={(fileName) => removeFileByChannelRef.current[selectedUploadChannel]?.(fileName)}
                      />
                    ) : null}
                    <UploadedFilesList
                      selectedChannel={selectedUploadChannel}
                      filterYear={dateFilterByChannel[selectedUploadChannel]?.year ?? null}
                      filterMonth={dateFilterByChannel[selectedUploadChannel]?.month ?? null}
                      onSelectDocument={(pdfFilename, totalPages) => setSelectedDocumentForPreview({ pdfFilename, totalPages })}
                      selectedPdfFilename={selectedDocumentForPreview?.pdfFilename ?? null}
                    />
                  </>
                ) : (
                  <div className="upload-list-placeholder">一覧をクリックしてアップロード済みファイルを表示</div>
                )}
              </div>
            </div>
          </div>
        )}

        {activeTab === 'search' && (
          <div className="search-tab">
            <CustomerSearch
              onNavigateToAnswerKey={(pdfFilename) => {
                setInitialDocumentForAnswerKey({
                  pdf_filename: pdfFilename,
                  total_pages: 0,
                  relative_path: null,
                })
                setActiveTab('ocr_test')
              }}
            />
          </div>
        )}

        {activeTab === 'sap_upload' && (
          <div className="sap-upload-tab-wrapper">
            <SAPUpload />
          </div>
        )}

        {activeTab === 'ocr_test' && (
          <div className="answer-key-tab-wrapper">
            <AnswerKeyTab
              initialDocument={initialDocumentForAnswerKey}
              onConsumeInitialDocument={() => setInitialDocumentForAnswerKey(null)}
              onRevokeSuccess={() => setActiveTab('search')}
            />
          </div>
        )}

        {activeTab === 'rag_admin' && isAdmin && (
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
  const { user, isLoading, mustChangePassword } = useAuth()

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

  // 비밀번호 변경 필요 시: 메인 화면으로 넘어가기 전에 풀페이지로 표시
  if (mustChangePassword) {
    return <ChangePasswordModal standalone />
  }

  return <AppContent />
}

export default App