/**
 * 과거 이력 조회 컴포넌트
 * 검토 탭과 동일한 레이아웃으로 년월별 데이터를 표시
 * 파일 트리는 App.tsx의 사이드바에 표시됨
 */
import { useState, useMemo, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { searchApi, itemsApi } from '@/api/client'
import { ItemsGridRdg } from '../Grid/ItemsGridRdg'
import { getApiBaseUrl } from '@/utils/apiConfig'
import './HistoryQuery.css'

// 검토 필터 타입: 1次/2次 각각 완료/미완료
type ReviewFilter = 'all' | 'first_reviewed' | 'first_not_reviewed' | 'second_reviewed' | 'second_not_reviewed'

// 문서 인터페이스
interface Document {
  pdf_filename: string
  form_type: string | null
  total_pages: number
  upload_date?: string  // 호환성
  created_at?: string   // 실제 필드명
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

// 년도별 그룹화된 데이터
interface YearGroup {
  year: number
  months: YearMonthGroup[]
  totalFiles: number
  totalPages: number
}

// 페이지 타입
interface Page {
  pdfFilename: string
  pageNumber: number
  formType: string | null
  totalPages: number
}

interface HistoryQueryProps {
  selectedYearMonth: { year: number; month: number } | null
  groupedData: YearMonthGroup[]
}

export const HistoryQuery = ({ selectedYearMonth, groupedData }: HistoryQueryProps) => {
  const [currentPageIndex, setCurrentPageIndex] = useState(0) // 현재 페이지 인덱스
  const [inputValue, setInputValue] = useState('') // 입력창에 표시되는 값
  const [searchQuery, setSearchQuery] = useState('') // 실제 검색에 사용되는 값 (엔터 또는 버튼 클릭 시 업데이트)
  const [reviewFilter, setReviewFilter] = useState<ReviewFilter>('all') // 검토 필터

  // 검토 상태 통계 조회
  const { data: reviewStats } = useQuery({
    queryKey: ['review-stats'],
    queryFn: () => itemsApi.getReviewStats(),
    refetchInterval: 5000, // 5초마다 갱신
  })

  // 거래처명으로 검색 (검색어가 있을 때만 실행)
  const { data: searchResult, isLoading: searchLoading } = useQuery({
    queryKey: ['search', 'customer', searchQuery],
    queryFn: () => searchApi.byCustomer(searchQuery, false), // 부분 일치 검색
    enabled: !!searchQuery.trim(), // 검색어가 있을 때만 실행
  })

  // 현재 연월 계산
  const currentYearMonth = useMemo(() => {
    const now = new Date()
    return {
      year: now.getFullYear(),
      month: now.getMonth() + 1
    }
  }, [])

  // 선택된 년월 이하의 모든 페이지를 평탄화하여 리스트 생성
  // selectedYearMonth가 있으면 해당 연월 이하의 데이터, 없으면 현재 연월 이하의 데이터 표시
  const allPages: Page[] = useMemo(() => {
    if (!groupedData || groupedData.length === 0) {
      return []
    }

    // 기준 연월: selectedYearMonth가 있으면 그것을 사용, 없으면 현재 연월 사용
    const targetYearMonth = selectedYearMonth || currentYearMonth

    // 기준 연월 이하의 그룹들 필터링 (선택한 연월 포함)
    const pastGroups = groupedData.filter((group) => {
      // year, month를 숫자로 명시적 변환
      const groupYear = Number(group.year)
      const groupMonth = Number(group.month)
      const targetYear = Number(targetYearMonth.year)
      const targetMonth = Number(targetYearMonth.month)

      // year, month가 유효한지 확인
      if (!groupYear || !groupMonth || groupYear <= 0 || groupMonth <= 0 || groupMonth > 12 || isNaN(groupYear) || isNaN(groupMonth)) {
        return false
      }

      // 기준 연월 이하인지 확인 (선택한 연월 포함)
      return groupYear < targetYear ||
        (groupYear === targetYear && groupMonth <= targetMonth)
    })

    // 모든 과거 문서의 모든 페이지를 평탄화
    const pages: Page[] = []
    pastGroups.forEach((group) => {
      group.documents.forEach((doc) => {
        for (let i = 1; i <= doc.total_pages; i++) {
          pages.push({
            pdfFilename: doc.pdf_filename,
            pageNumber: i,
            formType: doc.form_type,
            totalPages: doc.total_pages,
          })
        }
      })
    })

    return pages
  }, [selectedYearMonth, groupedData, currentYearMonth])

  // 검색 결과에서 페이지 리스트 생성 (검색어가 있을 때 사용)
  const searchPages: Page[] = useMemo(() => {
    if (!searchResult?.pages) return []

    // 기준 연월: selectedYearMonth가 있으면 그것을 사용, 없으면 현재 연월 사용
    const targetYearMonth = selectedYearMonth || currentYearMonth

    return searchResult.pages
      .map((page) => ({
        pdfFilename: page.pdf_filename,
        pageNumber: page.page_number,
        formType: page.form_type,
        totalPages: 1, // 검색 결과에서는 totalPages 정보가 없으므로 1로 설정
      }))
      .filter((page) => {
        // 검색 결과도 선택한 연월 이하로 필터링
        const doc = groupedData
          .flatMap(g => g.documents)
          .find(d => d.pdf_filename === page.pdfFilename)

        if (!doc) return false

        const docYear = doc.data_year || new Date(doc.created_at || doc.upload_date || '').getFullYear()
        const docMonth = doc.data_month || new Date(doc.created_at || doc.upload_date || '').getMonth() + 1
        const targetYear = Number(targetYearMonth.year)
        const targetMonth = Number(targetYearMonth.month)

        return docYear < targetYear ||
          (docYear === targetYear && docMonth <= targetMonth)
      })
  }, [searchResult, selectedYearMonth, currentYearMonth, groupedData])

  // 검색어가 있으면 검색 결과, 없으면 전체 페이지 사용 + 검토 필터 적용
  const displayPages: Page[] = useMemo(() => {
    const basePages = searchQuery.trim() ? searchPages : allPages

    // 검토 필터 적용
    if (reviewFilter === 'all' || !reviewStats?.page_stats) {
      return basePages
    }

    // page_stats를 Map으로 변환 (빠른 조회를 위해)
    const statsMap = new Map<string, { first: boolean; second: boolean }>()
    reviewStats.page_stats.forEach((stat) => {
      const key = `${stat.pdf_filename}_${stat.page_number}`
      statsMap.set(key, { first: stat.first_reviewed, second: stat.second_reviewed })
    })

    return basePages.filter((page) => {
      const key = `${page.pdfFilename}_${page.pageNumber}`
      const stat = statsMap.get(key) || { first: false, second: false }

      switch (reviewFilter) {
        case 'first_reviewed':
          return stat.first
        case 'first_not_reviewed':
          return !stat.first
        case 'second_reviewed':
          return stat.second
        case 'second_not_reviewed':
          return !stat.second
        default:
          return true
      }
    })
  }, [searchQuery, searchPages, allPages, reviewFilter, reviewStats])

  // 현재 페이지 정보
  const currentPage = displayPages[currentPageIndex] || null
  const totalFilteredPages = displayPages.length

  // 현재 페이지의 검토율 조회
  const currentPageStats = useMemo(() => {
    if (!currentPage || !reviewStats?.page_stats) return null
    return reviewStats.page_stats.find(
      (stat) => stat.pdf_filename === currentPage.pdfFilename && stat.page_number === currentPage.pageNumber
    )
  }, [currentPage, reviewStats])

  // 현재 페이지의 page_role 조회
  const { data: pageImageData } = useQuery({
    queryKey: ['page-image', currentPage?.pdfFilename, currentPage?.pageNumber],
    queryFn: () => {
      if (!currentPage) return null
      return searchApi.getPageImage(currentPage.pdfFilename, currentPage.pageNumber)
    },
    enabled: !!currentPage?.pdfFilename && !!currentPage?.pageNumber,
  })

  const currentPageRole = pageImageData?.page_role

  // 년월이 변경되면 첫 페이지로 이동
  useEffect(() => {
    if (selectedYearMonth) {
      setCurrentPageIndex(0)
    }
  }, [selectedYearMonth])

  // 페이지 이동 핸들러
  const handlePrevPage = () => {
    if (currentPageIndex > 0) {
      setCurrentPageIndex(currentPageIndex - 1)
    }
  }

  const handleNextPage = () => {
    if (currentPageIndex < totalFilteredPages - 1) {
      setCurrentPageIndex(currentPageIndex + 1)
    }
  }

  // 입력값 변경 핸들러 (검색은 실행하지 않음)
  const handleInputChange = (value: string) => {
    setInputValue(value)
  }

  // 검색 실행 핸들러 (엔터 또는 버튼 클릭 시 호출)
  const handleSearch = () => {
    setSearchQuery(inputValue.trim())
    setCurrentPageIndex(0)
  }

  // 엔터 키 입력 핸들러
  const handleKeyPress = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      handleSearch()
    }
  }

  // 검토 필터 변경 핸들러
  const handleReviewFilterChange = (filter: ReviewFilter) => {
    setReviewFilter(filter)
    setCurrentPageIndex(0) // 필터 변경 시 첫 페이지로 이동
  }

  const hasGroupedData = groupedData && groupedData.length > 0

  return (
    <div className="history-query">
      <div className="main-content-area">
        {displayPages.length === 0 ? (
          <div className="no-selection">
            <div className="no-selection-text">
              {hasGroupedData ? (
                <>
                  選択した年月のデータがありません
                  <div style={{ marginTop: '1rem', fontSize: '0.875rem', color: '#6b7280' }}>
                    (전체 데이터: {groupedData.length}개 그룹,
                    선택된 연월: {selectedYearMonth ? `${selectedYearMonth.year}-${selectedYearMonth.month}` : `${currentYearMonth.year}-${currentYearMonth.month}`})
                  </div>
                </>
              ) : (
                'データがありません'
              )}
            </div>
          </div>
        ) : (
          <>
            {/* 이미지 섹션 */}
            {currentPage && (
              <div className="selected-page-content">
                <PageImageViewer
                  pdfFilename={currentPage.pdfFilename}
                  pageNumber={currentPage.pageNumber}
                />
              </div>
            )}

            {/* 페이지 내비게이션 섹션 */}
            <div className="page-navigation-section">
              <div className="page-nav-controls">
                {/* 이전/다음 버튼 */}
                <div className="nav-buttons-group">
                  <button
                    onClick={handlePrevPage}
                    disabled={currentPageIndex === 0}
                    className="nav-button prev-button"
                  >
                    &lt;
                  </button>
                  <button
                    onClick={handleNextPage}
                    disabled={currentPageIndex >= totalFilteredPages - 1}
                    className="nav-button next-button"
                  >
                    &gt;
                  </button>
                </div>

                {/* 페이지 번호 배지 */}
                <div className="page-number-badge">
                  <span className="current-page-number">{currentPageIndex + 1}</span>
                  <span className="total-pages-text">of {totalFilteredPages}</span>
                </div>

                {/* 검색창 */}
                <input
                  type="text"
                  value={inputValue}
                  onChange={(e) => handleInputChange(e.target.value)}
                  onKeyPress={handleKeyPress}
                  placeholder="取引先名で検索"
                  className="page-search-input"
                />
                {/* 검색 버튼 */}
                <button
                  onClick={handleSearch}
                  className="search-button"
                >
                  検索
                </button>

                {/* 파일명 + 페이지 번호 */}
                <div className="page-filename-container">
                  <span className="page-filename">
                    {currentPage?.pdfFilename || ''}
                  </span>
                  {currentPage && (
                    <span className="page-number-in-file">
                      p.{currentPage.pageNumber}
                    </span>
                  )}
                  {/* 페이지 역할 배지 */}
                  <PageRoleBadge pageRole={currentPageRole} />
                  {/* 검토율 배지 */}
                  <ReviewRateBadges stats={currentPageStats} />
                </div>

                {/* 검토 상태 배지 */}
                <ReviewStatusBadges
                  firstReviewedCount={reviewStats?.first_reviewed_count || 0}
                  firstNotReviewedCount={reviewStats?.first_not_reviewed_count || 0}
                  secondReviewedCount={reviewStats?.second_reviewed_count || 0}
                  secondNotReviewedCount={reviewStats?.second_not_reviewed_count || 0}
                  currentFilter={reviewFilter}
                  onFilterChange={handleReviewFilterChange}
                />
              </div>
            </div>

            {/* 그리드 섹션 */}
            {currentPage && (
              <div className="selected-page-content">
                <ItemsGridRdg
                  pdfFilename={currentPage.pdfFilename}
                  pageNumber={currentPage.pageNumber}
                  formType={currentPage.formType}
                />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

// 페이지 이미지 뷰어 컴포넌트
const PageImageViewer = ({
  pdfFilename,
  pageNumber,
}: {
  pdfFilename: string
  pageNumber: number
}) => {
  const { data, isLoading, error } = useQuery({
    queryKey: ['page-image', pdfFilename, pageNumber],
    queryFn: () => {
      console.log('Fetching page image:', pdfFilename, pageNumber)
      return searchApi.getPageImage(pdfFilename, pageNumber)
    },
    enabled: !!pdfFilename && !!pageNumber,
  })

  return (
    <div className="page-image-viewer">
      {isLoading && <div className="image-loading">画像読み込み中...</div>}
      {error && (
        <div className="image-error">
          画像読み込みエラー: {error instanceof Error ? error.message : 'Unknown error'}
        </div>
      )}
      {data && (() => {
        // 상대 경로인 경우 백엔드 URL을 앞에 붙여서 절대 URL로 변환
        const imageUrl = data.image_url.startsWith('http')
          ? data.image_url
          : `${getApiBaseUrl()}${data.image_url}`

        return (
          <div className="image-container">
            <img
              src={imageUrl}
              alt={`Page ${pageNumber}`}
              onError={(e) => {
                console.error('Image load error:', e, 'URL:', imageUrl)
                const target = e.currentTarget
                target.style.display = 'none'
                const container = target.parentElement
                if (container) {
                  const errorDiv = document.createElement('div')
                  errorDiv.className = 'image-error'
                  errorDiv.textContent = `画像の表示に失敗しました (URL: ${imageUrl})`
                  container.appendChild(errorDiv)
                }
              }}
              onLoad={() => console.log('이미지 로드 성공:', imageUrl)}
            />
          </div>
        )
      })()}
      {!isLoading && !error && !data && (
        <div className="image-error">画像が見つかりません</div>
      )}
    </div>
  )
}

// 검토율 배지 컴포넌트
const ReviewRateBadges = ({ stats }: {
  stats?: {
    first_review_rate: number
    second_review_rate: number
    first_checked_count: number
    second_checked_count: number
    total_items: number
  } | null
}) => {
  if (!stats) return null

  // 배경색 계산 (검토율에 따라)
  const getColor = (rate: number) => {
    if (rate === 100) return '#4CAF50' // 완료: 녹색
    if (rate >= 50) return '#a78bfa'   // 진행중: 보라색 계열
    if (rate > 0) return '#667eea'     // 시작: 보라색
    return '#9E9E9E'                   // 미시작: 회색
  }

  return (
    <div className="review-rate-badges">
      <span
        className="review-rate-badge"
        style={{ backgroundColor: getColor(stats.first_review_rate) }}
        title={`1次: ${stats.first_checked_count}/${stats.total_items}`}
      >
        1次 {stats.first_review_rate}%
      </span>
      <span
        className="review-rate-badge"
        style={{ backgroundColor: getColor(stats.second_review_rate) }}
        title={`2次: ${stats.second_checked_count}/${stats.total_items}`}
      >
        2次 {stats.second_review_rate}%
      </span>
    </div>
  )
}

// 페이지 분류 배지 컴포넌트
const PageRoleBadge = ({ pageRole }: { pageRole?: string }) => {
  if (!pageRole) return null

  // page_role 한글/일본어 매핑
  const roleLabels: Record<string, string> = {
    'cover': '表紙',
    'detail': '詳細',
    'summary': 'サマリー',
    'reply': '返信',
    'main': 'メイン',
  }

  const roleLabel = roleLabels[pageRole] || pageRole

  // 배지 색상 설정
  const badgeColors: Record<string, string> = {
    'cover': '#4CAF50',      // 초록색
    'detail': '#2196F3',      // 파란색
    'summary': '#a78bfa',     // 보라색 계열
    'reply': '#667eea',       // 보라색
    'main': '#607D8B',        // 회색
  }

  const badgeColor = badgeColors[pageRole] || '#757575'

  return (
    <span
      className="page-role-badge"
      style={{ backgroundColor: badgeColor }}
    >
      {roleLabel}
    </span>
  )
}

// 검토 상태 배지 컴포넌트
const ReviewStatusBadges = ({
  firstReviewedCount,
  firstNotReviewedCount,
  secondReviewedCount,
  secondNotReviewedCount,
  currentFilter,
  onFilterChange,
}: {
  firstReviewedCount: number
  firstNotReviewedCount: number
  secondReviewedCount: number
  secondNotReviewedCount: number
  currentFilter: ReviewFilter
  onFilterChange: (filter: ReviewFilter) => void
}) => {
  return (
    <div className="review-status-badges">
      {/* 1次 검토 완료 배지 */}
      <button
        className={`review-badge first-reviewed ${currentFilter === 'first_reviewed' ? 'active' : ''}`}
        onClick={() => onFilterChange(currentFilter === 'first_reviewed' ? 'all' : 'first_reviewed')}
        title={currentFilter === 'first_reviewed' ? '전체 보기' : '1次 검토 완료만'}
      >
        <span className="badge-label">1次</span>
        <span className="badge-icon">✓</span>
        <span className="badge-count">{firstReviewedCount}</span>
      </button>

      {/* 1次 미검토 배지 */}
      <button
        className={`review-badge first-not-reviewed ${currentFilter === 'first_not_reviewed' ? 'active' : ''}`}
        onClick={() => onFilterChange(currentFilter === 'first_not_reviewed' ? 'all' : 'first_not_reviewed')}
        title={currentFilter === 'first_not_reviewed' ? '전체 보기' : '1次 미검토만'}
      >
        <span className="badge-label">1次</span>
        <span className="badge-icon">○</span>
        <span className="badge-count">{firstNotReviewedCount}</span>
      </button>

      {/* 2次 검토 완료 배지 */}
      <button
        className={`review-badge second-reviewed ${currentFilter === 'second_reviewed' ? 'active' : ''}`}
        onClick={() => onFilterChange(currentFilter === 'second_reviewed' ? 'all' : 'second_reviewed')}
        title={currentFilter === 'second_reviewed' ? '전체 보기' : '2次 검토 완료만'}
      >
        <span className="badge-label">2次</span>
        <span className="badge-icon">✓</span>
        <span className="badge-count">{secondReviewedCount}</span>
      </button>

      {/* 2次 미검토 배지 */}
      <button
        className={`review-badge second-not-reviewed ${currentFilter === 'second_not_reviewed' ? 'active' : ''}`}
        onClick={() => onFilterChange(currentFilter === 'second_not_reviewed' ? 'all' : 'second_not_reviewed')}
        title={currentFilter === 'second_not_reviewed' ? '전체 보기' : '2次 미검토만'}
      >
        <span className="badge-label">2次</span>
        <span className="badge-icon">○</span>
        <span className="badge-count">{secondNotReviewedCount}</span>
      </button>
    </div>
  )
}