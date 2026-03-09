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
import { useToast } from '@/contexts/ToastContext'
import { getPageImageAbsoluteUrl } from '@/utils/apiConfig'
import type { Document } from '@/types'
import {
  type GridRow,
  type InitialDocumentForAnswerKey,
  type AnswerKeyTabProps,
  SYSTEM_ROW_KEYS,
  ANSWER_KEY_HIDDEN_KEYS,
  CUSTOMER_KEYS,
  PRODUCT_NAME_KEYS,
  PAGE_META_DELETE_SENTINEL,
  pickFromGen,
} from './answerKeyTabConstants'
import {
  buildPagesPayload,
  attachOcrToPages,
  normalizePageRole,
} from './answerKeySaveUtils'
import { useAnswerKeyGrid } from './useAnswerKeyGrid'
import { AnswerKeyLeftPanel } from './AnswerKeyLeftPanel'
import { AnswerKeyRightPanel } from './AnswerKeyRightPanel'
import './AnswerKeyTab.css'

export type { InitialDocumentForAnswerKey }

export function AnswerKeyTab({ initialDocument, onConsumeInitialDocument, onRevokeSuccess }: AnswerKeyTabProps) {
  const { user } = useAuth()
  const isAdmin = user?.is_admin === true || user?.username === 'admin'
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const [selectedDoc, setSelectedDoc] = useState<{ pdf_filename: string; total_pages: number } | null>(null)
  const [currentPage, setCurrentPage] = useState(1)
  /** 検索タブから「このページのみ」で開いた場合の 실제 페이지 번호. 있으면 브릿지는 이 1페이지만 표시·저장 */
  const [bridgeSinglePageNumber, setBridgeSinglePageNumber] = useState<number | null>(null)
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'done' | 'error'>('idle')
  const [saveMessage, setSaveMessage] = useState<string>('')
  const [rightView, setRightView] = useState<'kv' | 'template'>('kv')
  const [templateEntries, setTemplateEntries] = useState<Array<{ id: string; key: string; value: string }>>([])
  const [answerProvider, setAnswerProvider] = useState<'gemini' | 'gpt-5.2'>('gpt-5.2')
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
  const { data: documentsData, isError: documentsListError } = useQuery({
    queryKey: ['documents', 'for-answer-key-tab'],
    queryFn: () => documentsApi.getListForAnswerKeyTab(),
  })

  const { data: inVectorData } = useQuery({
    queryKey: ['documents', 'in-vector-index'],
    queryFn: () => documentsApi.getInVectorIndex(),
  })
  const inVectorPdfSet = useMemo(
    () => new Set((inVectorData?.pdf_filenames ?? []).map((f) => (f ?? '').trim().toLowerCase())),
    [inVectorData?.pdf_filenames]
  )
  const isDocInVector = !!(
    selectedDoc && inVectorPdfSet.has(selectedDoc.pdf_filename.trim().toLowerCase())
  )

  /** base DB 문서: answer-json 한 번 로드 → 메모리에서 편집 → 저장 시에만 DB 반영 (순서/정렬 이슈 제거) */
  const { data: answerJsonFromDb } = useQuery({
    queryKey: ['document-answer-json', selectedDoc?.pdf_filename ?? ''],
    queryFn: () => documentsApi.getDocumentAnswerJson(selectedDoc!.pdf_filename),
    enabled: !!selectedDoc?.pdf_filename,
  })

  const [analyzingPage, setAnalyzingPage] = useState<number | null>(null)
  const analyzeSinglePageMutation = useMutation({
    mutationFn: async ({ pdfFilename, pageNumber }: { pdfFilename: string; pageNumber: number }) => {
      return documentsApi.analyzeSinglePage(pdfFilename, pageNumber)
    },
    onSuccess: (_, { pdfFilename }) => {
      queryClient.invalidateQueries({ queryKey: ['document-answer-json', pdfFilename] })
      queryClient.invalidateQueries({ queryKey: ['items', pdfFilename] })
      queryClient.invalidateQueries({ queryKey: ['page-meta', pdfFilename] })
      setAnalyzingPage(null)
    },
    onError: (e: unknown) => {
      setAnalyzingPage(null)
      const msg = e && typeof e === 'object' && 'response' in e
        ? (e as { response?: { data?: { detail?: string } } }).response?.data?.detail
        : (e as Error)?.message
      setSaveMessage(msg ? `ページ分析に失敗しました: ${msg}` : 'ページ分析に失敗しました。')
      setSaveStatus('error')
    },
  })

  // 解答作成は検討タブからブリッジされた1ページのみ表示。ページ遷移の自動分析は検討タブ(検索)でのみ行う。

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
      skipNextSyncRef.current = true
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

  // 검토 탭에서 넘어온 경우 해당 문서 자동 선택 (解答作成 지정 문서만). initialPage 있으면 해당 1페이지만 표시
  useEffect(() => {
    if (!initialDocument || !onConsumeInitialDocument) return
    const doc = documents.find((d) => d.pdf_filename === initialDocument.pdf_filename)
    if (doc) {
      const singlePage = initialDocument.initialPage != null && initialDocument.initialPage >= 1
      if (singlePage) {
        setBridgeSinglePageNumber(initialDocument.initialPage!)
        setSelectedDoc({ pdf_filename: doc.pdf_filename, total_pages: 1 })
        setCurrentPage(1)
      } else {
        setBridgeSinglePageNumber(null)
        setSelectedDoc({ pdf_filename: doc.pdf_filename, total_pages: doc.total_pages })
        setCurrentPage(1)
      }
      onConsumeInitialDocument()
    }
  }, [initialDocument, onConsumeInitialDocument, documents])

  const effectivePageNumber = bridgeSinglePageNumber ?? currentPage

  // 문서 변경 시 1페이지로 초기화, page_role 로컬 편집 초기화 (단일 페이지 모드 해제 시)
  useEffect(() => {
    if (selectedDoc && bridgeSinglePageNumber == null) setCurrentPage(1)
    if (selectedDoc) setPageRoleEdits({})
  }, [selectedDoc?.pdf_filename, bridgeSinglePageNumber])

  const pageImageQueries = useQueries({
    queries: selectedDoc
      ? Array.from(
          { length: bridgeSinglePageNumber != null ? 1 : selectedDoc.total_pages },
          (_, i) => {
            const pageNum = bridgeSinglePageNumber != null ? bridgeSinglePageNumber : i + 1
            return {
              queryKey: ['answer-key-page-image', selectedDoc.pdf_filename, pageNum],
              queryFn: () => searchApi.getPageImage(selectedDoc.pdf_filename, pageNum),
              enabled: true,
            }
          }
        )
      : [],
  })

  const pageItemsQueries = useQueries({
    queries: selectedDoc
      ? Array.from(
          { length: bridgeSinglePageNumber != null ? 1 : selectedDoc.total_pages },
          (_, i) => {
            const pageNum = bridgeSinglePageNumber != null ? bridgeSinglePageNumber : i + 1
            return {
              queryKey: ['items', selectedDoc.pdf_filename, pageNum],
              queryFn: () => itemsApi.getByPage(selectedDoc.pdf_filename, pageNum),
              enabled: true,
            }
          }
        )
      : [],
  })

  const pageMetaQueries = useQueries({
    queries: selectedDoc
      ? Array.from(
          { length: bridgeSinglePageNumber != null ? 1 : selectedDoc.total_pages },
          (_, i) => {
            const pageNum = bridgeSinglePageNumber != null ? bridgeSinglePageNumber : i + 1
            return {
              queryKey: ['page-meta', selectedDoc.pdf_filename, pageNum],
              queryFn: () => documentsApi.getPageMeta(selectedDoc.pdf_filename, pageNum),
              enabled: true,
              retry: false,
            }
          }
        )
      : [],
  })

  const pageOcrTextQueries = useQueries({
    queries: selectedDoc
      ? Array.from(
          { length: bridgeSinglePageNumber != null ? 1 : selectedDoc.total_pages },
          (_, i) => {
            const pageNum = bridgeSinglePageNumber != null ? bridgeSinglePageNumber : i + 1
            return {
              queryKey: ['page-ocr-text', selectedDoc.pdf_filename, pageNum],
              queryFn: () => searchApi.getPageOcrText(selectedDoc.pdf_filename, pageNum),
              enabled: !!selectedDoc,
            }
          }
        )
      : [],
  })

  const allItemsLoaded = !!answerJsonFromDb || pageItemsQueries.every((q) => !q.isLoading && (q.data != null || q.isError))
  const allPageMetaLoaded = !!answerJsonFromDb || pageMetaQueries.every((q) => !q.isLoading && (q.data != null || q.isError))
  const allDataLoaded = allItemsLoaded && allPageMetaLoaded
  const allImagesLoaded = pageImageQueries.every((q) => !q.isLoading && q.data != null)

  const answerJsonForGrid = useMemo(() => {
    if (bridgeSinglePageNumber == null || !answerJsonFromDb?.pages?.length) return answerJsonFromDb ?? null
    const filtered = answerJsonFromDb.pages.filter(
      (pg: Record<string, unknown>) => Number(pg.page_number) === bridgeSinglePageNumber
    )
    return filtered.length ? { pages: filtered } : null
  }, [answerJsonFromDb, bridgeSinglePageNumber])

  const grid = useAnswerKeyGrid({
    selectedDoc,
    currentPage,
    effectivePageNumber: bridgeSinglePageNumber ?? undefined,
    answerJsonFromDb: answerJsonForGrid,
    pageMetaQueries,
    pageItemsQueries,
    allDataLoaded,
  })

  const {
    skipNextSyncRef,
    rowsRef,
    dirtyIds,
    setDirtyIds,
    setRows,
    setItemDataKeys,
    pageMetaFlatEdits,
    setPageMetaFlatEdits,
    pageMetaDirtyPages,
    setPageMetaDirtyPages,
    setPageRoleEdits,
    pageRoleEdits,
    buildPageMetaFromEdits,
    setNestedByPath,
  } = grid

  /** page_meta 조회 실패(404 등) 페이지 번호 목록 */
  const pageMetaErrorPageNumbers = useMemo(() => {
    if (!selectedDoc) return []
    return pageMetaQueries
      .map((q, i) => (q.isError ? (bridgeSinglePageNumber != null ? bridgeSinglePageNumber : i + 1) : 0))
      .filter((p) => p > 0)
  }, [selectedDoc, pageMetaQueries, bridgeSinglePageNumber])

  /** 첫 행에서 템플릿 엔트리 초기값 생성 (시스템·frozen 제외) */
  const firstRowToTemplateEntries = useCallback((row: GridRow | undefined) => {
    if (!row) return []
    return Object.entries(row)
      .filter(([k]) => !SYSTEM_ROW_KEYS.includes(k) && !ANSWER_KEY_HIDDEN_KEYS.has(k))
      .map(([key, val], i) => ({
        id: `t-${currentPage}-${i}-${key}`,
        key,
        value: val == null ? '' : String(val),
      }))
  }, [currentPage])

  /** テンプレートタブ選択時・ページ変更時のみテンプレートエントリ初期化 */
  useEffect(() => {
    if (rightView !== 'template') return
    const first = grid.currentPageRows[0]
    setTemplateEntries(firstRowToTemplateEntries(first))
  }, [rightView, currentPage])

  useEffect(() => {
    if (rightView !== 'template' || !allDataLoaded) return
    const first = grid.currentPageRows[0]
    if (!first) return
    setTemplateEntries((prev) => {
      if (prev.length > 0) return prev
      return firstRowToTemplateEntries(first)
    })
  }, [rightView, allDataLoaded, grid.currentPageRows, firstRowToTemplateEntries])

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
        effectivePageNumber,
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

  const getPageRoleForSave = useCallback(
    (p: number) => {
      const raw =
        pageRoleEdits[p] ??
        (pageMetaQueries[p - 1]?.data as { page_role?: string } | undefined)?.page_role ??
        (answerJsonFromDb?.pages
          ? (answerJsonFromDb.pages.find((pg: any) => Number(pg.page_number) === p) as { page_role?: string } | undefined)?.page_role
          : undefined) ??
        'detail'
      return normalizePageRole(raw)
    },
    [pageRoleEdits, pageMetaQueries, answerJsonFromDb?.pages]
  )

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
      // Phase 1: 해당 페이지만 저장 (단일 페이지 저장 API 호출)
      const pageNum = bridgeSinglePageNumber ?? currentPage
      const pageRows = latestRows.filter((r) => r.page_number === pageNum)
      const single = buildPagesPayload(
        1,
        pageRows.map((r) => ({ ...r, page_number: 1 })),
        pageMetaFlatEdits,
        () => getPageRoleForSave(pageNum),
        () => buildPageMetaFromEdits(pageNum) as Record<string, unknown>
      )[0]
      const pages = single ? [{ ...single, page_number: pageNum }] : []
      attachOcrToPages(pages, selectedDoc.pdf_filename, queryClient)
      await documentsApi.saveAnswerJson(selectedDoc.pdf_filename, { pages })
      skipNextSyncRef.current = true
      queryClient.invalidateQueries({ queryKey: ['document-answer-json', selectedDoc.pdf_filename] })
      queryClient.invalidateQueries({ queryKey: ['items', selectedDoc.pdf_filename] })
      queryClient.invalidateQueries({ queryKey: ['page-meta', selectedDoc.pdf_filename] })
      setDirtyIds(new Set())
      setPageMetaFlatEdits({})
      setPageMetaDirtyPages(new Set())
      setPageRoleEdits((prev) => {
        const next = { ...prev }
        pageMetaDirtyPages.forEach((pn) => delete next[pn])
        return next
      })
      setSaveMessage('グリッドの変更を保存しました。')
      setSaveStatus('done')
    } catch (e: any) {
      setSaveMessage(e?.response?.data?.detail || e?.message || '保存に失敗しました。')
      setSaveStatus('error')
    }
  }, [selectedDoc, dirtyIds.size, pageMetaDirtyPages, pageMetaFlatEdits, getPageRoleForSave, buildPageMetaFromEdits, rowsRef, skipNextSyncRef, setDirtyIds, setPageMetaFlatEdits, setPageMetaDirtyPages, setPageRoleEdits, queryClient, bridgeSinglePageNumber])

  // to_do: 保存 버튼 또는 Ctrl+S — 키보드 단축키
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault()
        handleSaveGrid()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [handleSaveGrid])

  const imageUrls = useMemo(() => {
    return pageImageQueries.map((q) => {
      const data = q.data as { image_url?: string } | undefined
      return getPageImageAbsoluteUrl(data?.image_url) ?? null
    })
  }, [pageImageQueries])

  /** Phase 3: 현재 페이지 히스토리 (last_edited_at, is_rag_candidate) — 좌측 패널에 표시 */
  const currentPageHistory = useMemo(() => {
    if (!answerJsonFromDb?.pages) return null
    const pn = bridgeSinglePageNumber ?? currentPage
    const page = answerJsonFromDb.pages.find((p: { page_number?: number }) => Number(p?.page_number) === pn)
    if (!page) return null
    return {
      last_edited_at: (page as { last_edited_at?: string | null }).last_edited_at ?? null,
      is_rag_candidate: !!(page as { is_rag_candidate?: boolean }).is_rag_candidate,
    }
  }, [answerJsonFromDb?.pages, currentPage, bridgeSinglePageNumber])

  return (
    <div className="answer-key-tab">
      <div className="answer-key-header">
        <h2 className="answer-key-title">解答作成</h2>
        <p className="answer-key-desc">
          検索タブで「解答作成」を押して指定した文書のみここに表示されます。左のPDFを見ながら右のキー・値で正解を編集し、「保存」でDBに反映します。「再分析」で該当ページのみOCR＋RAG＋LLMを再実行してDBを更新できます。検討タブへは「検討タブに復帰」で戻ります。管理者は「学習リクエスト」で該当ページをベクターDBに反映できます。
        </p>
      </div>

      {/* ブリッジ: 請求タブから指定した1文書のみ。文書切り替えドロップダウンは不要 */}
      <div className="answer-key-select-row">
        {selectedDoc && (
          <>
            <span className="answer-key-current-doc" title={selectedDoc.pdf_filename}>
              {selectedDoc.pdf_filename}（{selectedDoc.total_pages}p）
            </span>
            <button
              type="button"
              className="answer-key-revoke-btn"
              onClick={() => {
                const full = documents.find((d) => d.pdf_filename === selectedDoc.pdf_filename)
                onRevokeSuccess?.({
                  pdf_filename: selectedDoc.pdf_filename,
                  form_type: full?.form_type ?? null,
                })
              }}
              title="検討タブに切り替えます（保存は行いません）"
            >
              検討タブに復帰
            </button>
            <button
              type="button"
              className="answer-key-btn answer-key-btn-save"
              onClick={() => handleSaveGrid()}
              disabled={saveStatus === 'saving'}
              title="変更をDBに保存します（このタブに留まります）"
            >
              {saveStatus === 'saving' ? '保存中…' : '保存'}
            </button>
            <button
              type="button"
              className="answer-key-btn answer-key-btn-reanalyze"
              onClick={() => {
                if (!selectedDoc) return
                const pn = bridgeSinglePageNumber ?? currentPage
                setAnalyzingPage(pn)
                analyzeSinglePageMutation.mutate(
                  { pdfFilename: selectedDoc.pdf_filename, pageNumber: pn },
                  { onSettled: () => setAnalyzingPage(null) }
                )
              }}
              disabled={analyzingPage != null || analyzeSinglePageMutation.isPending}
              title="該当ページのみ再分析してDBを更新します（OCR＋RAG＋LLM）"
            >
              {analyzingPage != null || analyzeSinglePageMutation.isPending ? '分析中…' : '再分析'}
            </button>
            {isAdmin && (
              <button
                type="button"
                className="answer-key-btn answer-key-btn-learning"
                onClick={async () => {
                  if (!selectedDoc) return
                  const hasDirty = dirtyIds.size > 0 || pageMetaDirtyPages.size > 0
                  if (hasDirty) {
                    alert('저장하지 않은 행이 있습니다. 저장 후 학습 요청해 주세요.')
                    return
                  }
                  try {
                    await ragAdminApi.learningRequestPage(selectedDoc.pdf_filename, effectivePageNumber)
                    queryClient.invalidateQueries({ queryKey: ['rag-admin', 'status'] })
                    queryClient.invalidateQueries({ queryKey: ['documents', 'in-vector-index'] })
                    setSaveMessage('해당 페이지를 벡터 DB에 반영했습니다.')
                    setSaveStatus('done')
                    showToast(
                      '이 페이지를 정답지로 반영했습니다. 현황 탭 → RAG(ベクターDB) 섹션의 「全体解答」「使用中解答」 수가 증가합니다.',
                      'success'
                    )
                  } catch (e: any) {
                    const msg = e?.response?.data?.detail || e?.message || '학습 요청에 실패했습니다.'
                    setSaveMessage(msg)
                    setSaveStatus('error')
                    showToast(msg, 'error')
                  }
                }}
                title="현재 페이지만 벡터 DB에 반영 (관리자 전용)"
              >
                学習リクエスト
              </button>
            )}
          </>
        )}
      </div>

      {selectedDoc && analyzingPage != null && (
        <div className="answer-key-analyzing-banner" role="status">
          페이지 {analyzingPage} 분석 중…
        </div>
      )}
      {selectedDoc && pageMetaErrorPageNumbers.length > 0 && (
        <div className="answer-key-meta-error-banner" role="alert">
          一部ページでメタデータを読み込めませんでした (p.{pageMetaErrorPageNumbers.join(', p.')})。該当ページには行・page_metaが無い場合があります。該当ページはスキップするか、検討タブで先にOCR・抽出を実行してください。
        </div>
      )}

      {/* 文書一覧取得失敗時 */}
      {documents.length === 0 && !selectedDoc && documentsListError && (
        <div className="answer-key-placeholder">
          <p>文書一覧の取得に失敗しました。ログインし直すか、ネットワーク・API接続を確認してください。（IPでアクセスする場合はCORS設定も確認）</p>
        </div>
      )}
      {documents.length === 0 && !selectedDoc && !documentsListError && (
        <div className="answer-key-placeholder">
          <p>解答作成対象に指定した文書がありません。検索タブで文書を開き、「解答作成」ボタンで指定してから、このタブで確認してください。</p>
        </div>
      )}

      {documents.length > 0 && !selectedDoc && (
        <div className="answer-key-placeholder">
          <p>検索タブで文書を開き、「解答作成」で指定したうえで、このタブに遷移してください。</p>
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
            pageHistory={currentPageHistory}
          />

          <AnswerKeyRightPanel
            viewCtx={{ rightView, setRightView }}
            templateCtx={{
              firstRowToTemplateEntries: (row: unknown) => firstRowToTemplateEntries(row as GridRow | undefined),
              setTemplateEntries,
              templateEntries,
              updateTemplateEntry,
              removeTemplateEntry,
              addTemplateEntry,
              generateFromTemplateMutation,
              allDataLoaded,
            }}
            gridCtx={{
              currentPage,
              currentPageRows: grid.currentPageRows,
              rows: grid.rows,
              itemDataKeys: grid.itemDataKeys,
              dirtyIds: grid.dirtyIds,
              displayKeys: grid.displayKeys,
              dataKeysForDisplay: grid.dataKeysForDisplay,
              editableKeys: grid.editableKeys,
              typeOptions: grid.typeOptions,
              editingKeyName: grid.editingKeyName,
              setEditingKeyName: grid.setEditingKeyName,
              editingKeyValue: grid.editingKeyValue,
              setEditingKeyValue: grid.setEditingKeyValue,
              onRenameKey: grid.onRenameKey,
              onValueChange: grid.onValueChange,
              onRemoveKey: grid.onRemoveKey,
              onAddKey: grid.onAddKey,
              getKuLabel: grid.getKuLabel,
              newKeyInput: grid.newKeyInput,
              setNewKeyInput: grid.setNewKeyInput,
            }}
            pageMetaCtx={{
              currentPageMetaFields: grid.currentPageMetaFields,
              pageMetaDirtyPages: grid.pageMetaDirtyPages,
              pageRoleEdits: grid.pageRoleEdits,
              setPageRoleEdits: grid.setPageRoleEdits,
              setPageMetaDirtyPages: grid.setPageMetaDirtyPages,
              currentPageMetaData: grid.currentPageMetaData,
              groupedPageMetaFields: grid.groupedPageMetaFields,
              onPageMetaGroupRemove: grid.onPageMetaGroupRemove,
              editingPageMetaKey: grid.editingPageMetaKey,
              setEditingPageMetaKey: grid.setEditingPageMetaKey,
              editingPageMetaKeyValue: grid.editingPageMetaKeyValue,
              setEditingPageMetaKeyValue: grid.setEditingPageMetaKeyValue,
              onPageMetaKeyRenameFull: grid.onPageMetaKeyRenameFull,
              onPageMetaChange: grid.onPageMetaChange,
              onPageMetaKeyRemove: grid.onPageMetaKeyRemove,
              newPageMetaKey: grid.newPageMetaKey,
              setNewPageMetaKey: grid.setNewPageMetaKey,
              newPageMetaValue: grid.newPageMetaValue,
              setNewPageMetaValue: grid.setNewPageMetaValue,
              onPageMetaKeyAdd: grid.onPageMetaKeyAdd,
            }}
            generateCtx={{
              answerProvider,
              setAnswerProvider,
              generateAnswerMutation: generateAnswerMutation as { mutate: (arg: unknown) => void; isPending: boolean },
              selectedDoc,
              effectivePageNumber,
            }}
            saveCtx={{
              saveStatus,
              saveMessage,
              readOnly: isDocInVector,
            }}
          />
        </div>
      )}
    </div>
  )
}
