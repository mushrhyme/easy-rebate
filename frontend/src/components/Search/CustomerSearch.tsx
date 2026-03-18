/**
 * 검토 탭 컴포넌트
 * 기본적으로 모든 페이지를 표시하고, 검색어 입력 시 거래처명으로 필터링
 */
import { useState, useMemo, useRef, useCallback, useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { documentsApi, searchApi, itemsApi, formTypesApi, ragAdminApi } from '@/api/client'
import { useToast } from '@/contexts/ToastContext'
import { useFormTypes } from '@/hooks/useFormTypes'
import { ItemsGridRdg, type ItemsGridRdgHandle } from '../Grid/ItemsGridRdg'
import { getApiBaseUrl, getPageImageAbsoluteUrl } from '@/utils/apiConfig'
import type { Document } from '@/types'
import { getDocumentYearMonth } from '@/utils/documentDate'
import './CustomerSearch.css'

// 페이지 타입
interface Page {
  pdfFilename: string
  pageNumber: number
  formType: string | null
  totalPages: number
  /** 분석 완료 여부. false면 검토 탭에서 "分析中…" 표시 */
  isAnalyzed?: boolean
}

// 검토 필터 타입: 1次/2次 각각 완료/미완료
type ReviewFilter = 'all' | 'first_reviewed' | 'first_not_reviewed' | 'second_reviewed' | 'second_not_reviewed'

/** 検討タブに復帰 시 열 문서·양식지·페이지 (문서·양식지 선택 후 해당 페이지로 이동) */
export type DocumentToOpenOnReturn = { pdf_filename: string; form_type: string | null; initialPage?: number }

interface CustomerSearchProps {
  /** 정답지 생성 탭으로 이동 시 (문서명, 현재 페이지 번호) 전달 — 브릿지에서 해당 페이지만 표시 */
  onNavigateToAnswerKey?: (pdfFilename: string, pageNumber: number) => void
  /** 検討タブに復帰 시 이 문서·양식지로 자동 선택 (설정 시 반영 후 소비) */
  documentToOpen?: DocumentToOpenOnReturn | null
  onConsumeDocumentToOpen?: () => void
}

export const CustomerSearch = ({ onNavigateToAnswerKey, documentToOpen, onConsumeDocumentToOpen }: CustomerSearchProps) => {
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const { options: formTypeOptions, formTypeLabel } = useFormTypes()
  const [showAnswerKeyModal, setShowAnswerKeyModal] = useState(false)
  /** 解答作成モーダルで選択した様式（確定時に updateFormType 反映） */
  const [answerKeyModalFormType, setAnswerKeyModalFormType] = useState<string | null>(null)
  /** 解答作成モーダル内「新規様式」入力（コードで追加） */
  const [newFormCodeInput, setNewFormCodeInput] = useState('')
  /** 様式ミニチュアでロード失敗したコード（プレースホルダー表示用） */
  const [formPreviewImageErrors, setFormPreviewImageErrors] = useState<Set<string>>(new Set())
  /** ホバー時拡大プレビュー表示する様式コード */
  const [hoverPreviewFormCode, setHoverPreviewFormCode] = useState<string | null>(null)
  /** 解答作成モーダル内「様式削除」で選択した様式コード */
  const [deleteFormCodeInput, setDeleteFormCodeInput] = useState('')
  const [currentPageIndex, setCurrentPageIndex] = useState(0) // 현재 페이지 인덱스
  /** 検討タブ復帰 시 복원할 페이지 번호 (documentToOpen 소비 후 effectiveDisplayPages 반영 시 인덱스로 설정) */
  const [pendingReturnPageNumber, setPendingReturnPageNumber] = useState<number | null>(null)
  const [inputValue, setInputValue] = useState('') // 입력창에 표시되는 값
  const [searchQuery, setSearchQuery] = useState('') // 실제 검색에 사용되는 값 (엔터 또는 버튼 클릭 시 업데이트)
  const [reviewFilter, setReviewFilter] = useState<ReviewFilter>('all') // 검토 필터
  const [formTypeFilter, setFormTypeFilter] = useState<string | null>(null) // 참조 양식지 필터 (null=전체)
  const [selectedYearMonth, setSelectedYearMonth] = useState<{ year: number; month: number } | null>(null) // 선택된 연월
  const [imageHeightPercent, setImageHeightPercent] = useState(50) // 이미지 영역 높이 비율 (20~80)
  const [isResizing, setIsResizing] = useState(false)
  const [pageJumpInput, setPageJumpInput] = useState<string>('') // 원하는 페이지 번호 입력값
  /** 문서별 보기: 설정 시 해당 문서의 페이지만 표시 (null = 전체 페이지) */
  const [selectedDocumentPdf, setSelectedDocumentPdf] = useState<string | null>(null)
  const [showCustomerListModal, setShowCustomerListModal] = useState(false)
  const [selectedCustomerNamesForFilter, setSelectedCustomerNamesForFilter] = useState<string[]>(() => {
    try {
      const s = localStorage.getItem('customer-list-modal-last-checked')
      if (s) {
        const a = JSON.parse(s)
        return Array.isArray(a) ? a : []
      }
    } catch {}
    return []
  })
  const [checkedFilterNames, setCheckedFilterNames] = useState<Set<string>>(new Set())
  const [applyCustomerFilter, setApplyCustomerFilter] = useState<boolean>(() => {
    try {
      const s = localStorage.getItem('customer-list-apply-filter')
      if (s !== null) return s === 'true'
    } catch {}
    return true
  })
  const [bulkCheckType, setBulkCheckType] = useState<'first' | 'second' | null>(null) // 1次/2次 一括 진행 중
  const [bulkCheckState, setBulkCheckState] = useState({
    allFirstChecked: false,
    allSecondChecked: false,
    someFirstChecked: false,
    someSecondChecked: false,
  })
  const bulkFirstCheckboxRef = useRef<HTMLInputElement>(null)
  const bulkSecondCheckboxRef = useRef<HTMLInputElement>(null)
  const [fileListPanelOpen, setFileListPanelOpen] = useState(false) // 우측 꼭지 호버 시 파일 목록 패널
  const fileListPanelCloseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const handleFileListPanelEnter = useCallback(() => {
    if (fileListPanelCloseTimerRef.current) {
      clearTimeout(fileListPanelCloseTimerRef.current)
      fileListPanelCloseTimerRef.current = null
    }
    setFileListPanelOpen(true)
  }, [])
  const handleFileListPanelLeave = useCallback(() => {
    fileListPanelCloseTimerRef.current = setTimeout(() => setFileListPanelOpen(false), 180)
  }, [])

  // 検討タブに復帰 시 해당 문서·양식지로 자동 선택（復帰先の文書・様式を保持）
  useEffect(() => {
    if (!documentToOpen?.pdf_filename?.trim()) return
    setSelectedDocumentPdf(documentToOpen.pdf_filename.trim())
    setFormTypeFilter(documentToOpen.form_type ?? null)
    setPendingReturnPageNumber(documentToOpen.initialPage ?? null)
    setCurrentPageIndex(0)
    onConsumeDocumentToOpen?.()
  }, [documentToOpen, onConsumeDocumentToOpen])

  // 復帰 후 표시 페이지가 준비되면 해당 페이지 번호로 인덱스 설정
  useEffect(() => {
    if (bulkFirstCheckboxRef.current) {
      bulkFirstCheckboxRef.current.indeterminate = bulkCheckState.someFirstChecked && !bulkCheckState.allFirstChecked
    }
    if (bulkSecondCheckboxRef.current) {
      bulkSecondCheckboxRef.current.indeterminate = bulkCheckState.someSecondChecked && !bulkCheckState.allSecondChecked
    }
  }, [bulkCheckState])
  const contentWrapperRef = useRef<HTMLDivElement>(null)
  const gridRef = useRef<ItemsGridRdgHandle>(null)

  const handleResizerMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    setIsResizing(true)
  }, [])

  useEffect(() => {
    if (!isResizing) return
    const onMove = (e: MouseEvent) => {
      const el = contentWrapperRef.current
      if (!el) return
      const rect = el.getBoundingClientRect()
      const y = e.clientY - rect.top
      const pct = Math.round((y / rect.height) * 100)
      setImageHeightPercent(() => {
        const next = Math.min(80, Math.max(20, pct))
        return next
      })
    }
    const onUp = () => setIsResizing(false)
    document.body.style.cursor = 'row-resize'
    document.body.style.userSelect = 'none'
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [isResizing])

  // 검토 탭 전용 문서 목록 (created_by_user_id IS NOT NULL만). 탭 진입 시마다 재조회로 캐시 리키지 방지
  const { data: documentsDataFull, isLoading: documentsLoading, error: documentsError } = useQuery({
    queryKey: ['documents', 'review'],
    queryFn: () => documentsApi.getList(undefined, { exclude_img_seed: true }),
    refetchOnMount: 'always',
  })

  // 검토 상태 통계 조회 (성능 최적화: 10초마다 갱신)
  const { data: reviewStats } = useQuery({
    queryKey: ['review-stats'],
    queryFn: () => itemsApi.getReviewStats(),
    refetchInterval: 10000, // 10초마다 갱신 (5초 -> 10초로 변경하여 부하 감소)
    staleTime: 5000, // 5초간 캐시 유지
  })

  // 거래처명으로 검색 (검색어가 있을 때만 실행)
  const { data: searchResult, isLoading: searchLoading, error: searchError } = useQuery({
    queryKey: ['search', 'customer', searchQuery, formTypeFilter],
    queryFn: () => searchApi.byCustomer(searchQuery, false, formTypeFilter ?? undefined, false),
    enabled: !!searchQuery.trim(),
  })

  // 거래처 목록 모달: 내 담당 거래처 (로그인 필요)
  const { data: mySupersData, isLoading: mySupersLoading, error: mySupersError } = useQuery({
    queryKey: ['search', 'my-supers'],
    queryFn: () => searchApi.getMySupers(),
    enabled: showCustomerListModal,
    retry: false,
  })

  // 현재 연월 계산
  const currentYearMonth = useMemo(() => {
    const now = new Date()
    return {
      year: now.getFullYear(),
      month: now.getMonth() + 1
    }
  }, [])

  // 정답지로 등록된 문서 pdf_filename 집합 (검색/거래처 필터 결과에서 정답지 페이지 제외용)
  const answerKeyPdfSet = useMemo(
    () =>
      new Set(
        (documentsDataFull?.documents ?? [])
          .filter((d: Document) => d.is_answer_key_document === true)
          .map((d: Document) => (d.pdf_filename ?? '').trim().toLowerCase())
      ),
    [documentsDataFull?.documents]
  )

  // 검토 탭 표시 문서: 업로드 탭과 동일한 전체 문서 (정답지는 UI에서 초록색으로만 구분)
  const documentsForReview = useMemo(() => {
    return documentsDataFull?.documents ?? []
  }, [documentsDataFull?.documents])

  // 문서 목록에서 선택 가능한 연월 목록 생성 (최신순)
  const availableYearMonths = useMemo(() => {
    if (!documentsForReview.length) return []

    const map = new Map<string, { year: number; month: number; count: number }>()

    documentsForReview.forEach((doc: Document) => {
      const { year, month } = getDocumentYearMonth(doc)
      const key = `${year}-${month}`
      const existing = map.get(key)
      if (existing) {
        existing.count += 1
      } else {
        map.set(key, { year, month, count: 1 })
      }
    })

    return Array.from(map.values()).sort((a, b) => {
      if (a.year !== b.year) return b.year - a.year
      return b.month - a.month
    })
  }, [documentsForReview])

  // 연도만 추출 (연도 드롭다운용, 최신순)
  const availableYears = useMemo(() => {
    const years = new Set<number>()
    availableYearMonths.forEach((ym) => years.add(ym.year))
    const list = Array.from(years).sort((a, b) => b - a)
    const current = currentYearMonth.year
    if (list.length === 0 || !list.includes(current)) return [current, ...list]
    return list
  }, [availableYearMonths, currentYearMonth.year])

  // 월 목록 (1–12, 월 드롭다운용)
  const monthOptions = useMemo(() => Array.from({ length: 12 }, (_, i) => i + 1), [])

  // 연월 선택 시 사용할 값: 선택된 연월이 있으면 그대로, 없으면 DB에 있는 연월 중 최신
  const effectiveYearMonth = useMemo(() => {
    if (selectedYearMonth) return selectedYearMonth
    if (availableYearMonths.length > 0) return availableYearMonths[0]
    return currentYearMonth
  }, [selectedYearMonth, availableYearMonths, currentYearMonth])

  // 거래처 목록 모달: 검토 탭 전체 거래처 (선택 연월 기준)
  const { data: reviewTabCustomersData, isLoading: reviewTabCustomersLoading } = useQuery({
    queryKey: ['search', 'review-tab-customers', effectiveYearMonth.year, effectiveYearMonth.month],
    queryFn: () => searchApi.getReviewTabCustomers(effectiveYearMonth.year, effectiveYearMonth.month),
    enabled: showCustomerListModal,
  })

  // 왼쪽(실제 거래처) vs 오른쪽(소매처명 전체) 유사도 매핑. notepad find_similar_supers와 동일하게 전체 풀에서 최적 매칭
  const leftList = reviewTabCustomersData?.customer_names ?? []
  const { data: allSuperNamesData } = useQuery({
    queryKey: ['search', 'all-super-names'],
    queryFn: () => searchApi.getAllSuperNames(),
    enabled: showCustomerListModal,
  })
  const rightListForMapping = allSuperNamesData?.super_names ?? []
  const { data: mappingData } = useQuery({
    queryKey: ['search', 'customer-similarity-mapping', leftList, rightListForMapping],
    queryFn: () => searchApi.getCustomerSimilarityMapping(leftList, rightListForMapping),
    enabled: showCustomerListModal && (leftList.length > 0 || rightListForMapping.length > 0),
  })
  const customerMappingRows = useMemo(() => {
    if (!mappingData) return { mapped: [], unmappedRights: [] }
    const mySupers = mySupersError ? [] : (mySupersData?.super_names ?? [])
    const usedRights = new Set((mappingData.mapped ?? []).map((m) => m.right))
    const unmappedRights = mySupers.filter((r) => !usedRights.has(r))
    return {
      mapped: mappingData.mapped,
      unmappedRights,
    }
  }, [mappingData, mySupersData?.super_names, mySupersError])

  // 取引先一覧 모달: 마지막 체크 상태 복원(저장 있음) / 없으면 유사도 90% 이상 자동 체크
  useEffect(() => {
    if (!showCustomerListModal || !customerMappingRows.mapped.length) return
    if (selectedCustomerNamesForFilter.length > 0) {
      setCheckedFilterNames(new Set(selectedCustomerNamesForFilter))
    } else {
      const toCheck = customerMappingRows.mapped.filter((r) => r.score >= 0.9).map((r) => r.left)
      setCheckedFilterNames(new Set(toCheck))
    }
  }, [showCustomerListModal, customerMappingRows.mapped, selectedCustomerNamesForFilter])

  // 모든 페이지를 평탄화하여 리스트 생성 (검색어가 없을 때 사용)
  // 선택된 연월(또는 기본 최신 연월)의 데이터만 필터링 (정답지 대상 문서 제외)
  const allPages: Page[] = useMemo(() => {
    if (!documentsForReview.length) return []

    const targetYearMonth = effectiveYearMonth
    const pages: Page[] = []

    documentsForReview.forEach((doc: Document) => {
      let docYear = doc.data_year
      let docMonth = doc.data_month
      if (!docYear || !docMonth) {
        const dateString = doc.created_at || doc.upload_date
        if (dateString) {
          const uploadDate = new Date(dateString)
          if (!isNaN(uploadDate.getTime())) {
            docYear = docYear ?? uploadDate.getFullYear()
            docMonth = docMonth ?? uploadDate.getMonth() + 1
          }
        }
      }
      if (docYear === targetYearMonth.year && docMonth === targetYearMonth.month) {
        const analyzedSet = new Set(doc.analyzed_page_numbers ?? [])
        for (let i = 1; i <= doc.total_pages; i++) {
          pages.push({
            pdfFilename: doc.pdf_filename,
            pageNumber: i,
            formType: doc.form_type,
            totalPages: doc.total_pages,
            isAnalyzed: analyzedSet.has(i),
          })
        }
      }
    })
    return pages
  }, [documentsForReview, effectiveYearMonth])

  // 검색 결과에서 페이지 리스트 생성 (검색어가 있을 때 사용)
  const searchPages: Page[] = useMemo(() => {
    if (!searchResult?.pages) return []

    return searchResult.pages.map((page: any) => ({
      pdfFilename: page.pdf_filename,
      pageNumber: page.page_number,
      formType: page.form_type,
      totalPages: 1, // 검색 결과에서는 totalPages 정보가 없으므로 1로 설정
      isAnalyzed: true, // 검색 결과는 이미 분석된 페이지만 옴
    }))
  }, [searchResult])

  // 선택한 거래처로 필터 (取引先一覧でチェック→確認)
  const { data: filterPagesData } = useQuery({
    queryKey: ['search', 'pages-by-customers', selectedCustomerNamesForFilter, formTypeFilter],
    queryFn: () => searchApi.postPagesByCustomers(selectedCustomerNamesForFilter, formTypeFilter ?? undefined),
    enabled: selectedCustomerNamesForFilter.length > 0,
  })
  const filterPages: Page[] = useMemo(() => {
    if (!filterPagesData?.pages) return []
    return filterPagesData.pages.map((page: any) => ({
      pdfFilename: page.pdf_filename,
      pageNumber: page.page_number,
      formType: page.form_type,
      totalPages: 1,
      isAnalyzed: true,
    }))
  }, [filterPagesData])

  // 우선순위: 검색어 > 선택 거래처 필터 > 전체 페이지. 그 다음 참조 양식지 + 검토 필터 적용
  // 정답지 문서도 목록에 포함 (업로드 탭과 동일하게 모두 표시, 정답지는 UI에서 초록색으로 구분)
  const displayPages: Page[] = useMemo(() => {
    let pages: Page[]
    if (searchQuery.trim()) {
      pages = searchPages
    } else if (selectedCustomerNamesForFilter.length > 0 && applyCustomerFilter) {
      pages = filterPages
    } else {
      pages = allPages
    }

    // 참조 양식지(form_type) 필터 적용
    if (formTypeFilter) {
      pages = pages.filter((p) => p.formType === formTypeFilter)
    }

    // 검토 필터 적용
    if (reviewFilter === 'all' || !reviewStats?.page_stats) {
      return pages
    }

    const statsMap = new Map<string, { first: boolean; second: boolean }>()
    reviewStats.page_stats.forEach((stat) => {
      const key = `${stat.pdf_filename}_${stat.page_number}`
      statsMap.set(key, { first: stat.first_reviewed, second: stat.second_reviewed })
    })

    return pages.filter((page) => {
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
  }, [selectedCustomerNamesForFilter, applyCustomerFilter, filterPages, searchQuery, searchPages, allPages, formTypeFilter, reviewFilter, reviewStats])

  // 검토 드롭다운 괄호 안 페이지 수: 담당자/검색/양식지 적용된 범위만 집계 (검토 필터 적용 전, 정답지 포함)
  const filteredReviewCounts = useMemo(() => {
    let pages: Page[]
    if (searchQuery.trim()) {
      pages = searchPages
    } else if (selectedCustomerNamesForFilter.length > 0 && applyCustomerFilter) {
      pages = filterPages
    } else {
      pages = allPages
    }
    if (formTypeFilter) {
      pages = pages.filter((p) => p.formType === formTypeFilter)
    }
    const keySet = new Set(pages.map((p) => `${p.pdfFilename}_${p.pageNumber}`))
    if (!reviewStats?.page_stats) {
      return { firstReviewed: 0, firstNotReviewed: 0, secondReviewed: 0, secondNotReviewed: 0 }
    }
    let firstReviewed = 0
    let firstNotReviewed = 0
    let secondReviewed = 0
    let secondNotReviewed = 0
    reviewStats.page_stats.forEach((stat) => {
      const key = `${stat.pdf_filename}_${stat.page_number}`
      if (!keySet.has(key)) return
      if (stat.first_reviewed) firstReviewed += 1
      else firstNotReviewed += 1
      if (stat.second_reviewed) secondReviewed += 1
      else secondNotReviewed += 1
    })
    return { firstReviewed, firstNotReviewed, secondReviewed, secondNotReviewed }
  }, [selectedCustomerNamesForFilter, applyCustomerFilter, filterPages, searchQuery, searchPages, allPages, formTypeFilter, reviewStats])

  // 문서별 필터: 선택 시 해당 문서 페이지만 (업로드 문서만 목록에 표시)
  const uploadedPdfSet = useMemo(
    () => new Set((documentsForReview ?? []).map((d: Document) => (d.pdf_filename ?? '').trim().toLowerCase())),
    [documentsForReview]
  )
  const effectiveDisplayPages = useMemo(() => {
    const base = displayPages
    if (!selectedDocumentPdf?.trim()) return base
    const key = selectedDocumentPdf.trim().toLowerCase()
    return base.filter((p) => (p.pdfFilename ?? '').trim().toLowerCase() === key)
  }, [displayPages, selectedDocumentPdf])

  const currentPage = effectiveDisplayPages[currentPageIndex] ?? null
  const totalFilteredPages = effectiveDisplayPages.length

  // 표시 중인 페이지 목록에서 파일별 첫 등장 인덱스 (우측 패널·파일 클릭 시 해당 문서만 표시)
  const fileNavOptions = useMemo(() => {
    const seen = new Set<string>()
    const list: { pdfFilename: string; firstIndex: number }[] = []
    displayPages.forEach((p, idx) => {
      const key = (p.pdfFilename ?? '').trim()
      if (key && !seen.has(key)) {
        seen.add(key)
        list.push({ pdfFilename: p.pdfFilename, firstIndex: idx })
      }
    })
    return list
  }, [displayPages])

  // 파일별 1次/2次 검토율 (우측 패널 표시용。벡터/解答済는 전용화면에서만 표시)
  const fileNavOptionsWithStats = useMemo(() => {
    if (!reviewStats?.page_stats) return fileNavOptions.map((o) => ({ ...o, totalPages: 0, firstReviewed: 0, secondReviewed: 0 }))
    return fileNavOptions.map((opt) => {
      const pagesInFile = displayPages.filter((p) => (p.pdfFilename ?? '').trim() === (opt.pdfFilename ?? '').trim())
      const keySet = new Set(pagesInFile.map((p) => `${p.pdfFilename}_${p.pageNumber}`))
      let firstReviewed = 0
      let secondReviewed = 0
      reviewStats.page_stats.forEach((stat) => {
        if (!keySet.has(`${stat.pdf_filename}_${stat.page_number}`)) return
        if (stat.first_reviewed) firstReviewed += 1
        if (stat.second_reviewed) secondReviewed += 1
      })
      const totalPages = pagesInFile.length
      return {
        ...opt,
        totalPages,
        firstReviewed,
        secondReviewed,
      }
    })
  }, [fileNavOptions, displayPages, reviewStats?.page_stats])

  // 업로드 문서만 파일 목록에 표시 (img 폴더 시드 문서 제외)
  const fileNavOptionsWithStatsFiltered = useMemo(
    () =>
      fileNavOptionsWithStats.filter((opt) =>
        uploadedPdfSet.has((opt.pdfFilename ?? '').trim().toLowerCase())
      ),
    [fileNavOptionsWithStats, uploadedPdfSet]
  )

  // 문서별 보기 시 인덱스가 범위를 벗어나면 0으로; 선택 문서가 필터 후 없으면 すべてに戻す
  // データ未読込で displayPages が空のときは selectedDocumentPdf をクリアしない（検討タブに復帰直後の文書が消えないように）
  useEffect(() => {
    if (effectiveDisplayPages.length > 0 && currentPageIndex >= effectiveDisplayPages.length) {
      setCurrentPageIndex(0)
    }
    if (selectedDocumentPdf && effectiveDisplayPages.length === 0 && displayPages.length > 0) {
      setSelectedDocumentPdf(null)
      setCurrentPageIndex(0)
    }
  }, [effectiveDisplayPages.length, currentPageIndex, selectedDocumentPdf, displayPages.length])

  // 현재 인덱스/전체 페이지 수 변경 시, 입력창에 현재 페이지 번호 동기화
  useEffect(() => {
    if (totalFilteredPages === 0) {
      setPageJumpInput('')
    } else {
      setPageJumpInput(String(currentPageIndex + 1))
    }
  }, [currentPageIndex, totalFilteredPages])

  // 復帰後 표시 페이지가 준비되면 해당 페이지 번호로 인덱스 설정
  useEffect(() => {
    if (pendingReturnPageNumber == null || effectiveDisplayPages.length === 0) return
    const isDocForReturn =
      selectedDocumentPdf?.trim() &&
      effectiveDisplayPages[0]?.pdfFilename?.trim()?.toLowerCase() === selectedDocumentPdf.trim().toLowerCase()
    if (!isDocForReturn) return
    const idx = effectiveDisplayPages.findIndex((p) => p.pageNumber === pendingReturnPageNumber)
    if (idx >= 0) setCurrentPageIndex(idx)
    setPendingReturnPageNumber(null)
  }, [pendingReturnPageNumber, effectiveDisplayPages, selectedDocumentPdf])

  // 현재 페이지의 검토율 조회
  const currentPageStats = useMemo(() => {
    if (!currentPage || !reviewStats?.page_stats) return null
    return reviewStats.page_stats.find(
      (stat) => stat.pdf_filename === currentPage.pdfFilename && stat.page_number === currentPage.pageNumber
    )
  }, [currentPage, reviewStats])

  // 解答作成指定可能か：この文書の全ページが1次・2次検討済みのときのみ true
  const canDesignateAnswerKey = useMemo(() => {
    if (!currentPage?.pdfFilename || !reviewStats?.page_stats?.length) return false
    const docPages = reviewStats.page_stats.filter((s) => s.pdf_filename === currentPage.pdfFilename)
    if (docPages.length === 0) return false
    return docPages.every((p) => p.first_reviewed && p.second_reviewed)
  }, [currentPage?.pdfFilename, reviewStats?.page_stats])

  // 현재 페이지의 page_role 조회
  const { data: pageImageData } = useQuery({
    queryKey: ['page-image', currentPage?.pdfFilename, currentPage?.pageNumber],
    queryFn: () => {
      if (!currentPage) return null
      console.log('🔍 이미지 요청:', currentPage.pdfFilename, currentPage.pageNumber)
      return searchApi.getPageImage(currentPage.pdfFilename, currentPage.pageNumber)
    },
    enabled: !!currentPage?.pdfFilename && !!currentPage?.pageNumber,
  })


  const currentPageRole = pageImageData?.page_role

  // 검토 탭: 현재 문서의 answer-json 조회 (해당 페이지 분석 여부 판단용)
  const { data: answerJsonForDoc } = useQuery({
    queryKey: ['document-answer-json', currentPage?.pdfFilename ?? ''],
    queryFn: () => documentsApi.getDocumentAnswerJson(currentPage!.pdfFilename),
    enabled: !!currentPage?.pdfFilename,
  })

  const [analyzingPageKey, setAnalyzingPageKey] = useState<string | null>(null)
  const analyzeSinglePageMutation = useMutation({
    mutationFn: ({ pdfFilename, pageNumber }: { pdfFilename: string; pageNumber: number }) =>
      documentsApi.analyzeSinglePage(pdfFilename, pageNumber),
    onSuccess: (_, { pdfFilename }) => {
      queryClient.invalidateQueries({ queryKey: ['document-answer-json', pdfFilename] })
      queryClient.invalidateQueries({ queryKey: ['items', pdfFilename] })
      queryClient.invalidateQueries({ queryKey: ['page-meta', pdfFilename] })
      queryClient.invalidateQueries({ queryKey: ['search', 'customer', searchQuery, formTypeFilter] })
      setAnalyzingPageKey(null)
    },
    onError: () => setAnalyzingPageKey(null),
  })

  // 검토 탭: 페이지 이동은 분석을 자동 실행하지 않음. 분석은 버튼(이 페이지 재분석 / 이 페이지 이후 전체 재분석)으로만 실행 (to_do 5).

  const [analyzingFromPage, setAnalyzingFromPage] = useState(false)
  const analyzeFromPageMutation = useMutation({
    mutationFn: ({ pdfFilename, fromPageNumber }: { pdfFilename: string; fromPageNumber: number }) =>
      documentsApi.analyzeFromPage(pdfFilename, fromPageNumber),
    onSuccess: (data, { pdfFilename }) => {
      queryClient.invalidateQueries({ queryKey: ['document-answer-json', pdfFilename] })
      queryClient.invalidateQueries({ queryKey: ['items', pdfFilename] })
      queryClient.invalidateQueries({ queryKey: ['page-meta', pdfFilename] })
      queryClient.invalidateQueries({ queryKey: ['search', 'customer', searchQuery, formTypeFilter] })
      setAnalyzingFromPage(false)
      if (data.cancelled) {
        alert('学習リクエストのため再分析を中断しました。必要に応じて再度「このページ以降の全ページを再分析」を実行してください。')
      }
    },
    onError: () => setAnalyzingFromPage(false),
  })

  const setAnswerKeyDocumentMutation = useMutation({
    mutationKey: ['documents', 'answer-key-designate'],
    mutationFn: ({ pdfFilename }: { pdfFilename: string; pageNumber: number }) =>
      documentsApi.setAnswerKeyDocument(pdfFilename),
    onSuccess: (_data, { pdfFilename, pageNumber }) => {
      queryClient.invalidateQueries({ queryKey: ['documents', 'all'] })
      queryClient.invalidateQueries({ queryKey: ['documents', 'review'] })
      queryClient.invalidateQueries({ queryKey: ['documents', 'for-answer-key-tab'] })
      queryClient.invalidateQueries({ queryKey: ['rag-admin', 'learning-pages'] })
      queryClient.invalidateQueries({ queryKey: ['form-types'] })
      setShowAnswerKeyModal(false)
      onNavigateToAnswerKey?.(pdfFilename, pageNumber)
    },
  })

  // 解答作成モーダルを開いたときに選択様式を現在値（または先頭）で初期化
  useEffect(() => {
    if (showAnswerKeyModal && currentPage) {
      setAnswerKeyModalFormType(currentPage.formType ?? formTypeOptions[0]?.value ?? null)
      setNewFormCodeInput('')
      setDeleteFormCodeInput('')
      setFormPreviewImageErrors(new Set())
    }
  }, [showAnswerKeyModal, currentPage?.pdf_filename, currentPage?.formType, formTypeOptions])

  const createFormTypeMutation = useMutation({
    mutationFn: (params: { form_code?: string; display_name?: string }) => formTypesApi.create(params),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['form-types'] })
      setAnswerKeyModalFormType(data.form_code)
      setNewFormCodeInput('')
    },
  })

  const deleteFormTypeMutation = useMutation({
    mutationFn: (formCode: string) => formTypesApi.delete(formCode),
    onSuccess: (_, formCode) => {
      queryClient.invalidateQueries({ queryKey: ['form-types'] })
      if (answerKeyModalFormType === formCode) {
        const rest = formTypeOptions.filter((o) => o.value !== formCode)
        setAnswerKeyModalFormType(rest[0]?.value ?? null)
      }
    },
  })

  const handleDeleteFormType = async () => {
    const code = deleteFormCodeInput.trim()
    if (!code) return
    if (!window.confirm(`様式「${formTypeLabel(code)}」（${code}）を削除しますか？\nこの様式で分類された文書がある場合は削除できません。`)) return
    try {
      await deleteFormTypeMutation.mutateAsync(code)
      setDeleteFormCodeInput('')
      alert('削除しました。')
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      const message =
        detail && String(detail).includes('使用している文書')
          ? detail
          : detail
            ? `削除に失敗しました: ${detail}`
            : '削除に失敗しました。'
      alert(message)
    }
  }

  const handleAddNewFormType = async () => {
    const code = newFormCodeInput.trim()
    if (!code) return
    try {
      await createFormTypeMutation.mutateAsync({ form_code: code })
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      if (detail && String(detail).includes('already exists')) {
        // 既存コードをそのまま選択
        setAnswerKeyModalFormType(code)
        queryClient.invalidateQueries({ queryKey: ['form-types'] })
        setNewFormCodeInput('')
      } else {
        alert(detail ? `エラー: ${detail}` : '様式の追加に失敗しました。')
      }
    }
  }

  const handleAnswerKeyConfirm = async () => {
    if (!currentPage) return
    const pdfFilename = currentPage.pdfFilename
    const pageNumber = currentPage.pageNumber
    try {
      // 様式を変更してから解答作成対象に指定
      if (answerKeyModalFormType && answerKeyModalFormType !== currentPage.formType) {
        await documentsApi.updateFormType(pdfFilename, answerKeyModalFormType)
        queryClient.invalidateQueries({ queryKey: ['documents', 'all'] })
        queryClient.invalidateQueries({ queryKey: ['documents', 'review'] })
        queryClient.invalidateQueries({ queryKey: ['documents', 'for-answer-key-tab'] })
      }
      await setAnswerKeyDocumentMutation.mutateAsync({ pdfFilename, pageNumber })
    } catch (err: unknown) {
      const msg = err && typeof err === 'object' && 'response' in err
        ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        : null
      alert(msg ? `エラー: ${msg}` : '処理に失敗しました。')
    }
  }

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

  // 페이지 점프 입력 변경
  const handlePageJumpInputChange = (value: string) => {
    setPageJumpInput(value)
  }

  // 입력된 페이지 번호로 이동
  const handlePageJumpSubmit = () => {
    if (!pageJumpInput.trim()) return
    if (totalFilteredPages <= 0) return

    const num = Number(pageJumpInput)
    if (Number.isNaN(num)) return

    const clamped = Math.min(Math.max(num, 1), totalFilteredPages)
    setCurrentPageIndex(clamped - 1)
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

  // 참조 양식지 필터 변경 시 인덱스 초기화
  useEffect(() => {
    setCurrentPageIndex(0)
  }, [formTypeFilter])

  // 검토 필터 변경 핸들러
  const handleReviewFilterChange = (filter: ReviewFilter) => {
    setReviewFilter(filter)
    setCurrentPageIndex(0) // 필터 변경 시 첫 페이지로 이동
  }

  const handleYearChange = (yearStr: string) => {
    const year = Number(yearStr)
    if (!year) return
    setSelectedYearMonth({ year, month: effectiveYearMonth.month })
    setCurrentPageIndex(0)
  }

  const handleMonthChange = (monthStr: string) => {
    const month = Number(monthStr)
    if (!month) return
    setSelectedYearMonth({ year: effectiveYearMonth.year, month })
    setCurrentPageIndex(0)
  }

  // 문서 로딩 중
  if (documentsLoading && !searchQuery.trim()) {
    return (
      <div className="customer-search">
        <div className="loading">문서 목록 로딩 중...</div>
      </div>
    )
  }

  // 검색 에러
  if (searchError && searchQuery.trim()) {
    return (
      <div className="customer-search">
        <div className="no-results">
          검색 중 오류가 발생했습니다: {searchError instanceof Error ? searchError.message : 'Unknown error'}
        </div>
      </div>
    )
  }

  // 검색어가 있고 검색 결과가 없을 때 (로딩 중이면 아래 메인 레이아웃에서 検索中... 표시)
  if (searchQuery.trim() && displayPages.length === 0 && !searchLoading) {
    return (
      <div className="customer-search">
        {/* 페이지 내비게이션 섹션 (검색창 포함) */}
        <div className="page-navigation-section">
          <div className="page-nav-controls" style={{ display: 'flex', gap: '10px', alignItems: 'center', justifyContent: 'center', margin: '20px' }}>
            {/* 검색창 */}
            <input
              type="text"
              value={inputValue}
              onChange={(e) => handleInputChange(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder="取引先名で検索"
              className="page-search-input"
              style={{ width: '300px', padding: '10px' }}
            />
            {/* 검색 버튼 */}
            <button
              onClick={handleSearch}
              style={{
                padding: '10px 20px',
                background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                color: 'white',
                border: 'none',
                borderRadius: '4px',
                cursor: 'pointer',
                fontWeight: 'bold'
              }}
            >
              検索
            </button>
          </div>
        </div>
        <div className="no-results">
          <p>검색 결과가 없습니다.</p>
        </div>
      </div>
    )
  }

  // 연월/검색 결과에 데이터가 없을 때는 아래 메인 레이아웃에서 처리 (드롭다운·그리드 영역 유지)

  const hasNoData = displayPages.length === 0
  const noDataMessage =
    searchLoading && searchQuery.trim()
      ? '検索中...'
      : searchQuery.trim()
        ? '検索結果がありません。'
        : documentsError
          ? '文書一覧を取得できません。バックエンドの接続を確認してください。（API接続エラー）'
          : documentsDataFull?.documents?.length
            ? '選択した期間にデータがありません。対象期間を変更してください。'
            : 'アップロードされたファイルがありません。'

  return (
    <div className="customer-search">
      <div ref={contentWrapperRef} className="customer-search-split">
        {/* 이미지 섹션: 데이터 있으면 이미지, 없으면 데이터 없음 메시지 */}
        {currentPage ? (
          <div
            className="selected-page-content image-section"
            style={{ height: `${imageHeightPercent}%` }}
          >
            <PageImageViewer
              pdfFilename={currentPage.pdfFilename}
              pageNumber={currentPage.pageNumber}
            />
          </div>
        ) : hasNoData ? (
          <div
            className="selected-page-content image-section no-data-placeholder"
            style={{ height: `${imageHeightPercent}%` }}
          >
            <div className="no-results">{noDataMessage}</div>
          </div>
        ) : null}

        {/* 경계선 리사이저: 드래그하면 이미지/그리드 비율 조절 */}
        {(currentPage || hasNoData) && (
          <div
            className="split-resizer"
            onMouseDown={handleResizerMouseDown}
            title="드래그하여 이미지/그리드 비율 조절"
            role="separator"
            aria-valuenow={imageHeightPercent}
            aria-valuemin={20}
            aria-valuemax={80}
          />
        )}

        {/* 페이지 내비게이션 섹션: 페이지 <> 2/4 → 연월 → 양식 → 검색 → 파일명 → p.N → 나머지 */}
        <div className="page-navigation-section">
        <div className="page-nav-controls">
          {/* 1. 페이지 <> 2/4 */}
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
          <div className="page-number-badge">
            <input
              type="number"
              className="page-number-input"
              min={1}
              max={totalFilteredPages || 1}
              value={pageJumpInput}
              onChange={(e) => handlePageJumpInputChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  handlePageJumpSubmit()
                }
              }}
            />
            <span className="total-pages-text">of {totalFilteredPages}</span>
          </div>

          {/* 2. 연월 선택 (커스텀 드롭다운) */}
          <NavCustomDropdown
            value={String(effectiveYearMonth.year)}
            onChange={handleYearChange}
            options={availableYears.map((y) => ({ value: String(y), label: `${y}年` }))}
            ariaLabel="年を選択"
            containerClass="nav-dropdown-year"
          />
          <NavCustomDropdown
            value={String(effectiveYearMonth.month)}
            onChange={handleMonthChange}
            options={monthOptions.map((m) => ({ value: String(m), label: `${m}月` }))}
            ariaLabel="月を選択"
            containerClass="nav-dropdown-month"
          />

          {/* 3. 양식 선택 */}
          <FormTypeFilterDropdown
            value={formTypeFilter}
            onChange={setFormTypeFilter}
            options={formTypeOptions}
          />

          {/* 4. 거래처 검색 */}
          <input
            type="text"
            value={inputValue}
            onChange={(e) => handleInputChange(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder="取引先名で検索"
            className="page-search-input"
          />
          <button
            onClick={handleSearch}
            className="search-button"
            disabled={searchLoading}
            title={searchLoading ? '検索中...' : undefined}
          >
            {searchLoading && searchQuery.trim() ? '検索中...' : '検索'}
          </button>
          <div
            className="customer-filter-pill"
            role="button"
            tabIndex={0}
            onClick={(e) => {
              if ((e.target as HTMLElement).closest('input[type="checkbox"]')) return
              setShowCustomerListModal(true)
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                setShowCustomerListModal(true)
              }
            }}
            title="担当取引先を選択"
          >
            <span className="customer-filter-pill-text">担当取引先のみ表示</span>
            <input
              type="checkbox"
              checked={applyCustomerFilter}
              onChange={(e) => {
                const v = e.target.checked
                setApplyCustomerFilter(v)
                try {
                  localStorage.setItem('customer-list-apply-filter', String(v))
                } catch {}
              }}
              aria-label="担当取引先で絞り込みを適用"
              onClick={(e) => e.stopPropagation()}
            />
          </div>
          {/* 保存 + 再分析 + 学習リクエスト + 解答作成：検討タブでページ単位の保存・再分析・学習 */}
          <div className="nav-action-buttons">
            <button
              type="button"
              className="nav-action-btn nav-save-btn"
              onClick={() => gridRef.current?.save?.()}
              title="編集中の行を保存（Ctrl+Sと同じ）"
            >
              保存
            </button>
            {currentPage && (
              <>
                <button
                  type="button"
                  className="nav-action-btn nav-reanalyze-btn"
                  onClick={() => {
                    const key = `${currentPage.pdfFilename}:${currentPage.pageNumber}`
                    setAnalyzingPageKey(key)
                    analyzeSinglePageMutation.mutate(
                      { pdfFilename: currentPage.pdfFilename, pageNumber: currentPage.pageNumber },
                      { onSettled: () => setAnalyzingPageKey(null) }
                    )
                  }}
                  disabled={!!analyzingPageKey || analyzeSinglePageMutation.isPending || analyzingFromPage || analyzeFromPageMutation.isPending}
                  title="このページのみ再分析（OCR＋RAG＋LLM）"
                >
                  {analyzingPageKey || analyzeSinglePageMutation.isPending ? '分析中…' : 'このページ再分析'}
                </button>
                <button
                  type="button"
                  className="nav-action-btn nav-reanalyze-from-btn"
                  onClick={() => {
                    setAnalyzingFromPage(true)
                    analyzeFromPageMutation.mutate(
                      {
                        pdfFilename: currentPage.pdfFilename,
                        fromPageNumber: currentPage.pageNumber,
                      },
                      { onSettled: () => setAnalyzingFromPage(false) }
                    )
                  }}
                  disabled={
                    analyzingFromPage ||
                    analyzeFromPageMutation.isPending ||
                    !!analyzingPageKey ||
                    analyzeSinglePageMutation.isPending ||
                    (totalFilteredPages !== null && currentPage.pageNumber >= totalFilteredPages)
                  }
                  title="このページから最終ページまで並列で再分析。学習リクエスト実行時は進行中の再分析を中断します。"
                >
                  {analyzingFromPage || analyzeFromPageMutation.isPending
                    ? '再分析中…'
                    : 'このページ以降の全ページを再分析'}
                </button>
                <button
                  type="button"
                  className="nav-action-btn nav-learning-request-btn"
                  onClick={async () => {
                    const sid = localStorage.getItem('sessionId')
                    if (!sid) {
                      showToast(
                        '세션이 만료되었거나 로그인이 필요합니다. 페이지를 새로고침한 뒤 다시 로그인해 주세요.',
                        'error'
                      )
                      return
                    }
                    if (gridRef.current?.hasUnsavedEdits?.()) {
                      alert('저장하지 않은 행이 있습니다. 저장 후 학습 요청해 주세요.')
                      return
                    }
                    try {
                      const res = await ragAdminApi.learningRequestPage(
                        currentPage.pdfFilename,
                        currentPage.pageNumber,
                        sid
                      )
                      queryClient.invalidateQueries({ queryKey: ['search', 'customer', searchQuery, formTypeFilter] })
                      queryClient.invalidateQueries({ queryKey: ['documents', 'in-vector-index'] })
                      queryClient.invalidateQueries({ queryKey: ['rag-admin', 'status'] })
                      showToast(
                        '이 페이지를 정답지로 반영했습니다. 현황 탭 → RAG(ベクターDB) 섹션의 「全体解答」「使用中解答」 수가 증가합니다.',
                        'success'
                      )
                      if (res.rag_rebuilt) {
                        showToast(
                          `제품/판매처·소매처 벡터 DB가 생성되었습니다. (제품 ${res.rag_rebuilt.product}건, 판매처·소매처 ${res.rag_rebuilt.retail}건)`,
                          'success'
                        )
                      }
                    } catch (e: unknown) {
                      const msg = e && typeof e === 'object' && 'response' in e
                        ? (e as { response?: { data?: { detail?: string } } }).response?.data?.detail
                        : (e as Error)?.message
                      showToast(msg ? `학습 요청 실패: ${msg}` : '학습 요청에 실패했습니다.', 'error')
                    }
                  }}
                  title="該当ページをベクターDBに反映"
                >
                  学習リクエスト
                </button>
                <button
                  type="button"
                  className="nav-action-btn answer-key-designate-btn"
                  onClick={() => setShowAnswerKeyModal(true)}
                  title="この文書を解答作成対象に指定（解答作成タブで編集・ベクターDB反映が可能）"
                >
                  解答作成
                </button>
              </>
            )}
          </div>

          {/* 1次/2次 一括 · 검토율 (파일 목록은 우측 패널) */}
          <div className="page-filename-container">
            <PageRoleBadge pageRole={currentPageRole} />
            {/* 1次/2次 一括チェックボックス（チェック=全チェック、解除=全解除） */}
            {currentPage && (
              <div className="nav-bulk-check-inline" title="このページの1次・2次検討を一括チェック/解除">
                <label className="bulk-check-label">
                  <input
                    ref={bulkFirstCheckboxRef}
                    type="checkbox"
                    className="bulk-check-cb"
                    checked={bulkCheckState.allFirstChecked}
                    disabled={bulkCheckType !== null}
                    title="このページの1次検討を一括チェック/解除"
                    onChange={async (e) => {
                      if (!gridRef.current) return
                      const checked = e.target.checked
                      setBulkCheckType('first')
                      try {
                        if (checked) await gridRef.current.checkAllFirst()
                        else await gridRef.current.uncheckAllFirst()
                      } finally {
                        setBulkCheckType(null)
                      }
                    }}
                  />
                  <span className="bulk-check-label-text">1次</span>
                </label>
                <label className="bulk-check-label">
                  <input
                    ref={bulkSecondCheckboxRef}
                    type="checkbox"
                    className="bulk-check-cb"
                    checked={bulkCheckState.allSecondChecked}
                    disabled={bulkCheckType !== null}
                    title="このページの2次検討を一括チェック/解除"
                    onChange={async (e) => {
                      if (!gridRef.current) return
                      const checked = e.target.checked
                      setBulkCheckType('second')
                      try {
                        if (checked) await gridRef.current.checkAllSecond()
                        else await gridRef.current.uncheckAllSecond()
                      } finally {
                        setBulkCheckType(null)
                      }
                    }}
                  />
                  <span className="bulk-check-label-text">2次</span>
                </label>
              </div>
            )}
            <ReviewRateBadges stats={currentPageStats} />
          </div>

          {/* 검토 필터 드롭다운: 담당자/검색/양식지 필터 적용 범위 기준 페이지 수 */}
          <ReviewFilterDropdown
            firstReviewedCount={filteredReviewCounts.firstReviewed}
            firstNotReviewedCount={filteredReviewCounts.firstNotReviewed}
            secondReviewedCount={filteredReviewCounts.secondReviewed}
            secondNotReviewedCount={filteredReviewCounts.secondNotReviewed}
            currentFilter={reviewFilter}
            onFilterChange={handleReviewFilterChange}
          />
        </div>
      </div>

      {analyzingPageKey && (
        <div className="search-tab-analyzing-banner" role="status">
          ページ分析中…
        </div>
      )}

      {/* 그리드 섹션: 아이템 조회 시 商品名 기준 시키리/본부장 자동 매칭되어 仕切・本部長 컬럼에 표시 */}
      {currentPage ? (
        <div className="selected-page-content grid-section">
          {currentPage.isAnalyzed === false ? (
            <div className="search-tab-page-analyzing" role="status">
              このページは分析中です
            </div>
          ) : (
            <ItemsGridRdg
              ref={gridRef}
              pdfFilename={currentPage.pdfFilename}
              pageNumber={currentPage.pageNumber}
              formType={currentPage.formType}
              onBulkCheckStateChange={setBulkCheckState}
              readOnly={false}
            />
          )}
        </div>
      ) : hasNoData ? (
        <div className="selected-page-content grid-section no-data-placeholder">
          <div className="no-results">{noDataMessage}</div>
        </div>
      ) : null}

      {/* 解答作成確認モーダル */}
      {showAnswerKeyModal && currentPage && (
        <div className="answer-key-modal-overlay" onClick={() => setShowAnswerKeyModal(false)}>
          <div className="answer-key-modal answer-key-modal-wide" onClick={(e) => e.stopPropagation()}>
            <h3 className="answer-key-modal-title">解答作成対象の指定</h3>
            <p className="answer-key-modal-body">
              この文書を解答作成対象に指定しますか？
              <br />
              <span className="answer-key-modal-hint">
                指定後は解答作成タブで編集できます。保存後、学習リクエストで該当ページをベクターDBに反映できます。
              </span>
              {!canDesignateAnswerKey && (
                <span className="answer-key-modal-warn" role="status">
                  ※1・2次検討が完了していない文書です。
                </span>
              )}
            </p>
            <p className="answer-key-modal-current-form">
              現在の様式: <strong>{formTypeLabel(currentPage.formType)}</strong>
              {currentPage.formType && `（${currentPage.formType}）`}
            </p>
            <p className="answer-key-modal-form-question">解答作成に使用する様式を選択してください。</p>
            <div className="answer-key-modal-form-grid">
              <p className="answer-key-modal-form-grid-label">様式プレビュー（クリックで選択）</p>
              <div className="answer-key-form-images" role="group" aria-label="様式プレビュー">
                {formTypeOptions.map((opt) => {
                  const selected = (answerKeyModalFormType ?? '') === opt.value
                  const imgFailed = formPreviewImageErrors.has(opt.value)
                  const previewSrc = `/images/form_${opt.value}.png`
                  return (
                    <div
                      key={opt.value}
                      className={`answer-key-form-image-item${selected ? ' selected' : ''}`}
                      onClick={() => setAnswerKeyModalFormType(opt.value)}
                      onMouseEnter={() => setHoverPreviewFormCode(opt.value)}
                      onMouseLeave={() => setHoverPreviewFormCode(null)}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault()
                          setAnswerKeyModalFormType(opt.value)
                        }
                      }}
                      aria-pressed={selected}
                      aria-label={`様式 ${opt.label}（${opt.value}）`}
                    >
                      <div className="answer-key-form-image-wrap">
                        {!imgFailed ? (
                          <img
                            src={previewSrc}
                            alt=""
                            onError={() =>
                              setFormPreviewImageErrors((prev) => new Set(prev).add(opt.value))
                            }
                          />
                        ) : null}
                        {imgFailed ? (
                          <span className="answer-key-form-image-placeholder">画像なし</span>
                        ) : null}
                      </div>
                      <span className="answer-key-form-image-label">
                        {opt.label}（{opt.value}）
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>
            <div className="answer-key-modal-form-choices" role="group" aria-label="様式選択">
              {formTypeOptions.map((opt) => (
                <label key={opt.value} className="answer-key-modal-form-choice">
                  <input
                    type="radio"
                    name="answer-key-modal-form-type"
                    value={opt.value}
                    checked={(answerKeyModalFormType ?? '') === opt.value}
                    onChange={() => setAnswerKeyModalFormType(opt.value)}
                  />
                  {opt.label}（{opt.value}）
                </label>
              ))}
            </div>
            <div className="answer-key-modal-new-form">
              <div className="answer-key-modal-new-form-label">
                新規様式（コードで追加）:
                <input
                  type="text"
                  className="answer-key-modal-new-form-input"
                  placeholder="例: 07"
                  value={newFormCodeInput}
                  onChange={(e) => setNewFormCodeInput(e.target.value)}
                  maxLength={10}
                  aria-label="新規様式コード"
                />
                <button
                  type="button"
                  className="answer-key-modal-btn"
                  onClick={handleAddNewFormType}
                  disabled={!newFormCodeInput.trim() || createFormTypeMutation.isPending}
                >
                  {createFormTypeMutation.isPending ? '追加中…' : '追加して選択'}
                </button>
              </div>
            </div>
            <div className="answer-key-modal-new-form">
              <div className="answer-key-modal-new-form-label">
                様式を削除:
                <select
                  className="answer-key-modal-new-form-input"
                  value={deleteFormCodeInput}
                  onChange={(e) => setDeleteFormCodeInput(e.target.value)}
                  aria-label="削除する様式を選択"
                  style={{ minWidth: '8rem' }}
                >
                  <option value="">— 選択 —</option>
                  {formTypeOptions.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}（{opt.value}）
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="answer-key-modal-btn cancel"
                  onClick={handleDeleteFormType}
                  disabled={!deleteFormCodeInput || deleteFormTypeMutation.isPending}
                >
                  {deleteFormTypeMutation.isPending ? '削除中…' : '削除'}
                </button>
              </div>
            </div>
            {hoverPreviewFormCode && (
              <div
                className="answer-key-form-preview-overlay"
                style={{
                  left: '50%',
                  top: '50%',
                  transform: 'translate(-50%, -50%)',
                }}
                aria-hidden
              >
                <img
                  src={`/images/form_${hoverPreviewFormCode}.png`}
                  alt=""
                  onError={(e) => {
                    e.currentTarget.style.display = 'none'
                  }}
                />
                <span className="answer-key-form-preview-label">
                  {formTypeLabel(hoverPreviewFormCode)}（{hoverPreviewFormCode}）
                </span>
              </div>
            )}
            <p className="answer-key-modal-filename">{currentPage.pdfFilename}</p>
            <div className="answer-key-modal-actions">
              <button
                type="button"
                className="answer-key-modal-btn cancel"
                onClick={() => setShowAnswerKeyModal(false)}
              >
                いいえ
              </button>
              <button
                type="button"
                className="answer-key-modal-btn confirm"
                onClick={handleAnswerKeyConfirm}
                disabled={setAnswerKeyDocumentMutation.isPending || !answerKeyModalFormType}
              >
                {setAnswerKeyDocumentMutation.isPending ? '処理中…' : 'はい（解答作成タブへ移動）'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 取引先一覧モーダル: 左=実際取引先、右=担当(retail_user)、類似度でマッピング */}
      {showCustomerListModal && (
        <div className="answer-key-modal-overlay" onClick={() => setShowCustomerListModal(false)}>
          <div className="answer-key-modal answer-key-modal-wide customer-list-modal" onClick={(e) => e.stopPropagation()}>
            <h3 className="answer-key-modal-title">取引先一覧（類似度マッピング）</h3>
            <p className="customer-list-modal-desc">
              左: 検討タブの実際の取引先（{effectiveYearMonth.year}年{effectiveYearMonth.month}月）、右: 担当（retail_user）。左を基準に最も類似度の高い右を1件マッピング。
            </p>
            {(reviewTabCustomersLoading || mySupersLoading) && (
              <p className="customer-list-loading">読込中…</p>
            )}
            {mySupersError && (
              <p className="customer-list-error">担当一覧はログインが必要です。</p>
            )}
            {!reviewTabCustomersLoading && !mySupersLoading && !mySupersError && (
              <div className="customer-list-table-wrap">
                <table className="customer-list-table">
                  <thead>
                    <tr>
                      <th className="customer-list-th-check">選択</th>
                      <th>実際の取引先（左）</th>
                      <th>担当（retail_user）（右）</th>
                      <th>類似度</th>
                    </tr>
                  </thead>
                  <tbody>
                    {customerMappingRows.mapped.map((row, idx) => {
                      const filterName = row.left
                      return (
                        <tr key={`mapped-${idx}-${row.left}`}>
                          <td className="customer-list-td-check">
                            <input
                              type="checkbox"
                              checked={checkedFilterNames.has(filterName)}
                              onChange={() => {
                                setCheckedFilterNames((prev) => {
                                  const next = new Set(prev)
                                  if (next.has(filterName)) next.delete(filterName)
                                  else next.add(filterName)
                                  return next
                                })
                              }}
                              aria-label={`${filterName}で絞り込み`}
                            />
                          </td>
                          <td>{row.left}</td>
                          <td>{row.right || '—'}</td>
                          <td className="customer-list-score">{row.right ? (row.score * 100).toFixed(1) + '%' : '—'}</td>
                        </tr>
                      )
                    })}
                    {customerMappingRows.unmappedRights.map((right) => (
                      <tr key={`unmapped-${right}`}>
                        <td className="customer-list-td-check">
                          <input
                            type="checkbox"
                            checked={checkedFilterNames.has(right)}
                            onChange={() => {
                              setCheckedFilterNames((prev) => {
                                const next = new Set(prev)
                                if (next.has(right)) next.delete(right)
                                else next.add(right)
                                return next
                              })
                            }}
                            aria-label={`${right}で絞り込み`}
                          />
                        </td>
                        <td className="customer-list-blank">—</td>
                        <td>{right}</td>
                        <td className="customer-list-score">—</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div className="answer-key-modal-actions">
              <button
                type="button"
                className="answer-key-modal-btn cancel"
                onClick={() => setShowCustomerListModal(false)}
              >
                閉じる
              </button>
              <button
                type="button"
                className="answer-key-modal-btn confirm"
                onClick={() => {
                  const names = Array.from(checkedFilterNames)
                  setSelectedCustomerNamesForFilter(names)
                  try {
                    localStorage.setItem('customer-list-modal-last-checked', JSON.stringify(names))
                  } catch {}
                  setCurrentPageIndex(0)
                  setShowCustomerListModal(false)
                }}
              >
                確認（選択した取引先で絞り込み）
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 우측 꼭지: 이미지 영역 높이만 사용, 호버 시 파일 목록 패널 슬라이드 인 */}
      {(currentPage || hasNoData) && (
      <div
        className="review-files-dock"
        style={{ height: `${imageHeightPercent}%` }}
        onMouseEnter={handleFileListPanelEnter}
        onMouseLeave={handleFileListPanelLeave}
      >
        <div className="review-files-tab" aria-label="ファイル一覧" title="ファイル一覧（ホバー）">
          📁
        </div>
        <div className={`review-files-panel ${fileListPanelOpen ? 'open' : ''}`}>
          <div className="review-files-panel-title">ファイル一覧</div>
          <ul className="review-files-list">
            <li className={`review-files-item ${!selectedDocumentPdf ? 'current' : ''}`}>
              <button
                type="button"
                className="review-files-item-btn"
                onClick={() => {
                  setSelectedDocumentPdf(null)
                  setCurrentPageIndex(0)
                }}
              >
                <span className="review-files-item-name">— すべて —</span>
              </button>
            </li>
            {fileNavOptionsWithStatsFiltered.length === 0 && (
              <li className="review-files-item empty">—</li>
            )}
            {fileNavOptionsWithStatsFiltered.map(({ pdfFilename, totalPages, firstReviewed, secondReviewed }) => {
              const firstPct = totalPages > 0 ? Math.round((firstReviewed / totalPages) * 100) : 0
              const secondPct = totalPages > 0 ? Math.round((secondReviewed / totalPages) * 100) : 0
              const rateClass = (pct: number) => (pct >= 100 ? 'full' : pct > 0 ? 'mid' : 'zero')
              const isCurrentDoc = !!selectedDocumentPdf && (pdfFilename ?? '').trim().toLowerCase() === selectedDocumentPdf.trim().toLowerCase()
              return (
                <li
                  key={pdfFilename}
                  className={`review-files-item ${isCurrentDoc ? 'current' : ''}`}
                >
                  <button
                    type="button"
                    className="review-files-item-btn"
                    onClick={() => {
                      setSelectedDocumentPdf(pdfFilename ?? '')
                      setCurrentPageIndex(0)
                    }}
                  >
                    <span className="review-files-item-name">{pdfFilename}</span>
                    <span className="review-files-item-meta">
                      <span className="review-files-item-pages">{totalPages}p</span>
                      <span className={`review-files-rate review-files-rate-1st ${rateClass(firstPct)}`} title="1次検討">1次 {firstPct}%</span>
                      <span className={`review-files-rate review-files-rate-2nd ${rateClass(secondPct)}`} title="2次検討">2次 {secondPct}%</span>
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      </div>
      )}
      </div>
    </div>
  )
}

// 검토 필터 드롭다운: 전체 / 1차 검토분만 / 1차 미검토 / 2차 검토분만 / 2차 미검토
const ReviewFilterDropdown = ({
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
    <div className="review-filter-dropdown-wrap">
      <select
        className="review-filter-select"
        value={currentFilter}
        onChange={(e) => onFilterChange(e.target.value as ReviewFilter)}
        aria-label="検討フィルター"
        title="検討状況で絞り込み"
      >
        <option value="all">全体</option>
        <option value="first_reviewed">1次検討済のみ ({firstReviewedCount})</option>
        <option value="first_not_reviewed">1次未検討 ({firstNotReviewedCount})</option>
        <option value="second_reviewed">2次検討済のみ ({secondReviewedCount})</option>
        <option value="second_not_reviewed">2次未検討 ({secondNotReviewedCount})</option>
      </select>
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

// 연·월·양식 공통: 커스텀 드롭다운 (네이티브 select 대체, 같은 스타일)
const NavCustomDropdown = ({
  value,
  onChange,
  options,
  ariaLabel,
  containerClass = '',
}: {
  value: string
  onChange: (v: string) => void
  options: { value: string; label: string }[]
  ariaLabel: string
  containerClass?: string
}) => {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  const currentLabel = options.find((o) => o.value === value)?.label ?? options[0]?.label ?? ''

  return (
    <div
      className={`form-type-filter form-type-filter-custom ${containerClass}`.trim()}
      ref={containerRef}
    >
      <button
        type="button"
        className="form-type-filter-trigger"
        onClick={() => setOpen((v) => !v)}
        aria-label={ariaLabel}
        aria-expanded={open}
        aria-haspopup="listbox"
      >
        <span className="form-type-filter-trigger-label">{currentLabel}</span>
        <span className="form-type-filter-chevron" aria-hidden>▼</span>
      </button>
      {open && (
        <ul className="form-type-filter-list" role="listbox" aria-label={ariaLabel}>
          {options.map((opt) => (
            <li
              key={opt.value}
              role="option"
              aria-selected={value === opt.value}
              className={`form-type-filter-option ${value === opt.value ? 'selected' : ''}`}
              onClick={() => {
                onChange(opt.value)
                setOpen(false)
              }}
            >
              {opt.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// 참조 양식지 필터: 커스텀 드롭다운 (NavCustomDropdown과 동일 스타일, null 허용)
const FormTypeFilterDropdown = ({
  value,
  onChange,
  options,
}: {
  value: string | null
  onChange: (v: string | null) => void
  options: Array<{ value: string; label: string }>
}) => {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  const currentLabel = value
    ? options.find((o) => o.value === value)?.label ?? value
    : '全て'

  return (
    <div className="form-type-filter form-type-filter-custom" ref={containerRef}>
      <button
        type="button"
        className="form-type-filter-trigger"
        onClick={() => setOpen((v) => !v)}
        title="参照フォームで絞り込み"
        aria-label="参照フォーム"
        aria-expanded={open}
        aria-haspopup="listbox"
      >
        <span className="form-type-filter-trigger-label">{currentLabel}</span>
        <span className="form-type-filter-chevron" aria-hidden>▼</span>
      </button>
      {open && (
        <ul
          className="form-type-filter-list"
          role="listbox"
          aria-label="参照フォーム"
        >
          <li
            role="option"
            aria-selected={value === null}
            className={`form-type-filter-option ${value === null ? 'selected' : ''}`}
            onClick={() => {
              onChange(null)
              setOpen(false)
            }}
          >
            全て
          </li>
          {options.map((opt) => (
            <li
              key={opt.value}
              role="option"
              aria-selected={value === opt.value}
              className={`form-type-filter-option ${value === opt.value ? 'selected' : ''}`}
              onClick={() => {
                onChange(opt.value)
                setOpen(false)
              }}
            >
              {opt.label}
            </li>
          ))}
        </ul>
      )}
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

  const errorMessage =
    error instanceof Error ? error.message : (error as unknown as { message?: string } | null)?.message
  const isNotFound = typeof errorMessage === 'string' && errorMessage.includes('404')
  const noImageMessage = '画像がまだ生成されていません'

  const [imageScale, setImageScale] = useState(1)
  const [imageSize, setImageSize] = useState<{ w: number; h: number } | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const userHasZoomedRef = useRef(false)

  useEffect(() => {
    setImageScale(1)
    setImageSize(null)
    userHasZoomedRef.current = false
  }, [pdfFilename, pageNumber])

  const applyScaleToWidth = useCallback(() => {
    if (!imageSize || !containerRef.current) return
    const cw = containerRef.current.clientWidth
    if (cw <= 0) return
    const scaleToWidth = cw / imageSize.w
    setImageScale((s) => (userHasZoomedRef.current ? s : scaleToWidth))
  }, [imageSize])

  useEffect(() => {
    if (!imageSize || !containerRef.current) return
    applyScaleToWidth()
    const el = containerRef.current
    const ro = new ResizeObserver(() => applyScaleToWidth())
    ro.observe(el)
    return () => ro.disconnect()
  }, [imageSize, applyScaleToWidth])

  /* 휠 확대 시 페이지 스크롤 방지: passive: false 로 preventDefault 유효화 */
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault()
        userHasZoomedRef.current = true
        setImageScale((s) => Math.min(3, Math.max(0.25, s - e.deltaY * 0.002)))
      }
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [data?.image_url])

  return (
    <div className="page-image-viewer">
      {isLoading && <div className="image-loading">画像読み込み中...</div>}
      {error && !isNotFound && (
        <div className="image-error">
          画像読み込みエラー: {error instanceof Error ? error.message : 'Unknown error'}
        </div>
      )}
      {error && isNotFound && (
        <div className="image-empty">{noImageMessage}</div>
      )}
      {data && data.image_url && (() => {
        const imageUrl = getPageImageAbsoluteUrl(data.image_url) ?? data.image_url

        return (
          <div
            ref={containerRef}
            className="image-container image-container-zoom"
            role="img"
            aria-label="Ctrl+ホイールで拡大縮小"
          >
            <div
              className="image-zoom-wrapper"
              style={
                imageSize
                  ? {
                      width: '100%',
                      height: imageSize.h * imageScale,
                    }
                  : undefined
              }
            >
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
                onLoad={(e) => {
                  const img = e.currentTarget
                  setImageSize({ w: img.naturalWidth, h: img.naturalHeight })
                }}
                style={
                  imageSize
                    ? {
                        width: imageSize.w,
                        height: imageSize.h,
                        transform: `scale(${imageScale})`,
                        transformOrigin: '0 0',
                      }
                    : undefined
                }
              />
            </div>
          </div>
        )
      })()}
      {data && !data.image_url && !isLoading && !error && (
        <div className="image-empty">{noImageMessage}</div>
      )}
      {!isLoading && !error && !data && (
        <div className="image-empty">{noImageMessage}</div>
      )}
    </div>
  )
}
