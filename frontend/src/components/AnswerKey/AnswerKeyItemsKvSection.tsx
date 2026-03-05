/**
 * 解答作成タブ — items キー・値ブロック（行ごと編集・キー追加）
 */
import { KEY_LABELS } from './answerKeyTabConstants'

export interface AnswerKeyItemsKvSectionProps {
  currentPageRows: Array<Record<string, unknown>>
  dirtyIds: Set<number>
  displayKeys: string[]
  dataKeysForDisplay: string[]
  editableKeys: Set<string>
  typeOptions: Array<{ value: string; label: string }>
  editingKeyName: string | null
  setEditingKeyName: (v: string | null) => void
  editingKeyValue: string
  setEditingKeyValue: (v: string) => void
  onRenameKey: (oldKey: string, newKey: string) => void
  onValueChange: (itemId: number, key: string, value: string | number | boolean | null) => void
  onRemoveKey: (key: string) => void
  onAddKey: (newKey: string) => void
  getKuLabel: (value: unknown) => string | null
  newKeyInput: string
  setNewKeyInput: (v: string) => void
}

export function AnswerKeyItemsKvSection({
  currentPageRows,
  dirtyIds,
  displayKeys,
  dataKeysForDisplay,
  editableKeys,
  typeOptions,
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
}: AnswerKeyItemsKvSectionProps) {
  return (
    <>
      <div className="answer-key-meta-section-label">items（キー・値の直接編集）</div>
      {currentPageRows.map((row: Record<string, unknown>, index: number) => (
        <div
          key={row.item_id as number}
          className={`answer-key-kv-block ${dirtyIds.has(row.item_id as number) ? 'answer-key-kv-dirty' : ''}`}
        >
          <div className="answer-key-kv-block-title">items[{index}]</div>
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
                  ? `配列(${(val as unknown[]).length}件)`
                  : isObject
                    ? '[オブジェクト]'
                    : String(val)
            const isDataKey = dataKeysForDisplay.includes(key)
            const isEditable = editableKeys.has(key)
            const keyDisplay =
              editingKeyName === key ? editingKeyValue : (KEY_LABELS[key] ?? key)
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
                  key === 'タイプ' ? (
                    <select
                      className="answer-key-kv-input answer-key-kv-select"
                      value={isComplex ? '' : strVal}
                      onChange={(e) =>
                        onValueChange(
                          row.item_id as number,
                          key,
                          e.target.value === '' ? null : e.target.value
                        )
                      }
                    >
                      {typeOptions.map((opt) => (
                        <option key={opt.value || '_'} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <span className="answer-key-kv-value-with-ku">
                      <input
                        type="text"
                        className="answer-key-kv-input"
                        value={isComplex ? '' : strVal}
                        onChange={(e) =>
                          onValueChange(
                            row.item_id as number,
                            key,
                            e.target.value === '' ? null : e.target.value
                          )
                        }
                        placeholder={isComplex ? strVal : undefined}
                      />
                      {key === '区' && getKuLabel(val) && (
                        <span className="answer-key-ku-label" title={`区_mapping: ${strVal} → ${getKuLabel(val)}`}>
                          {getKuLabel(val)}
                        </span>
                      )}
                    </span>
                  )
                ) : (
                  <span className="answer-key-kv-val">
                    {key === '区' && getKuLabel(val)
                      ? `${strVal} (${getKuLabel(val)})`
                      : (strVal || '—')}
                  </span>
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
          placeholder="新規キー（全行に追加）"
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              onAddKey(newKeyInput)
              setNewKeyInput('')
            }
          }}
        />
        <span className="answer-key-kv-add-hint">全行に追加</span>
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
  )
}
