/**
 * 정답지 생성 탭
 * - 좌측: 선택한 문서의 PDF 전체 페이지 이미지 (스크롤)
 * - 우측: page_meta + items キー・値 형태 (편집 가능)
 * - 정답지로 저장: 수정사항 DB 반영 후 학습 플래그 설정 및 벡터 DB 생성
 */
import { useState, useMemo, useCallback, useEffect, useRef } from 'react'
import { useQuery, useQueries, useMutation, useQueryClient } from '@tanstack/react-query'
import { documentsApi, itemsApi, searchApi, ragAdminApi } from '@/api/client'
import { useFormTypes } from '@/hooks/useFormTypes'
import { useAuth } from '@/contexts/AuthContext'
import { getApiBaseUrl } from '@/utils/apiConfig'
import type { Document } from '@/types'
import {
  type GridRow,
  type InitialDocumentForAnswerKey,
  type AnswerKeyTabProps,
  SYSTEM_ROW_KEYS,
  HIDDEN_ROW_KEYS,
  TYPE_OPTIONS_BASE,
  CUSTOMER_KEYS,
  PRODUCT_NAME_KEYS,
  PAGE_META_DELETE_SENTINEL,
  pickFromGen,
} from './answerKeyTabConstants'
import { AnswerKeyLeftPanel } from './AnswerKeyLeftPanel'
import { AnswerKeyRightPanel, type AnswerKeyRightPanelCtx } from './AnswerKeyRightPanel'
import './AnswerKeyTab.css'

export type { InitialDocumentForAnswerKey }

