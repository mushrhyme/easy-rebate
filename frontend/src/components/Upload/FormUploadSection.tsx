/**
 * 업로드 채널별 섹션: FINET(엑셀) / 우편물(Upstage OCR)
 */
import { useState, useRef, useEffect, useMemo, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { useQueryClient } from '@tanstack/react-query'
import { documentsApi } from '@/api/client'
import { useUploadStore } from '@/stores/uploadStore'
import { useWebSocket } from '@/hooks/useWebSocket'
import { UPLOAD_CHANNEL_CONFIGS } from '@/config/formConfig'
import type { UploadChannel } from '@/types'
import type { WebSocketMessage } from '@/types'
import './FormUploadSection.css'

export interface UploadProgressPayload {
  fileNames: string[]
  progress: Record<string, FileProgress>
  isUploading: boolean
}

interface FormUploadSectionProps {
  uploadChannel: UploadChannel
  /** 날짜 필터 (업로드 완료 목록과 연동, App에서 제어) */
  selectedYear?: number | null
  selectedMonth?: number | null
  onYearMonthChange?: (year: number | null, month: number | null) => void
  onShowFileList?: (channel: UploadChannel) => void
  isListSelected?: boolean
  onUploadProgressChange?: (channel: UploadChannel, payload: UploadProgressPayload) => void
  onRegisterRemove?: (channel: UploadChannel, removeFn: ((fileName: string) => void) | null) => void
}

// 파일별 진행 상태 타입
interface FileProgress {
  status: 'pending' | 'processing' | 'completed' | 'error'
  currentPage?: number
  totalPages?: number
  message?: string
  progress?: number
}

export const FormUploadSection = ({ uploadChannel, selectedYear: propYear, selectedMonth: propMonth, onYearMonthChange, onShowFileList, isListSelected, onUploadProgressChange, onRegisterRemove }: FormUploadSectionProps) => {
  const [files, setFiles] = useState<File[]>([])
  const [isUploading, setIsUploading] = useState(false)
  const [isHovered, setIsHovered] = useState(false) // 호버 상태
  const [tooltipPosition, setTooltipPosition] = useState({ top: 0, left: 0 }) // 툴팁 위치
  const [localYear, setLocalYear] = useState<number | null>(null)
  const [localMonth, setLocalMonth] = useState<number | null>(null)
  const isControlled = onYearMonthChange != null
  const selectedYear = isControlled ? (propYear ?? null) : localYear
  const selectedMonth = isControlled ? (propMonth ?? null) : localMonth
  const setSelectedYear = isControlled ? (y: number | null) => onYearMonthChange?.(y, selectedMonth) : setLocalYear
  const setSelectedMonth = isControlled ? (m: number | null) => onYearMonthChange?.(selectedYear, m) : setLocalMonth
  const fileInputRef = useRef<HTMLInputElement>(null)
  const hoverInfoRef = useRef<HTMLDivElement>(null) // 정보 아이콘 컨테이너 참조
  const queryClient = useQueryClient()
  const { sessionId, updateProgress } = useUploadStore()

  const config = UPLOAD_CHANNEL_CONFIGS[uploadChannel]

  /** 업로드/분석 완료 시 검토 탭·업로드 탭 문서 목록 동기화 */
  const invalidateDocumentLists = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['documents', 'all'] })
    queryClient.invalidateQueries({ queryKey: ['documents', 'upload_channel', uploadChannel] })
    queryClient.invalidateQueries({ queryKey: ['documents', 'in-vector-index'] })
  }, [queryClient, uploadChannel])

  // 파일별 진행 상태 관리 { 파일명: 진행상태 }
  const [fileProgresses, setFileProgresses] = useState<Record<string, FileProgress>>({})

  // WebSocket 연결 (업로드 시작 시)
  const [taskId, setTaskId] = useState<string | null>(null)

  // 파일이 이미 DB에 존재하는지 사전 체크
  const checkExistingDocuments = async (targetFiles: File[]) => {
    await Promise.all(
      targetFiles.map(async (file) => {
        try {
          // 문서가 존재하면 성공, 없으면 404
          await documentsApi.get(file.name)
          // 존재하는 경우: 즉시 "既に登録済みです" 표시
          setFileProgresses((prev) => ({
            ...prev,
            [file.name]: {
              status: 'completed',
              message: '既に登録済みです',
            },
          }))
        } catch (error: any) {
          const status = error?.response?.status
          if (status === 404) {
            // 존재하지 않으면 그대로 대기중 상태 유지
            return
          }
          // 그 외 에러는 에러 메시지로 표시
          setFileProgresses((prev) => ({
            ...prev,
            [file.name]: {
              status: 'error',
              message: '既存チェック中にエラーが発生しました',
            },
          }))
        }
      })
    )
  }

  useWebSocket({
    taskId: taskId,
    enabled: !!taskId,
    onMessage: (message: WebSocketMessage) => {
      switch (message.type) {
        case 'connected':
          console.log('WebSocket 연결됨:', message.task_id)
          break
        case 'start':
          // 파일 처리 시작
          if (message.file_name) {
            setFileProgresses((prev) => ({
              ...prev,
              [message.file_name!]: {
                status: 'processing',
                message: message.message || '処理を開始しました...',
              },
            }))
          }
          break
        case 'progress':
          // 파일별 진행 상태 업데이트
          if (message.file_name && message.current_page && message.total_pages) {
            setFileProgresses((prev) => ({
              ...prev,
              [message.file_name!]: {
                status: 'processing',
                currentPage: message.current_page,
                totalPages: message.total_pages,
                message: message.message || '',
                progress: message.progress || 0,
              },
            }))
            updateProgress(message.task_id || '', {
              currentPage: message.current_page,
              totalPages: message.total_pages,
              message: message.message || '',
              progress: message.progress || 0,
            })
          }
          break
        case 'complete':
          // 파일 처리 완료
          invalidateDocumentLists() // 파일별 완료 시마다 검토·업로드 탭 목록 동기화
          setFileProgresses((prev) => {
            const next = message.file_name
              ? {
                  ...prev,
                  [message.file_name!]: {
                    status: 'completed' as const,
                    message: `完了: ${message.pages}ページを${message.elapsed_time?.toFixed(1)}秒で処理しました`,
                  },
                }
              : prev
            const allCompleted =
              Object.keys(next).length === files.length &&
              Object.values(next).every((p) => p.status === 'completed' || p.status === 'error')
            if (allCompleted) {
              setIsUploading(false)
              setTaskId(null)
            }
            return next
          })
          break
        case 'error':
          // 파일 처리 오류
          if (message.file_name) {
            setFileProgresses((prev) => ({
              ...prev,
              [message.file_name!]: {
                status: 'error',
                message: `エラー: ${message.error}`,
              },
            }))
          }
          invalidateDocumentLists()
          setIsUploading(false)
          setTaskId(null)
          break
      }
    },
    onError: (error) => {
      console.error('WebSocket 에러:', error)
    },
    onClose: () => {
      console.log('WebSocket 연결 종료')
    },
  })

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      const newFiles = Array.from(e.target.files)
      setFiles(newFiles)
      // 새 파일 추가 시 진행 상태 초기화
      const newProgresses: Record<string, FileProgress> = {}
      newFiles.forEach((file) => {
        newProgresses[file.name] = { status: 'pending' }
      })
      setFileProgresses(newProgresses)

      // 선택한 파일이 이미 DB에 있는지 사전 체크
      void checkExistingDocuments(newFiles)
      
      // 파일 선택 후 input value 초기화 (같은 파일을 다시 선택할 수 있도록)
      // 약간의 지연을 두어 onChange 이벤트가 완전히 처리된 후에 초기화
      setTimeout(() => {
        if (fileInputRef.current) {
          fileInputRef.current.value = ''
        }
      }, 0)
    }
  }

  const handleUpload = async () => {
    if (files.length === 0 || selectedYear == null || selectedMonth == null) return

    setIsUploading(true)
    // 모든 파일을 일단 업로드 중 상태로 초기화
    const initialProgresses: Record<string, FileProgress> = {}
    files.forEach((file) => {
      initialProgresses[file.name] = { status: 'processing', message: 'アップロード中...' }
    })
    setFileProgresses(initialProgresses)

    try {
      const response = await documentsApi.upload(uploadChannel, files, selectedYear, selectedMonth)

      localStorage.setItem(`lastSelectedYear_${uploadChannel}`, selectedYear.toString())
      localStorage.setItem(`lastSelectedMonth_${uploadChannel}`, selectedMonth.toString())

      setTaskId(response.session_id)
      invalidateDocumentLists() // 검토·업로드 탭 목록 즉시 갱신

      // 결과 확인
      const hasNewFiles = response.results.some((r) => r.status === 'pending')

      // 파일별로 백엔드 결과를 반영
      response.results.forEach((result) => {
        const fileName = result.filename
        if (!fileName) return

        if (result.status === 'exists') {
          // 이미 등록된 문서: 바로 "既に登録済みです" 메시지 표시
          setFileProgresses((prev) => ({
            ...prev,
            [fileName]: {
              status: 'completed',
              message:
                result.pages && result.pages > 0
                  ? `既に登録済みです（${result.pages}ページ）`
                  : '既に登録済みです',
            },
          }))
        } else if (result.status === 'pending') {
          // 새로 처리될 파일: "解析待機中..."로 표시 (이후 WebSocket 진행률로 덮어쓰여짐)
          setFileProgresses((prev) => ({
            ...prev,
            [fileName]: {
              status: 'processing',
              message: '解析待機中...',
            },
          }))
        } else if (result.status === 'error') {
          setFileProgresses((prev) => ({
            ...prev,
            [fileName]: {
              status: 'error',
              message: result.error ? `アップロードエラー: ${result.error}` : 'アップロードエラーが発生しました',
            },
          }))
        }
      })

      if (!hasNewFiles) {
        // 모든 파일이 이미 처리된 경우: 업로드 상태 해제
        setIsUploading(false)
      }
    } catch (error: any) {
      console.error('Upload error:', error)
      // 422 에러의 상세 정보 로깅
      if (error?.response?.status === 422) {
        const detail = error?.response?.data?.detail
        console.error('❌ [422 Validation Error]', detail)
        if (Array.isArray(detail)) {
          detail.forEach((err: any, idx: number) => {
            console.error(`  Error ${idx + 1}:`, {
              loc: err.loc,
              msg: err.msg,
              type: err.type,
              input: err.input
            })
          })
        }
      }
      // 오류 발생 시 모든 파일을 오류 상태로
      const errorMessage = error?.response?.data?.detail 
        ? (Array.isArray(error.response.data.detail) 
            ? error.response.data.detail.map((e: any) => `${e.loc?.join('.')}: ${e.msg}`).join(', ')
            : JSON.stringify(error.response.data.detail))
        : error?.message || String(error)
      files.forEach((file) => {
        setFileProgresses((prev) => ({
          ...prev,
          [file.name]: {
            status: 'error',
            message: `アップロードエラー: ${errorMessage}`,
          },
        }))
      })
      setIsUploading(false)
    }
  }

  const handleClear = () => {
    setFiles([])
    setFileProgresses({})
    setTaskId(null)
    setIsUploading(false)
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  // 새 파일 업로드 버튼 핸들러 (완료 후 파일 목록 초기화 및 새 파일 선택)
  const handleNewUpload = () => {
    handleClear() // 파일 목록 초기화
    // 약간의 지연 후 파일 입력 트리거 (상태 업데이트 후)
    setTimeout(() => {
      if (fileInputRef.current) {
        fileInputRef.current.click()
      }
    }, 100)
  }

  // 개별 파일 삭제 (분석 개시 전에만 가능)
  const handleRemoveFile = useCallback((fileName: string) => {
    if (isUploading) return // 분석 중에는 삭제 불가
    
    setFiles((prev) => prev.filter((file) => file.name !== fileName))
    setFileProgresses((prev) => {
      const newProgresses = { ...prev }
      delete newProgresses[fileName]
      return newProgresses
    })
  }, [isUploading])

  // 파일별 진행 상태 메시지 생성
  const getFileStatusMessage = (fileName: string): string => {
    const progress = fileProgresses[fileName]
    if (!progress) return ''
    
    switch (progress.status) {
      case 'pending':
        return '待機中'
      case 'processing':
        if (progress.currentPage && progress.totalPages) {
          return `処理中: ${progress.currentPage}/${progress.totalPages} - ${progress.message || ''}`
        }
        return progress.message || '処理中...'
      case 'completed':
        return progress.message || '完了'
      case 'error':
        return progress.message || 'エラー'
      default:
        return ''
    }
  }

  // 툴팁 위치 계산 함수
  const updateTooltipPosition = () => {
    if (hoverInfoRef.current) {
      const rect = hoverInfoRef.current.getBoundingClientRect() // 아이콘의 뷰포트 기준 위치
      // 아이콘 아래 중앙에 배치
      const top = rect.bottom + 10 // 아이콘 아래 10px
      const left = rect.left + rect.width / 2 // 중앙점
      
      setTooltipPosition({ top, left })
    }
  }

  // 마우스 진입 시 툴팁 표시 및 위치 계산
  const handleMouseEnter = () => {
    setIsHovered(true)
    setTimeout(() => {
      updateTooltipPosition()
    }, 0)
  }

  // 마우스 이동 시 위치 업데이트 (스크롤 등 대응)
  const handleMouseMove = () => {
    if (isHovered) {
      updateTooltipPosition()
    }
  }

  // 마우스 이탈 시 툴팁 숨김
  const handleMouseLeave = () => {
    setIsHovered(false)
  }

  // 스크롤 시 위치 업데이트
  useEffect(() => {
    if (isHovered) {
      const handleScroll = () => {
        updateTooltipPosition()
      }
      window.addEventListener('scroll', handleScroll, true)
      return () => {
        window.removeEventListener('scroll', handleScroll, true)
      }
    }
  }, [isHovered])

  // 년·월 미선택 시 업로드 영역 비활성화
  const isYearMonthRequired = selectedYear == null || selectedMonth == null

  // 모든 파일이 완료되었는지 확인
  const allFilesCompleted = useMemo(() => {
    if (files.length === 0) return false
    return Object.values(fileProgresses).every(
      (p) => p.status === 'completed' || p.status === 'error'
    ) && Object.keys(fileProgresses).length === files.length
  }, [files, fileProgresses])

  // 오른쪽 패널에 업로드 진행 상태 전달
  useEffect(() => {
    onUploadProgressChange?.(uploadChannel, {
      fileNames: files.map((f) => f.name),
      progress: fileProgresses,
      isUploading,
    })
  }, [uploadChannel, files, fileProgresses, isUploading, onUploadProgressChange])

  // 오른쪽 패널에서 삭제 시 호출할 함수 등록
  useEffect(() => {
    onRegisterRemove?.(uploadChannel, handleRemoveFile)
    return () => {
      onRegisterRemove?.(uploadChannel, null)
    }
  }, [uploadChannel, handleRemoveFile, onRegisterRemove])


  const handleCardClick = () => {
    onShowFileList?.(uploadChannel)
  }

  return (
    <div 
      className={`form-upload-section ${files.length > 0 ? 'has-files' : ''} ${isListSelected ? 'form-upload-section-selected' : ''}`} 
      style={{ borderTopColor: config.color }}
      onClick={handleCardClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && handleCardClick()}
      aria-pressed={isListSelected}
    >
      <div className="form-header">
        <span>
          <span style={{ color: '#0f172a', fontWeight: 600 }}>{config.name}</span>
          <span className="form-header-label"> ({config.label})</span>
        </span>
        <div className="form-header-actions" onClick={(e) => e.stopPropagation()}>
          <div
            className="hover-info-container"
          ref={hoverInfoRef}
          onMouseEnter={handleMouseEnter}
          onMouseMove={handleMouseMove}
          onMouseLeave={handleMouseLeave}
        >
          <span className="hover-info" title="サンプル画像">
            i
          </span>
        </div>
        </div>
      </div>

      {/* 년월 선택 + 분석 개시 버튼 (한 줄, 높이 맞춤) */}
      <div className="form-date-and-actions" onClick={(e) => e.stopPropagation()}>
        <div className="year-month-selector">
          <select
            value={selectedYear ?? ''}
            onChange={(e) => setSelectedYear(e.target.value === '' ? null : parseInt(e.target.value))}
            className="year-selector"
            aria-label="年を選択"
          >
            <option value="">年を選択</option>
            {Array.from({ length: 5 }, (_, i) => 2026 + i).map(year => (
              <option key={year} value={year}>{year}年</option>
            ))}
          </select>
          <select
            value={selectedMonth ?? ''}
            onChange={(e) => setSelectedMonth(e.target.value === '' ? null : parseInt(e.target.value))}
            className="month-selector"
            aria-label="月を選択"
          >
            <option value="">月を選択</option>
            {Array.from({ length: 12 }, (_, i) => i + 1).map(month => (
              <option key={month} value={month}>{month.toString().padStart(2, '0')}月</option>
            ))}
          </select>
        </div>
        <div className="button-group">
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); handleUpload() }}
            disabled={files.length === 0 || isUploading || selectedYear == null || selectedMonth == null}
            className="btn-primary"
          >
            {isUploading ? '処理中...' : `解析開始 (${files.length}件)`}
          </button>
          {files.length > 0 && (
            <button type="button" onClick={(e) => { e.stopPropagation(); handleClear() }} className="btn-secondary" disabled={isUploading}>
              クリア
            </button>
          )}
        </div>
      </div>

      {/* Portal을 사용하여 body에 직접 렌더링 - 최상단 표시 보장 */}
      {isHovered && createPortal(
        <div 
          className="hover-tooltip"
          style={{
            top: `${tooltipPosition.top}px`,
            left: `${tooltipPosition.left}px`,
            transform: 'translateX(-50%)',
          }}
        >
          <img 
            src={config.imagePath} 
            alt={`${config.name} サンプル画像`}
            className="hover-tooltip-image"
          />
        </div>,
        document.body
      )}

      {/* 완료 후 새 파일 업로드 버튼 */}
      {allFilesCompleted && files.length > 0 && (
        <div className="new-upload-button-container" onClick={(e) => e.stopPropagation()}>
          <button 
            type="button"
            onClick={handleNewUpload}
            className="btn-new-upload"
          >
            新しいファイルをアップロード
          </button>
        </div>
      )}

      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf"
        multiple
        onChange={handleFileChange}
        disabled={isUploading || isYearMonthRequired}
        style={{ display: 'none' }}
        id={`file-input-${uploadChannel}`}
      />

      <div
        className={`file-upload-zone ${allFilesCompleted ? 'completed-state' : ''} ${isYearMonthRequired ? 'disabled-no-year-month' : ''}`}
        style={{
          opacity: isUploading ? 0.5 : 1,
          pointerEvents: isUploading ? 'none' : 'auto',
        }}
        onDragOver={(e) => {
          e.preventDefault()
          e.stopPropagation()
          if (!isYearMonthRequired) e.currentTarget.classList.add('drag-over')
        }}
        onDragLeave={(e) => {
          e.preventDefault()
          e.stopPropagation()
          e.currentTarget.classList.remove('drag-over')
        }}
        onDrop={(e) => {
          e.preventDefault()
          e.stopPropagation()
          e.currentTarget.classList.remove('drag-over')
          if (isUploading) return
          if (isYearMonthRequired) {
            alert('年・月を選択してください。')
            return
          }
          if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
            const droppedFiles = Array.from(e.dataTransfer.files).filter(
              (file) => file.type === 'application/pdf'
            )
            if (droppedFiles.length > 0) {
              setFiles(droppedFiles)
              const newProgresses: Record<string, FileProgress> = {}
              droppedFiles.forEach((file) => {
                newProgresses[file.name] = { status: 'pending' }
              })
              setFileProgresses(newProgresses)
              void checkExistingDocuments(droppedFiles)
            }
          }
        }}
      >
        <button
          type="button"
          className="file-upload-trigger-btn"
          disabled={isUploading}
          onClick={(e) => {
            e.stopPropagation()
            if (isYearMonthRequired) {
              alert('年・月を選択してください。')
              return
            }
            fileInputRef.current?.click()
          }}
        >
          <span className="file-upload-trigger-icon">↑</span>
          PDFを選択
        </button>
        <span className="file-upload-hint">
          {isYearMonthRequired ? '年・月を選択してください' : 'またはここにドラッグ'}
        </span>
      </div>
    </div>
  )
}
