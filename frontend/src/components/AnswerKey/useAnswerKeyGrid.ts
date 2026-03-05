/**
 * 解答作成タブ: グリッド・page_meta の状態とサーバ同期、編集ハンドラを集約
 * AnswerKeyTab の行数削減のため抽出
 */
import { useState, useMemo, useCallback, useEffect, useRef } from 'react'
import type { GridRow } from './answerKeyTabConstants'
import {
  SYSTEM_ROW_KEYS,
  HIDDEN_ROW_KEYS,
  ANSWER_KEY_HIDDEN_KEYS,
  TYPE_OPTIONS_BASE,
  PAGE_META_DELETE_SENTINEL,
} from './answerKeyTabConstants'

const PAGE_LEVEL_EXCLUDE_KEYS = new Set(['items', 'page_number', 'page_role'])

export interface UseAnswerKeyGridParams {
  selectedDoc: { pdf_filename: string; total_pages: number } | null
  currentPage: number
  /** ブリッジで「この1ページのみ」表示時、その 실제 페이지 번호. 없으면 currentPage 사용 */
  effectivePageNumber?: number
  answerJsonFromDb: { pages: Array<Record<string, unknown>> } | null | undefined
  pageMetaQueries: Array<{ data?: unknown; isError?: boolean }>
  pageItemsQueries: Array<{ data?: unknown; dataUpdatedAt?: number }>
  allDataLoaded: boolean
}

