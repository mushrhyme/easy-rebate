/**
 * 정답지 생성 탭
 * - 좌측: 선택한 문서의 PDF 전체 페이지 이미지 (스크롤)
 * - 우측: page_meta + items キー・値 형태 (편집 가능)
 * - 정답지로 저장: 수정사항 DB 반영 후 학습 플래그 설정 및 벡터 DB 생성
 */
import { useState, useMemo, useCallback, useEffect, useRef } from 'react'
import { useQuery, useQueries, useMutation, useQueryClient } from '@tanstack/react-query'
import { documentsApi, itemsApi, searchApi, ragAdminApi } from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import { getApiBaseUrl } from '@/utils/apiConfig'
import type { Document } from '@/types'
import './AnswerKeyTab.css'

interface GridRow {
  item_id: number
  page_number: number
  item_order: number
  version: number
  /** 데이터 필드는 모두 item_data의 키(예: 得意先, 商品名 등)를 그대로 사용 */
  [key: string]: string | number | boolean | null | undefined
}

const SYSTEM_ROW_KEYS = ['item_id', 'page_number', 'item_order', 'version']

const KEY_LABELS: Record<string, string> = {
  page_number: 'ページ',
  item_order: '順番',
  得意先: '得意先',
  '商品名': '商品名',
  item_id: 'item_id',
  version: 'version',
}

interface AnswerKeyTabProps {
  /** 검토 탭에서 정답지 지정 후 이동 시 자동 선택할 문서 */
  initialPdfFilename?: string | null
  /** initialPdfFilename 적용 후 호출 (한 번만 선택되도록) */
  onConsumeInitialPdfFilename?: () => void
}

/** API 정답 생성 결과의 일본어 키 → UI 표시 필드 매핑 (프롬프트가 일본어 키로 반환할 때) */
const CUSTOMER_KEYS = ['得意先名', '得意先様', '得意先', '取引先']
const PRODUCT_NAME_KEYS = ['商品名']
const PAGE_META_DELETE_SENTINEL = '__DELETE__'

function pickFromGen(gen: Record<string, unknown>, keys: string[]): string | null {
  for (const k of keys) {
    const v = gen[k]
    if (v != null && typeof v === 'string' && v.trim() !== '') return v.trim()
  }
  return null
}

