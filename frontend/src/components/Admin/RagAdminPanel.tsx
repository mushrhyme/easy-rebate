import { useState, useMemo, useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ragAdminApi, formTypesApi } from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import './RagAdminPanel.css'

const MASTER_CODE_KEYS = ['a', 'b', 'c', 'd', 'e', 'f'] as const
type MasterCodeRow = { a: string; b: string; c: string; d: string; e: string; f: string }

export const RagAdminPanel = () => {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const isAdmin = user?.username === 'admin'

  const {
    data: status,
    isLoading: statusLoading,
    refetch: refetchStatus,
  } = useQuery({
    queryKey: ['rag-admin', 'status'],
    queryFn: () => ragAdminApi.getStatus(),
  })

  const {
    mutateAsync: buildVectors,
    isPending: buildPending,
    data: buildResult,
  } = useMutation({
    mutationKey: ['rag-admin', 'build'],
    mutationFn: async () => ragAdminApi.build(undefined),
    onSuccess: () => {
      refetchStatus()
    },
  })

  const {
    data: masterCodeData,
    isLoading: masterCodeLoading,
    refetch: refetchMasterCode,
  } = useQuery({
    queryKey: ['rag-admin', 'master-code'],
    queryFn: () => ragAdminApi.getMasterCode(),
    enabled: isAdmin,
  })

  const { data: formTypesData, isLoading: formTypesLoading } = useQuery({
    queryKey: ['form-types'],
    queryFn: () => formTypesApi.getList(),
    enabled: isAdmin,
  })

  const updateFormTypeLabelMutation = useMutation({
    mutationFn: ({ formCode, displayName }: { formCode: string; displayName: string }) =>
      formTypesApi.updateLabel(formCode, displayName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['form-types'] })
    },
  })

  const [editedRows, setEditedRows] = useState<MasterCodeRow[]>([])
  const [newRowDraft, setNewRowDraft] = useState<MasterCodeRow>(() => ({
    a: '', b: '', c: '', d: '', e: '', f: '',
  }))
  const [columnFilters, setColumnFilters] = useState<Record<string, string>>({
    a: '', b: '', c: '', d: '', e: '', f: '',
  })

  /** 様式名の編集用（form_code → 表示名） */
  const [formTypeLabelDrafts, setFormTypeLabelDrafts] = useState<Record<string, string>>({})
  useEffect(() => {
    if (formTypesData?.form_types) {
      setFormTypeLabelDrafts(
        formTypesData.form_types.reduce<Record<string, string>>((acc, t) => {
          acc[t.value] = t.label
          return acc
        }, {})
      )
    }
  }, [formTypesData?.form_types])

  useEffect(() => {
    if (masterCodeData?.rows) {
      setEditedRows(masterCodeData.rows.map((r) => ({ ...r })))
    }
  }, [masterCodeData?.rows])

  const filteredRows = useMemo(() => {
    return editedRows
      .map((row, index) => ({ row, index }))
      .filter(({ row }) => {
        return MASTER_CODE_KEYS.every((key) => {
          const q = (columnFilters[key] ?? '').trim().toLowerCase()
          if (!q) return true
          return (row[key] ?? '').toLowerCase().includes(q)
        })
      })
  }, [editedRows, columnFilters])

  const {
    mutateAsync: saveMasterCode,
    isPending: saveMasterCodePending,
  } = useMutation({
    mutationKey: ['rag-admin', 'master-code-save'],
    mutationFn: (params: { headers?: string[]; rows: MasterCodeRow[] }) =>
      ragAdminApi.saveMasterCode(params),
    onSuccess: () => {
      refetchMasterCode()
    },
  })

  if (!isAdmin) {
    return (
      <div className="rag-admin-tab">
        <div className="rag-admin-header">
          <div className="rag-admin-title-container">
            <div className="rag-admin-title-icon">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M3 5H21V19H3V5Z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M7 9H17" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M7 13H13" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <div className="rag-admin-title-text">
              <h1 className="rag-admin-title-main">ベクターDB管理</h1>
              <p className="rag-admin-title-sub">Admin Only</p>
            </div>
          </div>
        </div>
        <div className="rag-admin-content">
          <div className="rag-admin-card">
            <p>この画面は管理者のみアクセスできます。</p>
          </div>
        </div>
      </div>
    )
  }

  const handleBuildClick = async () => {
    if (buildPending) return
    const confirmMessage =
      'img フォルダ直下の全フォルダ（finet / mail 等）を走査してベクターDBを再構築します。時間がかかる場合があります。実行しますか？'
    if (!window.confirm(confirmMessage)) return
    try {
      await buildVectors()
    } catch (error: any) {
      const message =
        error?.response?.data?.detail ||
        error?.message ||
        'ベクターDBの再構築中にエラーが発生しました。'
      alert(message)
    }
  }

  const handleMasterCodeCellChange = (rowIndex: number, key: string, value: string) => {
    setEditedRows((prev) => {
      const next = [...prev]
      if (!next[rowIndex]) return prev
      next[rowIndex] = { ...next[rowIndex], [key]: value }
      return next
    })
  }

  const handleNewRowDraftChange = (key: string, value: string) => {
    setNewRowDraft((prev) => ({ ...prev, [key]: value }))
  }

  const handleAddMasterCodeRow = () => {
    const row = { ...newRowDraft }
    setEditedRows((prev) => [...prev, row])
    setNewRowDraft({ a: '', b: '', c: '', d: '', e: '', f: '' })
  }

  const handleSaveMasterCode = async () => {
    if (saveMasterCodePending) return
    if (!window.confirm('基準管理データを保存しますか？')) return
    try {
      await saveMasterCode({
        headers: masterCodeData?.headers,
        rows: editedRows,
      })
      alert('保存しました。')
    } catch (error: any) {
      const message =
        error?.response?.data?.detail ||
        error?.message ||
        '保存に失敗しました。'
      alert(message)
    }
  }

  return (
    <div className="rag-admin-tab">
      <div className="rag-admin-header">
        <div className="rag-admin-title-container">
          <div className="rag-admin-title-icon">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M3 3H21V9H3V3Z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M3 15H21V21H3V15Z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M7 9V15" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <div className="rag-admin-title-text">
            <h1 className="rag-admin-title-main">ベクターDB管理</h1>
            <p className="rag-admin-title-sub">Vector Database Admin</p>
          </div>
        </div>
      </div>

      <div className="rag-admin-content">
        <section className="rag-admin-card">
          <h3 className="rag-admin-section-title">現在のステータス</h3>
        {statusLoading ? (
            <p>読み込み中...</p>
          ) : (
            <>
              <p className="rag-admin-total">
                合計ベクター数: <strong>{status?.total_vectors ?? 0}</strong>
              </p>
              {status?.per_form_type && status.per_form_type.length > 0 && (
                <table className="rag-admin-status-table">
                  <thead>
                    <tr>
                      <th>フォーム種別</th>
                      <th className="rag-admin-col-right">ベクター数</th>
                    </tr>
                  </thead>
                  <tbody>
                    {status.per_form_type.map((row) => (
                      <tr key={row.form_type ?? 'none'}>
                        <td>{row.form_type || '(未設定)'}</td>
                        <td className="rag-admin-col-right">{row.vector_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}
        </section>

        <section className="rag-admin-card">
          <h3 className="rag-admin-section-title">img フォルダからのベクターDB再構築</h3>
          <p className="rag-admin-helper">
            img 直下のフォルダ（finet / mail 等）をすべて走査し、変更分のみベクター化します。フォーム種別は区別しません。
          </p>
          <button
            type="button"
            onClick={handleBuildClick}
            disabled={buildPending}
            className="rag-admin-button primary"
          >
            {buildPending ? '再構築中...' : 'img フォルダ全体から再構築'}
          </button>

          {buildResult && (
            <p className="rag-admin-helper">
              {buildResult.message}（合計ベクター数: {buildResult.total_vectors}）
            </p>
          )}
        </section>

        <section className="rag-admin-card">
          <h3 className="rag-admin-section-title">様式名の管理（基準管理）</h3>
          <p className="rag-admin-helper">
            様式コード（01, 02…）の表示名を変更できます。一覧・フィルタ・検索などで使われる名前です。
          </p>
          {formTypesLoading ? (
            <p>読み込み中...</p>
          ) : (
            <div className="rag-admin-form-type-labels-wrap">
              <table className="rag-admin-form-type-labels-table">
                <thead>
                  <tr>
                    <th>様式コード</th>
                    <th>表示名</th>
                    <th className="rag-admin-col-action">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {(formTypesData?.form_types ?? []).map((opt) => (
                    <tr key={opt.value}>
                      <td className="rag-admin-form-type-code">{opt.value}</td>
                      <td>
                        <input
                          type="text"
                          className="rag-admin-form-type-label-input"
                          value={formTypeLabelDrafts[opt.value] ?? opt.label}
                          onChange={(e) =>
                            setFormTypeLabelDrafts((prev) => ({
                              ...prev,
                              [opt.value]: e.target.value,
                            }))
                          }
                          placeholder="表示名を入力"
                        />
                      </td>
                      <td className="rag-admin-col-action">
                        <button
                          type="button"
                          className="rag-admin-button rag-admin-button-small"
                          disabled={updateFormTypeLabelMutation.isPending}
                          onClick={() => {
                            const name = (formTypeLabelDrafts[opt.value] ?? opt.label).trim()
                            if (!name) return
                            updateFormTypeLabelMutation.mutate(
                              { formCode: opt.value, displayName: name },
                              {
                                onSuccess: () => alert('保存しました。'),
                                onError: (err: unknown) => {
                                  const msg =
                                    err && typeof err === 'object' && 'response' in err
                                      ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
                                      : null
                                  alert(msg ? `保存に失敗しました: ${msg}` : '保存に失敗しました。')
                                },
                              }
                            )
                          }}
                        >
                          {updateFormTypeLabelMutation.isPending ? '保存中...' : '保存'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="rag-admin-card rag-admin-card-wide">
          <h3 className="rag-admin-section-title">基準管理情報（master_code.xlsx）</h3>
          <p className="rag-admin-helper">
            取引先・スーパー等のマスタを表示・編集します。各列の検索欄で絞り込みできます。
          </p>
          {masterCodeLoading ? (
            <p>読み込み中...</p>
          ) : (
            <>
              <div className="rag-admin-master-actions rag-admin-master-actions-top">
                <button
                  type="button"
                  className="rag-admin-button primary"
                  onClick={handleSaveMasterCode}
                  disabled={saveMasterCodePending || editedRows.length === 0}
                >
                  {saveMasterCodePending ? '保存中...' : '保存'}
                </button>
              </div>
              <div className="rag-admin-master-grid-wrap">
                <table className="rag-admin-master-table">
                  <thead>
                    <tr>
                      {MASTER_CODE_KEYS.map((key, i) => (
                        <th key={key}>
                          {masterCodeData?.headers?.[i] ?? key}
                        </th>
                      ))}
                      <th className="rag-admin-master-col-action">操作</th>
                    </tr>
                    <tr className="rag-admin-master-filter-row">
                      {MASTER_CODE_KEYS.map((key) => (
                        <th key={key}>
                          <input
                            type="text"
                            className="rag-admin-master-filter-input"
                            placeholder="検索"
                            value={columnFilters[key] ?? ''}
                            onChange={(e) =>
                              setColumnFilters((prev) => ({ ...prev, [key]: e.target.value }))
                            }
                          />
                        </th>
                      ))}
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="rag-admin-master-new-row">
                      {MASTER_CODE_KEYS.map((key) => (
                        <td key={key}>
                          <input
                            type="text"
                            className="rag-admin-master-cell-input"
                            placeholder="追加する値を入力"
                            value={newRowDraft[key] ?? ''}
                            onChange={(e) => handleNewRowDraftChange(key, e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') {
                                e.preventDefault()
                                handleAddMasterCodeRow()
                              }
                            }}
                          />
                        </td>
                      ))}
                      <td className="rag-admin-master-col-action">
                        <button
                          type="button"
                          className="rag-admin-button rag-admin-button-add-row"
                          onClick={handleAddMasterCodeRow}
                        >
                          行を追加
                        </button>
                      </td>
                    </tr>
                    {filteredRows.map(({ row, index }) => (
                      <tr key={index}>
                        {MASTER_CODE_KEYS.map((key) => (
                          <td key={key}>
                            <input
                              type="text"
                              className="rag-admin-master-cell-input"
                              value={row[key] ?? ''}
                              onChange={(e) =>
                                handleMasterCodeCellChange(index, key, e.target.value)
                              }
                            />
                          </td>
                        ))}
                        <td className="rag-admin-master-col-action" />
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="rag-admin-helper">
                表示: {filteredRows.length} / {editedRows.length} 件
              </p>
            </>
          )}
        </section>

      </div>
    </div>
  )
}

