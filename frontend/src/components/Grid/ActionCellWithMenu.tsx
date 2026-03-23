/**
 * 액션 메뉴가 있는 셀 (편집/추가/삭제). 메뉴 위치를 동적으로 계산하여 버튼 옆에 표시
 * 마지막 행 등: 뷰포트 아래로 잘리면 메뉴 하단을 버튼(행) 하단에 맞춤
 */
import { useRef, useState, useEffect } from 'react'
import { createPortal } from 'react-dom'

const VIEWPORT_MARGIN = 8

/** menuHeight, buttonRect 기준으로 fixed top(px) — 아래 잘리면 bottom = button.bottom 정렬 */
function computeActionMenuTop(buttonRect: DOMRect, menuHeight: number): number {
  const vh = typeof window !== 'undefined' ? window.innerHeight : 800
  const buttonCenterY = buttonRect.top + buttonRect.height / 2
  let top = buttonCenterY - menuHeight / 2 // 기본: 버튼 세로 중앙 기준
  if (top + menuHeight > vh - VIEWPORT_MARGIN) {
    top = buttonRect.bottom - menuHeight // 행(버튼) 하단과 메뉴 하단 맞춤
  }
  if (top < VIEWPORT_MARGIN) {
    top = VIEWPORT_MARGIN
  }
  if (top + menuHeight > vh - VIEWPORT_MARGIN) {
    top = Math.max(VIEWPORT_MARGIN, vh - VIEWPORT_MARGIN - menuHeight)
  }
  return top
}

interface ActionCellWithMenuProps {
  isHovered: boolean
  isEditing: boolean
  isLockedByOthers: boolean
  lockedBy: string | null
  onMouseEnter: () => void
  onMouseLeave: () => void
  onAdd: () => void
  onDelete: () => void
  onUnitPrice: () => void
  onAttachments?: () => void
  createItemPending: boolean
  deleteItemPending: boolean
}

export function ActionCellWithMenu({
  isHovered,
  isEditing,
  isLockedByOthers,
  lockedBy,
  onMouseEnter,
  onMouseLeave,
  onAdd,
  onDelete,
  onUnitPrice,
  onAttachments,
  createItemPending,
  deleteItemPending,
}: ActionCellWithMenuProps) {
  const buttonRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const [menuPosition, setMenuPosition] = useState<{ top: number; left: number } | null>(null)

  useEffect(() => {
    if (isHovered && buttonRef.current) {
      const updatePosition = () => {
        if (!buttonRef.current) return
        const buttonRect = buttonRef.current.getBoundingClientRect()
        const left = buttonRect.right - 4
        if (menuRef.current) {
          const menuHeight = menuRef.current.offsetHeight
          setMenuPosition({
            top: computeActionMenuTop(buttonRect, menuHeight),
            left,
          })
        } else {
          setMenuPosition({
            top: buttonRect.top + buttonRect.height / 2 - 60,
            left,
          })
          setTimeout(() => {
            if (menuRef.current && buttonRef.current) {
              const menuHeight = menuRef.current.offsetHeight
              const br = buttonRef.current.getBoundingClientRect()
              setMenuPosition({
                top: computeActionMenuTop(br, menuHeight),
                left: br.right - 4,
              })
            }
          }, 0)
        }
      }
      updatePosition()
    } else {
      setMenuPosition(null)
    }
  }, [isHovered])

  useEffect(() => {
    if (!isHovered) return
    const sync = () => {
      if (!buttonRef.current || !menuRef.current) return
      const br = buttonRef.current.getBoundingClientRect()
      const mh = menuRef.current.offsetHeight
      setMenuPosition({ top: computeActionMenuTop(br, mh), left: br.right - 4 })
    }
    window.addEventListener('scroll', sync, true)
    window.addEventListener('resize', sync)
    return () => {
      window.removeEventListener('scroll', sync, true)
      window.removeEventListener('resize', sync)
    }
  }, [isHovered])

  const menuContent = isHovered && menuPosition ? (
    <div
      ref={menuRef}
      className="action-menu"
      style={{
        position: 'fixed',
        top: `${menuPosition.top}px`,
        left: `${menuPosition.left}px`,
        zIndex: 99999,
      }}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      <button
        onClick={(e) => {
          e.preventDefault()
          e.stopPropagation()
          onAdd()
        }}
        className="action-menu-item action-menu-add"
        disabled={isEditing || isLockedByOthers || createItemPending}
        title={isLockedByOthers ? `編集中: ${lockedBy}` : 'この行の下に行を追加'}
      >
        ➕ 追加
      </button>
      <button
        onClick={(e) => {
          e.preventDefault()
          e.stopPropagation()
          onUnitPrice()
        }}
        className="action-menu-item action-menu-unit-price"
        title="単価・代表スーパー候補を表示"
      >
        💰 マッピング
      </button>
      {onAttachments && (
        <button
          onClick={(e) => {
            e.preventDefault()
            e.stopPropagation()
            onAttachments()
          }}
          className="action-menu-item action-menu-attachments"
          title="添付ファイル（PDF）"
        >
          📎 添付
        </button>
      )}
      <button
        onClick={(e) => {
          e.preventDefault()
          e.stopPropagation()
          onDelete()
        }}
        className="action-menu-item action-menu-delete"
        disabled={isEditing || isLockedByOthers || deleteItemPending}
        title={isLockedByOthers ? `編集中: ${lockedBy}` : '行を削除'}
      >
        🗑️ 削除
      </button>
    </div>
  ) : null

  return (
    <>
      <div
        className="action-cell-container"
        onMouseEnter={onMouseEnter}
        onMouseLeave={onMouseLeave}
      >
        <button
          ref={buttonRef}
          className={`btn-action-main ${(isEditing || isLockedByOthers) ? 'btn-action-main-locked' : ''}`}
          title={isLockedByOthers ? `編集中: ${lockedBy ?? ''}` : isEditing ? '編集中' : '操作メニュー'}
        >
          {isEditing || isLockedByOthers ? '🔒' : '✏️'}
        </button>
      </div>
      {typeof document !== 'undefined' && menuContent && createPortal(menuContent, document.body)}
    </>
  )
}
