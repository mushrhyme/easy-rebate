import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ragAdminApi } from '@/api/client'
import { FORM_TYPES } from '@/config/formConfig'
import { useAuth } from '@/contexts/AuthContext'
import './RagAdminPanel.css'

export const RagAdminPanel = () => {
  const { user } = useAuth()
  const isAdmin = user?.username === 'admin'

  const [selectedFormType, setSelectedFormType] = useState<string | 'all'>('all')
  // 현재는 img 폴더 기반 생성 + 체크된 페이지 기반 생성만 사용

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
    mutationFn: async () => {
      const formType = selectedFormType === 'all' ? undefined : selectedFormType
      return ragAdminApi.build(formType)
    },
    onSuccess: () => {
      refetchStatus()
    },
  })

  const {
    data: learningPages,
  } = useQuery({
    queryKey: ['rag-admin', 'learning-pages'],
    queryFn: () => ragAdminApi.getLearningPages(),
  })

  const {
    mutateAsync: buildFromLearningPages,
    isPending: buildFromLearningPagesPending,
  } = useMutation({
    mutationKey: ['rag-admin', 'build-from-learning-pages'],
    mutationFn: async () => {
      const formType = selectedFormType === 'all' ? undefined : selectedFormType
      return ragAdminApi.buildFromLearningPages(formType)
    },
    onSuccess: () => {
      refetchStatus()
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
      selectedFormType === 'all'
        ? '全てのフォーム種別についてベクターDBを再構築します。時間がかかる場合があります。本当に実行しますか？'
        : `フォーム種別 ${selectedFormType} のベクターDBを再構築します。実行しますか？`
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

  const handleBuildFromLearningPagesClick = async () => {
    const count = learningPages?.count ?? 0
    if (buildFromLearningPagesPending) return
    if (!count) {
      alert('チェックされたページがありません。')
      return
    }
    const confirmMessage = `チェックされた ${count} ページからベクターを生成しますか？`
    if (!window.confirm(confirmMessage)) return

    try {
      const result = await buildFromLearningPages()
      alert(
        `${result.message}\n処理対象ページ数: ${result.processed_pages}\n合計ベクター数: ${result.total_vectors}`,
      )
    } catch (error: any) {
      const message =
        error?.response?.data?.detail ||
        error?.message ||
        'チェックされたページからのベクター生成中にエラーが発生しました。'
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
          <h3 className="rag-admin-section-title">チェック済みページからベクター生成</h3>
          <p className="rag-admin-helper">
            現在チェックされているページ数:{' '}
            <strong>{learningPages?.count ?? 0}</strong>
          </p>
          <button
            type="button"
            onClick={handleBuildFromLearningPagesClick}
            disabled={buildFromLearningPagesPending || !learningPages?.count}
            className="rag-admin-button success"
          >
            {buildFromLearningPagesPending ? '生成中...' : 'チェックされたページでベクター生成'}
          </button>
        </section>

        <section className="rag-admin-card">
          <h3 className="rag-admin-section-title">img フォルダからのベクターDB再構築</h3>

          <div className="rag-admin-field">
            <label htmlFor="form-type-select" className="rag-admin-label">
              対象フォーム種別
            </label>
          <select
            id="form-type-select"
            value={selectedFormType}
            onChange={(e) => setSelectedFormType(e.target.value as any)}
            style={{
              minWidth: '140px',
              padding: '6px 8px',
              borderRadius: '4px',
              border: '1px solid #cbd5f5',
              fontSize: '13px',
            }}
          >
            <option value="all">全て</option>
            {FORM_TYPES.map((ft) => (
              <option key={ft} value={ft}>
                {ft}
              </option>
            ))}
          </select>
          </div>

          <button
            type="button"
            onClick={handleBuildClick}
            disabled={buildPending}
            className="rag-admin-button primary"
          >
            {buildPending ? '再構築中...' : 'ベクターDBを再構築'}
          </button>

          {buildResult && (
            <p className="rag-admin-helper">
              {buildResult.message}（合計ベクター数: {buildResult.total_vectors}）
            </p>
          )}
        </section>

      </div>
    </div>
  )
}

