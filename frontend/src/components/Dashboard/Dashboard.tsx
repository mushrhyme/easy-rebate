/**
 * 現況（ダッシュボード）タブ
 * 文書・検討・RAG の統計を一覧表示
 */
import { useMemo, useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import { documentsApi, itemsApi, ragAdminApi, formTypesApi } from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import { useFormTypes } from '@/hooks/useFormTypes'
import './Dashboard.css'

const CHART_HUE_COLORS = ['#667eea', '#764ba2', '#10b981', '#f59e0b', '#ef4444', '#06b6d4']

export interface DashboardProps {
  /** 해당 문서로 정답지 탭을 열 때 호출 (문서 선택 시 정답지 탭으로 전환) */
  /** RAG 문서 클릭 시 정답지 탭으로 이동. relative_path 있으면 img 기반 뷰 사용 */
  onOpenAnswerKeyWithDocument?: (payload: {
    pdf_filename: string
    total_pages: number
    relative_path: string | null
  }) => void
}

export function Dashboard({ onOpenAnswerKeyWithDocument }: DashboardProps = {}) {
  const { user, logout } = useAuth()
  const queryClient = useQueryClient()
  const isAdmin = user?.username === 'admin'
  const [chartByFormType, setChartByFormType] = useState(false)
  const [formTypeListModalFormType, setFormTypeListModalFormType] = useState<string | null>(null)
  const { formTypeLabel } = useFormTypes()

  const { data: formTypesData, isLoading: formTypesLoading } = useQuery({
    queryKey: ['form-types'],
    queryFn: () => formTypesApi.getList(),
    enabled: isAdmin,
  })

  const updateFormTypeLabelMutation = useMutation({
    mutationFn: ({ formCode, displayName }: { formCode: string; displayName: string }) =>
      formTypesApi.updateLabel(formCode, displayName),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['form-types'] }),
  })

  const deleteFormTypeMutation = useMutation({
    mutationFn: (formCode: string) => formTypesApi.delete(formCode),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['form-types'] }),
  })

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

  const { data: reviewByItemsData, isLoading: reviewByItemsLoading, error: reviewByItemsError } = useQuery({
    queryKey: ['items', 'stats', 'review-by-items'],
    queryFn: () => itemsApi.getReviewStatsByItems(),
    refetchInterval: 60000,
  })

  const { data: reviewByUserData, isLoading: reviewByUserLoading, error: reviewByUserError } = useQuery({
    queryKey: ['items', 'stats', 'review-by-user'],
    queryFn: () => itemsApi.getReviewStatsByUser(),
    refetchInterval: 60000,
  })

  const { data: ragData, isLoading: ragLoading, error: ragError } = useQuery({
    queryKey: ['rag-admin', 'status'],
    queryFn: () => ragAdminApi.getStatus(),
    refetchInterval: 60000,
  })

  const { data: customerStatsData, isLoading: customerStatsLoading, error: customerStatsError } = useQuery({
    queryKey: ['items', 'stats', 'by-customer'],
    queryFn: () => itemsApi.getCustomerStats(100),
    refetchInterval: 60000,
  })

  const { data: detailSummaryData, isLoading: detailSummaryLoading, error: detailSummaryError } = useQuery({
    queryKey: ['items', 'stats', 'detail-summary'],
    queryFn: () => itemsApi.getDetailSummary(),
    refetchInterval: 60000,
  })

  const { data: documentsOverviewData } = useQuery({
    queryKey: ['documents', 'overview'],
    queryFn: () => documentsApi.getOverview(),
    refetchInterval: 60000,
  })

  /** RAG DB 소스: img 폴더(벡터 임베딩된 문서) form_type별 목록 — 그리드 嵌入文書数/ページ数·一覧 모달용 */
  const { data: answerKeysFromImgData } = useQuery({
    queryKey: ['documents', 'answer-keys-from-img'],
    queryFn: () => documentsApi.getAnswerKeysFromImg(),
    enabled: isAdmin,
  })

  const chartSeries = useMemo(() => {
    if (!chartByFormType || !detailSummaryData?.by_year_month_by_form?.length) return null
    const formTypes = [...new Set(detailSummaryData.by_year_month_by_form.map((r) => r.form_type))].sort()
    return formTypes.map((ft, i) => ({
      key: ft,
      label: formTypeLabel(ft),
      color: CHART_HUE_COLORS[i % CHART_HUE_COLORS.length],
    }))
  }, [chartByFormType, detailSummaryData?.by_year_month_by_form, formTypeLabel])

  const chartDataForRecharts = useMemo(() => {
    const ym = detailSummaryData?.by_year_month ?? []
    const ymByForm = detailSummaryData?.by_year_month_by_form ?? []
    if (chartByFormType && ymByForm.length > 0) {
      const byPeriod: Record<string, Record<string, string | number>> = {}
      ymByForm.forEach(({ year, month, form_type, item_count }) => {
        const period = `${year}年${String(month).padStart(2, '0')}月`
        if (!byPeriod[period]) byPeriod[period] = { period }
        byPeriod[period][form_type] = item_count
      })
      return Object.entries(byPeriod)
        .sort(([a], [b]) => b.localeCompare(a))
        .reverse()
        .map(([, v]) => v)
    }
    return ym
      .map(({ year, month, item_count }) => ({
        period: `${year}年${String(month).padStart(2, '0')}月`,
        item_count,
      }))
      .reverse()
  }, [detailSummaryData?.by_year_month, detailSummaryData?.by_year_month_by_form, chartByFormType])

  return (
    <div className="dashboard-tab">
      <header className="dashboard-header">
        <div className="dashboard-title-wrap">
          <div className="dashboard-title-icon">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </div>
          <h1 className="dashboard-title">
            <span className="dashboard-title-main">現況</span>
            <span className="dashboard-title-sub">Dashboard</span>
          </h1>
        </div>
        <div className="dashboard-header-user">
          <div className="dashboard-header-avatar">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M20 21V19C20 17.9391 19.5786 16.9217 18.8284 16.1716C18.0783 15.4214 17.0609 15 16 15H8C6.93913 15 5.92172 15.4214 5.17157 16.1716C4.42143 16.9217 4 17.9391 4 19V21M16 7C16 9.20914 14.2091 11 12 11C9.79086 11 8 9.20914 8 7C8 4.79086 9.79086 3 12 3C14.2091 3 16 4.79086 16 7Z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </div>
          <span className="dashboard-header-name">
            {user?.display_name_ja || user?.display_name || user?.username}
          </span>
          <button type="button" className="dashboard-header-logout" onClick={logout}>
            ログアウト
          </button>
        </div>
      </header>

      <div className="dashboard-body">
        {/* 検討状況（アイテム数基準・最上段）— 今月・前月比・処理量を見るため base DB 除く */}
        <section className="dashboard-section">
          <h2 className="dashboard-section-title">検討状況</h2>
          <p className="dashboard-section-note">
            ※ detail ページの請求明細<strong>行（アイテム）</strong>のみ集計。文書数・ページ数ではありません。
            <strong>請求年月（data_year/month）が設定された文書のみ</strong>（base DB・参照用 img 同期分は除く）。
          </p>
          {reviewByItemsLoading && <div className="dashboard-loading">読み込み中...</div>}
          {reviewByItemsError && <div className="dashboard-error">検討統計の取得に失敗しました</div>}
          {!reviewByItemsLoading && !reviewByItemsError && reviewByItemsData && (
            <>
              {(() => {
                const total = reviewByItemsData.total_item_count ?? 0
                const firstPct = total > 0 ? Math.round((reviewByItemsData.first_checked_count / total) * 100) : 0
                const secondPct = total > 0 ? Math.round((reviewByItemsData.second_checked_count / total) * 100) : 0
                return (
                  <div className="dashboard-cards dashboard-cards-review">
                    <div className="dashboard-card dashboard-card-review">
                      <div className="dashboard-card-value">{(reviewByItemsData.total_item_count ?? 0).toLocaleString()}</div>
                      <div className="dashboard-card-label">対象アイテム数（明細行数）</div>
                      {reviewByItemsData.total_document_count != null && (
                        <div className="dashboard-card-sublabel">
                          {reviewByItemsData.total_document_count.toLocaleString()} 文書の明細
                        </div>
                      )}
                    </div>
                    <div className="dashboard-card dashboard-card-review-ok">
                      <div className="dashboard-card-value">{(reviewByItemsData.first_checked_count ?? 0).toLocaleString()}</div>
                      <div className="dashboard-card-pct">{firstPct}%</div>
                      <div className="dashboard-card-label">1次検討完了</div>
                    </div>
                    <div className="dashboard-card dashboard-card-review-pending">
                      <div className="dashboard-card-value">{(reviewByItemsData.first_not_checked_count ?? 0).toLocaleString()}</div>
                      <div className="dashboard-card-pct">{100 - firstPct}%</div>
                      <div className="dashboard-card-label">1次未完了</div>
                    </div>
                    <div className="dashboard-card dashboard-card-review-ok">
                      <div className="dashboard-card-value">{(reviewByItemsData.second_checked_count ?? 0).toLocaleString()}</div>
                      <div className="dashboard-card-pct">{secondPct}%</div>
                      <div className="dashboard-card-label">2次検討完了</div>
                    </div>
                    <div className="dashboard-card dashboard-card-review-pending">
                      <div className="dashboard-card-value">{(reviewByItemsData.second_not_checked_count ?? 0).toLocaleString()}</div>
                      <div className="dashboard-card-pct">{100 - secondPct}%</div>
                      <div className="dashboard-card-label">2次未完了</div>
                    </div>
                  </div>
                )
              })()}
              {reviewByItemsData.total_item_count > 0 && (
                <div className="dashboard-progress-wrap">
                  <div className="dashboard-progress-row">
                    <span className="dashboard-progress-label">1次検討</span>
                    <div className="dashboard-progress-bar">
                      <div
                        className="dashboard-progress-fill dashboard-progress-fill-first"
                        style={{
                          width: `${Math.round(
                            (reviewByItemsData.first_checked_count / reviewByItemsData.total_item_count) * 100
                          )}%`,
                        }}
                      />
                    </div>
                    <span className="dashboard-progress-pct">
                      {Math.round(
                        (reviewByItemsData.first_checked_count / reviewByItemsData.total_item_count) * 100
                      )}
                      %
                    </span>
                  </div>
                  <div className="dashboard-progress-row">
                    <span className="dashboard-progress-label">2次検討</span>
                    <div className="dashboard-progress-bar">
                      <div
                        className="dashboard-progress-fill dashboard-progress-fill-second"
                        style={{
                          width: `${Math.round(
                            (reviewByItemsData.second_checked_count / reviewByItemsData.total_item_count) * 100
                          )}%`,
                        }}
                      />
                    </div>
                    <span className="dashboard-progress-pct">
                      {Math.round(
                        (reviewByItemsData.second_checked_count / reviewByItemsData.total_item_count) * 100
                      )}
                      %
                    </span>
                  </div>
                </div>
              )}
            </>
          )}
        </section>

        {/* 検討チェック担当者別（증빙용 현황판） */}
        <section className="dashboard-section">
          <h2 className="dashboard-section-title">検討チェック担当者別（증빙）</h2>
          <p className="dashboard-section-note">
            ※ 誰が1次・2次チェックを何件したか。上記「検討状況」と同じ対象（detail・得意先あり）のみ集計。
          </p>
          {reviewByUserLoading && <div className="dashboard-loading">読み込み中...</div>}
          {reviewByUserError && <div className="dashboard-error">担当者別統計の取得に失敗しました</div>}
          {!reviewByUserLoading && !reviewByUserError && reviewByUserData?.by_user?.length > 0 && (
            <div className="dashboard-table-wrap">
              <table className="dashboard-table">
                <thead>
                  <tr>
                    <th>担当者</th>
                    <th>1次チェック件数</th>
                    <th>2次チェック件数</th>
                    <th>合計</th>
                  </tr>
                </thead>
                <tbody>
                  {reviewByUserData.by_user.map((row) => (
                    <tr key={row.user_id}>
                      <td>{row.display_name}</td>
                      <td>{row.first_checked_count.toLocaleString()}</td>
                      <td>{row.second_checked_count.toLocaleString()}</td>
                      <td>{(row.first_checked_count + row.second_checked_count).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {!reviewByUserLoading && !reviewByUserError && reviewByUserData?.by_user?.length === 0 && (
            <p className="dashboard-section-note">まだチェック記録がありません。</p>
          )}
        </section>

        {/* 文書（detail ページ・得意先ありのアイテム数基準）— base DB 除く */}
        <section className="dashboard-section">
          <h2 className="dashboard-section-title">文書</h2>
          <p className="dashboard-section-note">
            ※ detail ページの請求明細アイテム数のみ集計（cover 等・得意先なしは除く）。
            <strong>請求年月が設定された文書のみ</strong>（base DB 除く）。
          </p>
          {detailSummaryLoading && <div className="dashboard-loading">読み込み中...</div>}
          {detailSummaryError && <div className="dashboard-error">集計データの取得に失敗しました</div>}
          {!detailSummaryLoading && !detailSummaryError && detailSummaryData && (
            <>
              <div className="dashboard-cards">
                <div className="dashboard-card dashboard-card-primary">
                  <div className="dashboard-card-value">{(detailSummaryData.total_document_count ?? 0).toLocaleString()}</div>
                  <div className="dashboard-card-label">総文書数</div>
                </div>
                <div className="dashboard-card dashboard-card-primary">
                  <div className="dashboard-card-value">{(detailSummaryData.total_item_count ?? 0).toLocaleString()}</div>
                  <div className="dashboard-card-label">総アイテム数</div>
                </div>
              </div>
              {detailSummaryData.by_form_type?.length > 0 && (
                <div className="dashboard-subsection">
                  <h3 className="dashboard-subtitle">様式別（アイテム数）</h3>
                  <div className="dashboard-table-wrap">
                    <table className="dashboard-table">
                      <thead>
                        <tr>
                          <th>様式</th>
                          <th className="dashboard-th-num">アイテム数</th>
                        </tr>
                      </thead>
                      <tbody>
                        {detailSummaryData.by_form_type.map(({ form_type, item_count }) => (
                          <tr key={form_type}>
                            <td>{formTypeLabel(form_type)}</td>
                            <td className="dashboard-td-num">{item_count.toLocaleString()}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
              {(detailSummaryData.by_year_month?.length > 0 || (chartByFormType && (detailSummaryData?.by_year_month_by_form?.length ?? 0) > 0)) && (
                <div className="dashboard-subsection">
                  <div className="dashboard-chart-header">
                    <h3 className="dashboard-subtitle">直近の請求年月別（アイテム数）</h3>
                    <label className="dashboard-chart-toggle">
                      <input
                        type="checkbox"
                        checked={chartByFormType}
                        onChange={(e) => setChartByFormType(e.target.checked)}
                      />
                      <span>様式別で表示</span>
                    </label>
                  </div>
                  <div className="dashboard-chart-wrap">
                    <ResponsiveContainer width="100%" height={280}>
                      <BarChart data={chartDataForRecharts} margin={{ top: 8, right: 8, left: 8, bottom: 8 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                        <XAxis dataKey="period" tick={{ fontSize: 12 }} stroke="#64748b" />
                        <YAxis tick={{ fontSize: 12 }} stroke="#64748b" tickFormatter={(v) => v.toLocaleString()} />
                        <Tooltip
                          formatter={(value: number, name: string) => [
                            value.toLocaleString(),
                            chartByFormType ? (chartSeries?.find((s) => s.key === name)?.label ?? name) : 'アイテム数',
                          ]}
                          labelFormatter={(label) => `請求年月: ${label}`}
                          contentStyle={{ fontSize: 12 }}
                        />
                        {!chartByFormType ? (
                          <Bar dataKey="item_count" name="アイテム数" fill="#667eea" radius={[4, 4, 0, 0]} />
                        ) : (
                          chartSeries?.map((s) => (
                            <Bar
                              key={s.key}
                              dataKey={s.key}
                              name={s.label}
                              stackId="a"
                              fill={s.color}
                              radius={s.key === (chartSeries?.[chartSeries.length - 1]?.key) ? [4, 4, 0, 0] : [0, 0, 0, 0]}
                            />
                          ))
                        )}
                        <Legend formatter={(value) => value} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )}
            </>
          )}
        </section>

        {/* 得意先別（detail ・得意先ありのみ）— base DB 除く */}
        <section className="dashboard-section">
          <h2 className="dashboard-section-title">得意先別</h2>
          <p className="dashboard-section-note">
            ※ detail ページの請求明細アイテムのみ（得意先なしは除く）。
            <strong>請求年月が設定された文書のみ</strong>（base DB 除く）。
          </p>
          {customerStatsLoading && <div className="dashboard-loading">読み込み中...</div>}
          {customerStatsError && <div className="dashboard-error">得意先別統計の取得に失敗しました</div>}
          {!customerStatsLoading && !customerStatsError && customerStatsData && (
            <>
              {customerStatsData.customers.length === 0 ? (
                <p className="dashboard-empty">アイテムがまだありません（得意先別の集計は検討データから算出されます）</p>
              ) : (
                <div className="dashboard-table-wrap dashboard-table-wrap-scroll">
                  <table className="dashboard-table">
                    <thead>
                      <tr>
                        <th>得意先名</th>
                        <th className="dashboard-th-num">アイテム数</th>
                        <th className="dashboard-th-num">文書数</th>
                        <th className="dashboard-th-num">ページ数</th>
                      </tr>
                    </thead>
                    <tbody>
                      {customerStatsData.customers.map((c) => (
                        <tr key={c.customer_name}>
                          <td className="dashboard-td-customer">{c.customer_name}</td>
                          <td className="dashboard-td-num">{c.item_count.toLocaleString()}</td>
                          <td className="dashboard-td-num">{c.document_count}</td>
                          <td className="dashboard-td-num">{c.page_count.toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </section>

        {/* RAG・文書様式・ページ役割 — ここだけ base DB 含む全体表示 */}
        <section className="dashboard-section">
          <h2 className="dashboard-section-title">RAG（ベクターDB）・文書様式・ページ役割</h2>
          <p className="dashboard-section-note">
            ※ ベクターDB・様式・ページ役割は<strong>全文書</strong>（base DB・img 同期分を含む）を表示。
          </p>
          {ragLoading && <div className="dashboard-loading">読み込み中...</div>}
          {ragError && <div className="dashboard-error dashboard-error-soft">RAG状態の取得に失敗しました（管理者のみの可能性があります）</div>}
          {!ragLoading && !ragError && ragData && (
            <div className="dashboard-cards">
              <div className="dashboard-card dashboard-card-rag">
                <div className="dashboard-card-value">{ragData.total_vectors.toLocaleString()}</div>
                <div className="dashboard-card-label">総ベクター数</div>
              </div>
              {ragData.per_form_type?.length > 0 && (
                <div className="dashboard-rag-by-form">
                  {ragData.per_form_type.map(({ form_type, vector_count }) => (
                    <div key={form_type ?? 'null'} className="dashboard-rag-form-row">
                      <span className="dashboard-rag-form-label">様式 {formTypeLabel(form_type ?? '')}</span>
                      <span className="dashboard-rag-form-value">{vector_count.toLocaleString()}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {isAdmin && (
            <div className="dashboard-subsection dashboard-form-type-labels-section">
              <h3 className="dashboard-subtitle">様式名の管理</h3>
              <p className="dashboard-section-note">
                様式コード（01, 02…）の表示名を変更できます。一覧・フィルタ・検索などで使われる名前です。
              </p>
              {formTypesLoading ? (
                <p className="dashboard-loading">読み込み中...</p>
              ) : (
                <div className="dashboard-form-type-labels-wrap">
                  <table className="dashboard-form-type-labels-table">
                    <colgroup>
                      <col style={{ width: '5rem' }} />
                      <col />
                      <col style={{ width: '5rem' }} />
                      <col style={{ width: '5rem' }} />
                      <col style={{ width: '12.5rem' }} />
                    </colgroup>
                    <thead>
                      <tr>
                        <th>様式コード</th>
                        <th>表示名</th>
                        <th className="dashboard-th-num">嵌入文書数</th>
                        <th className="dashboard-th-num">ページ数</th>
                        <th className="dashboard-col-action">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(formTypesData?.form_types ?? []).map((opt) => {
                        const ragDocs = answerKeysFromImgData?.by_form_type?.[opt.value] ?? []
                        const docCount = ragDocs.length
                        const pageCount = ragDocs.reduce((sum, d) => sum + (d.total_pages ?? 0), 0)
                        return (
                        <tr key={opt.value}>
                          <td className="dashboard-form-type-code">{opt.value}</td>
                          <td>
                            <input
                              type="text"
                              className="dashboard-form-type-label-input"
                              value={formTypeLabelDrafts[opt.value] ?? opt.label}
                              onChange={(e) =>
                                setFormTypeLabelDrafts((prev) => ({ ...prev, [opt.value]: e.target.value }))
                              }
                              placeholder="表示名を入力"
                            />
                          </td>
                          <td className="dashboard-td-num">{docCount.toLocaleString()}</td>
                          <td className="dashboard-td-num">{pageCount.toLocaleString()}</td>
                          <td className="dashboard-col-action">
                            {onOpenAnswerKeyWithDocument && (
                              <button
                                type="button"
                                className="dashboard-button dashboard-button-small dashboard-button-list"
                                onClick={() => setFormTypeListModalFormType(opt.value)}
                                title="該当様式の文書一覧を開き、クリックで正解表タブへ"
                              >
                                一覧
                              </button>
                            )}
                            <button
                              type="button"
                              className="dashboard-button dashboard-button-small"
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
                            <button
                              type="button"
                              className="dashboard-button dashboard-button-small dashboard-button-danger"
                              disabled={deleteFormTypeMutation.isPending}
                              onClick={() => {
                                if (
                                  !window.confirm(
                                    `様式「${opt.value}」を削除しますか？\n使用中の文書がある場合は削除できません。`
                                  )
                                )
                                  return
                                deleteFormTypeMutation.mutate(opt.value, {
                                  onSuccess: () => alert('削除しました。'),
                                  onError: (err: unknown) => {
                                    const msg =
                                      err && typeof err === 'object' && 'response' in err
                                        ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
                                        : null
                                    alert(msg ? `削除に失敗しました: ${msg}` : '削除に失敗しました。')
                                  },
                                })
                              }}
                            >
                              {deleteFormTypeMutation.isPending ? '削除中...' : '削除'}
                            </button>
                          </td>
                        </tr>
                      )})}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* 様式別 嵌入文書一覧 모달: 문서 클릭 시 정답지 탭으로 이동 */}
          {formTypeListModalFormType != null && onOpenAnswerKeyWithDocument && (
            <div
              className="dashboard-modal-overlay"
              onClick={() => setFormTypeListModalFormType(null)}
              role="dialog"
              aria-modal="true"
              aria-label="該当様式の文書一覧"
            >
              <div className="dashboard-modal" onClick={(e) => e.stopPropagation()}>
                <h3 className="dashboard-modal-title">
                  様式 {formTypeLabel(formTypeListModalFormType)} の文書一覧
                </h3>
                <p className="dashboard-modal-note">
                  ベクターDB（RAG）に嵌入された文書一覧です。クリックで正解表タブでその文書の正解を表示します。
                </p>
                <div className="dashboard-modal-list-wrap">
                  {(() => {
                    const docs = answerKeysFromImgData?.by_form_type?.[formTypeListModalFormType] ?? []
                    if (docs.length === 0) {
                      return <p className="dashboard-empty">該当様式でベクターDBに嵌入された文書がありません。</p>
                    }
                    return (
                      <ul className="dashboard-modal-doc-list">
                        {docs.map((d) => {
                          const pdfFilename = d.pdf_name?.endsWith('.pdf') ? d.pdf_name : `${d.pdf_name ?? ''}.pdf`
                          return (
                            <li key={d.relative_path ?? pdfFilename}>
                              <button
                                type="button"
                                className="dashboard-modal-doc-item"
                                onClick={() => {
                                  onOpenAnswerKeyWithDocument({
                                    pdf_filename: pdfFilename,
                                    total_pages: d.total_pages ?? 0,
                                    relative_path: d.relative_path ?? null,
                                  })
                                  setFormTypeListModalFormType(null)
                                }}
                              >
                                <span className="dashboard-modal-doc-name" title={pdfFilename}>
                                  {d.pdf_name ?? pdfFilename}
                                </span>
                                <span className="dashboard-modal-doc-pages">{d.total_pages ?? 0}ページ</span>
                              </button>
                            </li>
                          )
                        })}
                      </ul>
                    )
                  })()}
                </div>
                <div className="dashboard-modal-actions">
                  <button
                    type="button"
                    className="dashboard-button dashboard-button-small"
                    onClick={() => setFormTypeListModalFormType(null)}
                  >
                    閉じる
                  </button>
                </div>
              </div>
            </div>
          )}

        </section>
      </div>
    </div>
  )
}