export function useAnswerKeyGrid({
  selectedDoc,
  currentPage,
  effectivePageNumber,
  answerJsonFromDb,
  pageMetaQueries,
  pageItemsQueries,
  allDataLoaded,
}: UseAnswerKeyGridParams) {
  const skipNextSyncRef = useRef(false)
  const rowsRef = useRef<GridRow[]>([])

  const [rows, setRows] = useState<GridRow[]>([])
  const [itemDataKeys, setItemDataKeys] = useState<string[]>([])
  const [dirtyIds, setDirtyIds] = useState<Set<number>>(new Set())
  const [pageMetaFlatEdits, setPageMetaFlatEdits] = useState<Record<number, Record<string, string>>>({})
  const [pageMetaDirtyPages, setPageMetaDirtyPages] = useState<Set<number>>(new Set())
  const [pageRoleEdits, setPageRoleEdits] = useState<Record<number, string>>({})
  const [editingKeyName, setEditingKeyName] = useState<string | null>(null)
  const [editingKeyValue, setEditingKeyValue] = useState('')
  const [editingPageMetaKey, setEditingPageMetaKey] = useState<string | null>(null)
  const [editingPageMetaKeyValue, setEditingPageMetaKeyValue] = useState('')
  const [newPageMetaKey, setNewPageMetaKey] = useState('')
  const [newPageMetaValue, setNewPageMetaValue] = useState('')
  const [newKeyInput, setNewKeyInput] = useState('')

  // answer-json 由来で rows 同期
  useEffect(() => {
    if (!answerJsonFromDb?.pages?.length) return
    if (skipNextSyncRef.current) {
      skipNextSyncRef.current = false
      return
    }
    if (dirtyIds.size > 0 || pageMetaDirtyPages.size > 0) return
    const combined: GridRow[] = []
    const keysOrder: string[] = []
    const keysSet = new Set<string>()
    answerJsonFromDb.pages.forEach((page: Record<string, unknown>) => {
      const pageNum = Number(page.page_number) || 0
      const items = Array.isArray(page.items) ? page.items : []
      items.forEach((item: unknown, idx: number) => {
        const it = item as Record<string, unknown>
        const itemData = it?.item_data ?? it
        const row: GridRow = {
          item_id: pageNum * 1000 + idx,
          page_number: pageNum,
          item_order: idx + 1,
          version: 1,
        }
        if (itemData && typeof itemData === 'object') {
          Object.keys(itemData as object).forEach((k) => {
            if (SYSTEM_ROW_KEYS.includes(k)) return
            ;(row as Record<string, unknown>)[k] = (itemData as Record<string, unknown>)[k]
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
  }, [answerJsonFromDb, dirtyIds.size, pageMetaDirtyPages.size])

  const pageItemsDataUpdatedAt = pageItemsQueries.map((q) => q.dataUpdatedAt ?? 0).join(',')
  useEffect(() => {
    if (!selectedDoc || !allDataLoaded || answerJsonFromDb != null) return
    if (skipNextSyncRef.current) {
      skipNextSyncRef.current = false
      return
    }
    if (dirtyIds.size > 0 || pageMetaDirtyPages.size > 0) return
    const combined: GridRow[] = []
    let serverKeys: string[] = []
    const keysFromItems = new Set<string>()
    for (let p = 0; p < pageItemsQueries.length; p++) {
      const res = pageItemsQueries[p].data as { items?: { item_id: number; item_order: number; version?: number; item_data?: Record<string, unknown> }[]; item_data_keys?: string[] } | undefined
      if (!res?.items) continue
      if (res.item_data_keys?.length) serverKeys = res.item_data_keys
      const pageNum = effectivePageNumber != null ? effectivePageNumber : p + 1
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
            ;(row as Record<string, unknown>)[k] = item.item_data![k]
            keysFromItems.add(k)
          })
        }
        combined.push(row)
      })
    }
    combined.sort((a, b) => a.page_number - b.page_number || Number(a.item_order ?? 0) - Number(b.item_order ?? 0) || a.item_id - b.item_id)
    setRows(combined)
    const mergedKeys =
      serverKeys.length > 0
        ? [...serverKeys, ...[...keysFromItems].filter((k) => !serverKeys.includes(k))]
        : [...keysFromItems]
    if (mergedKeys.length) setItemDataKeys(mergedKeys)
    setDirtyIds(new Set())
    setPageMetaFlatEdits({})
    setPageMetaDirtyPages(new Set())
  }, [selectedDoc, allDataLoaded, pageItemsDataUpdatedAt, dirtyIds.size, pageMetaDirtyPages.size, effectivePageNumber])

  useEffect(() => {
    rowsRef.current = rows
  }, [rows])

  const pageNumberForCurrentView = effectivePageNumber ?? currentPage
  const currentPageRows = useMemo(() => {
    const filtered = rows.filter((r) => r.page_number === pageNumberForCurrentView)
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
  }, [rows, pageNumberForCurrentView])

  const dataKeysForDisplay = useMemo(() => {
    const fromCurrentPage = new Set<string>()
    currentPageRows.forEach((r) => {
      Object.keys(r).forEach((k) => {
        if (!SYSTEM_ROW_KEYS.includes(k) && !ANSWER_KEY_HIDDEN_KEYS.has(k)) fromCurrentPage.add(k)
      })
    })
    const keysList = Array.from(fromCurrentPage)
    if (itemDataKeys.length) {
      const ordered = itemDataKeys.filter((k) => fromCurrentPage.has(k) && !ANSWER_KEY_HIDDEN_KEYS.has(k))
      const extras = keysList.filter((k) => !itemDataKeys.includes(k))
      return [...ordered, ...extras]
    }
    return keysList
  }, [itemDataKeys, currentPageRows])

  const displayKeys = useMemo(() => {
    const head = ['page_number', 'item_order']
    const dataKeySet = new Set<string>()
    currentPageRows.forEach((r) =>
      Object.keys(r).forEach((k) => {
        if (!HIDDEN_ROW_KEYS.has(k) && !ANSWER_KEY_HIDDEN_KEYS.has(k)) dataKeySet.add(k)
      })
    )
    const ordered = itemDataKeys.length
      ? [...itemDataKeys.filter((k) => dataKeySet.has(k)), ...[...dataKeySet].filter((k) => !itemDataKeys.includes(k))]
      : [...dataKeySet]
    return [...head, ...ordered]
  }, [currentPageRows, itemDataKeys])

  const editableKeys = useMemo(() => new Set(['得意先', '商品名', ...dataKeysForDisplay]), [dataKeysForDisplay])

  const typeOptions = useMemo(() => {
    const fromRows = new Set<string>()
    rows.forEach((r) => {
      const v = (r as Record<string, unknown>)['タイプ']
      if (v != null && String(v).trim() !== '') fromRows.add(String(v).trim())
    })
    const baseValues = new Set(TYPE_OPTIONS_BASE.map((o) => o.value).filter(Boolean))
    const extra = [...fromRows].filter((v) => !baseValues.has(v)).sort()
    return [...TYPE_OPTIONS_BASE, ...extra.map((value) => ({ value, label: value }))]
  }, [rows])

  const onValueChange = useCallback((itemId: number, key: string, value: string | number | boolean | null) => {
    setRows((prev) => {
      const next = prev.map((r) => (r.item_id !== itemId ? r : { ...r, [key]: value }))
      rowsRef.current = next
      return next
    })
    setDirtyIds((d) => new Set(d).add(itemId))
  }, [])

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

  const flattenPageMeta = useCallback((obj: unknown, prefix = ''): Array<{ key: string; value: string }> => {
    const result: Array<{ key: string; value: string }> = []
    if (obj === null || obj === undefined) return result
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
    if (typeof obj === 'object') {
      Object.keys(obj as object).forEach((k) => {
        const newKey = prefix ? `${prefix}.${k}` : k
        const v = (obj as Record<string, unknown>)[k]
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

  const setNestedByPath = useCallback((obj: Record<string, unknown>, path: string, value: string) => {
    const parts = path.split(/\.|\[|\]/).filter(Boolean)
    let cur: unknown = obj
    for (let i = 0; i < parts.length - 1; i++) {
      const p = parts[i]
      const nextKey = parts[i + 1]
      const isArrayIndex = /^\d+$/.test(nextKey)
      if (!(p in (cur as object))) (cur as Record<string, unknown>)[p] = isArrayIndex ? [] : {}
      cur = (cur as Record<string, unknown>)[p]
    }
    if (parts.length) (cur as Record<string, unknown>)[parts[parts.length - 1]] = value
  }, [])

  const deleteNestedByPath = useCallback((obj: Record<string, unknown>, path: string) => {
    const parts = path.split(/\.|\[|\]/).filter(Boolean)
    if (parts.length === 0) return
    let cur: unknown = obj
    for (let i = 0; i < parts.length - 1; i++) {
      const p = parts[i]
      if (!(p in (cur as object))) return
      cur = (cur as Record<string, unknown>)[p]
      if (cur == null || typeof cur !== 'object') return
    }
    delete (cur as Record<string, unknown>)[parts[parts.length - 1]]
  }, [])

  const currentPageMetaData = useMemo((): { page_role: string | null; page_meta: Record<string, unknown> } | null => {
    if (!selectedDoc) return null
    if (answerJsonFromDb?.pages) {
      const page = answerJsonFromDb.pages.find((p: Record<string, unknown>) => Number(p.page_number) === currentPage)
      if (!page) return null
      let page_meta: Record<string, unknown> =
        page.page_meta != null && typeof page.page_meta === 'object' && !Array.isArray(page.page_meta)
          ? (page.page_meta as Record<string, unknown>)
          : {}
      if (Object.keys(page_meta).length === 0 && typeof page === 'object') {
        page_meta = {}
        Object.keys(page).forEach((k) => {
          if (!PAGE_LEVEL_EXCLUDE_KEYS.has(k)) page_meta![k] = (page as Record<string, unknown>)[k]
        })
      }
      const pr = page.page_role
      return { page_role: pr != null && typeof pr === 'string' ? pr : null, page_meta }
    }
    const q = pageMetaQueries[currentPage - 1]
    if (!q?.data) return null
    const d = q.data as { page_role?: string | null; page_meta?: Record<string, unknown> }
    const pr = d.page_role
    return { page_role: pr != null && typeof pr === 'string' ? pr : null, page_meta: d.page_meta ?? {} }
  }, [selectedDoc, currentPage, answerJsonFromDb, pageMetaQueries])

  const kuMapping = useMemo(() => {
    const meta = currentPageMetaData?.page_meta
    const raw = meta?.区_mapping ?? (meta as Record<string, unknown>)?.['区_mapping']
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
    const entries = Object.entries(raw as Record<string, string>).filter(([, v]) => v != null && typeof v === 'string')
    if (entries.length === 0) return null
    return Object.fromEntries(entries.map(([k, v]) => [String(k).trim(), v]))
  }, [currentPageMetaData?.page_meta])

  const getKuLabel = useCallback((value: unknown): string | null => {
    if (!kuMapping || value == null) return null
    const s = String(value).trim()
    if (!s) return null
    return (kuMapping as Record<string, string>)[s] ?? (kuMapping as Record<string, string>)[String(Number(s))] ?? null
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

  const groupedPageMetaFields = useMemo(() => {
    type Field = { key: string; value: string }
    type SubMap = Record<string, Field[]>
    const byGroup: Record<string, SubMap> = {}
    currentPageMetaFields.forEach((f) => {
      const tokens = f.key.split('.')
      const hasHierarchy = tokens.length > 1
      const group = hasHierarchy ? tokens[0] || 'root' : 'root'
      const sub = tokens.length > 2 ? tokens[1] : ''
      const subKey = sub || '__no_sub__'
      if (!byGroup[group]) byGroup[group] = {}
      if (!byGroup[group][subKey]) byGroup[group][subKey] = []
      byGroup[group][subKey].push(f)
    })
    const preferredOrder = ['document_meta', 'party', 'payment', 'totals', 'root']
    const result: Array<{ group: string; sub: string | null; fields: Field[] }> = []
    const pushGroup = (g: string) => {
      const subs = byGroup[g]
      if (!subs) return
      Object.keys(subs).sort().forEach((subKey) => {
        result.push({
          group: g,
          sub: subKey === '__no_sub__' ? null : subKey,
          fields: subs[subKey],
        })
      })
    }
    preferredOrder.forEach(pushGroup)
    Object.keys(byGroup).filter((g) => !preferredOrder.includes(g)).sort().forEach(pushGroup)
    return result
  }, [currentPageMetaFields])

  const onPageMetaChange = useCallback((flatKey: string, value: string) => {
    setPageMetaFlatEdits((prev) => ({
      ...prev,
      [currentPage]: { ...(prev[currentPage] ?? {}), [flatKey]: value },
    }))
    setPageMetaDirtyPages((d) => new Set(d).add(currentPage))
  }, [currentPage])

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

  const onPageMetaGroupRemove = useCallback(
    (_group: string, _sub: string | null, fields: Array<{ key: string; value: string }>) => {
      setPageMetaFlatEdits((prev) => {
        const page = { ...(prev[currentPage] ?? {}) }
        fields.forEach((f) => { page[f.key] = PAGE_META_DELETE_SENTINEL })
        return { ...prev, [currentPage]: page }
      })
      setPageMetaDirtyPages((d) => new Set(d).add(currentPage))
    },
    [currentPage]
  )

  const onPageMetaKeyAdd = useCallback((newKey: string, newValue: string) => {
    const raw = (newKey ?? '').trim()
    if (!raw) return
    const hasDocumentRef =
      (currentPageMetaData?.page_meta && typeof currentPageMetaData.page_meta === 'object' && currentPageMetaData.page_meta !== null && 'document_ref' in currentPageMetaData.page_meta) ||
      currentPageMetaFields.some((f) => f.key.startsWith('document_ref.'))
    const k = hasDocumentRef && !raw.includes('.') && !raw.startsWith('[') ? `document_ref.${raw}` : raw
    setPageMetaFlatEdits((prev) => ({
      ...prev,
      [currentPage]: { ...(prev[currentPage] ?? {}), [k]: newValue ?? '' },
    }))
    setPageMetaDirtyPages((d) => new Set(d).add(currentPage))
  }, [currentPage, currentPageMetaData, currentPageMetaFields])

  const buildPageMetaFromEdits = useCallback((pageNum: number): Record<string, unknown> => {
    const base = (pageMetaQueries[pageNum - 1]?.data as { page_meta?: Record<string, unknown> } | undefined)?.page_meta ?? {}
    const edits = pageMetaFlatEdits[pageNum] ?? {}
    if (Object.keys(edits).length === 0) return base
    const merged = JSON.parse(JSON.stringify(base))
    Object.entries(edits).forEach(([path, value]) => {
      if (value === PAGE_META_DELETE_SENTINEL) {
        deleteNestedByPath(merged, path)
      } else {
        setNestedByPath(merged, path, value)
      }
    })
    return merged
  }, [pageMetaQueries, pageMetaFlatEdits, setNestedByPath, deleteNestedByPath])

  return {
    skipNextSyncRef,
    rowsRef,
    rows,
    setRows,
    itemDataKeys,
    setItemDataKeys,
    dirtyIds,
    setDirtyIds,
    pageMetaFlatEdits,
    setPageMetaFlatEdits,
    pageMetaDirtyPages,
    setPageMetaDirtyPages,
    pageRoleEdits,
    setPageRoleEdits,
    editingKeyName,
    setEditingKeyName,
    editingKeyValue,
    setEditingKeyValue,
    editingPageMetaKey,
    setEditingPageMetaKey,
    editingPageMetaKeyValue,
    setEditingPageMetaKeyValue,
    newPageMetaKey,
    setNewPageMetaKey,
    newPageMetaValue,
    setNewPageMetaValue,
    newKeyInput,
    setNewKeyInput,
    currentPageRows,
    dataKeysForDisplay,
    displayKeys,
    editableKeys,
    typeOptions,
    currentPageMetaData,
    currentPageMetaFields,
    groupedPageMetaFields,
    getKuLabel,
    onValueChange,
    onAddKey,
    onRemoveKey,
    onRenameKey,
    onPageMetaChange,
    onPageMetaKeyRenameFull,
    onPageMetaKeyRemove,
    onPageMetaGroupRemove,
    onPageMetaKeyAdd,
    buildPageMetaFromEdits,
    setNestedByPath,
    deleteNestedByPath,
  }
}
