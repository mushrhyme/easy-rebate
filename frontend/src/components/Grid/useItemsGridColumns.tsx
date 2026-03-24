/**
 * 그리드 컬럼 정의 + 행 높이 계산. ItemsGridRdg에서 분리.
 */
import { useMemo } from 'react'
import type { Column } from 'react-data-grid'
import { CONDITION_AMOUNT_KEYS } from './types'
import { parseCellNum } from './utils'
import type { GridRow } from './types'
import { ReviewCheckboxCell } from './ReviewCheckboxCell'
import { ActionCellWithMenu } from './ActionCellWithMenu'

/** API items 요소 형태 (item_data, item_id 등) */
interface ApiItem {
  item_id: number
  item_order: number
  item_data?: Record<string, unknown>
}

export interface UseItemsGridColumnsParams {
  items: ApiItem[]
  itemDataKeysFromApi: string[] | null
  containerWidth: number
  editingItemIds: Set<number>
  hoveredRowId: number | null
  setHoveredRowId: (id: number | null) => void
  setReviewTooltip: (t: { text: string; x: number; y: number } | null) => void
  handleCellChange: (itemId: number, field: string, value: unknown) => void
  handleCheckboxUpdate: (itemId: number, field: 'first_review_checked' | 'second_review_checked', checked: boolean) => Promise<void>
  handleAddRow: (afterItemId?: number) => Promise<void>
  handleDeleteRow: (itemId: number) => Promise<void>
  isItemLocked: (itemId: number) => boolean
  getLockedBy: (itemId: number) => string | null
  sessionId: string | null
  getKuLabel: (value: unknown) => string | null
  createItemPending: boolean
  deleteItemPending: boolean
  /** 액션 메뉴에서 "単価" 클릭 시 해당 행으로 단가 후보 모달 열기 */
  onOpenUnitPriceModal: (row: GridRow) => void
  /** 액션 메뉴에서 "添付" 클릭 시 해당 행 item_id로 첨부 모달 열기 */
  onOpenAttachments?: (itemId: number) => void
  /** true면 편집·추가/삭제·체크박스 비활성 */
  readOnly?: boolean
  /** detail일 때만 タイプ/受注先コード/小売先コード/商品コード/仕切/本部長/NET 컬럼 표시 */
  pageRole?: string | null
  /** 양식 02: 最終金額 を 金額 の直後に表示 */
  formType?: string | null
}

const CHAR_PX = 11
const PADDING_PX = 18
const COL_WIDTH_MIN = 78
const COL_WIDTH_MAX = 280
const FIXED_ROW_HEIGHT_KEYS = new Set(['item_order', 'actions', 'first_review_checked', 'second_review_checked', 'タイプ', 'net'])
const PX_PER_CHAR = 10
const LINE_HEIGHT_PX = 22
const CELL_PADDING_V = 12
const ROW_HEIGHT_BUFFER = 8
const MIN_ROW_HEIGHT = 36
const MAX_CHARS_PER_LINE = 8

