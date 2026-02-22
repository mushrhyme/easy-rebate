import { useState, useMemo, useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ragAdminApi, authApi, type CreateUserPayload, type UpdateUserPayload } from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import './RagAdminPanel.css'

type AdminSubTab = 'master' | 'users'
/** super_import.csv 1行（CSV 5列のみ） */
type CsvRow = {
  super_code: string
  super_name: string
  person_id: string
  person_name: string
  username: string
}
/** users テーブル全項目（UIでは login_count は非表示） */
type UserRow = {
  user_id: number
  username: string
  display_name: string | null
  display_name_ja: string | null
  department_ko: string | null
  department_ja: string | null
  role: string | null
  category: string | null
  is_active: boolean
  created_at?: string | null
  last_login_at?: string | null
}

export const RagAdminPanel = () => {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const isAdmin = user?.username === 'admin'
  const [adminSubTab, setAdminSubTab] = useState<AdminSubTab>('master')

  const {
    data: csvData,
    isLoading: csvLoading,
    refetch: refetchCsv,
  } = useQuery({
    queryKey: ['rag-admin', 'super-import-csv'],
    queryFn: () => ragAdminApi.getSuperImportCsv(),
    enabled: isAdmin,
  })

  const { data: usersData, isLoading: usersLoading, refetch: refetchUsers } = useQuery({
    queryKey: ['admin', 'users'],
    queryFn: () => authApi.getUsers(),
    enabled: isAdmin,
  })

  const updateUserActiveMutation = useMutation({
    mutationFn: ({ userId, isActive }: { userId: number; isActive: boolean }) =>
      authApi.updateUser(userId, { is_active: isActive }),
    onSuccess: () => {
      refetchUsers()
    },
  })

  type UserDraft = {
    display_name: string
    display_name_ja: string
    department_ko: string
    department_ja: string
    role: string
    category: string
  }
  const [userDrafts, setUserDrafts] = useState<Record<number, UserDraft>>({})
  const [newUserDraft, setNewUserDraft] = useState<UserDraft & { username: string }>({
    username: '',
    display_name: '',
    display_name_ja: '',
    department_ko: '',
    department_ja: '',
    role: '',
    category: '',
  })
  const [userFilter, setUserFilter] = useState('')

  useEffect(() => {
    if (usersData && Array.isArray(usersData)) {
      const drafts: Record<number, UserDraft> = {}
      ;(usersData as UserRow[]).forEach((u) => {
        drafts[u.user_id] = {
          display_name: u.display_name ?? '',
          display_name_ja: u.display_name_ja ?? '',
          department_ko: u.department_ko ?? '',
          department_ja: u.department_ja ?? '',
          role: u.role ?? '',
          category: u.category ?? '',
        }
      })
      setUserDrafts(drafts)
    }
  }, [usersData])

  const filteredUsers = useMemo(() => {
    const list = (usersData ?? []) as UserRow[]
    const q = userFilter.trim().toLowerCase()
    if (!q) return list
    return list.filter(
      (u) =>
        (u.username ?? '').toLowerCase().includes(q) ||
        (u.display_name ?? '').toLowerCase().includes(q) ||
        (u.display_name_ja ?? '').toLowerCase().includes(q) ||
        (u.department_ko ?? '').toLowerCase().includes(q) ||
        (u.role ?? '').toLowerCase().includes(q) ||
        (u.category ?? '').toLowerCase().includes(q)
    )
  }, [usersData, userFilter])

  const updateUserInfoMutation = useMutation({
    mutationFn: ({ userId, draft }: { userId: number; draft: UserDraft }) => {
      const payload: UpdateUserPayload = {
        display_name: draft.display_name.trim() || undefined,
        display_name_ja: draft.display_name_ja.trim() || undefined,
        department_ko: draft.department_ko.trim() || undefined,
        department_ja: draft.department_ja.trim() || undefined,
        role: draft.role.trim() || undefined,
        category: draft.category.trim() || undefined,
      }
      return authApi.updateUser(userId, payload)
    },
    onSuccess: () => {
      refetchUsers()
    },
  })

  const createUserMutation = useMutation({
    mutationFn: () => {
      const payload: CreateUserPayload = {
        username: newUserDraft.username.trim(),
        display_name: newUserDraft.display_name.trim() || newUserDraft.username.trim(),
        display_name_ja: newUserDraft.display_name_ja.trim() || undefined,
        department_ko: newUserDraft.department_ko.trim() || undefined,
        department_ja: newUserDraft.department_ja.trim() || undefined,
        role: newUserDraft.role.trim() || undefined,
        category: newUserDraft.category.trim() || undefined,
      }
      return authApi.createUser(payload)
    },
    onSuccess: () => {
      setNewUserDraft({
        username: '',
        display_name: '',
        display_name_ja: '',
        department_ko: '',
        department_ja: '',
        role: '',
        category: '',
      })
      refetchUsers()
    },
  })

  const [csvFilter, setCsvFilter] = useState('')
  const [csvRows, setCsvRows] = useState<CsvRow[]>([])
  /** 新規行入力用（行を追加の上段の5セル） */
  const [newCsvRowDraft, setNewCsvRowDraft] = useState<CsvRow>({
    super_code: '',
    super_name: '',
    person_id: '',
    person_name: '',
    username: '',
  })

  useEffect(() => {
    if (!csvLoading && csvData?.rows) setCsvRows(csvData.rows as CsvRow[])
  }, [csvLoading, csvData])

  const saveCsvMutation = useMutation({
    mutationFn: (rows: CsvRow[]) => ragAdminApi.putSuperImportCsv(rows),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['rag-admin', 'super-import-csv'] })
      refetchCsv()
    },
  })

  const filteredCsvRows = useMemo(() => {
    const q = csvFilter.trim().toLowerCase()
    if (!q) return csvRows
    return csvRows.filter(
      (r) =>
        (r.username ?? '').toLowerCase().includes(q) ||
        (r.super_code ?? '').toLowerCase().includes(q) ||
        (r.super_name ?? '').toLowerCase().includes(q) ||
        (r.person_id ?? '').toLowerCase().includes(q) ||
        (r.person_name ?? '').toLowerCase().includes(q)
    )
  }, [csvRows, csvFilter])

  const updateCsvRow = (index: number, field: keyof CsvRow, value: string) => {
    setCsvRows((prev) =>
      prev.map((row, i) => (i === index ? { ...row, [field]: value } : row))
    )
  }
  const addCsvRow = () => {
    setCsvRows((prev) => [...prev, { ...newCsvRowDraft }])
    setNewCsvRowDraft({
      super_code: '',
      super_name: '',
      person_id: '',
      person_name: '',
      username: '',
    })
  }
  const removeCsvRow = (index: number) => {
    setCsvRows((prev) => prev.filter((_, i) => i !== index))
  }

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
              <h1 className="rag-admin-title-main">基準情報管理</h1>
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
            <h1 className="rag-admin-title-main">基準情報管理</h1>
            <p className="rag-admin-title-sub">Reference & Master Data Admin</p>
          </div>
        </div>
      </div>

      <div className="rag-admin-content">
        <section className="rag-admin-card rag-admin-card-wide">
          <h3 className="rag-admin-section-title">管理マスタ</h3>
          <div className="rag-admin-subtabs">
            <button
              type="button"
              className={`rag-admin-subtab-button ${adminSubTab === 'master' ? 'active' : ''}`}
              onClick={() => setAdminSubTab('master')}
            >
              super_import.csv
            </button>
            <button
              type="button"
              className={`rag-admin-subtab-button ${adminSubTab === 'users' ? 'active' : ''}`}
              onClick={() => setAdminSubTab('users')}
            >
              ユーザー管理
            </button>
          </div>

          {adminSubTab === 'master' && (
            <>
              <p className="rag-admin-helper">
                super_import.csv の内容を表示・編集します。編集後「CSVを保存」でファイルに上書きします。
              </p>
              {csvLoading ? (
                <p>読み込み中...</p>
              ) : (
                <>
                  <div className="rag-admin-master-actions rag-admin-master-actions-top">
                    <input
                      type="text"
                      className="rag-admin-master-filter-input"
                      placeholder="検索（スーパーコード・スーパー名・担当者ID・担当者名・ID）"
                      value={csvFilter}
                      onChange={(e) => setCsvFilter(e.target.value)}
                      style={{ minWidth: '280px' }}
                    />
                  </div>
                  <div className="rag-admin-master-grid-wrap">
                    <table className="rag-admin-master-table">
                      <thead>
                        <tr>
                          <th>代表スーパーコード</th>
                          <th>代表スーパー名</th>
                          <th>担当者ID</th>
                          <th>担当者名</th>
                          <th>ID</th>
                          <th className="rag-admin-master-col-action">操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr className="rag-admin-master-new-row">
                          <td>
                            <input
                              type="text"
                              className="rag-admin-master-cell-input"
                              value={newCsvRowDraft.super_code}
                              onChange={(e) =>
                                setNewCsvRowDraft((prev) => ({ ...prev, super_code: e.target.value }))
                              }
                              placeholder="代表スーパーコード"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className="rag-admin-master-cell-input"
                              value={newCsvRowDraft.super_name}
                              onChange={(e) =>
                                setNewCsvRowDraft((prev) => ({ ...prev, super_name: e.target.value }))
                              }
                              placeholder="代表スーパー名"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className="rag-admin-master-cell-input"
                              value={newCsvRowDraft.person_id}
                              onChange={(e) =>
                                setNewCsvRowDraft((prev) => ({ ...prev, person_id: e.target.value }))
                              }
                              placeholder="担当者ID"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className="rag-admin-master-cell-input"
                              value={newCsvRowDraft.person_name}
                              onChange={(e) =>
                                setNewCsvRowDraft((prev) => ({ ...prev, person_name: e.target.value }))
                              }
                              placeholder="担当者名"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className="rag-admin-master-cell-input"
                              value={newCsvRowDraft.username}
                              onChange={(e) =>
                                setNewCsvRowDraft((prev) => ({ ...prev, username: e.target.value }))
                              }
                              placeholder="ID"
                            />
                          </td>
                          <td className="rag-admin-master-col-action">
                            <button
                              type="button"
                              className="rag-admin-button rag-admin-button-small rag-admin-button-add-row"
                              onClick={addCsvRow}
                            >
                              行を追加
                            </button>
                          </td>
                        </tr>
                        {csvRows.map((row, index) => {
                          const q = csvFilter.trim().toLowerCase()
                          if (
                            q &&
                            ![
                              row.super_code,
                              row.super_name,
                              row.person_id,
                              row.person_name,
                              row.username,
                            ].some((v) => (v || '').toLowerCase().includes(q))
                          )
                            return null
                          return (
                            <tr key={index}>
                              <td>
                                <input
                                  type="text"
                                  className="rag-admin-master-cell-input"
                                  value={row.super_code}
                                  onChange={(e) => updateCsvRow(index, 'super_code', e.target.value)}
                                />
                              </td>
                              <td>
                                <input
                                  type="text"
                                  className="rag-admin-master-cell-input"
                                  value={row.super_name}
                                  onChange={(e) => updateCsvRow(index, 'super_name', e.target.value)}
                                />
                              </td>
                              <td>
                                <input
                                  type="text"
                                  className="rag-admin-master-cell-input"
                                  value={row.person_id}
                                  onChange={(e) => updateCsvRow(index, 'person_id', e.target.value)}
                                />
                              </td>
                              <td>
                                <input
                                  type="text"
                                  className="rag-admin-master-cell-input"
                                  value={row.person_name}
                                  onChange={(e) => updateCsvRow(index, 'person_name', e.target.value)}
                                />
                              </td>
                              <td>
                                <input
                                  type="text"
                                  className="rag-admin-master-cell-input"
                                  value={row.username}
                                  onChange={(e) => updateCsvRow(index, 'username', e.target.value)}
                                />
                              </td>
                              <td className="rag-admin-master-col-action">
                                <button
                                  type="button"
                                  className="rag-admin-button rag-admin-button-small rag-admin-button-danger"
                                  onClick={() => {
                                    if (!window.confirm('この行を削除しますか？')) return
                                    removeCsvRow(index)
                                  }}
                                >
                                  削除
                                </button>
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                  <p className="rag-admin-helper">
                    表示: {filteredCsvRows.length} / {csvRows.length} 件
                  </p>
                  <div className="rag-admin-master-actions">
                    <button
                      type="button"
                      className="rag-admin-button primary"
                      disabled={saveCsvMutation.isPending}
                      onClick={() => {
                        saveCsvMutation.mutate(csvRows, {
                          onSuccess: () => alert('保存しました。'),
                          onError: (err: unknown) => {
                            const msg =
                              err && typeof err === 'object' && 'response' in err
                                ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
                                : null
                            alert(msg ? `保存に失敗: ${msg}` : '保存に失敗しました。')
                          },
                        })
                      }}
                    >
                      {saveCsvMutation.isPending ? '保存中...' : 'CSVを保存'}
                    </button>
                  </div>
                </>
              )}
            </>
          )}

          {adminSubTab === 'users' && (
            <>
              <p className="rag-admin-helper">
                ユーザーDBの全項目を表示・編集します。ログイン回数はUIでは非表示です。
              </p>
              {usersLoading ? (
                <p>読み込み中...</p>
              ) : (
                <>
                  <div className="rag-admin-master-actions rag-admin-master-actions-top">
                    <input
                      type="text"
                      className="rag-admin-master-filter-input"
                      placeholder="検索（ログインID・表示名）"
                      value={userFilter}
                      onChange={(e) => setUserFilter(e.target.value)}
                      style={{ minWidth: '280px' }}
                    />
                  </div>
                  <div className="rag-admin-master-grid-wrap">
                    <table className="rag-admin-users-table">
                      <thead>
                        <tr>
                          <th>ID</th>
                          <th>ログインID</th>
                          <th>表示名(JA)</th>
                          <th>表示名(KO)</th>
                          <th>部署(KO)</th>
                          <th>部署(JA)</th>
                          <th>権限</th>
                          <th>分類</th>
                          <th>状態</th>
                          <th>最終ログイン</th>
                          <th className="rag-admin-master-col-action">操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr className="rag-admin-master-new-row">
                          <td>新規</td>
                          <td>
                            <input
                              type="text"
                              className="rag-admin-master-cell-input"
                              value={newUserDraft.username}
                              onChange={(e) => setNewUserDraft((prev) => ({ ...prev, username: e.target.value }))}
                              placeholder="login_id"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className="rag-admin-master-cell-input"
                              value={newUserDraft.display_name_ja}
                              onChange={(e) => setNewUserDraft((prev) => ({ ...prev, display_name_ja: e.target.value }))}
                              placeholder="表示名(JA)"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className="rag-admin-master-cell-input"
                              value={newUserDraft.display_name}
                              onChange={(e) => setNewUserDraft((prev) => ({ ...prev, display_name: e.target.value }))}
                              placeholder="表示名(KO)"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className="rag-admin-master-cell-input"
                              value={newUserDraft.department_ko}
                              onChange={(e) => setNewUserDraft((prev) => ({ ...prev, department_ko: e.target.value }))}
                              placeholder="部署(KO)"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className="rag-admin-master-cell-input"
                              value={newUserDraft.department_ja}
                              onChange={(e) => setNewUserDraft((prev) => ({ ...prev, department_ja: e.target.value }))}
                              placeholder="部署(JA)"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className="rag-admin-master-cell-input"
                              value={newUserDraft.role}
                              onChange={(e) => setNewUserDraft((prev) => ({ ...prev, role: e.target.value }))}
                              placeholder="権限"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className="rag-admin-master-cell-input"
                              value={newUserDraft.category}
                              onChange={(e) => setNewUserDraft((prev) => ({ ...prev, category: e.target.value }))}
                              placeholder="分類"
                            />
                          </td>
                          <td colSpan={2}>—</td>
                          <td className="rag-admin-master-col-action">
                            <button
                              type="button"
                              className="rag-admin-button rag-admin-button-small rag-admin-button-add-row"
                              disabled={
                                createUserMutation.isPending ||
                                !newUserDraft.username.trim()
                              }
                              onClick={() => createUserMutation.mutate()}
                            >
                              {createUserMutation.isPending ? '追加中...' : 'ユーザー追加'}
                            </button>
                          </td>
                        </tr>
                        {filteredUsers.map((u: UserRow) => {
                          const draft = userDrafts[u.user_id] ?? {
                            display_name: u.display_name ?? '',
                            display_name_ja: u.display_name_ja ?? '',
                            department_ko: u.department_ko ?? '',
                            department_ja: u.department_ja ?? '',
                            role: u.role ?? '',
                            category: u.category ?? '',
                          }
                          return (
                            <tr key={u.user_id}>
                              <td>{u.user_id}</td>
                              <td>{u.username}</td>
                              <td>
                                <input
                                  type="text"
                                  className="rag-admin-master-cell-input"
                                  value={draft.display_name_ja}
                                  onChange={(e) =>
                                    setUserDrafts((prev) => ({
                                      ...prev,
                                      [u.user_id]: { ...(prev[u.user_id] ?? draft), display_name_ja: e.target.value },
                                    }))
                                  }
                                  placeholder="表示名(JA)"
                                />
                              </td>
                              <td>
                                <input
                                  type="text"
                                  className="rag-admin-master-cell-input"
                                  value={draft.display_name}
                                  onChange={(e) =>
                                    setUserDrafts((prev) => ({
                                      ...prev,
                                      [u.user_id]: { ...(prev[u.user_id] ?? draft), display_name: e.target.value },
                                    }))
                                  }
                                  placeholder="表示名(KO)"
                                />
                              </td>
                              <td>
                                <input
                                  type="text"
                                  className="rag-admin-master-cell-input"
                                  value={draft.department_ko}
                                  onChange={(e) =>
                                    setUserDrafts((prev) => ({
                                      ...prev,
                                      [u.user_id]: { ...(prev[u.user_id] ?? draft), department_ko: e.target.value },
                                    }))
                                  }
                                  placeholder="部署(KO)"
                                />
                              </td>
                              <td>
                                <input
                                  type="text"
                                  className="rag-admin-master-cell-input"
                                  value={draft.department_ja}
                                  onChange={(e) =>
                                    setUserDrafts((prev) => ({
                                      ...prev,
                                      [u.user_id]: { ...(prev[u.user_id] ?? draft), department_ja: e.target.value },
                                    }))
                                  }
                                  placeholder="部署(JA)"
                                />
                              </td>
                              <td>
                                <input
                                  type="text"
                                  className="rag-admin-master-cell-input"
                                  value={draft.role}
                                  onChange={(e) =>
                                    setUserDrafts((prev) => ({
                                      ...prev,
                                      [u.user_id]: { ...(prev[u.user_id] ?? draft), role: e.target.value },
                                    }))
                                  }
                                  placeholder="権限"
                                />
                              </td>
                              <td>
                                <input
                                  type="text"
                                  className="rag-admin-master-cell-input"
                                  value={draft.category}
                                  onChange={(e) =>
                                    setUserDrafts((prev) => ({
                                      ...prev,
                                      [u.user_id]: { ...(prev[u.user_id] ?? draft), category: e.target.value },
                                    }))
                                  }
                                  placeholder="分類"
                                />
                              </td>
                              <td>{u.is_active ? '有効' : '無効'}</td>
                              <td>{u.last_login_at ?? '—'}</td>
                              <td className="rag-admin-master-col-action">
                                <button
                                  type="button"
                                  className="rag-admin-button rag-admin-button-small"
                                  disabled={updateUserInfoMutation.isPending}
                                  onClick={() =>
                                    updateUserInfoMutation.mutate({ userId: u.user_id, draft })
                                  }
                                >
                                  {updateUserInfoMutation.isPending ? '保存中...' : '保存'}
                                </button>
                                <button
                                  type="button"
                                  className="rag-admin-button rag-admin-button-small rag-admin-button-danger"
                                  disabled={updateUserActiveMutation.isPending || u.user_id === user?.user_id}
                                  onClick={() =>
                                    updateUserActiveMutation.mutate({
                                      userId: u.user_id,
                                      isActive: !u.is_active,
                                    })
                                  }
                                >
                                  {u.is_active ? '無効化' : '有効化'}
                                </button>
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                  <p className="rag-admin-helper">
                    表示: {filteredUsers.length} / {(usersData ?? []).length} 件
                  </p>
                </>
              )}
            </>
          )}
        </section>

      </div>
    </div>
  )
}

