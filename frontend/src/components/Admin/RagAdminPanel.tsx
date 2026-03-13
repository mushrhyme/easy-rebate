import { useState, useMemo, useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ragAdminApi, authApi, type CreateUserPayload, type UpdateUserPayload } from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import './RagAdminPanel.css'

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

  const {
    data: csvListData,
    isError: csvListError,
    error: csvListErrorDetail,
  } = useQuery({
    queryKey: ['rag-admin', 'csv-list'],
    queryFn: () => ragAdminApi.getCsvList(),
    enabled: isAdmin,
  })
  const csvFiles = (csvListData?.files ?? []).filter((f) => f !== 'users_import')
  const [adminSubTab, setAdminSubTab] = useState<string>('')
  useEffect(() => {
    if (adminSubTab === '' && csvFiles.length > 0) setAdminSubTab(csvFiles[0])
    else if (adminSubTab === '' && csvFiles.length === 0) setAdminSubTab('users')
  }, [csvFiles, adminSubTab])
  const effectiveTab = adminSubTab === '' ? (csvFiles[0] ?? 'users') : adminSubTab
  const isUsersTab = effectiveTab === 'users'
  const activeCsvTab = csvFiles.includes(effectiveTab) ? effectiveTab : ''

  const { data: csvContent, isLoading: csvContentLoading, refetch: refetchCsvContent } = useQuery({
    queryKey: ['rag-admin', 'csv', activeCsvTab],
    queryFn: () => ragAdminApi.getCsv(activeCsvTab),
    enabled: isAdmin && activeCsvTab !== '',
  })
  const [csvFilter, setCsvFilter] = useState('')
  const csvHeaders = csvContent?.headers ?? []
  const csvRows = csvContent?.rows ?? []
  const filteredCsvRows = useMemo(() => {
    const q = csvFilter.trim().toLowerCase()
    if (!q) return csvRows
    return csvRows.filter((row) =>
      Object.values(row).some((v) => String(v ?? '').toLowerCase().includes(q))
    )
  }, [csvRows, csvFilter])

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
    受注先コード: string
    小売先コード: string
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

  const { data: productRagAnswerData, isLoading: productRagAnswerLoading } = useQuery({
    queryKey: ['rag-admin', 'product-rag-answer-items'],
    queryFn: () => ragAdminApi.getProductRagAnswerItems(),
    enabled: isAdmin,
  })
  const productRagAnswerItems = (productRagAnswerData?.items ?? []) as Array<{
    商品名: string
    商品コード: string
    仕切: string
    本部長: string
  }>

  const rebuildProductRagIndexMutation = useMutation({
    mutationFn: () => ragAdminApi.rebuildProductRagAnswerIndex(),
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
            created_by_user_id가 null이 아닌 문서에 속한 item의 得意先 / 受注先コード / 小売先コード 목록입니다. 아래 목록으로 벡터 인덱스를 구축하면 매핑 모달 1번(得意先 RAG 정답지 類似度)에서 검색됩니다.
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
                    <th>受注先コード</th>
                    <th>小売先コード</th>
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
                        <td>{row.受注先コード || '—'}</td>
                        <td>{row.小売先コード || '—'}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="rag-admin-card rag-admin-card-wide">
          <h3 className="rag-admin-section-title">제품 RAG 정답지</h3>
          <p className="rag-admin-helper">
            created_by_user_id가 null이 아닌 문서에 속한 item의 商品名 / 商品コード / 仕切 / 本部長 목록입니다. 아래 목록으로 벡터 인덱스를 구축하면 商品名→商品コード 매핑 시 RAG 검색이 우선 적용됩니다.
          </p>
          <p className="rag-admin-helper">
            <button
              type="button"
              className="rag-admin-button primary"
              disabled={rebuildProductRagIndexMutation.isPending || productRagAnswerItems.length === 0}
              onClick={() => rebuildProductRagIndexMutation.mutate()}
            >
              {rebuildProductRagIndexMutation.isPending ? '구축 중…' : '벡터 인덱스 재구축'}
            </button>
          </p>
          {productRagAnswerLoading ? (
            <p>読み込み中...</p>
          ) : (
            <div className="rag-admin-master-grid-wrap">
              <table className="rag-admin-master-table">
                <thead>
                  <tr>
                    <th>商品名</th>
                    <th>商品コード</th>
                    <th>仕切</th>
                    <th>本部長</th>
                  </tr>
                </thead>
                <tbody>
                  {productRagAnswerItems.length === 0 ? (
                    <tr>
                      <td colSpan={4}>該当データがありません。</td>
                    </tr>
                  ) : (
                    productRagAnswerItems.map((row, idx) => (
                      <tr key={idx}>
                        <td>{row.商品名 || '—'}</td>
                        <td>{row.商品コード || '—'}</td>
                        <td>{row.仕切 || '—'}</td>
                        <td>{row.本部長 || '—'}</td>
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
          {csvListError && (
            <p className="rag-admin-helper" style={{ color: '#c53030' }}>
              csv-list 로드 실패: {(csvListErrorDetail as { message?: string })?.message ?? String(csvListErrorDetail)}. 백엔드 로그에서 CSV_DIR 경로 확인.
            </p>
          )}
          <div className="rag-admin-subtabs">
            {csvFiles.map((name) => (
              <button
                key={name}
                type="button"
                className={`rag-admin-subtab-button ${effectiveTab === name ? 'active' : ''}`}
                onClick={() => setAdminSubTab(name)}
              >
                {name}
              </button>
            ))}
            <button
              type="button"
              className={`rag-admin-subtab-button ${isUsersTab ? 'active' : ''}`}
              onClick={() => setAdminSubTab('users')}
            >
              users
            </button>
          </div>

          {activeCsvTab !== '' && (
            <>
              <p className="rag-admin-helper">
                CSV 内容を表示します。Excel ダウンロード・アップロードで database/csv/{activeCsvTab}.csv を上書きできます。
              </p>
              {csvContentLoading ? (
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
                        placeholder="検索"
                        value={csvFilter}
                        onChange={(e) => setCsvFilter(e.target.value)}
                        aria-label="検索"
                      />
                    </div>
                    <button
                      type="button"
                      className="rag-admin-button"
                      onClick={async () => {
                        try {
                          const blob = await ragAdminApi.downloadCsvExcel(activeCsvTab)
                          const url = URL.createObjectURL(blob)
                          const a = document.createElement('a')
                          a.href = url
                          a.download = `${activeCsvTab}.xlsx`
                          a.click()
                          URL.revokeObjectURL(url)
                        } catch (e) {
                          alert('ダウンロードに失敗しました')
                        }
                      }}
                    >
                      ダウンロード
                    </button>
                    <label className="rag-admin-button">
                      アップロード
                      <input
                        type="file"
                        accept=".csv,.xlsx"
                        className="sr-only"
                        onChange={async (e) => {
                          const f = e.target.files?.[0]
                          if (!f) return
                          try {
                            await ragAdminApi.uploadCsv(activeCsvTab, f)
                            refetchCsvContent()
                            alert('上書きしました')
                          } catch (err: unknown) {
                            const msg = err && typeof err === 'object' && 'response' in err
                              ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
                              : null
                            alert(msg ? `アップロード失敗: ${msg}` : 'アップロードに失敗しました')
                          }
                          e.target.value = ''
                        }}
                      />
                    </label>
                  </div>
                  <div className="rag-admin-master-grid-wrap">
                    <table className="rag-admin-master-table">
                      <thead>
                        <tr>
                          {csvHeaders.map((h) => (
                            <th key={h}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {filteredCsvRows.length === 0 ? (
                          <tr>
                            <td colSpan={csvHeaders.length || 1}>該当データがありません。</td>
                          </tr>
                        ) : (
                          filteredCsvRows.map((row, index) => (
                            <tr key={index}>
                              {csvHeaders.map((h) => (
                                <td key={h}>{row[h] ?? '—'}</td>
                              ))}
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                  <p className="rag-admin-helper">
                    表示: {filteredCsvRows.length} / {csvRows.length} 件
                  </p>
                </>
              )}
            </>
          )}

          {isUsersTab && (
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

