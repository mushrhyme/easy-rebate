/**
 * 정답지 탭 — 우측: キー・値 / テンプレート 탭（保存はヘッダで実行）
 * 役割別に ctx を分割し、page_meta / items はサブコンポーネントへ
 */
import { AnswerKeyPageMetaSection } from './AnswerKeyPageMetaSection'
import { AnswerKeyItemsKvSection } from './AnswerKeyItemsKvSection'

/** タブ切替（キー・値 / テンプレート） */
export interface AnswerKeyViewCtx {
  rightView: 'kv' | 'template'
  setRightView: (v: 'kv' | 'template') => void
}

/** テンプレートタブ用（currentPageRows は gridCtx と共有） */
export interface AnswerKeyTemplateCtx {
  firstRowToTemplateEntries: (row: unknown) => Array<{ id: string; key: string; value: string }>
  setTemplateEntries: React.Dispatch<React.SetStateAction<Array<{ id: string; key: string; value: string }>>>
  templateEntries: Array<{ id: string; key: string; value: string }>
  updateTemplateEntry: (id: string, field: 'key' | 'value', value: string) => void
  removeTemplateEntry: (id: string) => void
  addTemplateEntry: () => void
  generateFromTemplateMutation: { mutate: () => void; isPending: boolean }
  allDataLoaded: boolean
}

/** items キー・値グリッド用 */
export interface AnswerKeyGridCtx {
  currentPage: number
  currentPageRows: Array<Record<string, unknown>>
  rows: Array<Record<string, unknown>>
  itemDataKeys: string[]
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

/** page_meta / page_role 編集用（currentPage は gridCtx と共有） */
export interface AnswerKeyPageMetaCtx {
  currentPageMetaFields: Array<{ key: string; value: string }>
  pageMetaDirtyPages: Set<number>
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
  newPageMetaKey: string
  setNewPageMetaKey: (v: string) => void
  newPageMetaValue: string
  setNewPageMetaValue: (v: string) => void
  onPageMetaKeyAdd: (newKey: string, newValue: string) => void
}

/** 正解生成（GPT/Gemini）用 */
export interface AnswerKeyGenerateCtx {
  answerProvider: string
  setAnswerProvider: (v: 'gemini' | 'gpt-5.2') => void
  generateAnswerMutation: { mutate: (arg: unknown) => void; isPending: boolean }
  selectedDoc: { pdf_filename: string; total_pages: number } | null
  /** API 호출 시 사용할 페이지 번호（ブリッジ単一ページ時は 그 페이지만） */
  effectivePageNumber?: number
}

/** 保存状態・メッセージ・読取専用（保存はヘッダの「保存」で実行） */
export interface AnswerKeySaveCtx {
  saveStatus: string
  saveMessage: string
  readOnly?: boolean
}

export interface AnswerKeyRightPanelProps {
  viewCtx: AnswerKeyViewCtx
  templateCtx: AnswerKeyTemplateCtx
  gridCtx: AnswerKeyGridCtx
  pageMetaCtx: AnswerKeyPageMetaCtx
  generateCtx: AnswerKeyGenerateCtx
  saveCtx: AnswerKeySaveCtx
}

export function AnswerKeyRightPanel({ viewCtx, templateCtx, gridCtx, pageMetaCtx, generateCtx, saveCtx }: AnswerKeyRightPanelProps) {
  const { rightView, setRightView } = viewCtx
  const {
    firstRowToTemplateEntries,
    setTemplateEntries,
    templateEntries,
    updateTemplateEntry,
    removeTemplateEntry,
    addTemplateEntry,
    generateFromTemplateMutation,
    allDataLoaded,
  } = templateCtx
  const currentPage = gridCtx.currentPage
  const {
    currentPageRows,
    rows,
    itemDataKeys,
    dirtyIds,
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
  } = gridCtx
  const {
    currentPageMetaFields,
    pageMetaDirtyPages,
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
    newPageMetaKey,
    setNewPageMetaKey,
    newPageMetaValue,
    setNewPageMetaValue,
    onPageMetaKeyAdd,
  } = pageMetaCtx
  const { answerProvider, setAnswerProvider, generateAnswerMutation, selectedDoc, effectivePageNumber } = generateCtx
  const { saveStatus, saveMessage, readOnly = false } = saveCtx

  const typeOptions = gridCtx.typeOptions

  return (
    <div className="answer-key-right">
      <div
        className="answer-key-right-body"
        style={
          readOnly
            ? { pointerEvents: 'none' as const, opacity: 0.85, userSelect: 'none' as const }
            : undefined
        }
      >
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
                pageNumber: effectivePageNumber ?? currentPage,
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
      <div className="answer-key-right-content">
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
          <AnswerKeyPageMetaSection
            currentPage={currentPage}
            pageRoleEdits={pageRoleEdits}
            setPageRoleEdits={setPageRoleEdits}
            setPageMetaDirtyPages={setPageMetaDirtyPages}
            currentPageMetaData={currentPageMetaData}
            pageMetaDirtyPages={pageMetaDirtyPages}
            groupedPageMetaFields={groupedPageMetaFields}
            onPageMetaGroupRemove={onPageMetaGroupRemove}
            editingPageMetaKey={editingPageMetaKey}
            setEditingPageMetaKey={setEditingPageMetaKey}
            editingPageMetaKeyValue={editingPageMetaKeyValue}
            setEditingPageMetaKeyValue={setEditingPageMetaKeyValue}
            onPageMetaKeyRenameFull={onPageMetaKeyRenameFull}
            onPageMetaChange={onPageMetaChange}
            onPageMetaKeyRemove={onPageMetaKeyRemove}
            typeOptions={typeOptions}
            newPageMetaKey={newPageMetaKey}
            setNewPageMetaKey={setNewPageMetaKey}
            newPageMetaValue={newPageMetaValue}
            setNewPageMetaValue={setNewPageMetaValue}
            onPageMetaKeyAdd={onPageMetaKeyAdd}
          />
          {currentPageRows.length === 0 ? (
            currentPageMetaFields.length > 0 ? null : <p className="answer-key-empty">このページには行がありません。</p>
          ) : (
            <AnswerKeyItemsKvSection
              currentPageRows={currentPageRows}
              dirtyIds={dirtyIds}
              displayKeys={displayKeys}
              dataKeysForDisplay={dataKeysForDisplay}
              editableKeys={editableKeys}
              typeOptions={typeOptions}
              editingKeyName={editingKeyName}
              setEditingKeyName={setEditingKeyName}
              editingKeyValue={editingKeyValue}
              setEditingKeyValue={setEditingKeyValue}
              onRenameKey={onRenameKey}
              onValueChange={onValueChange}
              onRemoveKey={onRemoveKey}
              onAddKey={onAddKey}
              getKuLabel={getKuLabel}
              newKeyInput={newKeyInput}
              setNewKeyInput={setNewKeyInput}
            />
          )}
        </div>
      )}
      </div>
      </div>
      {readOnly && (
        <p className="answer-key-status">既にベクターDBに登録された文書です。編集できません。</p>
      )}
      {saveMessage && (
        <p className={`answer-key-status ${saveStatus === 'error' ? 'answer-key-status-error' : ''}`}>
          {saveMessage}
        </p>
      )}
    </div>
  )
}
