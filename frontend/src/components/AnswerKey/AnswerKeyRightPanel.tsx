/**
 * 정답지 탭 — 우측: キー・値 / テンプレート / JSON 탭 및 저장 버튼
 */
import { KEY_LABELS } from './answerKeyTabConstants'

/** 우측 패널에 필요한 상태·핸들러 (AnswerKeyTab에서 한 번에 전달) */
export interface AnswerKeyRightPanelCtx {
  rightView: 'kv' | 'json' | 'template'
  setRightView: (v: 'kv' | 'json' | 'template') => void
  firstRowToTemplateEntries: (row: unknown) => Array<{ id: string; key: string; value: string }>
  currentPageRows: Array<Record<string, unknown>>
  setTemplateEntries: React.Dispatch<React.SetStateAction<Array<{ id: string; key: string; value: string }>>>
  syncJsonEditFromAnswer: () => void
  dirtyIds: Set<number>
  pageMetaDirtyPages: Set<number>
  answerProvider: string
  setAnswerProvider: (v: 'gemini' | 'gpt-5.2') => void
  generateAnswerMutation: { mutate: (arg: unknown) => void; isPending: boolean }
  selectedDoc: { pdf_filename: string; total_pages: number } | null
  rows: Array<Record<string, unknown>>
  itemDataKeys: string[]
  jsonEditText: string
  setJsonEditText: (v: string) => void
  applyJsonEdit: () => void
  allDataLoaded: boolean
  templateEntries: Array<{ id: string; key: string; value: string }>
  updateTemplateEntry: (id: string, field: 'key' | 'value', value: string) => void
  removeTemplateEntry: (id: string) => void
  addTemplateEntry: () => void
  generateFromTemplateMutation: { mutate: () => void; isPending: boolean }
  currentPage: number
  currentPageMetaFields: Array<{ key: string; value: string }>
  pageRoleEdits: Record<number, string>
  setPageRoleEdits: React.Dispatch<React.SetStateAction<Record<number, string>>>
  setPageMetaDirtyPages: (fn: (prev: Set<number>) => Set<number>) => void
  currentPageMetaData: { page_role: string | null; page_meta: Record<string, unknown> } | null
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
  displayKeys: string[]
  dataKeysForDisplay: string[]
  editableKeys: Set<string>
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
  handleSaveGrid: () => void
  handleSaveAsAnswerKey: () => void
  saveStatus: string
  saveMessage: string
}

export function AnswerKeyRightPanel({ ctx }: { ctx: AnswerKeyRightPanelCtx }) {
  const {
    rightView,
    setRightView,
    firstRowToTemplateEntries,
    currentPageRows,
    syncJsonEditFromAnswer,
    dirtyIds,
    pageMetaDirtyPages,
    answerProvider,
    setAnswerProvider,
    generateAnswerMutation,
    selectedDoc,
    rows,
    itemDataKeys,
    jsonEditText,
    setJsonEditText,
    applyJsonEdit,
    allDataLoaded,
    templateEntries,
    setTemplateEntries,
    updateTemplateEntry,
    removeTemplateEntry,
    addTemplateEntry,
    generateFromTemplateMutation,
    currentPage,
    currentPageMetaFields,
    pageRoleEdits,
    setPageRoleEdits,
    setPageMetaDirtyPages,
    currentPageMetaData,
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
    displayKeys,
    dataKeysForDisplay,
    editableKeys,
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
    handleSaveGrid,
    handleSaveAsAnswerKey,
    saveStatus,
    saveMessage,
  } = ctx

  return (
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
        {(dirtyIds.size > 0 || pageMetaDirtyPages.size > 0) && (
          <span className="answer-key-dirty-badge">未保存: {dirtyIds.size + pageMetaDirtyPages.size}件</span>
        )}
        <div className="answer-key-provider-row">
          <select
            className="answer-key-provider-select"
            value={answerProvider}
            onChange={(e) => setAnswerProvider(e.target.value as 'gemini' | 'gpt-5.2')}
            title="画像からページ全体の正解を一度に生成（Vision）"
          >
            <option value="gpt-5.2">GPT</option>
            <option value="gemini">Gemini</option>
          </select>
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
            title="選択したモデルでこのページの正解を一括生成"
          >
            {generateAnswerMutation.isPending ? '生成中…' : '正解生成'}
          </button>
        </div>
      </div>
      {rightView === 'json' && (
        <div className="answer-key-json-view">
          <label className="answer-key-ocr-label">解答JSON（編集後に適用）</label>
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
            先頭行のみ表示します。キー・値を編集し、「残り行を生成」で選択中のモデル（GPT/Gemini）が同じキー構造の全行を生成します。
          </p>
          {!allDataLoaded && <p className="answer-key-template-loading">データ読み込み中…</p>}
          {allDataLoaded && currentPageRows.length === 0 && templateEntries.length === 0 && (
            <p className="answer-key-template-empty-hint">
              このページに行がありません。「キー追加」でキーを入力した後「残り行を生成」を押すと、全行を生成します。
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
            title="この行をテンプレートにし、選択中のモデルで残りの行を生成します"
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
          <div className="answer-key-page-role-row">
            <label className="answer-key-ocr-label">page_role</label>
            <select
              className="answer-key-page-role-select"
              value={pageRoleEdits[currentPage] ?? currentPageMetaData?.page_role ?? 'detail'}
              onChange={(e) => {
                setPageRoleEdits((prev) => ({ ...prev, [currentPage]: e.target.value }))
                setPageMetaDirtyPages((d) => new Set(d).add(currentPage))
              }}
              title="표지(cover) / 상세(detail) / 요약(summary) / 회신(reply)"
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
          {currentPageRows.length === 0 ? (
            currentPageMetaFields.length > 0 ? null : <p className="answer-key-empty">このページには行がありません。</p>
          ) : (
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
          title="変更をDBにだけ反映します。ベクターDBは作らないので短時間で完了します。"
        >
          {saveStatus === 'saving' ? '保存中…' : '保存（DBのみ・ベクターDBなし）'}
        </button>
        <button
          type="button"
          className="answer-key-btn answer-key-btn-primary"
          onClick={handleSaveAsAnswerKey}
          disabled={saveStatus === 'saving' || saveStatus === 'building'}
          title="DB反映のあと、学習フラグを立ててベクターDBを再構築します。時間がかかります。"
        >
          {saveStatus === 'building' ? '登録中…' : '解答として保存（ベクターDBに登録）'}
        </button>
      </div>
      {saveMessage && (
        <p className={`answer-key-status ${saveStatus === 'error' ? 'answer-key-status-error' : ''}`}>
          {saveMessage}
        </p>
      )}
    </div>
  )
}