export function AnswerKeyTab({ initialPdfFilename, onConsumeInitialPdfFilename }: AnswerKeyTabProps) {
  const { sessionId } = useAuth()
  const queryClient = useQueryClient()
  /** 정답 생성 직후 한 번은 서버 동기화 effect가 rows를 덮어쓰지 않도록 */
  const skipNextSyncFromServerRef = useRef(false)
  const [selectedDoc, setSelectedDoc] = useState<{ pdf_filename: string; total_pages: number } | null>(null)
  const [currentPage, setCurrentPage] = useState(1)
  const [rows, setRows] = useState<GridRow[]>([])
  const [itemDataKeys, setItemDataKeys] = useState<string[]>([])
  const [dirtyIds, setDirtyIds] = useState<Set<number>>(new Set())
  const [pageMetaFlatEdits, setPageMetaFlatEdits] = useState<Record<number, Record<string, string>>>({})
  const [pageMetaDirtyPages, setPageMetaDirtyPages] = useState<Set<number>>(new Set())
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
  /** キー・値 탭: page_meta 새 키/값 추가용 */
  const [newPageMetaKey, setNewPageMetaKey] = useState('')
  const [newPageMetaValue, setNewPageMetaValue] = useState('')
  /** キー・値タブ: items用の新規キー追加 */
  const [newKeyInput, setNewKeyInput] = useState('')
  /** 정답 생성 시 사용할 모델: Gemini 2.5 Flash Lite | GPT 5.2 만 허용 */
  const [answerProvider, setAnswerProvider] = useState<'gemini' | 'gpt-5.2'>('gemini')
  /** 画像 Ctrl+ホイール 拡大縮小 */
  const [imageScale, setImageScale] = useState(1)
  const [imageSize, setImageSize] = useState<{ w: number; h: number } | null>(null)
  const imageScrollRef = useRef<HTMLDivElement>(null)

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

  const { data: documentsData } = useQuery({
    queryKey: ['documents', 'for-answer-key-tab'],
    queryFn: () => documentsApi.getListForAnswerKeyTab(),
  })

  const revokeAnswerKeyMutation = useMutation({
    mutationFn: (pdfFilename: string) => documentsApi.revokeAnswerKeyDocument(pdfFilename),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents', 'for-answer-key-tab'] })
      setShowRevokeModal(false)
      setSelectedDoc(null)
      setRows([])
      setSaveMessage('正解表の指定を解除しました。検索タブで再度確認できます。')
    },
    onError: (e: any) => {
      setSaveMessage(e?.response?.data?.detail || e?.message || '解除に失敗しました。')
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
        setSaveMessage(`Geminiで${data.createdCount}件を新規生成しました。`)
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
        setSaveMessage('このページには既存項目がなく、Geminiが生成した項目もありません。')
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
          ? `Geminiで${applyCount}件を適用（生成${generatedItems.length}件、既存項目数を超えた分は未適用）`
          : `Geminiで正解${applyCount}件を生成・適用しました。`
      setSaveMessage(msg)
      setSaveStatus('done')
    },
    onError: (e: any) => {
      setSaveMessage(e?.response?.data?.detail || e?.message || 'Geminiでの正解生成に失敗しました。')
      setSaveStatus('error')
    },
  })
  const documents: Document[] = useMemo(() => {
    const raw = documentsData?.documents
    return Array.isArray(raw) ? raw : []
  }, [documentsData])

  // 검토 탭에서 정답지 지정 후 넘어온 경우 해당 문서 자동 선택
  useEffect(() => {
    if (!initialPdfFilename || !onConsumeInitialPdfFilename || documents.length === 0) return
    const doc = documents.find((d) => d.pdf_filename === initialPdfFilename)
    if (doc) {
      setSelectedDoc({ pdf_filename: doc.pdf_filename, total_pages: doc.total_pages })
      setCurrentPage(1)
      onConsumeInitialPdfFilename()
    }
  }, [initialPdfFilename, onConsumeInitialPdfFilename, documents])

  // 문서 변경 시 1페이지로 초기화
  useEffect(() => {
    if (selectedDoc) setCurrentPage(1)
  }, [selectedDoc?.pdf_filename])

  const pageImageQueries = useQueries({
    queries: selectedDoc
      ? Array.from({ length: selectedDoc.total_pages }, (_, i) => ({
          queryKey: ['answer-key-page-image', selectedDoc.pdf_filename, i + 1],
          queryFn: () => searchApi.getPageImage(selectedDoc.pdf_filename, i + 1),
          enabled: !!selectedDoc,
        }))
      : [],
  })

  const pageItemsQueries = useQueries({
    queries: selectedDoc
      ? Array.from({ length: selectedDoc.total_pages }, (_, i) => ({
          queryKey: ['items', selectedDoc.pdf_filename, i + 1],
          queryFn: () => itemsApi.getByPage(selectedDoc.pdf_filename, i + 1),
          enabled: !!selectedDoc,
        }))
      : [],
  })

  const pageMetaQueries = useQueries({
    queries: selectedDoc
      ? Array.from({ length: selectedDoc.total_pages }, (_, i) => ({
          queryKey: ['page-meta', selectedDoc.pdf_filename, i + 1],
          queryFn: () => documentsApi.getPageMeta(selectedDoc.pdf_filename, i + 1),
          enabled: !!selectedDoc,
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

  const allItemsLoaded = pageItemsQueries.every((q) => !q.isLoading && (q.data != null || q.isError))
  const allPageMetaLoaded = pageMetaQueries.every((q) => !q.isLoading && (q.data != null || q.isError))
  const allDataLoaded = allItemsLoaded && allPageMetaLoaded
  const allImagesLoaded = pageImageQueries.every((q) => !q.isLoading && q.data != null)

  /** page_meta 조회 실패(404 등) 페이지 번호 목록 — 일부 페이지만 page_data가 있을 때 안내용 */
  const pageMetaErrorPageNumbers = useMemo(() => {
    if (!selectedDoc) return []
    return pageMetaQueries
      .map((q, i) => (q.isError ? i + 1 : 0))
      .filter((p) => p > 0)
  }, [selectedDoc, pageMetaQueries])

  // 서버 items/page_meta가 갱신될 때만 로컬 rows 동기화 (dataUpdatedAt 사용으로 refetch 완료 시 확실히 반영)
  const pageItemsDataUpdatedAt = pageItemsQueries.map((q) => q.dataUpdatedAt ?? 0).join(',')
  useEffect(() => {
    if (!selectedDoc || !allDataLoaded) return
    // 정답 생성 직후 한 번은 서버 데이터로 덮어쓰지 않음 (생성 결과가 UI에 유지되도록)
    if (skipNextSyncFromServerRef.current) {
      skipNextSyncFromServerRef.current = false
      return
    }
    // 사용자가 편집 중이면 서버 데이터로 덮어쓰지 않음 (편집/생성 결과 손실 방지)
    if (dirtyIds.size > 0 || pageMetaDirtyPages.size > 0) return
    const combined: GridRow[] = []
    let keys: string[] = []
    for (let p = 0; p < pageItemsQueries.length; p++) {
      const res = pageItemsQueries[p].data as { items: any[]; item_data_keys?: string[] | null } | undefined
      if (!res?.items) continue
      if (res.item_data_keys?.length) keys = res.item_data_keys
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
          })
        }
        combined.push(row)
      })
    }
    setRows(combined)
    if (keys.length) setItemDataKeys(keys)
    setDirtyIds(new Set())
    setPageMetaFlatEdits({})
    setPageMetaDirtyPages(new Set())
  }, [selectedDoc, allDataLoaded, pageItemsDataUpdatedAt, dirtyIds.size, pageMetaDirtyPages.size])

  const currentPageRows = useMemo(
    () => rows.filter((r) => r.page_number === currentPage),
    [rows, currentPage]
  )

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

  const displayKeys = useMemo(() => {
    const base = ['page_number', 'item_order', '得意先', '商品名'] as const
    const rest = dataKeysForDisplay.filter((k) => !(base as readonly string[]).includes(k))
    return [...base, ...rest, 'item_id', 'version']
  }, [dataKeysForDisplay])

  const editableKeys = useMemo(() => {
    return new Set(['得意先', '商品名', ...dataKeysForDisplay])
  }, [dataKeysForDisplay])

  const onValueChange = useCallback((itemId: number, key: string, value: string | number | boolean | null) => {
    setRows((prev) =>
      prev.map((r) => (r.item_id !== itemId ? r : { ...r, [key]: value }))
    )
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

  const currentPageMetaData = useMemo(() => {
    if (!selectedDoc) return null
    const q = pageMetaQueries[currentPage - 1]
    if (!q?.data) return null
    return q.data as { page_role: string | null; page_meta: Record<string, any> }
  }, [selectedDoc, currentPage, pageMetaQueries])

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

  const onPageMetaKeyRename = useCallback((oldKey: string, newKey: string) => {
    const n = (newKey ?? '').trim()
    if (!n || n === oldKey) return
    setPageMetaFlatEdits((prev) => {
      const page = prev[currentPage] ?? {}
      const val = page[oldKey]
      if (val === undefined) return prev
      const next = { ...page }
      delete next[oldKey]
      next[n] = val
      return { ...prev, [currentPage]: next }
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
      const excludeFromItemData = ['item_id', 'page_number', 'item_order', 'version']
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
        templateItem
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
    const pageRole = currentPageMetaData?.page_role ?? 'detail'
    const items = currentPageRows.map(({ item_id, page_number, item_order, version, ...rest }) => rest)
    return { page_role: pageRole, ...pageMeta, items }
  }, [currentPage, currentPageMetaData?.page_role, currentPageRows, buildPageMetaFromEdits])

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
                (a, b) => (a.page_number - b.page_number) || ((a.item_order ?? 0) - (b.item_order ?? 0))
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
            const excludeFromItemData = ['customer', 'item_id', 'page_number', 'item_order', 'version']
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
                customer ?? undefined,
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
    if (!selectedDoc || (dirtyIds.size === 0 && pageMetaDirtyPages.size === 0)) {
      setSaveMessage('変更がありません。')
      return
    }
    setSaveStatus('saving')
    setSaveMessage('')
    try {
      for (const itemId of dirtyIds) {
        const row = rows.find((r) => r.item_id === itemId)
        if (!row) continue
        await updateItemMutation.mutateAsync({ itemId, row })
      }
      for (const pageNum of pageMetaDirtyPages) {
        const pageMeta = buildPageMetaFromEdits(pageNum)
        await documentsApi.updatePageMeta(selectedDoc.pdf_filename, pageNum, pageMeta)
      }
      setDirtyIds(new Set())
      setPageMetaFlatEdits({})
      setPageMetaDirtyPages(new Set())
      queryClient.invalidateQueries({ queryKey: ['items', selectedDoc.pdf_filename] })
      queryClient.invalidateQueries({ queryKey: ['page-meta', selectedDoc.pdf_filename] })
      setSaveMessage('グリッドの変更を保存しました。')
      setSaveStatus('done')
    } catch (e: any) {
      setSaveMessage(e?.response?.data?.detail || e?.message || '保存に失敗しました。')
      setSaveStatus('error')
    }
  }, [selectedDoc, dirtyIds, rows, pageMetaDirtyPages, updateItemMutation, buildPageMetaFromEdits, queryClient])

  const handleSaveAsAnswerKey = useCallback(async () => {
    if (!selectedDoc) return
    setSaveStatus('saving')
    setSaveMessage('')
    try {
      if (dirtyIds.size > 0) {
        for (const itemId of dirtyIds) {
          const row = rows.find((r) => r.item_id === itemId)
          if (!row) continue
          await updateItemMutation.mutateAsync({ itemId, row })
        }
        setDirtyIds(new Set())
      }
      if (pageMetaDirtyPages.size > 0) {
        for (const pageNum of pageMetaDirtyPages) {
          const pageMeta = buildPageMetaFromEdits(pageNum)
          await documentsApi.updatePageMeta(selectedDoc.pdf_filename, pageNum, pageMeta)
        }
        setPageMetaFlatEdits({})
        setPageMetaDirtyPages(new Set())
      }
      queryClient.invalidateQueries({ queryKey: ['items', selectedDoc.pdf_filename] })
      queryClient.invalidateQueries({ queryKey: ['page-meta', selectedDoc.pdf_filename] })
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
  }, [selectedDoc, dirtyIds, rows, pageMetaDirtyPages, buildPageMetaFromEdits, updateItemMutation, queryClient])

  const imageUrls = useMemo(() => {
    return pageImageQueries.map((q) => {
      const data = q.data as { image_url?: string } | undefined
      if (!data?.image_url) return null
      const url = data.image_url.startsWith('http') ? data.image_url : `${getApiBaseUrl()}${data.image_url}`
      return url
    })
  }, [pageImageQueries])

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
              setRows([])
              return
            }
            const doc = documents.find((d) => d.pdf_filename === v)
            if (doc) setSelectedDoc({ pdf_filename: doc.pdf_filename, total_pages: doc.total_pages })
          }}
        >
          <option value="">— 選択 —</option>
          {documents.map((d) => (
            <option key={d.pdf_filename} value={d.pdf_filename}>
              {d.pdf_filename} ({d.total_pages}ページ)
            </option>
          ))}
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

      {documents.length === 0 && (
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
          <div className="answer-key-left">
            <div className="answer-key-page-nav">
              <button
                type="button"
                className="answer-key-nav-btn"
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                disabled={currentPage <= 1}
                aria-label="前のページ"
              >
                ← 前
              </button>
              <span className="answer-key-page-info">
                {currentPage} / {selectedDoc.total_pages}
              </span>
              <button
                type="button"
                className="answer-key-nav-btn"
                onClick={() =>
                  setCurrentPage((p) => Math.min(selectedDoc.total_pages, p + 1))
                }
                disabled={currentPage >= selectedDoc.total_pages}
                aria-label="次のページ"
              >
                次 →
              </button>
            </div>
            <div ref={imageScrollRef} className="answer-key-left-scroll">
              <div
                className="answer-key-page-view answer-key-page-view-zoom"
                onWheel={(e) => {
                  if (e.ctrlKey || e.metaKey) {
                    e.preventDefault()
                    setImageScale((s) => Math.min(3, Math.max(0.25, s - e.deltaY * 0.002)))
                  }
                }}
              >
                {!allImagesLoaded && <p className="answer-key-loading">画像読み込み中…</p>}
                {allImagesLoaded && imageUrls[currentPage - 1] && (
                  <div
                    className="answer-key-image-zoom-wrapper"
                    style={
                      imageSize
                        ? { width: imageSize.w * imageScale, height: imageSize.h * imageScale }
                        : undefined
                    }
                  >
                    <img
                      src={imageUrls[currentPage - 1]!}
                      alt={`Page ${currentPage}`}
                      className="answer-key-page-img"
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
                )}
              </div>
              <div className="answer-key-ocr-section">
                <label className="answer-key-ocr-label">OCRテキスト</label>
                <textarea
                  className="answer-key-ocr-text"
                  readOnly
                  value={
                    pageOcrTextQueries[currentPage - 1]?.data?.ocr_text ??
                    (pageOcrTextQueries[currentPage - 1]?.isLoading ? '読み込み中…' : '')
                  }
                  placeholder="（OCR 텍스트 없음）"
                  rows={6}
                />
              </div>
            </div>
          </div>

          <div className="answer-key-right">
            <div className="answer-key-right-tabs">
              <button
                type="button"
                className={`answer-key-tab-btn ${rightView === 'kv' ? 'active' : ''}`}
                onClick={() => setRightView('kv')}
              >
                キー・値
              </button>
              <button
                type="button"
                className={`answer-key-tab-btn ${rightView === 'template' ? 'active' : ''}`}
                onClick={() => {
                  setRightView('template')
                  setTemplateEntries(firstRowToTemplateEntries(currentPageRows[0]))
                }}
              >
                テンプレート（先頭行）
              </button>
              <button
                type="button"
                className={`answer-key-tab-btn ${rightView === 'json' ? 'active' : ''}`}
                onClick={() => {
                  setRightView('json')
                  syncJsonEditFromAnswer()
                }}
              >
                JSON
              </button>
            </div>
            <div className="answer-key-grid-header">
              <span className="answer-key-grid-title">正解（キー・値編集後に保存）</span>
              {(dirtyIds.size > 0 || pageMetaDirtyPages.size > 0) && (
                <span className="answer-key-dirty-badge">未保存: {dirtyIds.size + pageMetaDirtyPages.size}件</span>
              )}
              <button
                type="button"
                className="answer-key-gemini-btn"
                onClick={() =>
                  selectedDoc &&
                  generateAnswerMutation.mutate({
                    pdfFilename: selectedDoc.pdf_filename,
                    pageNumber: currentPage,
                    currentRows: rows,
                    currentItemDataKeys: itemDataKeys,
                    provider: answerProvider,
                  })
                }
                disabled={!selectedDoc || generateAnswerMutation.isPending}
                title="同一プロンプト(prompt_v3.txt)で選択したモデルで正解を生成"
              >
                {generateAnswerMutation.isPending
                  ? '生成中…'
                  : 'gpt geminiで正解を生成'}
              </button>
            </div>
            <div className="answer-key-provider-row">
              <label className="answer-key-provider-label">正解生成モデル（gpt gemini）:</label>
              <select
                className="answer-key-provider-select"
                value={answerProvider}
                onChange={(e) => setAnswerProvider(e.target.value as 'gemini' | 'gpt-5.2')}
                title="gpt gemini (Gemini / GPT 5.2). バージョンはサーバー側設定に従います。"
              >
                <option value="gemini">gpt gemini (Gemini)</option>
                <option value="gpt-5.2">gpt gemini (GPT 5.2)</option>
              </select>
            </div>
            {rightView === 'json' && (
              <div className="answer-key-json-view">
                <label className="answer-key-ocr-label">正解表JSON（編集後に適用）</label>
                <textarea
                  className="answer-key-json-textarea"
                  value={jsonEditText}
                  onChange={(e) => setJsonEditText(e.target.value)}
                  placeholder='{"page_role":"detail","items":[...]}'
                  spellCheck={false}
                />
                <button
                  type="button"
                  className="answer-key-btn answer-key-apply-json-btn"
                  onClick={applyJsonEdit}
                >
                  JSONを適用
                </button>
              </div>
            )}
            {rightView === 'template' && (
              <div className="answer-key-template-view">
                <p className="answer-key-template-desc">
                  先頭行のみ表示します。キー・値を直接編集し、キー追加/削除後に「残り行を生成」で同じキー構造の全行をLLMが生成します。
                </p>
                {!allDataLoaded && (
                  <p className="answer-key-template-loading">データ読み込み中…</p>
                )}
                {allDataLoaded && currentPageRows.length === 0 && templateEntries.length === 0 && (
                  <p className="answer-key-template-empty-hint">
                    このページに行がありません。「キー追加」でキーを入力した後「残り行を生成」を押すと、LLMが全行を生成します。
                  </p>
                )}
                <div className="answer-key-template-entries">
                  {templateEntries.map((entry) => (
                    <div key={entry.id} className="answer-key-template-row">
                      <input
                        type="text"
                        className="answer-key-template-key"
                        value={entry.key}
                        onChange={(e) => updateTemplateEntry(entry.id, 'key', e.target.value)}
                        placeholder="キー"
                      />
                      <input
                        type="text"
                        className="answer-key-template-value"
                        value={entry.value}
                        onChange={(e) => updateTemplateEntry(entry.id, 'value', e.target.value)}
                        placeholder="値"
                      />
                      <button
                        type="button"
                        className="answer-key-template-remove"
                        onClick={() => removeTemplateEntry(entry.id)}
                        title="削除"
                      >
                        ×
                      </button>
                    </div>
                  ))}
                </div>
                <button type="button" className="answer-key-btn answer-key-template-add" onClick={addTemplateEntry}>
                  キー追加
                </button>
                <button
                  type="button"
                  className="answer-key-btn answer-key-gemini-btn"
                  onClick={() => generateFromTemplateMutation.mutate()}
                  disabled={!selectedDoc || generateFromTemplateMutation.isPending || templateEntries.every((e) => !(e.key ?? '').trim())}
                  title="この行をテンプレートにし、残りの行をLLMが生成します"
                >
                  {generateFromTemplateMutation.isPending ? '生成中…' : '残り行を生成'}
                </button>
              </div>
            )}
            {rightView === 'kv' && !allDataLoaded && <p className="answer-key-loading">データ読み込み中…</p>}
            {rightView === 'kv' && allDataLoaded && rows.length === 0 && currentPageMetaFields.length === 0 && (
              <p className="answer-key-empty">このページにはpage_metaも行もありません。</p>
            )}
            {rightView === 'kv' && allDataLoaded && (rows.length > 0 || currentPageMetaFields.length > 0 || itemDataKeys.length > 0) && (
              <div className="answer-key-kv-scroll">
                <div className="answer-key-page-label">p.{currentPage}</div>
                <div className={`answer-key-meta-block ${pageMetaDirtyPages.has(currentPage) ? 'answer-key-kv-dirty' : ''}`}>
                  <div className="answer-key-meta-section-label">page_meta（キー・値の直接編集）</div>
                  {groupedPageMetaFields.map(({ group, sub, fields }, groupIdx) => (
                    <div key={`page-meta-group-${currentPage}-${groupIdx}-${group}-${sub ?? 'root'}`} className="answer-key-meta-group">
                      <div className="answer-key-meta-group-label">
                        {group === 'root' ? 'その他' : group}
                        {sub ? ` / ${sub}` : ''}
                      </div>
                      {fields.map(({ key: metaKey, value }, metaIdx) => {
                    const lastDot = metaKey.lastIndexOf('.')
                    const basePrefix = lastDot >= 0 ? metaKey.slice(0, lastDot + 1) : ''
                    const leafKey = lastDot >= 0 ? metaKey.slice(lastDot + 1) : metaKey
                    return (
                      <div
                            key={`page-meta-${currentPage}-${metaIdx}-${metaKey}`}
                        className="answer-key-kv-row answer-key-kv-row-with-delete"
                      >
                        <input
                          type="text"
                          className="answer-key-kv-key-input"
                          value={leafKey}
                          onChange={(e) => {
                            const leafNext = e.target.value
                            const nextFull = (leafNext ?? '').trim()
                              ? `${basePrefix}${leafNext.trim()}`
                              : ''
                            setPageMetaFlatEdits((prev) => {
                              const page = prev[currentPage] ?? {}
                              if (nextFull === metaKey) return prev
                              const p = { ...page }
                              delete p[metaKey]
                              if (nextFull) p[nextFull] = value
                              return { ...prev, [currentPage]: p }
                            })
                            setPageMetaDirtyPages((d) => new Set(d).add(currentPage))
                          }}
                          placeholder="キー"
                        />
                        <input
                          type="text"
                          className="answer-key-kv-input"
                          value={value}
                          onChange={(e) => onPageMetaChange(metaKey, e.target.value)}
                          placeholder="値"
                        />
                        <button
                          type="button"
                          className="answer-key-kv-delete-btn"
                          onClick={() => onPageMetaKeyRemove(metaKey)}
                          title="このキーを削除"
                            >
                              ×
                            </button>
                          </div>
                        )
                      })}
                    </div>
                  ))}
                  <div className="answer-key-kv-row answer-key-kv-row-with-delete answer-key-add-row">
                    <input
                      type="text"
                      className="answer-key-kv-key-input"
                      value={newPageMetaKey}
                      onChange={(e) => setNewPageMetaKey(e.target.value)}
                      placeholder="新規キー"
                    />
                    <input
                      type="text"
                      className="answer-key-kv-input"
                      value={newPageMetaValue}
                      onChange={(e) => setNewPageMetaValue(e.target.value)}
                      placeholder="値"
                    />
                    <button
                      type="button"
                      className="answer-key-btn answer-key-kv-add-btn"
                      onClick={() => {
                        onPageMetaKeyAdd(newPageMetaKey, newPageMetaValue)
                        setNewPageMetaKey('')
                        setNewPageMetaValue('')
                      }}
                      disabled={!newPageMetaKey.trim()}
                    >
                      キー追加
                    </button>
                  </div>
                </div>
                {currentPageRows.length === 0 ? (
                  currentPageMetaFields.length > 0 ? null : <p className="answer-key-empty">このページには行がありません。</p>
                ) : (
                  <>
                    <div className="answer-key-meta-section-label">items（キー・値の直接編集）</div>
                    {currentPageRows.map((row) => (
                      <div
                        key={row.item_id}
                        className={`answer-key-kv-block ${dirtyIds.has(row.item_id) ? 'answer-key-kv-dirty' : ''}`}
                      >
                        {displayKeys.map((key) => {
                            const label = KEY_LABELS[key] ?? key
                            const val = row[key]
                            const isArray = Array.isArray(val)
                            const isObject = !isArray && val !== null && typeof val === 'object'
                            const isComplex = isArray || isObject
                            const strVal =
                              val == null
                                ? ''
                                : isArray
                                  ? `配列(${val.length}件)`
                                  : isObject
                                    ? '[オブジェクト]'
                                    : String(val)
                            const isDataKey = dataKeysForDisplay.includes(key)
                            const isEditable = editableKeys.has(key)
                            const keyDisplay =
                              editingKeyName === key
                                ? editingKeyValue
                                : (KEY_LABELS[key] ?? key)
                            return (
                              <div key={key} className="answer-key-kv-row answer-key-kv-row-with-delete">
                                {isDataKey ? (
                                  <input
                                    type="text"
                                    className="answer-key-kv-key-input"
                                    value={editingKeyName === key ? editingKeyValue : keyDisplay}
                                    onChange={(e) => {
                                      setEditingKeyName(key)
                                      setEditingKeyValue(e.target.value)
                                    }}
                                    onBlur={() => {
                                      const n = editingKeyValue.trim()
                                      if (n && n !== key) onRenameKey(key, n)
                                      setEditingKeyName(null)
                                    }}
                                    onKeyDown={(e) => {
                                      if (e.key === 'Enter') {
                                        const n = editingKeyValue.trim()
                                        if (n && n !== key) onRenameKey(key, n)
                                        setEditingKeyName(null)
                                      }
                                      if (e.key === 'Escape') setEditingKeyName(null)
                                    }}
                                    onFocus={() => {
                                      setEditingKeyName(key)
                                      setEditingKeyValue(keyDisplay)
                                    }}
                                    placeholder="キー"
                                  />
                                ) : (
                                  <span className="answer-key-kv-key">{label}</span>
                                )}
                                {isEditable ? (
                                  <input
                                    type="text"
                                    className="answer-key-kv-input"
                                    value={isComplex ? '' : strVal}
                                    onChange={(e) =>
                                      onValueChange(
                                        row.item_id,
                                        key,
                                        e.target.value === '' ? null : e.target.value
                                      )
                                    }
                                    placeholder={isComplex ? strVal : undefined}
                                  />
                                ) : (
                                  <span className="answer-key-kv-val">{strVal || '—'}</span>
                                )}
                                {isDataKey ? (
                                  <button
                                    type="button"
                                    className="answer-key-kv-delete-btn"
                                    onClick={() => onRemoveKey(key)}
                                    title="このキーを削除"
                                  >
                                    ×
                                  </button>
                                ) : (
                                  <span className="answer-key-kv-delete-placeholder" />
                                )}
                              </div>
                            )
                          })}
                      </div>
                    ))}
                    <div className="answer-key-kv-row answer-key-add-row answer-key-items-add-key">
                      <input
                        type="text"
                        className="answer-key-kv-key-input"
                        value={newKeyInput}
                        onChange={(e) => setNewKeyInput(e.target.value)}
                        placeholder="새 키（모든 행에 추가）"
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            onAddKey(newKeyInput)
                            setNewKeyInput('')
                          }
                        }}
                      />
                      <span className="answer-key-kv-add-hint">모든 행에 추가</span>
                      <button
                        type="button"
                        className="answer-key-btn answer-key-kv-add-btn"
                        onClick={() => {
                          onAddKey(newKeyInput)
                          setNewKeyInput('')
                        }}
                        disabled={!newKeyInput.trim()}
                      >
                        キー追加
                      </button>
                    </div>
                  </>
                )}
              </div>
            )}
            <div className="answer-key-actions">
              <button
                type="button"
                className="answer-key-btn answer-key-btn-secondary"
                onClick={handleSaveGrid}
                disabled={(dirtyIds.size === 0 && pageMetaDirtyPages.size === 0) || saveStatus === 'saving' || saveStatus === 'building'}
              >
                変更保存
              </button>
              <button
                type="button"
                className="answer-key-btn answer-key-btn-primary"
                onClick={handleSaveAsAnswerKey}
                disabled={saveStatus === 'saving' || saveStatus === 'building'}
              >
                {saveStatus === 'building' ? '登録中…' : '正解表として保存（ベクターDBに登録）'}
              </button>
            </div>
            {saveMessage && (
              <p className={`answer-key-status ${saveStatus === 'error' ? 'answer-key-status-error' : ''}`}>
                {saveMessage}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
