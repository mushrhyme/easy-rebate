/**
 * SAP 업로드 탭 컴포넌트
 * 이번달 검토 탭의 모든 분석 결과물을 SAP 업로드 양식에 맞게 엑셀 파일로 다운로드
 */
import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { documentsApi, sapUploadApi } from '@/api/client'
import { getApiBaseUrl } from '@/utils/apiConfig'
import type { Document } from '@/types'
import './SAPUpload.css'

// 열 번호를 열 문자로 변환 (A=1, B=2, ..., Z=26, AA=27, ..., BB=54)
function getColumnLetter(columnNumber: number): string {
  let result = ''
  while (columnNumber > 0) {
    columnNumber--
    result = String.fromCharCode(65 + (columnNumber % 26)) + result
    columnNumber = Math.floor(columnNumber / 26)
  }
  return result
}

export const SAPUpload = () => {
  const [isGenerating, setIsGenerating] = useState(false)
  const [showPreview, setShowPreview] = useState(false)
  const [selectedFormType, setSelectedFormType] = useState<string>('all') // 'all' 또는 '01', '02', '03', '04', '05'

  // 현재 연월 계산
  const currentYearMonth = useMemo(() => {
    const now = new Date()
    return {
      year: now.getFullYear(),
      month: now.getMonth() + 1
    }
  }, [])

  // SAP 엑셀 미리보기 데이터 조회
  const { data: previewData, isLoading: previewLoading, refetch: refetchPreview } = useQuery({
    queryKey: ['sap-upload', 'preview'],
    queryFn: () => sapUploadApi.preview(),
    enabled: showPreview, // 미리보기 버튼 클릭 시에만 조회
  })

  // 필터링된 미리보기 데이터
  const filteredPreviewData = useMemo(() => {
    if (!previewData || !previewData.preview_rows) return null

    if (selectedFormType === 'all') {
      return previewData
    }

    return {
      ...previewData,
      preview_rows: previewData.preview_rows.filter(
        (row) => row.form_type === selectedFormType
      ),
    }
  }, [previewData, selectedFormType])

  // 미리보기 토글 핸들러
  const handleTogglePreview = () => {
    if (!showPreview) {
      setShowPreview(true)
      refetchPreview()
    } else {
      setShowPreview(false)
    }
  }

  // 엑셀 파일 다운로드 핸들러
  const handleDownloadExcel = async () => {
    setIsGenerating(true)
    
    try {
      const response = await fetch(`${getApiBaseUrl()}/api/sap-upload/download`, {
        method: 'GET',
        headers: {
          'X-Session-ID': localStorage.getItem('sessionId') || '',
        },
      })
      
      if (!response.ok) {
        throw new Error('ダウンロードに失敗しました')
      }
      
      const blob = await response.blob()
      
      // Content-Disposition 헤더에서 파일명 추출
      const contentDisposition = response.headers.get('Content-Disposition')
      let filename = `SAP_Upload_${new Date().toISOString().slice(0, 10).replace(/-/g, '')}.xlsx`
      
      if (contentDisposition) {
        const filenameMatch = contentDisposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/)
        if (filenameMatch && filenameMatch[1]) {
          filename = filenameMatch[1].replace(/['"]/g, '')
        }
      }
      
      // Blob을 다운로드 링크로 변환
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      window.URL.revokeObjectURL(url)
    } catch (error) {
      console.error('엑셀 파일 다운로드 오류:', error)
      alert('엑셀 파일 다운로드 중 오류가 발생했습니다.')
    } finally {
      setIsGenerating(false)
    }
  }

  return (
    <div className="sap-upload-tab">
      {/* 헤더 섹션 */}
      <div className="sap-upload-header">
        <div className="sap-upload-title-container">
          <div className="sap-upload-title-icon">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M14 2H6C5.46957 2 4.96086 2.21071 4.58579 2.58579C4.21071 2.96086 4 3.46957 4 4V20C4 20.5304 4.21071 21.0391 4.58579 21.4142C4.96086 21.7893 5.46957 22 6 22H18C18.5304 22 19.0391 21.7893 19.4142 21.4142C19.7893 21.0391 20 20.5304 20 20V8L14 2Z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="M14 2V8H20" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="M16 13H8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="M16 17H8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="M10 9H9H8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </div>
          <div className="sap-upload-title-text">
            <h1 className="sap-upload-title-main">SAPアップロード</h1>
            <p className="sap-upload-title-sub">SAP Upload</p>
          </div>
        </div>
      </div>

      {/* 메인 컨텐츠 */}
      <div className="sap-upload-content">
        {/* 현재 연월 정보 */}
        <div className="sap-upload-period-card">
          <div className="period-label">対象期間</div>
          <div className="period-value">
            {currentYearMonth.year}年 {currentYearMonth.month}月
          </div>
        </div>

        {/* 통계 카드 */}
        <div className="sap-upload-stats-grid">
          <div className="stat-card">
            <div className="stat-icon">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M9 11L12 14L22 4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                <path d="M21 12V19C21 19.5304 20.7893 20.0391 20.4142 20.4142C20.0391 20.7893 19.5304 21 19 21H5C4.46957 21 3.96086 20.7893 3.58579 20.4142C3.21071 20.0391 3 19.5304 3 19V5C3 4.46957 3.21071 3.96086 3.58579 3.58579C3.96086 3.21071 4.46957 3 5 3H16" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </div>
            <div className="stat-content">
              <div className="stat-value">{previewLoading ? '...' : (previewData?.total_items || 0)}</div>
              <div className="stat-label">総件数（行数）</div>
            </div>
          </div>
        </div>

        {/* 다운로드 버튼 섹션 */}
        <div className="sap-upload-download-section">
          <div className="download-info">
            <p className="download-description">
              document_currentに保存されているすべての分析結果を、SAPアップロード用のExcelファイル形式でダウンロードします。
            </p>
            <p className="download-note">
              ※ ファイルとページの区別なく、すべての情報を統合して処理します。
            </p>
          </div>
          
          <div className="button-group">
            <button
              className="preview-button"
              onClick={handleTogglePreview}
              disabled={previewLoading}
            >
              {showPreview ? (
                <>
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M1 12S5 4 12 4S23 12 23 12S19 20 12 20S1 12 1 12Z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                    <path d="M12 15C13.6569 15 15 13.6569 15 12C15 10.3431 13.6569 9 12 9C10.3431 9 9 10.3431 9 12C9 13.6569 10.3431 15 12 15Z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                  <span>プレビューを閉じる</span>
                </>
              ) : (
                <>
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M1 12S5 4 12 4S23 12 23 12S19 20 12 20S1 12 1 12Z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                    <path d="M12 15C13.6569 15 15 13.6569 15 12C15 10.3431 13.6569 9 12 9C10.3431 9 9 10.3431 9 12C9 13.6569 10.3431 15 12 15Z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                  <span>プレビューを表示</span>
                </>
              )}
            </button>

            <button
              className="download-button"
              onClick={handleDownloadExcel}
              disabled={isGenerating || previewLoading}
            >
              {isGenerating ? (
                <>
                  <svg className="spinner" width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M12 2V6M12 18V22M4.93 4.93L7.76 7.76M16.24 16.24L19.07 19.07M2 12H6M18 12H22M4.93 19.07L7.76 16.24M16.24 7.76L19.07 4.93" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                  <span>生成中...</span>
                </>
              ) : (
                <>
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M21 15V19C21 19.5304 20.7893 20.0391 20.4142 20.4142C20.0391 20.7893 19.5304 21 19 21H5C4.46957 21 3.96086 20.7893 3.58579 20.4142C3.21071 20.0391 3 19.5304 3 19V15" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                    <path d="M7 10L12 15L17 10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                    <path d="M12 15V3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                  <span>Excelファイルをダウンロード</span>
                </>
              )}
            </button>
          </div>

          {/* 미리보기 섹션 */}
          {showPreview && (
            <div className="preview-section">
              {previewLoading ? (
                <div className="preview-loading">
                  <svg className="spinner" width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M12 2V6M12 18V22M4.93 4.93L7.76 7.76M16.24 16.24L19.07 19.07M2 12H6M18 12H22M4.93 19.07L7.76 16.24M16.24 7.76L19.07 4.93" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                  <span>読み込み中...</span>
                </div>
              ) : filteredPreviewData ? (
                <>
                  <div className="preview-header">
                    <h3 className="preview-title">プレビュー</h3>
                    <p className="preview-info">{filteredPreviewData.message}</p>
                    {/* 폼 필터 */}
                    <div className="preview-filter">
                      <label htmlFor="form-filter" className="filter-label">
                        フォームフィルター:
                      </label>
                      <select
                        id="form-filter"
                        value={selectedFormType}
                        onChange={(e) => setSelectedFormType(e.target.value)}
                        className="form-filter-select"
                      >
                        <option value="all">すべて</option>
                        <option value="01">フォーム 01</option>
                        <option value="02">フォーム 02</option>
                        <option value="03">フォーム 03</option>
                        <option value="04">フォーム 04</option>
                        <option value="05">フォーム 05</option>
                      </select>
                      {selectedFormType !== 'all' && (
                        <span className="filter-count">
                          ({filteredPreviewData.preview_rows.length}件表示)
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="preview-table-container">
                    <table className="preview-table">
                      <thead>
                        <tr>
                          <th>ファイル名</th>
                          <th>ページ</th>
                          <th>フォーム</th>
                          {filteredPreviewData.column_names && filteredPreviewData.column_names.length > 0 ? (
                            filteredPreviewData.column_names.map((colName, idx) => (
                              // 컬럼명이 공란이면 헤더도 공란으로 표시
                              <th key={idx}>{colName ?? ''}</th>
                            ))
                          ) : (
                            // 컬럼명이 없으면 A~BB까지 표시
                            Array.from({ length: 54 }, (_, i) => (
                              <th key={i}>{getColumnLetter(i + 1)}</th>
                            ))
                          )}
                        </tr>
                      </thead>
                      <tbody>
                        {filteredPreviewData.preview_rows.length > 0 ? (
                          filteredPreviewData.preview_rows.map((row, index) => (
                            <tr key={index}>
                              <td className="filename-cell">{row.pdf_filename}</td>
                              <td>{row.page_number}</td>
                              <td>{row.form_type}</td>
                              {filteredPreviewData.column_names && filteredPreviewData.column_names.length > 0 ? (
                                filteredPreviewData.column_names.map((_, idx) => {
                                  const colLetter = getColumnLetter(idx + 1)
                                  const value = row[colLetter]
                                  // 값이 없으면 완전 공란으로 표시
                                  return (
                                    <td key={idx}>{value === undefined || value === null ? '' : value}</td>
                                  )
                                })
                              ) : (
                                // 컬럼명이 없으면 A~BB까지 표시
                                Array.from({ length: 54 }, (_, i) => {
                                  const colLetter = getColumnLetter(i + 1)
                                  const value = row[colLetter]
                                  return (
                                    <td key={i}>{value === undefined || value === null ? '' : value}</td>
                                  )
                                })
                              )}
                            </tr>
                          ))
                        ) : (
                          <tr>
                            <td colSpan={filteredPreviewData.column_names?.length ? filteredPreviewData.column_names.length + 3 : 57} className="no-data-cell">
                              該当するデータがありません
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </>
              ) : (
                <div className="no-data-message">
                  <p>データがありません。</p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