export function AnswerKeyTab({ initialDocument, onConsumeInitialDocument, onRevokeSuccess }: AnswerKeyTabProps) {
  const { sessionId } = useAuth()
  const queryClient = useQueryClient()
  /** 정답 생성 직후 한 번은 서버 동기화 effect가 rows를 덮어쓰지 않도록 */
  const skipNextSyncFromServerRef = useRef(false)
  /** 저장 시 항상 최신 rows 사용 (클로저 지연으로 タイプ 등이 빠지는 것 방지) */
  const rowsRef = useRef<GridRow[]>([])
  const [selectedDoc, setSelectedDoc] = useState<{ pdf_filename: string; total_pages: number } | null>(null)
  /** RAG(img) 문서일 때 relative_path — 이게 있으면 img 기반 answer.json/이미지 사용 */
  const [selectedDocRelativePath, setSelectedDocRelativePath] = useState<string | null>(null)
  const [currentPage, setCurrentPage] = useState(1)
  const [rows, setRows] = useState<GridRow[]>([])
  const [itemDataKeys, setItemDataKeys] = useState<string[]>([])
  const [dirtyIds, setDirtyIds] = useState<Set<number>>(new Set())
  const [pageMetaFlatEdits, setPageMetaFlatEdits] = useState<Record<number, Record<string, string>>>({})
  const [pageMetaDirtyPages, setPageMetaDirtyPages] = useState<Set<number>>(new Set())
  /** キー・値 탭: page_role 선택 (cover/detail/summary/reply) — 저장 시 DB 반영 */
  const [pageRoleEdits, setPageRoleEdits] = useState<Record<number, string>>({})
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'building' | 'done' | 'error'>( 'idle')
  const [saveMessage, setSaveMessage] = useState<string>('')
  const [showRevokeModal, setShowRevokeModal] = useState(false)
  const [rightView, setRightView] = useState<'kv' | 'json' | 'template'>('kv')
  const [jsonEditText, setJsonEditText] = useState('')
  /** 템플릿 뷰: 첫 행만 キー・値 목록 (키/값 추가·삭제·편집 가능) */
  const [templateEntries, setTemplateEntries] = useState<Array<{ id: string; key: string; value: string }>>([])
  /** キー・値 탭: items에서 키 이름 인라인 편집용 */
  const [editingKeyName, setEditingKeyName] = useState<string | null>(null)
  const [editingKeyValue, setEditingKeyValue] = useState('')
  /** キー・値 탭: page_meta 키 경로 인라인 편집 중인 키 (편집값은 editingPageMetaKeyValue) */
  const [editingPageMetaKey, setEditingPageMetaKey] = useState<string | null>(null)
  const [editingPageMetaKeyValue, setEditingPageMetaKeyValue] = useState('')
  /** キー・値 탭: page_meta 새 키/값 추가용 */
  const [newPageMetaKey, setNewPageMetaKey] = useState('')
  const [newPageMetaValue, setNewPageMetaValue] = useState('')
  /** キー・値タブ: items用の新規キー追加 */
  const [newKeyInput, setNewKeyInput] = useState('')
  /** 정답 생성: Gemini / GPT 5.2 (Vision) | Azure+RAG(표 구조 보존) */
  const [answerProvider, setAnswerProvider] = useState<'gemini' | 'gpt-5.2'>('gpt-5.2')
  /** OCR 다시 인식: Azure 모델 (prebuilt-read / prebuilt-layout / prebuilt-document) */
  const [ocrRerunAzureModel, setOcrRerunAzureModel] = useState<string>('prebuilt-layout')
  /** 画像 Ctrl+ホイール 拡大縮小 */
  const [imageScale, setImageScale] = useState(1)
  const [imageSize, setImageSize] = useState<{ w: number; h: number } | null>(null)
  const imageScrollRef = useRef<HTMLDivElement>(null)
  const imageZoomContainerRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    setImageScale(1)
    setImageSize(null)
  }, [currentPage, selectedDoc?.pdf_filename])

  useEffect(() => {
    if (!imageSize || !imageScrollRef.current) return
    const el = imageScrollRef.current
    const cw = el.clientWidth
    if (cw <= 0) return
    /*  가로 스크롤 없음: 너비에 맞춤 → 세로만 스크롤 */
    const scaleToWidth = cw / imageSize.w
    setImageScale((s) => (s === 1 ? scaleToWidth : s))
  }, [imageSize])

  /* 휠 확대 시 페이지 스크롤 방지: passive: false 로 preventDefault 유효화 */
  useEffect(() => {
    const el = imageZoomContainerRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault()
        setImageScale((s) => Math.min(3, Math.max(0.25, s - e.deltaY * 0.002)))
      }
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  useFormTypes()
  const { data: documentsData } = useQuery({
    queryKey: ['documents', 'for-answer-key-tab'],
    queryFn: () => documentsApi.getListForAnswerKeyTab(),
  })

  /** RAG(img) 문서일 때 해당 폴더의 answer.json 전체 (ocr_text는 별도 API) */
  const { data: answerJsonFromImg } = useQuery({
    queryKey: ['answer-json-from-img', selectedDocRelativePath ?? ''],
    queryFn: () => documentsApi.getAnswerJsonFromImg(selectedDocRelativePath!),
    enabled: !!selectedDocRelativePath,
  })

  /** base DB 문서: answer-json 한 번 로드 → 메모리에서 편집 → 저장 시에만 DB 반영 (순서/정렬 이슈 제거) */
  const { data: answerJsonFromDb } = useQuery({
    queryKey: ['document-answer-json', selectedDoc?.pdf_filename ?? ''],
    queryFn: () => documentsApi.getDocumentAnswerJson(selectedDoc!.pdf_filename),
    enabled: !!selectedDoc?.pdf_filename && !selectedDocRelativePath,
  })

  const revokeAnswerKeyMutation = useMutation({
    mutationFn: (pdfFilename: string) => documentsApi.revokeAnswerKeyDocument(pdfFilename),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents', 'for-answer-key-tab'] })
      setShowRevokeModal(false)
      setSelectedDoc(null)
      setRows([])
      setSaveMessage('正解表の指定を解除しました。検索タブで再度確認できます。')
      onRevokeSuccess?.()
    },
    onError: (e: any) => {
      setSaveMessage(e?.response?.data?.detail || e?.message || '解除に失敗しました。')
      setSaveStatus('error')
    },
  })

  /** OCR 다시 인식 (Azure 전용) — 결과를 debug2에 저장 후 화면 갱신 */
  const rerunOcrMutation = useMutation({
    mutationFn: ({ azureModel }: { azureModel?: string }) =>
      searchApi.rerunPageOcr(selectedDoc!.pdf_filename, currentPage, azureModel),
    onSuccess: (data) => {
      queryClient.setQueryData(
        ['page-ocr-text', selectedDoc?.pdf_filename, currentPage],
        data
      )
      setSaveMessage('OCRを再認識しました。')
      setSaveStatus('done')
    },
    onError: (e: any) => {
      setSaveMessage(e?.response?.data?.detail || e?.message || 'OCR再認識に失敗しました。')
      setSaveStatus('error')
    },
  })

  const generateAnswerMutation = useMutation({
    mutationFn: async ({
      pdfFilename,
      pageNumber,
      currentRows,
      currentItemDataKeys,
      provider,
    }: {
      pdfFilename: string
      pageNumber: number
      currentRows: GridRow[]
      currentItemDataKeys: string[]
      provider: 'gemini' | 'gpt-5.2'
    }) => {
      const res =
        provider === 'gemini'
          ? await documentsApi.generateAnswerWithGemini(pdfFilename, pageNumber)
          : await documentsApi.generateAnswerWithGpt(
              pdfFilename,
              pageNumber,
              'gpt-5.2-2025-12-11'
            )
      const { items: generatedItems, page_role, page_meta } = res
      const pageIndices = currentRows
        .map((r, i) => (r.page_number === pageNumber ? i : -1))
        .filter((i) => i >= 0)

      if (pageIndices.length === 0 && generatedItems.length > 0) {
        await documentsApi.createItemsFromAnswer(pdfFilename, pageNumber, generatedItems, page_role, page_meta ?? undefined)
        return {
          mode: 'created' as const,
          pdfFilename,
          pageNumber,
          createdCount: generatedItems.length,
          itemDataKeys: Array.from(
            new Set([
              ...currentItemDataKeys,
              ...generatedItems.flatMap((g: Record<string, unknown>) =>
                Object.keys(g).filter((k) => !SYSTEM_ROW_KEYS.includes(k))
              ),
            ])
          ),
        }
      }
      return {
        mode: 'updated' as const,
        ...res,
        _pdfFilename: pdfFilename,
        _currentRows: currentRows,
        _pageNum: pageNumber,
        _itemDataKeys: currentItemDataKeys,
      }
    },
    onSuccess: (data) => {
      if (data.mode === 'created') {
        queryClient.invalidateQueries({
          queryKey: ['items', data.pdfFilename, data.pageNumber],
        })
        queryClient.invalidateQueries({ queryKey: ['items', data.pdfFilename] })
        if (data.itemDataKeys.length > 0) {
          setItemDataKeys(data.itemDataKeys)
        }
        setSaveMessage(`${data.createdCount}件を新規生成しました。`)
        setSaveStatus('done')
        return
      }

      const {
        items: generatedItems,
        _currentRows: currentRows,
        _pdfFilename: pdfFn,
        _pageNum: pageNum,
        _itemDataKeys: currentItemDataKeys,
        page_meta: pageMeta,
      } = data as typeof data & {
        _currentRows: GridRow[]
        _pdfFilename?: string
        _pageNum?: number
        _itemDataKeys: string[]
        page_meta?: Record<string, unknown>
      }
      const pageIndices = currentRows
        .map((r, i) => (r.page_number === pageNum ? i : -1))
        .filter((i) => i >= 0)
      if (pageIndices.length === 0 && (!generatedItems || generatedItems.length === 0)) {
        setSaveMessage('このページには既存項目がなく、生成した項目もありません。')
        setSaveStatus('done')
        return
      }
      skipNextSyncFromServerRef.current = true
      const next = [...currentRows]
      const newDirty = new Set<number>()
      const applyCount = Math.min(pageIndices.length, generatedItems.length)
      for (let j = 0; j < applyCount; j++) {
        const idx = pageIndices[j]
        const row = next[idx]
        const gen = generatedItems[j] as Record<string, unknown>
        const updated: GridRow = {
          item_id: row.item_id,
          page_number: row.page_number,
          item_order: row.item_order,
          version: row.version ?? 1,
        }
        const customerVal = pickFromGen(gen, CUSTOMER_KEYS) ?? (row as Record<string, unknown>)['得意先']
        if (customerVal != null) (updated as Record<string, unknown>)['得意先'] = customerVal
        const productNameVal = pickFromGen(gen, PRODUCT_NAME_KEYS) ?? (row as Record<string, unknown>)['商品名']
        if (productNameVal != null) (updated as Record<string, unknown>)['商品名'] = productNameVal
        for (const k of Object.keys(gen)) {
          if (SYSTEM_ROW_KEYS.includes(k) || k === '商品名') continue
          if (CUSTOMER_KEYS.includes(k) || PRODUCT_NAME_KEYS.includes(k)) continue
          ;(updated as Record<string, unknown>)[k] = gen[k]
        }
        next[idx] = updated
        newDirty.add(row.item_id)
      }
      setRows(next)
      setDirtyIds((prev) => {
        const s = new Set(prev)
        newDirty.forEach((id) => s.add(id))
        return s
      })
      const firstGen = generatedItems[0] as Record<string, unknown> | undefined
      const keysInJsonOrder = firstGen
        ? Object.keys(firstGen).filter(
            (k) =>
              !['item_id', 'page_number', 'item_order', 'version'].includes(k)
          )
        : []
      if (keysInJsonOrder.length > 0) {
        setItemDataKeys(keysInJsonOrder)
      }
      // 기존 행이 있어도 Gemini page_meta를 DB에 저장
      if (pdfFn != null && pageNum != null && pageMeta != null && Object.keys(pageMeta).length > 0) {
        documentsApi.updatePageMeta(pdfFn, pageNum, pageMeta as Record<string, any>).then(
          () => queryClient.invalidateQueries({ queryKey: ['page-meta', pdfFn] }),
          () => { /* 저장 실패 시 무시 */ }
        )
      }
      const msg =
        applyCount < generatedItems.length
          ? `${applyCount}件を適用（生成${generatedItems.length}件、既存項目数を超えた分は未適用）`
          : `正解${applyCount}件を生成・適用しました。`
      setSaveMessage(msg)
      setSaveStatus('done')
    },
    onError: (e: any) => {
      setSaveMessage(e?.response?.data?.detail || e?.message || '正解の一括生成に失敗しました。')
      setSaveStatus('error')
    },
  })
  const documents: Document[] = useMemo(() => {
    const raw = documentsData?.documents
    return Array.isArray(raw) ? raw : []
  }, [documentsData])

  // 검토 탭 또는 RAG 현황판에서 넘어온 경우 해당 문서 자동 선택
  useEffect(() => {
    if (!initialDocument || !onConsumeInitialDocument) return
    const doc = documents.find((d) => d.pdf_filename === initialDocument.pdf_filename)
    if (doc) {
      setSelectedDoc({ pdf_filename: doc.pdf_filename, total_pages: doc.total_pages })
      setSelectedDocRelativePath(null)
      setCurrentPage(1)
      onConsumeInitialDocument()
    } else if (initialDocument.relative_path && initialDocument.total_pages > 0) {
      // RAG 목록에만 있고 정답지 탭 목록에 없는 문서 → img 기반 뷰
      setSelectedDoc({
        pdf_filename: initialDocument.pdf_filename,
        total_pages: initialDocument.total_pages,
      })
      setSelectedDocRelativePath(initialDocument.relative_path)
      setCurrentPage(1)
      onConsumeInitialDocument()
    }
  }, [initialDocument, onConsumeInitialDocument, documents])

  // 문서 변경 시 1페이지로 초기화, page_role 로컬 편집 초기화
  useEffect(() => {
    if (selectedDoc) setCurrentPage(1)
    setPageRoleEdits({})
  }, [selectedDoc?.pdf_filename])

  const isRagMode = !!selectedDocRelativePath

  const pageImageQueries = useQueries({
    queries: selectedDoc && !isRagMode
      ? Array.from({ length: selectedDoc.total_pages }, (_, i) => ({
          queryKey: ['answer-key-page-image', selectedDoc.pdf_filename, i + 1],
          queryFn: () => searchApi.getPageImage(selectedDoc.pdf_filename, i + 1),
          enabled: true,
        }))
      : [],
  })

  const pageItemsQueries = useQueries({
    queries: selectedDoc && !isRagMode
      ? Array.from({ length: selectedDoc.total_pages }, (_, i) => ({
          queryKey: ['items', selectedDoc.pdf_filename, i + 1],
          queryFn: () => itemsApi.getByPage(selectedDoc.pdf_filename, i + 1),
          enabled: true,
        }))
      : [],
  })

  const pageMetaQueries = useQueries({
    queries: selectedDoc && !isRagMode
      ? Array.from({ length: selectedDoc.total_pages }, (_, i) => ({
          queryKey: ['page-meta', selectedDoc.pdf_filename, i + 1],
          queryFn: () => documentsApi.getPageMeta(selectedDoc.pdf_filename, i + 1),
          enabled: true,
          retry: false,
        }))
      : [],
  })

  const pageOcrTextQueries = useQueries({
    queries: selectedDoc
      ? Array.from({ length: selectedDoc.total_pages }, (_, i) => ({
          queryKey: ['page-ocr-text', selectedDoc.pdf_filename, i + 1],
          queryFn: () => searchApi.getPageOcrText(selectedDoc.pdf_filename, i + 1),
          enabled: !!selectedDoc,
        }))
      : [],
  })

  const allItemsLoaded = isRagMode ? !!answerJsonFromImg : (!!answerJsonFromDb || pageItemsQueries.every((q) => !q.isLoading && (q.data != null || q.isError)))
  const allPageMetaLoaded = isRagMode ? !!answerJsonFromImg : (!!answerJsonFromDb || pageMetaQueries.every((q) => !q.isLoading && (q.data != null || q.isError)))
  const allDataLoaded = allItemsLoaded && allPageMetaLoaded
  const allImagesLoaded = isRagMode ? true : pageImageQueries.every((q) => !q.isLoading && q.data != null)

  /** page_meta 조회 실패(404 등) 페이지 번호 목록 — 일부 페이지만 page_data가 있을 때 안내용 */
  const pageMetaErrorPageNumbers = useMemo(() => {
    if (!selectedDoc) return []
    return pageMetaQueries
      .map((q, i) => (q.isError ? i + 1 : 0))
      .filter((p) => p > 0)
  }, [selectedDoc, pageMetaQueries])

  // RAG(img) 문서: answer.json 순서 그대로 — pages/items 모두 인덱스 순으로만 접근해 0,1,2,...,10,11 보장
  useEffect(() => {
    if (!isRagMode || !answerJsonFromImg?.pages) return
    const pagesArr = Array.isArray(answerJsonFromImg.pages) ? answerJsonFromImg.pages : []
    if (pagesArr.length === 0) return
    const combined: GridRow[] = []
    const keysOrder: string[] = []
    const keysSet = new Set<string>()
    for (let pi = 0; pi < pagesArr.length; pi++) {
      const page = pagesArr[pi] as Record<string, any>
      const pageNum = Number(page?.page_number) || pi + 1
      let items: any[] = []
      const rawItems = page?.items
      if (Array.isArray(rawItems)) {
        // 인덱스 0,1,2,... 순으로만 추출 (이터레이션 순서 의존 제거)
        items = Array.from({ length: rawItems.length }, (_, i) => rawItems[i])
      } else if (rawItems && typeof rawItems === 'object') {
        items = Object.entries(rawItems)
          .sort((a, b) => Number(a[0]) - Number(b[0]))
          .map(([, v]) => v)
      }
      for (let idx = 0; idx < items.length; idx++) {
        const item = items[idx]
        const itemData = item?.item_data ?? item
        const row: GridRow = {
          item_id: pageNum * 1000 + idx,
          page_number: pageNum,
          item_order: idx + 1,
          version: 1,
        }
        if (itemData && typeof itemData === 'object') {
          Object.keys(itemData).forEach((k) => {
            if (SYSTEM_ROW_KEYS.includes(k)) return
            row[k] = itemData[k]
            if (!keysSet.has(k)) {
              keysSet.add(k)
              keysOrder.push(k)
            }
          })
        }
        row.item_order = idx + 1
        ;(row as Record<string, unknown>)._displayIndex = pageNum * 10000 + idx
        combined.push(row)
      }
    }
    combined.sort(
      (a, b) =>
        a.page_number - b.page_number ||
        Number((a as Record<string, unknown>)._displayIndex ?? 0) - Number((b as Record<string, unknown>)._displayIndex ?? 0)
    )
    setRows(combined)
    setItemDataKeys(keysOrder)
  }, [isRagMode, answerJsonFromImg])

  // base DB: answer-json 한 번 로드 → rows 동기화 (JSON 배열 순서 그대로, DB N회 조회 없음)
  useEffect(() => {
    if (!!selectedDocRelativePath || !answerJsonFromDb?.pages?.length) return
    if (skipNextSyncFromServerRef.current) {
      skipNextSyncFromServerRef.current = false
      return
    }
    if (dirtyIds.size > 0 || pageMetaDirtyPages.size > 0) return
    const combined: GridRow[] = []
    const keysOrder: string[] = []
    const keysSet = new Set<string>()
    answerJsonFromDb.pages.forEach((page: Record<string, any>) => {
      const pageNum = Number(page.page_number) || 0
      const items = Array.isArray(page.items) ? page.items : []
      items.forEach((item: any, idx: number) => {
        const itemData = item?.item_data ?? item
        const row: GridRow = {
          item_id: pageNum * 1000 + idx,
          page_number: pageNum,
          item_order: idx + 1,
          version: 1,
        }
        if (itemData && typeof itemData === 'object') {
          Object.keys(itemData).forEach((k) => {
            if (SYSTEM_ROW_KEYS.includes(k)) return
            row[k] = itemData[k]
            if (!keysSet.has(k)) {
              keysSet.add(k)
              keysOrder.push(k)
            }
          })
        }
        row.item_order = idx + 1
        combined.push(row)
      })
    })
    combined.sort((a, b) => a.page_number - b.page_number || Number(a.item_order ?? 0) - Number(b.item_order ?? 0) || a.item_id - b.item_id)
    setRows(combined)
    setItemDataKeys(keysOrder.length ? keysOrder : [...keysSet])
    setDirtyIds(new Set())
    setPageMetaFlatEdits({})
    setPageMetaDirtyPages(new Set())
  }, [answerJsonFromDb, selectedDocRelativePath, dirtyIds.size, pageMetaDirtyPages.size])

  // (레거시) base DB를 answer-json이 아닌 페이지별 API로 로드할 때만 사용 — answerJsonFromDb 사용 시 미실행
  const pageItemsDataUpdatedAt = pageItemsQueries.map((q) => q.dataUpdatedAt ?? 0).join(',')
  useEffect(() => {
    if (!selectedDoc || !allDataLoaded || !!selectedDocRelativePath || answerJsonFromDb != null) return
    if (skipNextSyncFromServerRef.current) {
      skipNextSyncFromServerRef.current = false
      return
    }
    if (dirtyIds.size > 0 || pageMetaDirtyPages.size > 0) return
    const combined: GridRow[] = []
    let serverKeys: string[] = []
    const keysFromItems = new Set<string>()
    for (let p = 0; p < pageItemsQueries.length; p++) {
      const res = pageItemsQueries[p].data as { items: any[]; item_data_keys?: string[] | null } | undefined
      if (!res?.items) continue
      if (res.item_data_keys?.length) serverKeys = res.item_data_keys
      const pageNum = p + 1
      res.items.forEach((item) => {
        const row: GridRow = {
          item_id: item.item_id,
          page_number: pageNum,
          item_order: item.item_order,
          version: item.version ?? 1,
        }
        if (item.item_data && typeof item.item_data === 'object') {
          Object.keys(item.item_data).forEach((k) => {
            if (SYSTEM_ROW_KEYS.includes(k)) return
            row[k] = item.item_data[k]
            keysFromItems.add(k)
          })
        }
        combined.push(row)
      })
    }
    // API/응답 순서가 문자열 정렬일 수 있으므로, 저장 전에 page_number → item_order(숫자) 순으로 정렬
    combined.sort((a, b) => a.page_number - b.page_number || Number(a.item_order ?? 0) - Number(b.item_order ?? 0) || a.item_id - b.item_id)
    setRows(combined)
    // 서버 키 순서 유지 + items에만 있는 키(예: タイプ) 추가 → 저장 후에도 드롭다운 값 유지
    const mergedKeys =
      serverKeys.length > 0
        ? [...serverKeys, ...[...keysFromItems].filter((k) => !serverKeys.includes(k))]
        : [...keysFromItems]
    if (mergedKeys.length) setItemDataKeys(mergedKeys)
    setDirtyIds(new Set())
    setPageMetaFlatEdits({})
    setPageMetaDirtyPages(new Set())
  }, [selectedDoc, allDataLoaded, isRagMode, pageItemsDataUpdatedAt, dirtyIds.size, pageMetaDirtyPages.size])

  useEffect(() => {
    rowsRef.current = rows
  }, [rows])

  // 우측 정답 목록: RAG는 _displayIndex(페이지별 0,1,2,...,10,11) 숫자 순, 없으면 item_order 숫자 순
  const currentPageRows = useMemo(() => {
    const filtered = rows.filter((r) => r.page_number === currentPage)
    return filtered.sort((a, b) => {
      const da = (a as Record<string, unknown>)._displayIndex
      const db = (b as Record<string, unknown>)._displayIndex
      const na = Number(da)
      const nb = Number(db)
      if (Number.isFinite(na) && Number.isFinite(nb)) return na - nb
      const oa = parseInt(String(a.item_order ?? 0), 10) || 0
      const ob = parseInt(String(b.item_order ?? 0), 10) || 0
      return oa - ob || a.item_id - b.item_id
    })
  }, [rows, currentPage])

  /** キー・値 그리드/관리용 데이터 키: 현재 페이지만 사용 (페이지별로 다른 item 구조 대응) */
  const dataKeysForDisplay = useMemo(() => {
    const fromCurrentPage = new Set<string>()
    currentPageRows.forEach((r) => {
      Object.keys(r).forEach((k) => {
        if (!SYSTEM_ROW_KEYS.includes(k)) fromCurrentPage.add(k)
      })
    })
    const keysList = Array.from(fromCurrentPage)
    if (itemDataKeys.length) {
      const ordered = itemDataKeys.filter((k) => fromCurrentPage.has(k))
      const extras = keysList.filter((k) => !itemDataKeys.includes(k))
      return [...ordered, ...extras]
    }
    return keysList
  }, [itemDataKeys, currentPageRows])

  /** キー・値 탭: API item_data_keys 순서 = JSON/문서 순서. item_id/version은 내부 식별용 → 표시하지 않음 */
  const displayKeys = useMemo(() => {
    const head = ['page_number', 'item_order']
    const dataKeySet = new Set<string>()
    currentPageRows.forEach((r) => Object.keys(r).forEach((k) => { if (!HIDDEN_ROW_KEYS.has(k)) dataKeySet.add(k) }))
    const ordered = itemDataKeys.length
      ? [...itemDataKeys.filter((k) => dataKeySet.has(k)), ...[...dataKeySet].filter((k) => !itemDataKeys.includes(k))]
      : [...dataKeySet]
    return [...head, ...ordered]
  }, [currentPageRows, itemDataKeys])

  const editableKeys = useMemo(() => {
    return new Set(['得意先', '商品名', ...dataKeysForDisplay])
  }, [dataKeysForDisplay])

  /** タイプ 드롭다운: 기본 옵션 + 현재 문서 items에 이미 있는 タイプ 값 (기존 목록) */
  const typeOptions = useMemo(() => {
    const fromRows = new Set<string>()
    rows.forEach((r) => {
      const v = r['タイプ']
      if (v != null && String(v).trim() !== '') fromRows.add(String(v).trim())
    })
    const baseValues = new Set(TYPE_OPTIONS_BASE.map((o) => o.value).filter(Boolean))
    const extra = [...fromRows].filter((v) => !baseValues.has(v)).sort()
    return [
      ...TYPE_OPTIONS_BASE,
      ...extra.map((value) => ({ value, label: value })),
    ]
  }, [rows])

  const onValueChange = useCallback((itemId: number, key: string, value: string | number | boolean | null) => {
    setRows((prev) => {
      const next = prev.map((r) => (r.item_id !== itemId ? r : { ...r, [key]: value }))
      rowsRef.current = next
      return next
    })
    setDirtyIds((d) => new Set(d).add(itemId))
  }, [])

  /** キー・値 탭: キー追加 (기존 dataKeys 유지 + 새 키, 모든 행에 해당 キー追加, 현재 페이지 행 dirty) */
  const onAddKey = useCallback(
    (newKey: string) => {
      const k = (newKey ?? '').trim()
      if (!k) return
      setItemDataKeys((prev) => {
        const merged = new Set([...prev, ...dataKeysForDisplay, k])
        if (merged.size === prev.length && prev.includes(k)) return prev
        return Array.from(merged)
      })
      setRows((prev) =>
        prev.map((r) => {
          const val = (r as Record<string, unknown>)[k]
          const v = val === undefined || val === null ? '' : typeof val === 'object' ? String(val) : val
          return { ...r, [k]: v } as GridRow
        })
      )
      setDirtyIds((prev) => new Set([...prev, ...currentPageRows.map((r) => r.item_id)]))
    },
    [dataKeysForDisplay, currentPageRows]
  )

  /** キー・値 탭: 키 삭제 (itemDataKeys 및 모든 행에서 제거, 현재 페이지 행 dirty) */
  const onRemoveKey = useCallback(
    (key: string) => {
      if (['page_number', 'item_order', '得意先', '商品名', 'item_id', 'version'].includes(key)) return
      setItemDataKeys((prev) => prev.filter((k) => k !== key))
      setRows((prev) =>
        prev.map((r) => {
          const next = { ...r } as Record<string, unknown>
          delete next[key]
          return next as GridRow
        })
      )
      setDirtyIds((prev) => new Set([...prev, ...currentPageRows.map((r) => r.item_id)]))
    },
    [currentPageRows]
  )

  /** キー・値 탭: 키 이름 변경 (itemDataKeys 및 모든 행에서 oldKey → newKey) */
  const onRenameKey = useCallback(
    (oldKey: string, newKey: string) => {
      const n = (newKey ?? '').trim()
      if (!n || n === oldKey) return
      if (['page_number', 'item_order', '得意先', '商品名', 'item_id', 'version'].includes(oldKey)) return
      setItemDataKeys((prev) => prev.map((k) => (k === oldKey ? n : k)))
      setRows((prev) =>
        prev.map((r) => {
          const next = { ...r } as Record<string, unknown>
          if (oldKey in next) {
            next[n] = next[oldKey]
            delete next[oldKey]
          }
          return next as GridRow
        })
      )
      setDirtyIds((prev) => new Set([...prev, ...currentPageRows.map((r) => r.item_id)]))
    },
    [currentPageRows]
  )

  const flattenPageMeta = useCallback((obj: any, prefix = ''): Array<{ key: string; value: string }> => {
    const result: Array<{ key: string; value: string }> = []
    if (obj === null || obj === undefined) return result

    // 배열: prefix를 포함한 경로에 [i]를 붙여 전개 (예: totals.明細行[0].本体金額)
    if (Array.isArray(obj)) {
      obj.forEach((item, i) => {
        const base = prefix ? `${prefix}[${i}]` : `[${i}]`
        if (item !== null && typeof item === 'object') {
          result.push(...flattenPageMeta(item, base))
        } else {
          result.push({ key: base, value: String(item ?? '') })
        }
      })
      return result
    }

    // 객체: 각 키에 대해 newKey를 만들고, 값 타입에 따라 재귀/단일 값 처리
    if (typeof obj === 'object') {
      Object.keys(obj).forEach((k) => {
        const newKey = prefix ? `${prefix}.${k}` : k
        const v = obj[k]
        if (v === null || v === undefined) {
          result.push({ key: newKey, value: '' })
        } else if (Array.isArray(v)) {
          v.forEach((item, i) => {
            const base = `${newKey}[${i}]`
            if (item !== null && typeof item === 'object') {
              result.push(...flattenPageMeta(item, base))
            } else {
              result.push({ key: base, value: String(item ?? '') })
            }
          })
        } else if (typeof v === 'object') {
          result.push(...flattenPageMeta(v, newKey))
        } else {
          result.push({ key: newKey, value: String(v) })
        }
      })
    }
    return result
  }, [])

  const setNestedByPath = useCallback((obj: Record<string, any>, path: string, value: string) => {
    const parts = path.split(/\.|\[|\]/).filter(Boolean)
    let cur: any = obj
    for (let i = 0; i < parts.length - 1; i++) {
      const p = parts[i]
      const nextKey = parts[i + 1]
      const isArrayIndex = /^\d+$/.test(nextKey)
      if (!(p in cur)) cur[p] = isArrayIndex ? [] : {}
      cur = cur[p]
    }
    if (parts.length) cur[parts[parts.length - 1]] = value
  }, [])

  const deleteNestedByPath = useCallback((obj: Record<string, any>, path: string) => {
    const parts = path.split(/\.|\[|\]/).filter(Boolean)
    if (parts.length === 0) return
    let cur: any = obj
    for (let i = 0; i < parts.length - 1; i++) {
      const p = parts[i]
      if (!(p in cur)) return
      cur = cur[p]
      if (cur == null || typeof cur !== 'object') return
    }
    delete cur[parts[parts.length - 1]]
  }, [])

  /** page 레벨에서 page_meta로 쓸 때 제외할 키 (items는 항상 제외) */
  const PAGE_LEVEL_EXCLUDE_KEYS = useMemo(() => new Set(['items', 'page_number', 'page_role']), [])

  const currentPageMetaData = useMemo(() => {
    if (!selectedDoc) return null
    if (isRagMode && answerJsonFromImg?.pages) {
      const page = answerJsonFromImg.pages.find((p: any) => Number(p.page_number) === currentPage)
      if (!page) return null
      // RAG answer.json에는 page_meta 키가 없을 수 있음 → page 루트에서 items/page_number/page_role 제외한 것만 page_meta로 사용
      let page_meta: Record<string, any> =
        page.page_meta != null && typeof page.page_meta === 'object' && !Array.isArray(page.page_meta)
          ? page.page_meta
          : {}
      if (Object.keys(page_meta).length === 0 && typeof page === 'object') {
        page_meta = {}
        Object.keys(page).forEach((k) => {
          if (!PAGE_LEVEL_EXCLUDE_KEYS.has(k)) page_meta[k] = (page as Record<string, any>)[k]
        })
      }
      return {
        page_role: page.page_role ?? null,
        page_meta,
      }
    }
    if (answerJsonFromDb?.pages) {
      const page = answerJsonFromDb.pages.find((p: any) => Number(p.page_number) === currentPage)
      if (!page) return null
      // DB 쪽도 page_meta 없으면 page 전체 쓰지 않고, items 제외한 키만 사용
      let page_meta: Record<string, any> =
        page.page_meta != null && typeof page.page_meta === 'object' && !Array.isArray(page.page_meta)
          ? page.page_meta
          : {}
      if (Object.keys(page_meta).length === 0 && typeof page === 'object') {
        page_meta = {}
        Object.keys(page).forEach((k) => {
          if (!PAGE_LEVEL_EXCLUDE_KEYS.has(k)) page_meta[k] = (page as Record<string, any>)[k]
        })
      }
      return {
        page_role: page.page_role ?? null,
        page_meta,
      }
    }
    const q = pageMetaQueries[currentPage - 1]
    if (!q?.data) return null
    return q.data as { page_role: string | null; page_meta: Record<string, any> }
  }, [selectedDoc, currentPage, isRagMode, answerJsonFromImg, answerJsonFromDb, pageMetaQueries, PAGE_LEVEL_EXCLUDE_KEYS])

  /** detail 페이지용: page_meta.区_mapping (숫자 → ラベル). 키/값 문자열 정규화 (number 혼용 대비) */
  const kuMapping = useMemo(() => {
    const meta = currentPageMetaData?.page_meta
    const raw = meta?.区_mapping ?? meta?.['区_mapping']
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
    const entries = Object.entries(raw).filter(
      ([, v]) => v != null && typeof v === 'string'
    ) as [string, string][]
    if (entries.length === 0) return null
    return Object.fromEntries(entries.map(([k, v]) => [String(k).trim(), v]))
  }, [currentPageMetaData?.page_meta])

  const getKuLabel = useCallback((value: unknown): string | null => {
    if (!kuMapping || value == null) return null
    const s = String(value).trim()
    if (!s) return null
    return kuMapping[s] ?? kuMapping[String(Number(s))] ?? null
  }, [kuMapping])

  const currentPageMetaFields = useMemo(() => {
    const base = currentPageMetaData?.page_meta ?? {}
    const edits = pageMetaFlatEdits[currentPage] ?? {}
    const flat = flattenPageMeta(base)
    const merged = new Map<string, string>()
    flat.forEach(({ key, value }) => {
      const editVal = edits[key]
      if (editVal === PAGE_META_DELETE_SENTINEL) return
      merged.set(key, editVal ?? value)
    })
    Object.keys(edits).forEach((k) => {
      const v = edits[k]
      if (v === PAGE_META_DELETE_SENTINEL) return
      if (!merged.has(k)) merged.set(k, v)
    })
    return Array.from(merged.entries()).map(([key, value]) => ({ key, value }))
  }, [currentPageMetaData, pageMetaFlatEdits, currentPage, flattenPageMeta])

  /** page_meta를 1단계/2단계 키 기준으로 그룹핑해서 보여주기
   * 예) party.宛先.住所 → group=party, sub=宛先, leaf=住所
   *     totals.明細行[0].本体金額 → group=totals, sub=明細行[0], leaf=本体金額
   */
  const groupedPageMetaFields = useMemo(() => {
    type Field = { key: string; value: string }
    type SubMap = Record<string, Field[]>
    const byGroup: Record<string, SubMap> = {}

    currentPageMetaFields.forEach((f) => {
      const fullKey = f.key
      const tokens = fullKey.split('.')
      const hasHierarchy = tokens.length > 1
      const group = hasHierarchy ? tokens[0] || 'root' : 'root'
      const sub =
        tokens.length > 2
          ? tokens[1] // 2단계까지 섹션 헤더로 사용
          : ''        // 1단계(또는 단일 키)는 서브 없이 그룹 바로 아래에 표시
      const subKey = sub || '__no_sub__'

      if (!byGroup[group]) byGroup[group] = {}
      if (!byGroup[group][subKey]) byGroup[group][subKey] = []
      byGroup[group][subKey].push(f)
    })

    const preferredOrder = ['document_meta', 'party', 'payment', 'totals', 'root']
    const result: Array<{ group: string; sub: string | null; fields: Field[] }> = []

    const pushGroup = (group: string) => {
      const subs = byGroup[group]
      if (!subs) return
      const subKeys = Object.keys(subs).sort()
      subKeys.forEach((subKey) => {
        const fields = subs[subKey]
        result.push({
          group,
          sub: subKey === '__no_sub__' ? null : subKey,
          fields,
        })
      })
    }

    preferredOrder.forEach((g) => pushGroup(g))
    Object.keys(byGroup)
      .filter((g) => !preferredOrder.includes(g))
      .sort()
      .forEach((g) => pushGroup(g))

    return result
  }, [currentPageMetaFields])

  const onPageMetaChange = useCallback((flatKey: string, value: string) => {
    setPageMetaFlatEdits((prev) => ({
      ...prev,
      [currentPage]: { ...(prev[currentPage] ?? {}), [flatKey]: value },
    }))
    setPageMetaDirtyPages((d) => new Set(d).add(currentPage))
  }, [currentPage])

  /** page_meta 키 전체 경로 변경 (편집된 값이 없어도 현재 표시값으로 새 키 설정) */
  const onPageMetaKeyRenameFull = useCallback((oldKey: string, newKey: string, currentValue: string) => {
    const n = (newKey ?? '').trim()
    if (!n || n === oldKey) return
    setPageMetaFlatEdits((prev) => {
      const page = { ...(prev[currentPage] ?? {}) }
      page[oldKey] = PAGE_META_DELETE_SENTINEL
      page[n] = currentValue
      return { ...prev, [currentPage]: page }
    })
    setPageMetaDirtyPages((d) => new Set(d).add(currentPage))
  }, [currentPage])

  const onPageMetaKeyRemove = useCallback((flatKey: string) => {
    setPageMetaFlatEdits((prev) => {
      const page = { ...(prev[currentPage] ?? {}) }
      page[flatKey] = PAGE_META_DELETE_SENTINEL
      return { ...prev, [currentPage]: page }
    })
    setPageMetaDirtyPages((d) => new Set(d).add(currentPage))
  }, [currentPage])

  /** page_meta 그룹(예: totals/役務提供) 전체 삭제 — 해당 group.sub 내 모든 키 제거 */
  const onPageMetaGroupRemove = useCallback(
    (group: string, sub: string | null, fields: Array<{ key: string; value: string }>) => {
      setPageMetaFlatEdits((prev) => {
        const page = { ...(prev[currentPage] ?? {}) }
        fields.forEach((f) => {
          page[f.key] = PAGE_META_DELETE_SENTINEL
        })
        return { ...prev, [currentPage]: page }
      })
      setPageMetaDirtyPages((d) => new Set(d).add(currentPage))
    },
    [currentPage]
  )

  const onPageMetaKeyAdd = useCallback((newKey: string, newValue: string) => {
    const raw = (newKey ?? '').trim()
    if (!raw) return
    // document_ref가 있는 경우, 점(.)이 없는 키는 자동으로 document_ref 하위로 취급해 입력 부담을 줄임
    const hasDocumentRef =
      (currentPageMetaData?.page_meta &&
        typeof currentPageMetaData.page_meta === 'object' &&
        currentPageMetaData.page_meta !== null &&
        'document_ref' in currentPageMetaData.page_meta) ||
      currentPageMetaFields.some((f) => f.key.startsWith('document_ref.'))
    const k =
      hasDocumentRef && !raw.includes('.') && !raw.startsWith('[')
        ? `document_ref.${raw}`
        : raw
    setPageMetaFlatEdits((prev) => ({
      ...prev,
      [currentPage]: { ...(prev[currentPage] ?? {}), [k]: newValue ?? '' },
    }))
    setPageMetaDirtyPages((d) => new Set(d).add(currentPage))
  }, [currentPage, currentPageMetaData, currentPageMetaFields])

  const updateItemMutation = useMutation({
    mutationFn: ({ itemId, row }: { itemId: number; row: GridRow }) => {
      const item_data: Record<string, unknown> = {}
      const excludeFromItemData = ['item_id', 'page_number', 'item_order', 'version', '_displayIndex']
      Object.keys(row).forEach((k) => {
        if (excludeFromItemData.includes(k)) return
        item_data[k] = row[k]
      })
      return itemsApi.update(itemId, {
        item_data: item_data as Record<string, any>,
        expected_version: row.version,
        session_id: sessionId || localStorage.getItem('sessionId') || '',
      })
    },
  })

  const buildPageMetaFromEdits = useCallback((pageNum: number): Record<string, any> => {
    const base = (pageMetaQueries[pageNum - 1]?.data as { page_meta?: Record<string, any> } | undefined)?.page_meta ?? {}
    const edits = pageMetaFlatEdits[pageNum] ?? {}
    if (Object.keys(edits).length === 0) return base
    const merged = JSON.parse(JSON.stringify(base))
    Object.entries(edits).forEach(([path, value]) => {
      if (value === PAGE_META_DELETE_SENTINEL) {
        deleteNestedByPath(merged, path)
      } else {
        setNestedByPath(merged, path, value as string)
      }
    })
    return merged
  }, [pageMetaQueries, pageMetaFlatEdits, setNestedByPath, deleteNestedByPath])

  /** 첫 행에서 템플릿 엔트리 초기값 생성 (시스템 필드 제외) */
  const firstRowToTemplateEntries = useCallback((row: GridRow | undefined) => {
    if (!row) return []
    const exclude = ['item_id', 'page_number', 'item_order', 'version']
    return Object.entries(row)
      .filter(([k]) => !exclude.includes(k))
      .map(([key, val], i) => ({
        id: `t-${currentPage}-${i}-${key}`,
        key,
        value: val == null ? '' : String(val),
      }))
  }, [currentPage])

  /** 템플릿 탭 선택 시 또는 페이지 변경 시에만 템플릿 엔트리 초기화 (편집 내용 덮어쓰기 방지)
   * currentPageRows를 의존성에서 제외하여, 행 데이터 갱신 시 사용자 편집이 사라지지 않도록 함 */
  useEffect(() => {
    if (rightView !== 'template') return
    const first = currentPageRows[0]
    setTemplateEntries(firstRowToTemplateEntries(first))
    // eslint-disable-next-line react-hooks/exhaustive-deps -- currentPageRows 제외 의도적
  }, [rightView, currentPage])

  /** 데이터 로드 후 템플릿 탭에 첫 행이 비어 있으면 채우기 (로드 타이밍 보정) */
  useEffect(() => {
    if (rightView !== 'template' || !allDataLoaded) return
    const first = currentPageRows[0]
    if (!first) return
    setTemplateEntries((prev) => {
      if (prev.length > 0) return prev
      return firstRowToTemplateEntries(first)
    })
  }, [rightView, allDataLoaded, currentPageRows, firstRowToTemplateEntries])

  const addTemplateEntry = useCallback(() => {
    setTemplateEntries((prev) => [...prev, { id: `new-${Date.now()}`, key: '', value: '' }])
  }, [])

  const removeTemplateEntry = useCallback((id: string) => {
    setTemplateEntries((prev) => prev.filter((e) => e.id !== id))
  }, [])

  const updateTemplateEntry = useCallback((id: string, field: 'key' | 'value', value: string) => {
    setTemplateEntries((prev) =>
      prev.map((e) => (e.id === id ? { ...e, [field]: value } : e))
    )
  }, [])

  const buildTemplateItem = useCallback((): Record<string, string> => {
    const obj: Record<string, string> = {}
    templateEntries.forEach(({ key: k, value: v }) => {
      const trimmed = (k ?? '').trim()
      if (trimmed) obj[trimmed] = v ?? ''
    })
    return obj
  }, [templateEntries])

  const generateFromTemplateMutation = useMutation({
    mutationFn: async () => {
      if (!selectedDoc) throw new Error('No document selected')
      const templateItem = buildTemplateItem()
      if (Object.keys(templateItem).length === 0) throw new Error('テンプレートにキーを1つ以上入力してください。')
      return documentsApi.generateItemsFromTemplate(
        selectedDoc.pdf_filename,
        currentPage,
        templateItem,
        answerProvider
      )
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['items', selectedDoc?.pdf_filename] })
      setSaveMessage(`テンプレートに基づき${data.items_count}行を生成しました。`)
      setSaveStatus('done')
      setRightView('kv')
    },
    onError: (e: any) => {
      setSaveMessage(e?.response?.data?.detail || e?.message || '残り行の生成に失敗しました。')
      setSaveStatus('error')
    },
  })

  const answerJson = useMemo(() => {
    const pageMeta = buildPageMetaFromEdits(currentPage)
    const pageRole =
      pageRoleEdits[currentPage] ?? currentPageMetaData?.page_role ?? 'detail'
    // _displayIndex는 정렬용 내부 키 → JSON/저장에는 포함하지 않음
    const items = currentPageRows.map(({ item_id, page_number, item_order, version, _displayIndex, ...rest }) => rest)
    return { page_role: pageRole, ...pageMeta, items }
  }, [currentPage, pageRoleEdits, currentPageMetaData?.page_role, currentPageRows, buildPageMetaFromEdits])

  const syncJsonEditFromAnswer = useCallback(() => {
    try {
      setJsonEditText(JSON.stringify(answerJson, null, 2))
    } catch {
      setJsonEditText('{}')
    }
  }, [answerJson])

  // JSON 탭: キー・値/생성 결과와 연동 — 탭 진입 시·페이지 변경 시·rows(answerJson) 변경 시 항상 현재 정답 상태 반영
  useEffect(() => {
    if (rightView !== 'json') return
    try {
      setJsonEditText(JSON.stringify(answerJson, null, 2))
    } catch {
      setJsonEditText('{}')
    }
  }, [rightView, currentPage, answerJson])

  /** parsed item → GridRow (시스템 필드 유지, item 키만 반영해 삭제된 키는 제거) */
  const itemToGridRow = useCallback((r: GridRow, item: Record<string, unknown>): GridRow => {
    const system: Partial<GridRow> = {
      item_id: r.item_id,
      page_number: r.page_number,
      item_order: r.item_order,
      version: r.version,
    }
    const customer = (item.customer ?? item['得意先'] ?? r.customer) as string | null
    const rest: Record<string, string | number | boolean | null | undefined> = {}
    Object.entries(item).forEach(([k, v]) => {
      if (!SYSTEM_ROW_KEYS.includes(k) && k !== 'customer') rest[k] = v as string | number | boolean | null | undefined
    })
    if (item['商品名'] != null || (r as Record<string, unknown>)['商品名'] != null) {
      rest['商品名'] = (item['商品名'] ?? (r as Record<string, unknown>)['商品名']) as string | null
    }
    return { ...system, customer, ...rest } as GridRow
  }, [])

  const applyJsonEdit = useCallback(async () => {
    try {
      const parsed = JSON.parse(jsonEditText) as { page_role?: string; items?: Record<string, unknown>[]; [k: string]: unknown }
      if (!parsed || typeof parsed !== 'object') return
      const { items: parsedItems, page_role: parsedPageRole, ...restMeta } = parsed
      const flatMeta: Record<string, string> = {}
      const pushFlat = (obj: Record<string, unknown>, prefix: string) => {
        Object.entries(obj).forEach(([k, v]) => {
          if (v !== null && v !== undefined && typeof v === 'object' && !Array.isArray(v)) {
            pushFlat(v as Record<string, unknown>, prefix ? `${prefix}.${k}` : k)
          } else {
            flatMeta[prefix ? `${prefix}.${k}` : k] = String(v ?? '')
          }
        })
      }
      pushFlat(restMeta as Record<string, unknown>, '')
      if (Object.keys(flatMeta).length > 0) {
        setPageMetaFlatEdits((prev) => ({ ...prev, [currentPage]: flatMeta }))
        setPageMetaDirtyPages((d) => new Set(d).add(currentPage))
      }
      const hasParsedItems = Array.isArray(parsedItems)
      const parsedCount = (parsedItems?.length ?? 0) as number
      const isEmptyPage = currentPageRows.length === 0

      /** 적용 후 itemDataKeys를 parsed items 기준으로 갱신 */
      const syncItemDataKeysFromParsed = (items: Record<string, unknown>[]) => {
        const keys = new Set<string>()
        items.forEach((item) => {
          Object.keys(item).forEach((k) => {
            if (!SYSTEM_ROW_KEYS.includes(k)) keys.add(k)
          })
        })
        if (keys.size) setItemDataKeys(Array.from(keys))
      }

      if (hasParsedItems && parsedCount > 0 && isEmptyPage && selectedDoc) {
        try {
          await documentsApi.createItemsFromAnswer(
            selectedDoc.pdf_filename,
            currentPage,
            parsedItems!,
            parsedPageRole ?? 'detail'
          )
          if (Object.keys(restMeta).length > 0) {
            await documentsApi.updatePageMeta(selectedDoc.pdf_filename, currentPage, restMeta as Record<string, unknown>)
          }
          syncItemDataKeysFromParsed(parsedItems!)
          queryClient.invalidateQueries({ queryKey: ['items', selectedDoc.pdf_filename] })
          queryClient.invalidateQueries({ queryKey: ['page-meta', selectedDoc.pdf_filename] })
          setSaveMessage('空ページにJSONを適用しDBに保存しました。')
        } catch (e: unknown) {
          const err = e as { response?: { data?: { detail?: string } }; message?: string }
          setSaveMessage(err?.response?.data?.detail || err?.message || 'DBの保存に失敗しました。')
          setSaveStatus('error')
        }
        return
      }

      if (hasParsedItems && parsedCount === 0 && !isEmptyPage && selectedDoc) {
        try {
          for (const row of currentPageRows) {
            await itemsApi.delete(row.item_id)
          }
          setRows((prev) => prev.filter((r) => r.page_number !== currentPage))
          setDirtyIds((prev) => {
            const next = new Set(prev)
            currentPageRows.forEach((r) => next.delete(r.item_id))
            return next
          })
          queryClient.invalidateQueries({ queryKey: ['items', selectedDoc.pdf_filename] })
          setSaveMessage('このページのすべての行を削除しました。')
        } catch (e: unknown) {
          const err = e as { response?: { data?: { detail?: string } }; message?: string }
          setSaveMessage(err?.response?.data?.detail || err?.message || '行の削除に失敗しました。')
          setSaveStatus('error')
        }
        return
      }

      if (hasParsedItems && parsedCount > 0 && !isEmptyPage) {
        const existingCount = currentPageRows.length
        const hasExtraItems = selectedDoc != null && parsedCount > existingCount
        const hasFewerItems = parsedCount < existingCount

        if (hasFewerItems && selectedDoc) {
          try {
            const toDelete = currentPageRows.slice(parsedCount)
            for (const row of toDelete) {
              await itemsApi.delete(row.item_id)
            }
            const kept = currentPageRows.slice(0, parsedCount)
            const updatedCurrent = kept.map((r, i) => itemToGridRow(r, parsedItems![i] as Record<string, unknown>))
            const newDirty = new Set(updatedCurrent.map((r) => r.item_id))
            setRows((prev) => {
              const other = prev.filter((r) => r.page_number !== currentPage)
              return [...other, ...updatedCurrent].sort(
                (a, b) => (a.page_number - b.page_number) || (Number(a.item_order ?? 0) - Number(b.item_order ?? 0))
              )
            })
            setDirtyIds((d) => new Set([...d, ...newDirty]))
            syncItemDataKeysFromParsed(parsedItems!)
            queryClient.invalidateQueries({ queryKey: ['items', selectedDoc.pdf_filename] })
            setSaveMessage(`JSON適用: ${toDelete.length}行削除、${parsedCount}行を更新しました。`)
          } catch (e: unknown) {
            const err = e as { response?: { data?: { detail?: string } }; message?: string }
            setSaveMessage(err?.response?.data?.detail || err?.message || '削除・更新に失敗しました。')
            setSaveStatus('error')
          }
          return
        }

        if (hasExtraItems) {
          try {
            for (let i = 0; i < existingCount; i++) {
              const row = currentPageRows[i]
              const item = parsedItems![i] as Record<string, unknown>
              const updatedRow = itemToGridRow(row, item)
              await updateItemMutation.mutateAsync({ itemId: row.item_id, row: updatedRow })
            }
            const extraItems = parsedItems!.slice(existingCount) as Record<string, unknown>[]
            const excludeFromItemData = ['customer', 'item_id', 'page_number', 'item_order', 'version', '_displayIndex']
            let lastItemId = currentPageRows[currentPageRows.length - 1].item_id
            for (const item of extraItems) {
              const customer = (item.customer ?? item['得意先'] ?? null) as string | null
              const item_data = Object.fromEntries(
                Object.entries(item).filter(([k]) => !excludeFromItemData.includes(k))
              ) as Record<string, any>
              const created = await itemsApi.create(
                selectedDoc!.pdf_filename,
                currentPage,
                item_data,
                lastItemId
              )
              lastItemId = created.item_id
            }
            setDirtyIds((prev) => {
              const next = new Set(prev)
              currentPageRows.forEach((r) => next.delete(r.item_id))
              return next
            })
            syncItemDataKeysFromParsed(parsedItems!)
            queryClient.invalidateQueries({ queryKey: ['items', selectedDoc!.pdf_filename] })
            setSaveMessage(`기존 ${existingCount}행 갱신, ${extraItems.length}행 추가 후 DB에 반영했습니다。`)
          } catch (e: unknown) {
            const err = e as { response?: { data?: { detail?: string } }; message?: string }
            setSaveMessage(err?.response?.data?.detail || err?.message || 'DBの保存に失敗しました。')
            setSaveStatus('error')
          }
          return
        }

        const newDirty = new Set<number>()
        setRows((prev) =>
          prev.map((r) => {
            if (r.page_number !== currentPage) return r
            const idx = currentPageRows.findIndex((row) => row.item_id === r.item_id)
            if (idx < 0 || idx >= parsedItems!.length) return r
            const updated = itemToGridRow(r, parsedItems![idx] as Record<string, unknown>)
            newDirty.add(r.item_id)
            return updated
          })
        )
        setDirtyIds((d) => new Set([...d, ...newDirty]))
        syncItemDataKeysFromParsed(parsedItems!)
        setSaveMessage('JSONを適用しました。')
      } else {
        setSaveMessage('JSONを適用しました。')
      }
    } catch (_e) {
      setSaveMessage('JSONの形式が不正です。')
      setSaveStatus('error')
    }
  }, [jsonEditText, currentPage, currentPageRows, selectedDoc, queryClient, itemToGridRow, updateItemMutation])

  const handleSaveGrid = useCallback(async () => {
    if (!selectedDoc) return
    const latestRows = rowsRef.current
    const hasDirty = dirtyIds.size > 0 || pageMetaDirtyPages.size > 0
    if (!hasDirty) {
      setSaveMessage('変更がありません。')
      return
    }
    setSaveStatus('saving')
    setSaveMessage('')
    try {
      const excludeFromItemData = ['item_id', 'page_number', 'item_order', 'version', '_displayIndex']
      const pages: Array<{ page_number: number; page_role: string; page_meta: Record<string, unknown>; items: Array<Record<string, unknown>> }> = []
      for (let p = 1; p <= selectedDoc.total_pages; p++) {
        const pageRows = latestRows.filter((r) => r.page_number === p)
        let item_data_list = pageRows
          .sort((a, b) => Number(a.item_order ?? 0) - Number(b.item_order ?? 0))
          .map((row) => {
            const item_data: Record<string, unknown> = {}
            Object.keys(row).forEach((k) => {
              if (!excludeFromItemData.includes(k)) item_data[k] = row[k]
            })
            return item_data
          })
        const edits = pageMetaFlatEdits[p] ?? {}
        Object.entries(edits).forEach(([path, value]) => {
          if (value === PAGE_META_DELETE_SENTINEL) return
          const m = /^items\[(\d+)\]\.(.+)$/.exec(path)
          if (m) {
            const idx = parseInt(m[1], 10)
            const field = m[2]
            if (idx >= 0 && idx < item_data_list.length) item_data_list[idx][field] = value
          }
        })
        const page_roleRaw =
          pageRoleEdits[p] ??
          (pageMetaQueries[p - 1]?.data as { page_role?: string } | undefined)?.page_role ??
          (isRagMode && answerJsonFromImg?.pages
            ? (answerJsonFromImg.pages.find((pg: any) => Number(pg.page_number) === p) as { page_role?: string } | undefined)?.page_role
            : undefined) ??
          'detail'
        const page_role = ['cover', 'detail', 'summary', 'reply'].includes(page_roleRaw) ? page_roleRaw : 'detail'
        let page_meta: Record<string, unknown>
        if (isRagMode && answerJsonFromImg?.pages) {
          const basePage = answerJsonFromImg.pages.find((pg: any) => Number(pg.page_number) === p) as Record<string, unknown> | undefined
          page_meta = {}
          if (basePage) {
            Object.keys(basePage).forEach((k) => {
              if (k !== 'items' && k !== 'page_number' && k !== 'page_role헉') page_meta[k] = basePage[k]
            })
          }
          const edits = pageMetaFlatEdits[p] ?? {}
          Object.entries(edits).forEach(([path, value]) => {
            if (value === PAGE_META_DELETE_SENTINEL) return
            setNestedByPath(page_meta, path, value)
          })
        } else {
          page_meta = buildPageMetaFromEdits(p) as Record<string, unknown>
        }
        pages.push({ page_number: p, page_role, page_meta, items: item_data_list })
      }
      if (isRagMode && selectedDocRelativePath) {
        await documentsApi.saveAnswerJsonFromImg(selectedDocRelativePath, { pages })
        queryClient.invalidateQueries({ queryKey: ['answer-json-from-img', selectedDocRelativePath] })
      } else {
        await documentsApi.saveAnswerJson(selectedDoc.pdf_filename, { pages })
        skipNextSyncFromServerRef.current = true
        queryClient.invalidateQueries({ queryKey: ['document-answer-json', selectedDoc.pdf_filename] })
        queryClient.invalidateQueries({ queryKey: ['items', selectedDoc.pdf_filename] })
        queryClient.invalidateQueries({ queryKey: ['page-meta', selectedDoc.pdf_filename] })
      }
      setDirtyIds(new Set())
      setPageMetaFlatEdits({})
      setPageMetaDirtyPages(new Set())
      setPageRoleEdits((prev) => {
        const next = { ...prev }
        pageMetaDirtyPages.forEach((pn) => delete next[pn])
        return next
      })
      setSaveMessage(isRagMode ? 'JSONファイルを保存しました。' : 'グリッドの変更を保存しました。')
      setSaveStatus('done')
    } catch (e: any) {
      setSaveMessage(e?.response?.data?.detail || e?.message || '保存に失敗しました。')
      setSaveStatus('error')
    }
  }, [selectedDoc, selectedDocRelativePath, isRagMode, answerJsonFromImg, answerJsonFromDb, dirtyIds.size, pageMetaDirtyPages, pageRoleEdits, pageMetaQueries, pageMetaFlatEdits, buildPageMetaFromEdits, setNestedByPath, queryClient])

  const handleSaveAsAnswerKey = useCallback(async () => {
    if (!selectedDoc) return
    setSaveStatus('saving')
    setSaveMessage('')
    try {
      const latestRows = rowsRef.current
      const hasDirty = dirtyIds.size > 0 || pageMetaDirtyPages.size > 0
      if (hasDirty) {
        const excludeFromItemData = ['item_id', 'page_number', 'item_order', 'version', '_displayIndex']
        const pages: Array<{ page_number: number; page_role: string; page_meta: Record<string, unknown>; items: Array<Record<string, unknown>> }> = []
        for (let p = 1; p <= selectedDoc.total_pages; p++) {
          const pageRows = latestRows.filter((r) => r.page_number === p)
          let item_data_list = pageRows
            .sort((a, b) => Number(a.item_order ?? 0) - Number(b.item_order ?? 0))
            .map((row) => {
              const item_data: Record<string, unknown> = {}
              Object.keys(row).forEach((k) => {
                if (!excludeFromItemData.includes(k)) item_data[k] = row[k]
              })
              return item_data
            })
          const edits = pageMetaFlatEdits[p] ?? {}
          Object.entries(edits).forEach(([path, value]) => {
            if (value === PAGE_META_DELETE_SENTINEL) return
            const m = /^items\[(\d+)\]\.(.+)$/.exec(path)
            if (m) {
              const idx = parseInt(m[1], 10)
              const field = m[2]
              if (idx >= 0 && idx < item_data_list.length) item_data_list[idx][field] = value
            }
          })
          const page_roleRaw =
            pageRoleEdits[p] ??
            (pageMetaQueries[p - 1]?.data as { page_role?: string } | undefined)?.page_role ??
            (isRagMode && answerJsonFromImg?.pages
              ? (answerJsonFromImg.pages.find((pg: any) => Number(pg.page_number) === p) as { page_role?: string } | undefined)?.page_role
              : answerJsonFromDb?.pages
                ? (answerJsonFromDb.pages.find((pg: any) => Number(pg.page_number) === p) as { page_role?: string } | undefined)?.page_role
                : undefined) ??
            'detail'
        const page_role = ['cover', 'detail', 'summary', 'reply'].includes(page_roleRaw) ? page_roleRaw : 'detail'
        let page_meta: Record<string, unknown>
        if (isRagMode && answerJsonFromImg?.pages) {
          const basePage = answerJsonFromImg.pages.find((pg: any) => Number(pg.page_number) === p) as Record<string, unknown> | undefined
          page_meta = {}
          if (basePage) {
            Object.keys(basePage).forEach((k) => {
              if (k !== 'items' && k !== 'page_number' && k !== 'page_role') page_meta[k] = basePage[k]
            })
          }
          const editsForMeta = pageMetaFlatEdits[p] ?? {}
          Object.entries(editsForMeta).forEach(([path, value]) => {
            if (value === PAGE_META_DELETE_SENTINEL) return
            if (/^items\[\d+\]\./.test(path)) return
            setNestedByPath(page_meta, path, value)
          })
        } else if (answerJsonFromDb?.pages) {
          const basePage = answerJsonFromDb.pages.find((pg: any) => Number(pg.page_number) === p) as Record<string, unknown> | undefined
          page_meta = {}
          if (basePage) {
            Object.keys(basePage).forEach((k) => {
              if (k !== 'items' && k !== 'page_number' && k !== 'page_role') page_meta[k] = basePage[k]
            })
          }
          const editsForMeta = pageMetaFlatEdits[p] ?? {}
          Object.entries(editsForMeta).forEach(([path, value]) => {
            if (value === PAGE_META_DELETE_SENTINEL) return
            if (/^items\[\d+\]\./.test(path)) return
            setNestedByPath(page_meta, path, value)
          })
        } else {
          page_meta = buildPageMetaFromEdits(p) as Record<string, unknown>
        }
        pages.push({ page_number: p, page_role, page_meta, items: item_data_list })
      }
      if (isRagMode && selectedDocRelativePath) {
          await documentsApi.saveAnswerJsonFromImg(selectedDocRelativePath, { pages })
          queryClient.invalidateQueries({ queryKey: ['answer-json-from-img', selectedDocRelativePath] })
        } else {
          await documentsApi.saveAnswerJson(selectedDoc.pdf_filename, { pages })
          skipNextSyncFromServerRef.current = true
          queryClient.invalidateQueries({ queryKey: ['document-answer-json', selectedDoc.pdf_filename] })
          queryClient.invalidateQueries({ queryKey: ['items', selectedDoc.pdf_filename] })
          queryClient.invalidateQueries({ queryKey: ['page-meta', selectedDoc.pdf_filename] })
        }
        setDirtyIds(new Set())
        setPageMetaFlatEdits({})
        setPageMetaDirtyPages(new Set())
        setPageRoleEdits((prev) => {
          const next = { ...prev }
          pageMetaDirtyPages.forEach((pn) => delete next[pn])
          return next
        })
      }
      setSaveStatus('building')
      setSaveMessage('学習フラグを設定し、ベクターDBに登録しています…')
      for (let p = 1; p <= selectedDoc.total_pages; p++) {
        await ragAdminApi.setLearningFlag({
          pdf_filename: selectedDoc.pdf_filename,
          page_number: p,
          selected: true,
        })
      }
      await ragAdminApi.buildFromLearningPages(undefined)
      queryClient.invalidateQueries({ queryKey: ['rag-admin', 'learning-pages'] })
      queryClient.invalidateQueries({ queryKey: ['rag-admin', 'status'] })
      setSaveMessage('正解表として保存し、ベクターDBに登録しました。')
      setSaveStatus('done')
    } catch (e: any) {
      setSaveMessage(e?.response?.data?.detail || e?.message || '正解表の保存に失敗しました。')
      setSaveStatus('error')
    }
  }, [selectedDoc, selectedDocRelativePath, isRagMode, answerJsonFromImg, answerJsonFromDb, dirtyIds.size, pageMetaDirtyPages, pageRoleEdits, pageMetaQueries, pageMetaFlatEdits, buildPageMetaFromEdits, setNestedByPath, queryClient])

  const imageUrls = useMemo(() => {
    if (isRagMode && selectedDocRelativePath && selectedDoc?.total_pages) {
      return Array.from({ length: selectedDoc.total_pages }, (_, i) =>
        documentsApi.getImgPageImageUrl(selectedDocRelativePath, i + 1)
      )
    }
    return pageImageQueries.map((q) => {
      const data = q.data as { image_url?: string } | undefined
      if (!data?.image_url) return null
      const url = data.image_url.startsWith('http') ? data.image_url : `${getApiBaseUrl()}${data.image_url}`
      return url
    })
  }, [isRagMode, selectedDocRelativePath, selectedDoc?.total_pages, pageImageQueries])

  return (
    <div className="answer-key-tab">
      <div className="answer-key-header">
        <h2 className="answer-key-title">正解表作成</h2>
        <p className="answer-key-desc">
          検索タブで「正解表作成」を押して指定した文書のみここに表示されます。文書を選択し、左のPDFを見ながら右のキー・値で正解を編集して保存すると、ベクターDBの学習例として登録されます。
        </p>
      </div>

      <div className="answer-key-select-row">
        <label className="answer-key-label">文書選択（正解表作成指定文書のみ）</label>
        <select
          className="answer-key-select"
          value={selectedDoc ? selectedDoc.pdf_filename : ''}
          onChange={(e) => {
            const v = e.target.value
            if (!v) {
              setSelectedDoc(null)
              setSelectedDocRelativePath(null)
              setRows([])
              return
            }
            const doc = documents.find((d) => d.pdf_filename === v)
            if (doc) {
              setSelectedDoc({ pdf_filename: doc.pdf_filename, total_pages: doc.total_pages })
              setSelectedDocRelativePath(null)
            }
          }}
        >
          <option value="">— 選択 —</option>
          {documents.map((d) => (
            <option key={d.pdf_filename} value={d.pdf_filename}>
              {d.pdf_filename} ({d.total_pages}ページ)
            </option>
          ))}
          {/* RAG 현황판에서 넘어온 문서는 목록에 없으므로 option 추가 */}
          {selectedDoc && !documents.some((d) => d.pdf_filename === selectedDoc.pdf_filename) && (
            <option value={selectedDoc.pdf_filename}>
              {selectedDoc.pdf_filename} ({selectedDoc.total_pages}ページ) — RAG参照
            </option>
          )}
        </select>
        {selectedDoc && (
          <button
            type="button"
            className="answer-key-revoke-btn"
            onClick={() => setShowRevokeModal(true)}
            title="正解表指定の解除（検索タブで再表示）"
          >
            正解表指定を解除
          </button>
        )}
      </div>

      {selectedDoc && pageMetaErrorPageNumbers.length > 0 && (
        <div className="answer-key-meta-error-banner" role="alert">
          一部ページでメタデータを読み込めませんでした (p.{pageMetaErrorPageNumbers.join(', p.')})。該当ページには行・page_metaが無い場合があります。
        </div>
      )}

      {/* 正解表指定解除確認モーダル */}
      {showRevokeModal && selectedDoc && (
        <div className="answer-key-modal-overlay" onClick={() => !revokeAnswerKeyMutation.isPending && setShowRevokeModal(false)}>
          <div className="answer-key-modal" onClick={(e) => e.stopPropagation()}>
            <h3 className="answer-key-modal-title">正解表指定の解除</h3>
            <p className="answer-key-modal-desc">
              この文書の正解表作成対象指定を解除しますか？<br />
              解除すると検索タブで再表示されます。
            </p>
            <p className="answer-key-modal-filename">{selectedDoc.pdf_filename}</p>
            <div className="answer-key-modal-actions">
              <button
                type="button"
                className="answer-key-btn answer-key-btn-secondary"
                onClick={() => setShowRevokeModal(false)}
                disabled={revokeAnswerKeyMutation.isPending}
              >
                キャンセル
              </button>
              <button
                type="button"
                className="answer-key-btn answer-key-btn-revoke"
                onClick={() => revokeAnswerKeyMutation.mutate(selectedDoc.pdf_filename)}
                disabled={revokeAnswerKeyMutation.isPending}
              >
                {revokeAnswerKeyMutation.isPending ? '処理中…' : '解除'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* RAG에서 문서 클릭해 넘어온 경우 selectedDoc 있으므로 이 안내 숨김 */}
      {documents.length === 0 && !selectedDoc && (
        <div className="answer-key-placeholder">
          <p>正解表作成対象に指定した文書がありません。検索タブで文書を開き、「正解表作成」ボタンで指定してから、このタブで確認してください。</p>
        </div>
      )}

      {documents.length > 0 && !selectedDoc && (
        <div className="answer-key-placeholder">
          <p>左にPDF、右にキー・値一覧が表示されます。上で文書を選択してください。</p>
        </div>
      )}

      {selectedDoc && (
        <div className="answer-key-main">
          <AnswerKeyLeftPanel
            selectedDoc={selectedDoc}
            currentPage={currentPage}
            setCurrentPage={setCurrentPage}
            imageScrollRef={imageScrollRef}
            imageZoomContainerRef={imageZoomContainerRef}
            allImagesLoaded={allImagesLoaded}
            imageUrls={imageUrls}
            imageScale={imageScale}
            imageSize={imageSize}
            setImageSize={setImageSize}
            pageOcrTextQueries={pageOcrTextQueries}
            ocrRerunAzureModel={ocrRerunAzureModel}
            setOcrRerunAzureModel={setOcrRerunAzureModel}
            rerunOcrMutation={rerunOcrMutation}
          />

          <AnswerKeyRightPanel
            ctx={{
              rightView,
              setRightView,
              firstRowToTemplateEntries: (row: unknown) => firstRowToTemplateEntries(row as GridRow | undefined),
              currentPageRows,
              setTemplateEntries,
              syncJsonEditFromAnswer,
              dirtyIds,
              pageMetaDirtyPages,
              answerProvider,
              setAnswerProvider,
              generateAnswerMutation: generateAnswerMutation as AnswerKeyRightPanelCtx['generateAnswerMutation'],
              selectedDoc,
              rows,
              itemDataKeys,
              jsonEditText,
              setJsonEditText,
              applyJsonEdit,
              allDataLoaded,
              templateEntries,
              updateTemplateEntry,
              removeTemplateEntry,
              addTemplateEntry,
              generateFromTemplateMutation,
              currentPage,
              currentPageMetaFields,
              pageRoleEdits,
              setPageRoleEdits,
              setPageMetaDirtyPages,
              currentPageMetaData,
              groupedPageMetaFields,
              onPageMetaGroupRemove,
              editingPageMetaKey,
              setEditingPageMetaKey,
              editingPageMetaKeyValue,
              setEditingPageMetaKeyValue,
              onPageMetaKeyRenameFull,
              onPageMetaChange,
              onPageMetaKeyRemove,
              typeOptions,
              newPageMetaKey,
              setNewPageMetaKey,
              newPageMetaValue,
              setNewPageMetaValue,
              onPageMetaKeyAdd,
              displayKeys,
              dataKeysForDisplay,
              editableKeys,
              editingKeyName,
              setEditingKeyName,
              editingKeyValue,
              setEditingKeyValue,
              onRenameKey,
              onValueChange,
              onRemoveKey,
              onAddKey,
              getKuLabel,
              newKeyInput,
              setNewKeyInput,
              handleSaveGrid,
              handleSaveAsAnswerKey,
              saveStatus,
              saveMessage,
            }}
          />
        </div>
      )}
    </div>
  )
}
