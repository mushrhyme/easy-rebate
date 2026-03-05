/**
 * 解答作成タブ — page_role + page_meta ブロック（キー・値編集・グループ削除・追加）
 */
export interface AnswerKeyPageMetaSectionProps {
  currentPage: number
  pageRoleEdits: Record<number, string>
  setPageRoleEdits: React.Dispatch<React.SetStateAction<Record<number, string>>>
  setPageMetaDirtyPages: (fn: (prev: Set<number>) => Set<number>) => void
  currentPageMetaData: { page_role: string | null; page_meta: Record<string, unknown> } | null
  pageMetaDirtyPages: Set<number>
  groupedPageMetaFields: Array<{ group: string; sub: string | null; fields: Array<{ key: string; value: string }> }>
  onPageMetaGroupRemove: (group: string, sub: string | null, fields: Array<{ key: string; value: string }>) => void
  editingPageMetaKey: string | null
  setEditingPageMetaKey: (v: string | null) => void
  editingPageMetaKeyValue: string
  setEditingPageMetaKeyValue: (v: string) => void
  onPageMetaKeyRenameFull: (oldKey: string, newKey: string, currentValue: string) => void
  onPageMetaChange: (flatKey: string, value: string) => void
  onPageMetaKeyRemove: (flatKey: string) => void
  typeOptions: Array<{ value: string; label: string }>
  newPageMetaKey: string
  setNewPageMetaKey: (v: string) => void
  newPageMetaValue: string
  setNewPageMetaValue: (v: string) => void
  onPageMetaKeyAdd: (newKey: string, newValue: string) => void
}

export function AnswerKeyPageMetaSection({
  currentPage,
  pageRoleEdits,
  setPageRoleEdits,
  setPageMetaDirtyPages,
  currentPageMetaData,
  pageMetaDirtyPages,
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
}: AnswerKeyPageMetaSectionProps) {
  return (
    <>
      <div className="answer-key-page-label">p.{currentPage}</div>
      <div className="answer-key-page-role-row">
        <label className="answer-key-ocr-label">page_role</label>
        <select
          className="answer-key-page-role-select"
          value={pageRoleEdits[currentPage] ?? currentPageMetaData?.page_role ?? 'detail'}
          onChange={(e) => {
            setPageRoleEdits((prev) => ({ ...prev, [currentPage]: e.target.value }))
            setPageMetaDirtyPages((d) => new Set(d).add(currentPage))
          }}
          title="表紙(cover) / 明細(detail) / 合計(summary) / 返信(reply)"
        >
          <option value="detail">detail（明細）</option>
          <option value="cover">cover（表紙）</option>
          <option value="summary">summary（合計）</option>
          <option value="reply">reply（返信）</option>
        </select>
      </div>
      <div className={`answer-key-meta-block ${pageMetaDirtyPages.has(currentPage) ? 'answer-key-kv-dirty' : ''}`}>
        <div className="answer-key-meta-section-label">page_meta（キー・値の直接編集）</div>
        {groupedPageMetaFields.map(({ group, sub, fields }, groupIdx) => (
          <div key={`page-meta-group-${currentPage}-${groupIdx}-${group}-${sub ?? 'root'}`} className="answer-key-meta-group">
            <div className="answer-key-meta-group-header">
              <span className="answer-key-meta-group-label">
                {group === 'root' ? 'その他' : group}
                {sub ? ` / ${sub}` : ''}
              </span>
              <button
                type="button"
                className="answer-key-meta-group-delete-btn"
                onClick={() => onPageMetaGroupRemove(group, sub, fields)}
                title="このグループ全体を削除"
              >
                グループ削除
              </button>
            </div>
            {fields.map(({ key: metaKey, value }, metaIdx) => (
              <div
                key={`page-meta-${currentPage}-${metaIdx}-${metaKey}`}
                className="answer-key-kv-row answer-key-kv-row-with-delete"
              >
                <input
                  type="text"
                  className="answer-key-kv-key-input"
                  value={editingPageMetaKey === metaKey ? editingPageMetaKeyValue : metaKey}
                  title="キー（フルパス編集可）"
                  onChange={(e) => {
                    if (editingPageMetaKey !== metaKey) {
                      setEditingPageMetaKey(metaKey)
                      setEditingPageMetaKeyValue(e.target.value)
                    } else {
                      setEditingPageMetaKeyValue(e.target.value)
                    }
                  }}
                  onFocus={() => {
                    setEditingPageMetaKey(metaKey)
                    setEditingPageMetaKeyValue(metaKey)
                  }}
                  onBlur={() => {
                    if (editingPageMetaKey === metaKey) {
                      const n = editingPageMetaKeyValue.trim()
                      if (n && n !== metaKey) onPageMetaKeyRenameFull(metaKey, n, value)
                      setEditingPageMetaKey(null)
                    }
                  }}
                  onKeyDown={(e) => {
                    if (editingPageMetaKey === metaKey && e.key === 'Enter') {
                      const n = editingPageMetaKeyValue.trim()
                      if (n && n !== metaKey) onPageMetaKeyRenameFull(metaKey, n, value)
                      setEditingPageMetaKey(null)
                      e.currentTarget.blur()
                    }
                    if (e.key === 'Escape') {
                      setEditingPageMetaKey(null)
                      e.currentTarget.blur()
                    }
                  }}
                  placeholder="例: totals.役務提供.入金額"
                />
                {metaKey === 'タイプ' || metaKey.endsWith('.タイプ') ? (
                  <select
                    className="answer-key-kv-input answer-key-kv-select"
                    value={value}
                    onChange={(e) => onPageMetaChange(metaKey, e.target.value)}
                  >
                    {(() => {
                      const opts = [...typeOptions]
                      if (value != null && String(value).trim() !== '' && !opts.some((o) => o.value === value)) {
                        opts.unshift({ value: String(value).trim(), label: String(value).trim() })
                      }
                      return opts.map((opt) => (
                        <option key={opt.value || '_'} value={opt.value}>
                          {opt.label}
                        </option>
                      ))
                    })()}
                  </select>
                ) : (
                  <input
                    type="text"
                    className="answer-key-kv-input"
                    value={value}
                    onChange={(e) => onPageMetaChange(metaKey, e.target.value)}
                    placeholder="値"
                  />
                )}
                <button
                  type="button"
                  className="answer-key-kv-delete-btn"
                  onClick={() => onPageMetaKeyRemove(metaKey)}
                  title="このキーを削除"
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        ))}
        <div className="answer-key-kv-row answer-key-kv-row-with-delete answer-key-add-row">
          <input
            type="text"
            className="answer-key-kv-key-input"
            value={newPageMetaKey}
            onChange={(e) => setNewPageMetaKey(e.target.value)}
            placeholder="例: totals.役務提供.新規キー"
            title="フルパスで入力（例: totals.役務提供.入金額）"
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
    </>
  )
}