export function useItemsGridColumns(params: UseItemsGridColumnsParams): {
  columns: Column<GridRow>[]
  getRowHeight: (row: GridRow) => number
} {
  const {
    items,
    itemDataKeysFromApi,
    containerWidth,
    editingItemIds,
    hoveredRowId,
    setHoveredRowId,
    setReviewTooltip,
    handleCellChange,
    handleCheckboxUpdate,
    handleAddRow,
    handleDeleteRow,
    isItemLocked,
    getLockedBy,
    sessionId,
    getKuLabel,
    createItemPending,
    deleteItemPending,
    onOpenUnitPriceModal,
    onOpenAttachments,
    readOnly = false,
    pageRole = null,
    formType = null,
  } = params

  const hasItems = items.length > 0
  const isDetailPage = pageRole === 'detail'

  return useMemo(() => {
    const formTypeNorm = String(formType ?? '').trim().replace(/^0+/, '')
    let orderedKeys: string[] = []
    if (hasItems) {
      const firstItem = items[0]
      const keysInDb = new Set<string>()
      items.forEach((item) => {
        if (item.item_data) {
          Object.keys(item.item_data).forEach((key) => keysInDb.add(key))
        }
      })
      // 첫 행 item_data의 키 삽입 순서(파싱·DB 저장 순)를 우선 — API item_data_keys(RAG/메타)는 보조만
      const rawFromItem = firstItem.item_data ? Object.keys(firstItem.item_data) : []
      const itemDataKeys =
        rawFromItem.length > 0
          ? rawFromItem
          : itemDataKeysFromApi?.length
            ? [...itemDataKeysFromApi]
            : []
      const normalizeKey = (key: string): string => {
        if ((key === '得意先名' || key === '得意先') && keysInDb.has('得意先')) return '得意先'
        if ((key === '得意先名' || key === '得意先') && keysInDb.has('得意先名')) return '得意先名'
        return key
      }
      const normalizedItemDataKeys = itemDataKeys.map(normalizeKey)
      const orderedFromApi = normalizedItemDataKeys.filter((k) => keysInDb.has(k))
      const extraKeys = Array.from(keysInDb).filter((k) => !normalizedItemDataKeys.includes(k))
      const reviewHiddenKeys = new Set([
        'first_review_reviewed_at',
        'first_review_reviewed_by',
        'second_review_reviewed_at',
        'second_review_reviewed_by',
      ])
      orderedKeys = [...orderedFromApi, ...extraKeys].filter((k) => !reviewHiddenKeys.has(k))
      // 양식 02: 金額 → 金額2 → 最終金額（金額2 컬럼은 金額 があれば常に表示）
      if (formTypeNorm === '2' && keysInDb.has('金額')) {
        const A1 = '金額'
        const A2 = '金額2'
        const FN = '最終金額'
        const rest = orderedKeys.filter((k) => k !== A1 && k !== A2 && k !== FN)
        const oldIdx = orderedKeys.indexOf(A1)
        if (oldIdx >= 0) {
          const countBefore = orderedKeys.slice(0, oldIdx).filter((k) => k !== A1 && k !== A2 && k !== FN).length
          orderedKeys = [...rest.slice(0, countBefore), A1, A2, FN, ...rest.slice(countBefore)]
        } else {
          orderedKeys = [...rest, A1, A2, FN]
        }
      }
    }

    const calculateColumnWidth = (key: string, name: string): number => {
      const headerWidth = name.length * CHAR_PX + PADDING_PX
      let maxDataLength = 0
      if (hasItems) {
        items.forEach((item) => {
          const value = item.item_data?.[key]
          if (value != null) {
            const len = String(value).length
            if (len > maxDataLength) maxDataLength = len
          }
        })
      }
      const dataWidth = maxDataLength * CHAR_PX + PADDING_PX
      return Math.min(Math.max(headerWidth, dataWidth, COL_WIDTH_MIN), COL_WIDTH_MAX)
    }

    const getColWidth = (col: Column<GridRow>): number => {
      const w = col.width
      if (typeof w === 'number') return w
      if (typeof w === 'string') return parseInt(w, 10) || COL_WIDTH_MIN
      return COL_WIDTH_MIN
    }

    const cols: Column<GridRow>[] = [
      {
        key: 'item_order',
        name: '行',
        width: 34,
        minWidth: 34,
        frozen: true,
        resizable: false,
        renderCell: ({ row }) => (
          <div className="rdg-cell-no" title={`No. ${row.item_order}`}>
            {row.item_order}
          </div>
        ),
      },
    ]

    if (hasItems) {
      cols.push({
        key: 'actions',
        name: '編',
        width: 34,
        minWidth: 34,
        frozen: true,
        resizable: false,
        renderCell: ({ row }) => {
          if (readOnly) return <span className="rdg-cell-no">—</span>
          const itemId = row.item_id
          return (
            <ActionCellWithMenu
              isHovered={hoveredRowId === itemId}
              isEditing={editingItemIds.has(itemId)}
              isLockedByOthers={isItemLocked(itemId) && getLockedBy(itemId) !== sessionId}
              lockedBy={getLockedBy(itemId)}
              onMouseEnter={() => setHoveredRowId(itemId)}
              onMouseLeave={() => setHoveredRowId(null)}
              onAdd={() => handleAddRow(itemId)}
              onDelete={() => handleDeleteRow(itemId)}
              onUnitPrice={() => onOpenUnitPriceModal(row)}
              onAttachments={onOpenAttachments ? () => onOpenAttachments(itemId) : undefined}
              createItemPending={createItemPending}
              deleteItemPending={deleteItemPending}
            />
          )
        },
      })

      cols.push({
        key: 'first_review_checked',
        name: '1次',
        width: 40,
        minWidth: 40,
        frozen: true,
        resizable: false,
        editable: false,
        renderCell: ({ row }) => (
          <ReviewCheckboxCell
            row={row}
            field="first_review_checked"
            label="1次"
            onToggle={handleCheckboxUpdate}
            onTooltip={(text, x, y) => setReviewTooltip({ text, x, y })}
            onTooltipClear={() => setReviewTooltip(null)}
            disabled={readOnly}
          />
        ),
      })
      cols.push({
        key: 'second_review_checked',
        name: '2次',
        width: 40,
        minWidth: 40,
        frozen: true,
        resizable: false,
        editable: false,
        renderCell: ({ row }) => (
          <ReviewCheckboxCell
            row={row}
            field="second_review_checked"
            label="2次"
            onToggle={handleCheckboxUpdate}
            onTooltip={(text, x, y) => setReviewTooltip({ text, x, y })}
            onTooltipClear={() => setReviewTooltip(null)}
            disabled={readOnly}
          />
        ),
      })

      // detail 페이지 한정: タイプ, 受注先コード, 小売先コード, 商品コード, 仕切, 本部長, NET (summary/cover 등에서는 매핑 불필요·혼선 방지)
      if (isDetailPage) {
        cols.push({
          key: 'タイプ',
          name: 'タイプ',
          width: 100,
          minWidth: 100,
          frozen: true,
          resizable: false,
          editable: false,
          renderCell: ({ row }) => {
            const raw = row['タイプ']
            const displayValue = raw != null && String(raw).trim() !== '' ? String(raw) : '条件'
            const isEditing = !readOnly && editingItemIds.has(row.item_id)
            if (isEditing) {
              const selectValue = raw != null && String(raw).trim() !== '' ? String(raw) : '条件'
              return (
                <select
                  value={selectValue}
                  onChange={(e) => {
                    handleCellChange(row.item_id, 'タイプ', e.target.value)
                  }}
                  style={{
                    width: '100%',
                    border: '1px solid #ccc',
                    padding: '4px',
                    borderRadius: '4px',
                    fontSize: '13px',
                  }}
                  onClick={(e) => e.stopPropagation()}
                >
                  <option value="条件">条件</option>
                  <option value="販促費8%">販促費8%</option>
                  <option value="販促費10%">販促費10%</option>
                  <option value="CF8%">CF8%</option>
                  <option value="CF10%">CF10%</option>
                  <option value="非課税">非課税</option>
                  <option value="消費税">消費税</option>
                </select>
              )
            }
            return <span>{displayValue}</span>
          },
        })

        const conditionAmountKey = CONDITION_AMOUNT_KEYS.find((k) => orderedKeys.includes(k)) ?? null
        cols.push({
          key: '受注先コード',
          name: '受注先コード',
          width: 100,
          minWidth: 80,
          frozen: true,
          resizable: true,
          editable: false,
          renderCell: ({ row }) => {
            const v = row['受注先コード']
            return <span>{v != null && String(v).trim() !== '' ? String(v) : '—'}</span>
          },
        })
        cols.push({
          key: '小売先コード',
          name: '小売先コード',
          width: 100,
          minWidth: 80,
          frozen: true,
          resizable: true,
          editable: false,
          renderCell: ({ row }) => {
            const v = row['小売先コード']
            return <span>{v != null && String(v).trim() !== '' ? String(v) : '—'}</span>
          },
        })
        cols.push({
          key: '商品コード',
          name: '商品コード',
          width: 100,
          minWidth: 80,
          frozen: true,
          resizable: true,
          editable: false,
          renderCell: ({ row }) => {
            const v = row['商品コード']
            return <span>{v != null && String(v).trim() !== '' ? String(v) : '—'}</span>
          },
        })
        cols.push({
          key: '仕切',
          name: '仕切',
          width: 90,
          minWidth: 80,
          frozen: true,
          resizable: true,
          editable: false,
          renderCell: ({ row }) => {
            const v = row['仕切']
            const n = parseCellNum(v)
            return <span>{n != null ? Number(n).toLocaleString() : '—'}</span>
          },
        })
        cols.push({
          key: '本部長',
          name: '本部長',
          width: 90,
          minWidth: 80,
          frozen: true,
          resizable: true,
          editable: false,
          renderCell: ({ row }) => {
            const v = row['本部長']
            const n = parseCellNum(v)
            return <span>{n != null ? Number(n).toLocaleString() : '—'}</span>
          },
        })
        cols.push({
          key: 'net',
          name: 'NET',
          width: 90,
          minWidth: 90,
          frozen: true,
          resizable: true,
          editable: false,
          renderCell: ({ row }) => {
            const shikiriNum = parseCellNum(row['仕切'])
            if (shikiriNum == null) return <span>—</span>

            // 4번 유형(form_type=04): NET 비교는 반드시 未収条件 + 未収条件2(없으면 0)
            // 이 타입에는 '条件'이 없고, '対象数量又は金額'(예: "60個")은 parseCellNum 실패 가능.
            // 따라서 미수 키가 존재하면 그것을 우선 사용한다.
            const hasMishuKeys = orderedKeys.includes('未収条件') || orderedKeys.includes('未収条件2') || ('未収条件' in row)
            if (hasMishuKeys) {
              const misu1 = parseCellNum(row['未収条件'])
              const misu2 = parseCellNum(row['未収条件2'])
              if (misu1 == null) return <span>—</span>
              const condNum = misu1 + (misu2 ?? 0)
              return <span>{(shikiriNum - condNum).toLocaleString()}</span>
            }

            // 그 외 유형: 조건금액 후보(条件 / 対象数量又は金額 중 존재하는 키) 사용
            const condNum = conditionAmountKey != null ? parseCellNum(row[conditionAmountKey]) : null
            if (condNum == null) return <span>—</span>
            
            // FINET 01 + 数量単位=CS:
            // 仕切・本部長은 단가리스트 원본 그대로 유지.
            // NET 비교/표시는 条件을 入数로 나눈 단가 기준으로 계산.
            const unitRaw = String(row['数量単位'] ?? '').trim()
            const unitNorm = unitRaw.replace('\uFF23', 'C').replace('\uFF33', 'S').toUpperCase() // 全角ＣＳ→CS
            const irisuNum = parseCellNum(row['入数'])
            const condForNet =
              unitNorm === 'CS' && conditionAmountKey === '条件' && irisuNum != null && irisuNum > 0 ? condNum / irisuNum : condNum
            
            return <span>{(shikiriNum - condForNet).toLocaleString()}</span>
          },
        })
      }
    }

    if (hasItems) {
      for (const key of orderedKeys) {
        if (key === 'customer' || key === 'タイプ' || key === '受注先コード' || key === '小売先コード' || key === '商品コード' || key === '仕切' || key === '本部長') continue
        const firstValue = items[0]?.item_data?.[key]
        const isComplexType =
          firstValue != null && (typeof firstValue === 'object' || Array.isArray(firstValue))
        if (isComplexType) continue
        if (key === '最終金額') {
          const dataBasedWidth = calculateColumnWidth(key, key)
          cols.push({
            key,
            name: '最終金額',
            width: dataBasedWidth,
            minWidth: Math.max(dataBasedWidth, 100),
            resizable: true,
            editable: false,
            renderCell: ({ row }) => {
              const v = row[key]
              let n = parseCellNum(v)
              if (n == null && formTypeNorm === '2') {
                const r1 = row['金額']
                const r2 = row['金額2']
                const hasRaw =
                  (r1 != null && String(r1).trim() !== '') || (r2 != null && String(r2).trim() !== '')
                const a1 = parseCellNum(r1)
                const a2 = parseCellNum(r2)
                if (hasRaw || a1 != null || a2 != null) {
                  n = (a1 ?? 0) + (a2 ?? 0)
                }
              }
              if (n != null) return <span>{Number(n).toLocaleString()}</span>
              const s = String(v ?? '').trim()
              return <span>{s || '—'}</span>
            },
          })
          continue
        }
        const dataBasedWidth = calculateColumnWidth(key, key)
        const isKuCol = key === '区'
        cols.push({
          key,
          name: key,
          width: dataBasedWidth,
          minWidth: Math.max(dataBasedWidth, COL_WIDTH_MIN),
          resizable: true,
          editable: !readOnly,
          renderCell: ({ row }) => {
            const isEditing = !readOnly && editingItemIds.has(row.item_id)
            const value = row[key] ?? ''
            if (isEditing) {
              return (
                <input
                  type="text"
                  value={String(value)}
                  onChange={(e) => handleCellChange(row.item_id, key, e.target.value)}
                  style={{ width: '100%', border: 'none', padding: '4px' }}
                  onClick={(e) => e.stopPropagation()}
                />
              )
            }
            const strVal = String(value ?? '').trim()
            const label = isKuCol ? getKuLabel(value) : null
            const displayText = label ? `${strVal} (${label})` : strVal || ''
            return <span>{displayText}</span>
          },
        })
      }
      // NET은 frozen에 이미 포함됨 (위 검토 탭 frozen 블록)
    }

    const adjustedCols: Column<GridRow>[] = cols.map((col) => {
      const w = getColWidth(col)
      const existingMin = col.minWidth
      const minW = existingMin != null ? existingMin : col.frozen ? w : Math.max(w, COL_WIDTH_MIN)
      return { ...col, width: w, minWidth: minW }
    })

    const totalWidth = adjustedCols.reduce((sum, col) => sum + getColWidth(col), 0)
    const availableWidth = containerWidth || totalWidth
    let scaledCols: Column<GridRow>[] | null = null
    if (availableWidth > 0 && totalWidth < availableWidth) {
      const frozenCols = adjustedCols.filter((col) => col.frozen)
      const flexibleCols = adjustedCols.filter((col) => !col.frozen)
      const frozenWidth = frozenCols.reduce((sum, col) => sum + getColWidth(col), 0)
      const flexibleWidth = flexibleCols.reduce((sum, col) => sum + getColWidth(col), 0)
      const targetFlexibleWidth = Math.max(flexibleWidth, availableWidth - frozenWidth)
      if (flexibleWidth > 0 && targetFlexibleWidth > flexibleWidth) {
        const scale = targetFlexibleWidth / flexibleWidth
        let remaining = availableWidth - frozenWidth
        scaledCols = adjustedCols.map((col, idx) => {
          if (col.frozen) return col
          const w = getColWidth(col)
          let newWidth = Math.max(col.minWidth ?? COL_WIDTH_MIN, Math.floor(w * scale))
          const isLastFlexible = adjustedCols.slice(idx + 1).every((next) => next.frozen)
          if (isLastFlexible) newWidth = Math.max(newWidth, remaining)
          remaining -= newWidth
          return { ...col, width: newWidth }
        })
      }
    }
    const finalCols = scaledCols ?? adjustedCols
    // 동결 컬럼은 헤더 DnD 비활성 (defaultColumnOptions.draggable=true일 때도 드래그 불가)
    const finalColsWithDrag = finalCols.map((col) =>
      col.frozen ? { ...col, draggable: false } : col
    )

    const wrapColumnWidths: Record<string, number> = {}
    finalColsWithDrag.forEach((col) => {
      if (!FIXED_ROW_HEIGHT_KEYS.has(col.key)) wrapColumnWidths[col.key] = getColWidth(col)
    })
    const getRowHeight = (row: GridRow): number => {
      let maxLines = 1
      for (const [key, width] of Object.entries(wrapColumnWidths)) {
        const val = row[key] ?? (key === '得意先' ? row['得意先名'] : key === '得意先名' ? row['得意先'] : undefined)
        if (val == null) continue
        const str = String(val).trim()
        if (!str) continue
        const effectiveWidth = Math.max(40, width - 20)
        let charsPerLine = Math.min(MAX_CHARS_PER_LINE, Math.max(1, Math.floor(effectiveWidth / PX_PER_CHAR)))
        let lines = Math.ceil(str.length / charsPerLine)
        if (str.length >= 4 && str.length <= 12) lines = Math.max(lines, 2)
        if (lines > maxLines) maxLines = lines
      }
      return Math.max(MIN_ROW_HEIGHT, CELL_PADDING_V + maxLines * LINE_HEIGHT_PX + ROW_HEIGHT_BUFFER)
    }

    return { columns: finalColsWithDrag, getRowHeight }
  }, [
    items,
    itemDataKeysFromApi,
    hasItems,
    containerWidth,
    editingItemIds,
    hoveredRowId,
    setHoveredRowId,
    setReviewTooltip,
    handleCellChange,
    handleCheckboxUpdate,
    handleAddRow,
    handleDeleteRow,
    isItemLocked,
    getLockedBy,
    sessionId,
    getKuLabel,
    createItemPending,
    deleteItemPending,
    onOpenUnitPriceModal,
    onOpenAttachments,
    readOnly,
    pageRole,
    formType,
  ])
}
