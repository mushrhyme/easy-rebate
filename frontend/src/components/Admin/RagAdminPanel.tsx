import { useState, useMemo, useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ragAdminApi, authApi, type CreateUserPayload, type UpdateUserPayload } from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import './RagAdminPanel.css'

type AdminSubTab = 'dist_retail' | 'master' | 'users'
/** dist_retail.csv 1行（CSV 6列） */
type DistRetailRow = {
  dist_code: string
  dist_name: string
  super_code: string
  super_name: string
  person_id: string
  person_name: string
}
/** retail_user.csv 1行（CSV 5列のみ） */
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
  is_admin?: boolean
  created_at?: string | null
  last_login_at?: string | null
}

export const RagAdminPanel = () => {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const isAdmin = user?.is_admin === true || user?.username === 'admin'
  const [adminSubTab, setAdminSubTab] = useState<AdminSubTab>('dist_retail')

  const {
    data: csvData,
    isLoading: csvLoading,
    refetch: refetchCsv,
  } = useQuery({
    queryKey: ['rag-admin', 'retail-user-csv'],
    queryFn: () => ragAdminApi.getRetailUserCsv(),
    enabled: isAdmin,
  })

  const { data: usersData, isLoading: usersLoading, refetch: refetchUsers } = useQuery({
    queryKey: ['admin', 'users'],
    queryFn: () => authApi.getUsers(),
    enabled: isAdmin,
  })

  const { data: retailRagAnswerData, isLoading: retailRagAnswerLoading } = useQuery({
    queryKey: ['rag-admin', 'retail-rag-answer-items'],
    queryFn: () => ragAdminApi.getRetailRagAnswerItems(),
    enabled: isAdmin,
  })
  const retailRagAnswerItems = (retailRagAnswerData?.items ?? []) as Array<{
    得意先: string
    受注先CD: string
    小売先CD: string
  }>

  const rebuildRetailRagIndexMutation = useMutation({
    mutationFn: () => ragAdminApi.rebuildRetailRagAnswerIndex(),
    onSuccess: (data) => {
      alert(`벡터 인덱스 구축 완료: ${data.vector_count}건`)
    },
    onError: (err: any) => {
      alert(err?.response?.data?.detail ?? err?.message ?? '인덱스 구축 실패')
    },
  })

  const deleteUserMutation = useMutation({
    mutationFn: (userId: number) => authApi.deleteUser(userId),
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
  const [resettingPasswordUserId, setResettingPasswordUserId] = useState<number | null>(null)

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
    const filtered = q
      ? list.filter(
          (u) =>
            (u.username ?? '').toLowerCase().includes(q) ||
            (u.display_name ?? '').toLowerCase().includes(q) ||
            (u.display_name_ja ?? '').toLowerCase().includes(q) ||
            (u.department_ko ?? '').toLowerCase().includes(q) ||
            (u.role ?? '').toLowerCase().includes(q) ||
            (u.category ?? '').toLowerCase().includes(q)
        )
      : list
    return [...filtered].sort((a, b) => a.user_id - b.user_id)
  }, [usersData, userFilter])

  const saveAllUsersMutation = useMutation({
    mutationFn: async () => {
      const promises = Object.entries(userDrafts).map(([userId, draft]) => {
        const payload: UpdateUserPayload = {
          display_name: draft.display_name.trim() || undefined,
          display_name_ja: draft.display_name_ja.trim() || undefined,
          department_ko: draft.department_ko.trim() || undefined,
          department_ja: draft.department_ja.trim() || undefined,
          role: draft.role.trim() || undefined,
          category: draft.category.trim() || undefined,
        }
        return authApi.updateUser(Number(userId), payload)
      })
      return Promise.all(promises)
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

  // ---- 販売先-小売先 (dist_retail.csv) ----
  const {
    data: distRetailData,
    isLoading: distRetailLoading,
    refetch: refetchDistRetail,
  } = useQuery({
    queryKey: ['rag-admin', 'dist-retail-csv'],
    queryFn: () => ragAdminApi.getDistRetailCsv(),
    enabled: isAdmin,
  })

  const [distRetailFilter, setDistRetailFilter] = useState('')
  const [distRetailRows, setDistRetailRows] = useState<DistRetailRow[]>([])
  const [newDistRetailDraft, setNewDistRetailDraft] = useState<DistRetailRow>({
    dist_code: '', dist_name: '', super_code: '', super_name: '', person_id: '', person_name: '',
  })

  useEffect(() => {
    if (!distRetailLoading && distRetailData?.rows) setDistRetailRows(distRetailData.rows as DistRetailRow[])
  }, [distRetailLoading, distRetailData])

  const saveDistRetailMutation = useMutation({
    mutationFn: (rows: DistRetailRow[]) => ragAdminApi.putDistRetailCsv(rows),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['rag-admin', 'dist-retail-csv'] })
      refetchDistRetail()
    },
  })

  const filteredDistRetailRows = useMemo(() => {
    const q = distRetailFilter.trim().toLowerCase()
    const filtered = q
      ? distRetailRows.filter((r) =>
          (r.dist_code ?? '').toLowerCase().includes(q) ||
          (r.dist_name ?? '').toLowerCase().includes(q) ||
          (r.super_code ?? '').toLowerCase().includes(q) ||
          (r.super_name ?? '').toLowerCase().includes(q) ||
          (r.person_id ?? '').toLowerCase().includes(q) ||
          (r.person_name ?? '').toLowerCase().includes(q)
        )
      : distRetailRows
    return [...filtered].sort((a, b) =>
      (a.dist_code ?? '').localeCompare(b.dist_code ?? '') ||
      (a.super_code ?? '').localeCompare(b.super_code ?? '')
    )
  }, [distRetailRows, distRetailFilter])

  const updateDistRetailRow = (index: number, field: keyof DistRetailRow, value: string) => {
    setDistRetailRows((prev) => prev.map((row, i) => (i === index ? { ...row, [field]: value } : row)))
  }
  const addDistRetailRow = () => {
    setDistRetailRows((prev) => [...prev, { ...newDistRetailDraft }])
    setNewDistRetailDraft({ dist_code: '', dist_name: '', super_code: '', super_name: '', person_id: '', person_name: '' })
  }
  const removeDistRetailRow = (index: number) => {
    setDistRetailRows((prev) => prev.filter((_, i) => i !== index))
  }

  // ---- 小売先管理 (retail_user.csv) ----
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
    mutationFn: (rows: CsvRow[]) => ragAdminApi.putRetailUserCsv(rows),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['rag-admin', 'retail-user-csv'] })
      refetchCsv()
    },
  })

  const filteredCsvRows = useMemo(() => {
    const q = csvFilter.trim().toLowerCase()
    const filtered = q
      ? csvRows.filter(
          (r) =>
            (r.username ?? '').toLowerCase().includes(q) ||
            (r.super_code ?? '').toLowerCase().includes(q) ||
            (r.super_name ?? '').toLowerCase().includes(q) ||
            (r.person_id ?? '').toLowerCase().includes(q) ||
            (r.person_name ?? '').toLowerCase().includes(q)
        )
      : csvRows
    return [...filtered].sort((a, b) =>
      (a.super_code ?? '').localeCompare(b.super_code ?? '') ||
      (a.person_id ?? '').localeCompare(b.person_id ?? '')
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
            <p className="rag-admin-title-sub">Master Data Management</p>
          </div>
        </div>
      </div>

      <div className="rag-admin-content">
        <section className="rag-admin-card rag-admin-card-wide">
          <h3 className="rag-admin-section-title">판매처-소매처 RAG 정답지</h3>
          <p className="rag-admin-helper">
            created_by_user_id가 null이 아닌 문서에 속한 item의 得意先 / 受注先CD / 小売先CD 목록입니다. 아래 목록으로 벡터 인덱스를 구축하면 매핑 모달 4번(得意先 RAG 정답지 類似度)에서 검색됩니다.
          </p>
          <p className="rag-admin-helper">
            <button
              type="button"
              className="rag-admin-button primary"
              disabled={rebuildRetailRagIndexMutation.isPending || retailRagAnswerItems.length === 0}
              onClick={() => rebuildRetailRagIndexMutation.mutate()}
            >
              {rebuildRetailRagIndexMutation.isPending ? '구축 중…' : '벡터 인덱스 재구축'}
            </button>
          </p>
          {retailRagAnswerLoading ? (
            <p>読み込み中...</p>
          ) : (
            <div className="rag-admin-master-grid-wrap">
              <table className="rag-admin-master-table">
                <thead>
                  <tr>
                    <th>得意先</th>
                    <th>受注先CD</th>
                    <th>小売先CD</th>
                  </tr>
                </thead>
                <tbody>
                  {retailRagAnswerItems.length === 0 ? (
                    <tr>
                      <td colSpan={3}>該当データがありません。</td>
                    </tr>
                  ) : (
                    retailRagAnswerItems.map((row, idx) => (
                      <tr key={idx}>
                        <td>{row.得意先 || '—'}</td>
                        <td>{row.受注先CD || '—'}</td>
                        <td>{row.小売先CD || '—'}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="rag-admin-card rag-admin-card-wide">
          <h3 className="rag-admin-section-title">管理マスタ</h3>
          <div className="rag-admin-subtabs">
            <button
              type="button"
              className={`rag-admin-subtab-button ${adminSubTab === 'dist_retail' ? 'active' : ''}`}
              onClick={() => setAdminSubTab('dist_retail')}
            >
              販売先-小売先
            </button>
            <button
              type="button"
              className={`rag-admin-subtab-button ${adminSubTab === 'master' ? 'active' : ''}`}
              onClick={() => setAdminSubTab('master')}
            >
              小売先-担当者
            </button>
            <button
              type="button"
              className={`rag-admin-subtab-button ${adminSubTab === 'users' ? 'active' : ''}`}
              onClick={() => setAdminSubTab('users')}
            >
              ユーザーアカウント
            </button>
          </div>

          {adminSubTab === 'dist_retail' && (
            <>
              <p className="rag-admin-helper">
                販売先と小売先のマッピングを表示・編集します。編集後「保存」で上書きします。
              </p>
              {distRetailLoading ? (
                <p>読み込み中...</p>
              ) : (
                <>
                  <div className="rag-admin-master-actions rag-admin-master-actions-top">
                    <div className="rag-admin-search-wrap" role="search">
                      <svg className="rag-admin-search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                        <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
                      </svg>
                      <input
                        type="search"
                        className="rag-admin-master-filter-input"
                        placeholder="販売先コード・販売先名・スーパーコード・スーパー名・担当者ID・担当者名"
                        value={distRetailFilter}
                        onChange={(e) => setDistRetailFilter(e.target.value)}
                        aria-label="検索"
                      />
                    </div>
                  </div>
                  <div className="rag-admin-master-grid-wrap">
                    <table className="rag-admin-master-table">
                      <thead>
                        <tr>
                          <th>販売先コード</th>
                          <th>販売先名</th>
                          <th>代表スーパーコード</th>
                          <th>代表スーパー名</th>
                          <th>担当者ID</th>
                          <th>担当者名</th>
                          <th className="rag-admin-master-col-action">操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr className="rag-admin-master-new-row">
                          <td>
                            <input type="text" className="rag-admin-master-cell-input"
                              value={newDistRetailDraft.dist_code}
                              onChange={(e) => setNewDistRetailDraft((prev) => ({ ...prev, dist_code: e.target.value }))}
                              placeholder="販売先コード" />
                          </td>
                          <td>
                            <input type="text" className="rag-admin-master-cell-input"
                              value={newDistRetailDraft.dist_name}
                              onChange={(e) => setNewDistRetailDraft((prev) => ({ ...prev, dist_name: e.target.value }))}
                              placeholder="販売先名" />
                          </td>
                          <td>
                            <input type="text" className="rag-admin-master-cell-input"
                              value={newDistRetailDraft.super_code}
                              onChange={(e) => setNewDistRetailDraft((prev) => ({ ...prev, super_code: e.target.value }))}
                              placeholder="代表スーパーコード" />
                          </td>
                          <td>
                            <input type="text" className="rag-admin-master-cell-input"
                              value={newDistRetailDraft.super_name}
                              onChange={(e) => setNewDistRetailDraft((prev) => ({ ...prev, super_name: e.target.value }))}
                              placeholder="代表スーパー名" />
                          </td>
                          <td>
                            <input type="text" className="rag-admin-master-cell-input"
                              value={newDistRetailDraft.person_id}
                              onChange={(e) => setNewDistRetailDraft((prev) => ({ ...prev, person_id: e.target.value }))}
                              placeholder="担当者ID" />
                          </td>
                          <td>
                            <input type="text" className="rag-admin-master-cell-input"
                              value={newDistRetailDraft.person_name}
                              onChange={(e) => setNewDistRetailDraft((prev) => ({ ...prev, person_name: e.target.value }))}
                              placeholder="担当者名" />
                          </td>
                          <td className="rag-admin-master-col-action">
                            <button
                              type="button"
                              className="rag-admin-button rag-admin-button-small rag-admin-button-add-row"
                              onClick={addDistRetailRow}
                            >
                              行を追加
                            </button>
                          </td>
                        </tr>
                        {distRetailRows.map((row, index) => {
                          const q = distRetailFilter.trim().toLowerCase()
                          if (
                            q &&
                            ![row.dist_code, row.dist_name, row.super_code, row.super_name, row.person_id, row.person_name]
                              .some((v) => (v || '').toLowerCase().includes(q))
                          ) return null
                          return (
                            <tr key={index}>
                              <td>
                                <input type="text" className="rag-admin-master-cell-input"
                                  value={row.dist_code}
                                  onChange={(e) => updateDistRetailRow(index, 'dist_code', e.target.value)} />
                              </td>
                              <td>
                                <input type="text" className="rag-admin-master-cell-input"
                                  value={row.dist_name}
                                  onChange={(e) => updateDistRetailRow(index, 'dist_name', e.target.value)} />
                              </td>
                              <td>
                                <input type="text" className="rag-admin-master-cell-input"
                                  value={row.super_code}
                                  onChange={(e) => updateDistRetailRow(index, 'super_code', e.target.value)} />
                              </td>
                              <td>
                                <input type="text" className="rag-admin-master-cell-input"
                                  value={row.super_name}
                                  onChange={(e) => updateDistRetailRow(index, 'super_name', e.target.value)} />
                              </td>
                              <td>
                                <input type="text" className="rag-admin-master-cell-input"
                                  value={row.person_id}
                                  onChange={(e) => updateDistRetailRow(index, 'person_id', e.target.value)} />
                              </td>
                              <td>
                                <input type="text" className="rag-admin-master-cell-input"
                                  value={row.person_name}
                                  onChange={(e) => updateDistRetailRow(index, 'person_name', e.target.value)} />
                              </td>
                              <td className="rag-admin-master-col-action">
                                <button
                                  type="button"
                                  className="rag-admin-button rag-admin-button-small rag-admin-button-danger"
                                  onClick={() => {
                                    if (!window.confirm('この行を削除しますか？')) return
                                    removeDistRetailRow(index)
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
                    表示: {filteredDistRetailRows.length} / {distRetailRows.length} 件
                  </p>
                  <div className="rag-admin-master-actions">
                    <button
                      type="button"
                      className="rag-admin-button primary"
                      disabled={saveDistRetailMutation.isPending}
                      onClick={() => {
                        saveDistRetailMutation.mutate(distRetailRows, {
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
                      {saveDistRetailMutation.isPending ? '保存中...' : '保存'}
                    </button>
                  </div>
                </>
              )}
            </>
          )}

          {adminSubTab === 'master' && (
            <>
              <p className="rag-admin-helper">
                小売店マスターの内容を表示し、編集します。 編集後、ファイルを「保存」で上書きします。
              </p>
              {csvLoading ? (
                <p>読み込み中...</p>
              ) : (
                <>
                  <div className="rag-admin-master-actions rag-admin-master-actions-top">
                    <div className="rag-admin-search-wrap" role="search">
                      <svg className="rag-admin-search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                        <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
                      </svg>
                      <input
                        type="search"
                        className="rag-admin-master-filter-input"
                        placeholder="スーパーコード・スーパー名・担当者ID・担当者名・ID"
                        value={csvFilter}
                        onChange={(e) => setCsvFilter(e.target.value)}
                        aria-label="検索"
                      />
                    </div>
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
                      {saveCsvMutation.isPending ? '保存中...' : '保存'}
                    </button>
                  </div>
                </>
              )}
            </>
          )}

          {adminSubTab === 'users' && (
            <>
              <p className="rag-admin-helper">
                ユーザーDBの全項目を表示・編集します。ログイン回数はUIでは非表示です。初期パスワードはログインIDと同一です。「初期化」でログインIDと同一のパスワードに戻します（忘れた場合に使用）。
              </p>
              {usersLoading ? (
                <p>読み込み中...</p>
              ) : (
                <>
                  <div className="rag-admin-master-actions rag-admin-master-actions-top">
                    <div className="rag-admin-search-wrap" role="search">
                      <svg className="rag-admin-search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                        <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
                      </svg>
                      <input
                        type="search"
                        className="rag-admin-master-filter-input"
                        placeholder="ユーザー名・表示名・部署・権限・分類で検索"
                        value={userFilter}
                        onChange={(e) => setUserFilter(e.target.value)}
                        aria-label="検索"
                      />
                    </div>
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
                          <th className="rag-admin-th-password">パスワード</th>
                          <th className="rag-admin-th-admin">管理者</th>
                          <th className="rag-admin-th-lastlogin">最終ログイン</th>
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
                          <td>—</td>
                          <td className="rag-admin-th-admin">—</td>
                          <td>—</td>
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
                              {createUserMutation.isPending ? '追加中...' : '行を追加'}
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
                              <td className="rag-admin-users-password-cell">
                                <button
                                  type="button"
                                  className="rag-admin-button rag-admin-button-small"
                                  disabled={resettingPasswordUserId !== null}
                                  onClick={async () => {
                                    setResettingPasswordUserId(u.user_id)
                                    try {
                                      await authApi.updateUser(u.user_id, { password: '' })
                                      refetchUsers()
                                    } catch (err: unknown) {
                                      const msg =
                                        err && typeof err === 'object' && 'response' in err
                                          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
                                          : null
                                      alert(msg ? `初期化に失敗: ${msg}` : '初期化に失敗しました。')
                                    } finally {
                                      setResettingPasswordUserId(null)
                                    }
                                  }}
                                >
                                  {resettingPasswordUserId === u.user_id ? '初期化中...' : '初期化'}
                                </button>
                              </td>
                              <td className="rag-admin-th-admin">
                                <input
                                  type="checkbox"
                                  checked={!!u.is_admin}
                                  disabled={u.user_id === user?.user_id}
                                  title={u.user_id === user?.user_id ? '自分自身の管理者権限は変更できません' : ''}
                                  onChange={async () => {
                                    const next = !u.is_admin
                                    try {
                                      await authApi.updateUser(u.user_id, { is_admin: next })
                                      refetchUsers()
                                    } catch (e) {
                                      alert('管理者権限の更新に失敗しました')
                                    }
                                  }}
                                />
                              </td>
                              <td className="rag-admin-cell-lastlogin" title={u.last_login_at ?? undefined}>
                                  {u.last_login_at
                                    ? u.last_login_at.replace('T', ' ').slice(0, 19)
                                    : '—'}
                                </td>
                              <td className="rag-admin-master-col-action">
                                <button
                                  type="button"
                                  className="rag-admin-button rag-admin-button-small rag-admin-button-danger"
                                  disabled={deleteUserMutation.isPending || u.user_id === user?.user_id}
                                  onClick={() => {
                                    if (!window.confirm(`「${u.username}」を削除しますか？この操作は元に戻せません。`)) return
                                    deleteUserMutation.mutate(u.user_id)
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
                    表示: {filteredUsers.length} / {(usersData ?? []).length} 件
                  </p>
                  <div className="rag-admin-master-actions">
                    <button
                      type="button"
                      className="rag-admin-button primary"
                      disabled={
                        saveAllUsersMutation.isPending ||
                        Object.keys(userDrafts).length === 0
                      }
                      onClick={() => saveAllUsersMutation.mutate()}
                    >
                      {saveAllUsersMutation.isPending ? '保存中...' : '保存'}
                    </button>
                  </div>
                </>
              )}
            </>
          )}
        </section>

      </div>
    </div>
  )
}

