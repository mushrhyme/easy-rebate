/**
 * 1次/2次 검토 체크박스 셀 (증빙 툴팁 포함)
 */
import { formatReviewDate } from './utils'
import type { GridRow } from './types'

type ReviewField = 'first_review_checked' | 'second_review_checked'

interface ReviewCheckboxCellProps {
  row: GridRow
  field: ReviewField
  label: '1次' | '2次'
  onToggle: (itemId: number, field: ReviewField, checked: boolean) => void
  onTooltip: (text: string, x: number, y: number) => void
  onTooltipClear: () => void
  disabled?: boolean
}

export function ReviewCheckboxCell({
  row,
  field,
  label,
  onToggle,
  onTooltip,
  onTooltipClear,
  disabled = false,
}: ReviewCheckboxCellProps) {
  const isChecked = (row[field] as boolean) || false
  const reviewedAt = field === 'first_review_checked' ? row.first_review_reviewed_at : row.second_review_reviewed_at
  const reviewedBy = field === 'first_review_checked' ? row.first_review_reviewed_by : row.second_review_reviewed_by
  const tooltipText =
    isChecked && (reviewedBy || reviewedAt)
      ? `${label}: ${reviewedBy ?? ''}${reviewedAt ? ` (${formatReviewDate(reviewedAt)})` : ''}`.trim()
      : isChecked
        ? `${label}レビュー完了`
        : `${label}レビュー未完了`

  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        height: '100%',
        width: '100%',
      }}
    >
      <button
        type="button"
        disabled={disabled}
        onClick={(e) => {
          e.stopPropagation()
          e.preventDefault()
          if (!disabled) onToggle(row.item_id, field, !isChecked)
        }}
        onMouseDown={(e) => e.stopPropagation()}
        onMouseEnter={(e) => {
          if (disabled) return
          const rect = e.currentTarget.getBoundingClientRect()
          onTooltip(tooltipText, rect.left + rect.width / 2, rect.top)
        }}
        onMouseLeave={onTooltipClear}
        style={{
          cursor: disabled ? 'default' : 'pointer',
          opacity: disabled ? 0.7 : 1,
          width: '20px',
          height: '20px',
          border: '2px solid',
          borderColor: isChecked ? '#667eea' : '#999',
          borderRadius: '3px',
          backgroundColor: isChecked ? '#667eea' : '#fff',
          color: isChecked ? '#fff' : 'transparent',
          fontSize: '14px',
          fontWeight: 'bold',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: 0,
          margin: 0,
          lineHeight: 1,
          transition: 'all 0.2s ease',
        }}
        title={tooltipText}
      >
        {isChecked ? '✓' : ''}
      </button>
    </div>
  )
}
