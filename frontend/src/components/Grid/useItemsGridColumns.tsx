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

/** 단가 관련 컬럼: 호버 시 "단가 후보" 버튼 표시 → 클릭 시 모달 */
const UNIT_PRICE_HOVER_KEYS = new Set(['商品名', '仕切', '本部長'])

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
  /** 단가 셀 호버 시 표시할 셀: { itemId, columnKey } */
  hoveredUnitPriceCell: { itemId: number; columnKey: string } | null
  setHoveredUnitPriceCell: (v: { itemId: number; columnKey: string } | null) => void
  /** "단가 후보" 클릭 시 모달 열기 */
  onOpenUnitPriceModal: (row: GridRow) => void
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
    hoveredUnitPriceCell,
    setHoveredUnitPriceCell,
    onOpenUnitPriceModal,
  } = params

  const hasItems = items.length > 0

  return useMemo(() => {
    let orderedKeys: string[] = []
    if (hasItems) {
      const firstItem = items[0]
      const keysInDb = new Set<string>()
      items.forEach((item) => {
        if (item.item_data) {
          Object.keys(item.item_data).forEach((key) => keysInDb.add(key))
        }
      })
      const itemDataKeys = itemDataKeysFromApi?.length
        ? [...itemDataKeysFromApi]
        : firstItem.item_data
          ? Object.keys(firstItem.item_data)
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
          />
        ),
      })

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
          // JSON 결과 그대로 표시 (디폴트 없음)
          const displayValue = raw != null && String(raw).trim() !== '' ? String(raw) : '—'
          const isEditing = editingItemIds.has(row.item_id)
          if (isEditing) {
            const selectValue = raw != null && String(raw).trim() !== '' ? String(raw) : ''
            return (
              <select
                value={selectValue}
                onChange={(e) => {
                  const newValue = e.target.value === '' ? null : e.target.value
                  handleCellChange(row.item_id, 'タイプ', newValue)
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
                <option value="">—</option>
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
    }

    if (hasItems) {
      const conditionAmountKey = CONDITION_AMOUNT_KEYS.find((k) => orderedKeys.includes(k)) ?? null
      for (const key of orderedKeys) {
        if (key === 'customer' || key === 'タイプ') continue
        const firstValue = items[0]?.item_data?.[key]
        const isComplexType =
          firstValue != null && (typeof firstValue === 'object' || Array.isArray(firstValue))
        if (isComplexType) continue
        const dataBasedWidth = calculateColumnWidth(key, key)
        const isKuCol = key === '区'
        const isUnitPriceCol = UNIT_PRICE_HOVER_KEYS.has(key)
        const isHovered = isUnitPriceCol && hoveredUnitPriceCell != null &&
          hoveredUnitPriceCell.itemId === row.item_id && hoveredUnitPriceCell.columnKey === key
        cols.push({
          key,
          name: key,
          width: dataBasedWidth,
          minWidth: Math.max(dataBasedWidth, COL_WIDTH_MIN),
          resizable: true,
          renderCell: ({ row }) => {
            const isEditing = editingItemIds.has(row.item_id)
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
            const cellContent = <span>{displayText}</span>
            if (isUnitPriceCol) {
              return (
                <div
                  className="rdg-cell-unit-price-hover"
                  onMouseEnter={() => setHoveredUnitPriceCell({ itemId: row.item_id, columnKey: key })}
                  onMouseLeave={() => setHoveredUnitPriceCell(null)}
                  style={{ width: '100%', height: '100%', position: 'relative' }}
                >
                  {cellContent}
                  {isHovered && (
                    <button
                      type="button"
                      className="unit-price-cell-btn"
                      onClick={(e) => {
                        e.stopPropagation()
                        onOpenUnitPriceModal(row)
                        setHoveredUnitPriceCell(null)
                      }}
                    >
                      단가 후보
                    </button>
                  )}
                </div>
              )
            }
            return cellContent
          },
        })
      }

      cols.push({
        key: 'net',
        name: 'NET',
        width: 90,
        minWidth: 90,
        frozen: false,
        resizable: true,
        editable: false,
        renderCell: ({ row }) => {
          const condNum = conditionAmountKey != null ? parseCellNum(row[conditionAmountKey]) : null
          const shikiriNum = parseCellNum(row['仕切'])
          if (condNum == null || shikiriNum == null) return <span>—</span>
          return <span>{(shikiriNum - condNum).toLocaleString()}</span>
        },
      })
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

    const wrapColumnWidths: Record<string, number> = {}
    finalCols.forEach((col) => {
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

    return { columns: finalCols, getRowHeight }
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
    hoveredUnitPriceCell,
    setHoveredUnitPriceCell,
    onOpenUnitPriceModal,
  ])
}
