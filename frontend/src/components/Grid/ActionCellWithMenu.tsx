/**
 * 액션 메뉴가 있는 셀 (편집/추가/삭제). 메뉴 위치를 동적으로 계산하여 버튼 아래에 표시
 */
import { useRef, useState, useEffect } from 'react'
import { createPortal } from 'react-dom'

interface ActionCellWithMenuProps {
  isHovered: boolean
  isEditing: boolean
  isLockedByOthers: boolean
  lockedBy: string | null
  onMouseEnter: () => void
  onMouseLeave: () => void
  onAdd: () => void
  onDelete: () => void
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
        if (menuRef.current) {
          const menuHeight = menuRef.current.offsetHeight
          const buttonCenterY = buttonRect.top + buttonRect.height / 2
          setMenuPosition({
            top: buttonCenterY - menuHeight / 2,
            left: buttonRect.right - 4,
          })
        } else {
          setMenuPosition({
            top: buttonRect.top + buttonRect.height / 2 - 60,
            left: buttonRect.right - 4,
          })
          setTimeout(() => {
            if (menuRef.current && buttonRef.current) {
              const menuHeight = menuRef.current.offsetHeight
              const buttonRect = buttonRef.current.getBoundingClientRect()
              const buttonCenterY = buttonRect.top + buttonRect.height / 2
              setMenuPosition({
                top: buttonCenterY - menuHeight / 2,
                left: buttonRect.right - 4,
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
