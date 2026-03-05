/**
 * ベクターDB反映専用画面
 * - 文書を展開してページ単位で表示
 * - 文書全体チェック・ページ別チェックで未反映ページを選択してベクターDBに登録
 * - 各ページにサムネイル画像と反映/修正済み状態を表示
 */
import { useState, useMemo, useCallback, Fragment } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { documentsApi, ragAdminApi, searchApi } from '@/api/client'
import { getPageImageAbsoluteUrl } from '@/utils/apiConfig'
import './VectorReflectTab.css'

function pageKey(pdf: string, page: number): string {
  return `${pdf}|${page}`
}

/** 左パネル用：選択中ページの画像を大きく表示。API: getPageImage → { image_url }。画像未生成時は生成ボタン表示 */
function LeftPagePreview({
  pdfFilename,
  pageNumber,
  label,
}: {
  pdfFilename: string | null
  pageNumber: number | null
  label: string
}) {
  const queryClient = useQueryClient()
  const { data, isLoading, error } = useQuery({
    queryKey: ['page-image', pdfFilename, pageNumber],
    queryFn: () => searchApi.getPageImage(pdfFilename!, pageNumber!),
    enabled: !!pdfFilename && !!pageNumber && pageNumber >= 1,
    staleTime: 5 * 60 * 1000,
  })
  const generateMutation = useMutation({
    mutationFn: (name: string) => documentsApi.generatePageImages(name),
    onSuccess: (_data, name) => {
      queryClient.invalidateQueries({ queryKey: ['page-image', name] })
    },
    onError: (err: unknown) => {
      const msg =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      window.alert(msg ? `画像の生成に失敗しました: ${msg}` : '画像の生成に失敗しました。')
    },
  })
  const src = data?.image_url ? getPageImageAbsoluteUrl(data.image_url) : null
  const noImage = !!pdfFilename && !!pageNumber && !isLoading && !error && !src

  if (!pdfFilename || !pageNumber) {
    return (
      <div className="vector-reflect-left-preview vector-reflect-left-preview-empty">
        <p className="vector-reflect-left-preview-msg">右の一覧で行をクリックすると<br />ここにページ画像を表示します</p>
      </div>
    )
  }
  if (isLoading) {
    return (
      <div className="vector-reflect-left-preview vector-reflect-left-preview-loading">
        <p className="vector-reflect-left-preview-msg">読込中…</p>
      </div>
    )
  }
  if (error) {
    return (
      <div className="vector-reflect-left-preview vector-reflect-left-preview-empty">
        <p className="vector-reflect-left-preview-msg">画像の取得に失敗しました</p>
      </div>
    )
  }
  if (noImage) {
    return (
      <div className="vector-reflect-left-preview vector-reflect-left-preview-empty vector-reflect-left-preview-noimage">
        <p className="vector-reflect-left-preview-msg">このページの画像がまだありません</p>
        <p className="vector-reflect-left-preview-hint">下のボタンで文書のページ画像を生成してください</p>
        <button
          type="button"
          className="vector-reflect-generate-btn"
          onClick={() => generateMutation.mutate(pdfFilename)}
          disabled={generateMutation.isPending}
        >
          {generateMutation.isPending ? '生成中…' : 'ページ画像を生成'}
        </button>
      </div>
    )
  }
  return (
    <div className="vector-reflect-left-preview">
      <p className="vector-reflect-left-preview-label">{label}</p>
      <div className="vector-reflect-left-preview-img-wrap">
        <img src={src!} alt={label} className="vector-reflect-left-preview-img" />
      </div>
    </div>
  )
}

export function VectorReflectTab() {
  const queryClient = useQueryClient()
  const [expandedDocs, setExpandedDocs] = useState<Set<string>>(new Set())
  const [selectedPages, setSelectedPages] = useState<Set<string>>(new Set())
  /** 左パネルに表示するページ。{ pdf, pageNumber } | null */
  const [previewPage, setPreviewPage] = useState<{ pdf: string; pageNumber: number } | null>(null)

  const { data: pagesData, isLoading: docsLoading, error: docsError } = useQuery({
    queryKey: ['documents', 'vector-reflect-pages'],
    queryFn: () => documentsApi.getVectorReflectPages(),
  })

  const documents = useMemo(() => pagesData?.documents ?? [], [pagesData?.documents])

  const toggleExpand = useCallback((pdf: string) => {
    setExpandedDocs((prev) => {
      const next = new Set(prev)
      if (next.has(pdf)) next.delete(pdf)
      else next.add(pdf)
      return next
    })
  }, [])

  const togglePage = useCallback((pdf: string, pageNum: number, inVector: boolean) => {
    if (inVector) return
    const key = pageKey(pdf, pageNum)
    setSelectedPages((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }, [])

  const toggleDocWhole = useCallback((doc: { pdf_filename: string; pages: Array<{ page_number: number; in_vector: boolean }> }) => {
    const unreflected = doc.pages.filter((p) => !p.in_vector).map((p) => pageKey(doc.pdf_filename, p.page_number))
    const allSelected = unreflected.length > 0 && unreflected.every((k) => selectedPages.has(k))
    setSelectedPages((prev) => {
      const next = new Set(prev)
      if (allSelected) unreflected.forEach((k) => next.delete(k))
      else unreflected.forEach((k) => next.add(k))
      return next
    })
  }, [selectedPages])

  const selectAllUnreflected = useCallback(() => {
    const keys = new Set<string>()
    documents.forEach((doc) => {
      doc.pages.forEach((p) => {
        if (!p.in_vector) keys.add(pageKey(doc.pdf_filename, p.page_number))
      })
    })
    setSelectedPages(keys)
  }, [documents])

  const clearSelection = useCallback(() => setSelectedPages(new Set()), [])

  const reflectMutation = useMutation({
    mutationFn: async (keys: string[]) => {
      for (const key of keys) {
        const [pdf, p] = key.split('|')
        const pageNum = parseInt(p, 10)
        if (pdf && !Number.isNaN(pageNum)) {
          await ragAdminApi.setLearningFlag({ pdf_filename: pdf, page_number: pageNum, selected: true })
        }
      }
      return ragAdminApi.buildFromLearningPages(undefined)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents', 'in-vector-index'] })
      queryClient.invalidateQueries({ queryKey: ['documents', 'vector-reflect-pages'] })
      queryClient.invalidateQueries({ queryKey: ['rag-admin', 'learning-pages'] })
      queryClient.invalidateQueries({ queryKey: ['rag-admin', 'status'] })
      setSelectedPages(new Set())
    },
  })

  const handleReflect = useCallback(() => {
    if (selectedPages.size === 0) return
    reflectMutation.mutate(Array.from(selectedPages))
  }, [selectedPages, reflectMutation])

  const canReflect = selectedPages.size > 0 && !reflectMutation.isPending
  const totalUnreflected = useMemo(
    () => documents.reduce((acc, doc) => acc + doc.pages.filter((p) => !p.in_vector).length, 0),
    [documents]
  )

  if (docsLoading) {
    return (
      <div className="vector-reflect-tab">
        <p className="vector-reflect-loading">読込中…</p>
      </div>
    )
  }
  if (docsError) {
    return (
      <div className="vector-reflect-tab">
        <p className="vector-reflect-error">文書一覧の取得に失敗しました。</p>
      </div>
    )
  }

  const previewLabel = previewPage
    ? `${previewPage.pdf} — p.${previewPage.pageNumber}`
    : ''

  return (
    <div className="vector-reflect-tab">
      <div className="vector-reflect-header">
        <h2 className="vector-reflect-title">ベクターDB反映</h2>
        <p className="vector-reflect-desc">
          文書を展開し、反映するページを選択してベクターDBに登録します。反映済は編集・解答作成の内容が学習に使われた状態です。行をクリックで左にページ画像を表示。
        </p>
      </div>

      <div className="vector-reflect-actions">
        <button
          type="button"
          className="vector-reflect-btn vector-reflect-btn-primary"
          onClick={handleReflect}
          disabled={!canReflect}
          title={selectedPages.size > 0 ? `選択した${selectedPages.size}ページをベクターDBに反映します` : '未反映のページを選択してください'}
        >
          {reflectMutation.isPending ? '反映中…' : `選択をベクターDBに反映（${selectedPages.size}p）`}
        </button>
        <button type="button" className="vector-reflect-btn vector-reflect-btn-secondary" onClick={selectAllUnreflected}>
          未反映を全選択
        </button>
        <button type="button" className="vector-reflect-btn vector-reflect-btn-secondary" onClick={clearSelection}>
          選択解除
        </button>
      </div>

      {reflectMutation.isSuccess && (
        <p className="vector-reflect-status success" role="status">
          反映しました。（{reflectMutation.data?.processed_pages ?? 0}p → {reflectMutation.data?.total_vectors ?? 0}ベクター）
        </p>
      )}
      {reflectMutation.isError && (
        <p className="vector-reflect-status error" role="alert">
          {String(reflectMutation.error)}
        </p>
      )}

      <div className="vector-reflect-body">
        <aside className="vector-reflect-left">
          <LeftPagePreview
            pdfFilename={previewPage?.pdf ?? null}
            pageNumber={previewPage?.pageNumber ?? null}
            label={previewLabel}
          />
        </aside>
        <div className="vector-reflect-right">
          <div className="vector-reflect-table-wrap">
            <table className="vector-reflect-table">
              <thead>
                <tr>
                  <th className="vector-reflect-th-expand" />
                  <th className="vector-reflect-th-check">選択</th>
                  <th>文書名 / ページ</th>
                  <th className="vector-reflect-th-pages">p</th>
                  <th className="vector-reflect-th-status">状態</th>
                </tr>
              </thead>
              <tbody>
                {documents.length === 0 && (
                  <tr>
                    <td colSpan={5} className="vector-reflect-empty">
                      文書がありません。
                    </td>
                  </tr>
                )}
                {documents.map((doc) => {
                  const unreflectedPages = doc.pages.filter((p) => !p.in_vector)
                  const modifiedCount = doc.pages.filter((p) => p.modified).length
                  const unreflectedCount = unreflectedPages.length
                  const docAllUnreflectedSelected =
                    unreflectedCount > 0 &&
                    unreflectedPages.every((p) => selectedPages.has(pageKey(doc.pdf_filename, p.page_number)))
                  const isExpanded = expandedDocs.has(doc.pdf_filename)

                  return (
                    <Fragment key={doc.pdf_filename}>
                      <tr className="vector-reflect-doc-row">
                        <td className="vector-reflect-td-expand">
                          <button
                            type="button"
                            className="vector-reflect-expand-btn"
                            onClick={() => toggleExpand(doc.pdf_filename)}
                            aria-expanded={isExpanded}
                            title={isExpanded ? '折りたたむ' : '展開してページを表示'}
                          >
                            {isExpanded ? '▼' : '▶'}
                          </button>
                        </td>
                        <td className="vector-reflect-td-check">
                          {unreflectedCount === 0 ? (
                            <span className="vector-reflect-check-disabled">—</span>
                          ) : (
                            <input
                              type="checkbox"
                              checked={docAllUnreflectedSelected}
                              onChange={() => toggleDocWhole(doc)}
                              aria-label={`${doc.pdf_filename}の未反映ページを全て選択`}
                            />
                          )}
                        </td>
                        <td className="vector-reflect-td-name">{doc.pdf_filename}</td>
                        <td className="vector-reflect-td-pages">{doc.total_pages}p</td>
                        <td className="vector-reflect-td-status vector-reflect-doc-status">
                          {doc.total_pages}ページ中 {modifiedCount}ページ修正済 / {unreflectedCount}ページ未反映
                        </td>
                      </tr>
                      {isExpanded &&
                        doc.pages.map((p) => {
                          const key = pageKey(doc.pdf_filename, p.page_number)
                          const isPreviewRow =
                            previewPage?.pdf === doc.pdf_filename && previewPage?.pageNumber === p.page_number
                          return (
                            <tr
                              key={key}
                              className={`vector-reflect-page-row ${p.in_vector ? 'vector-reflect-row-reflected' : ''} ${p.modified ? 'vector-reflect-page-modified' : ''} ${isPreviewRow ? 'vector-reflect-page-selected' : ''}`}
                              onClick={() => setPreviewPage({ pdf: doc.pdf_filename, pageNumber: p.page_number })}
                              role="button"
                              tabIndex={0}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter' || e.key === ' ') {
                                  e.preventDefault()
                                  setPreviewPage({ pdf: doc.pdf_filename, pageNumber: p.page_number })
                                }
                              }}
                              aria-label={`${doc.pdf_filename} p.${p.page_number} をプレビュー`}
                            >
                              <td className="vector-reflect-td-expand" />
                              <td className="vector-reflect-td-check" onClick={(e) => e.stopPropagation()}>
                                {p.in_vector ? (
                                  <span className="vector-reflect-check-disabled">—</span>
                                ) : (
                                  <input
                                    type="checkbox"
                                    checked={selectedPages.has(key)}
                                    onChange={() => togglePage(doc.pdf_filename, p.page_number, p.in_vector)}
                                    aria-label={`${doc.pdf_filename} p.${p.page_number}`}
                                    onClick={(e) => e.stopPropagation()}
                                  />
                                )}
                              </td>
                              <td className="vector-reflect-td-name vector-reflect-page-name">p.{p.page_number}</td>
                              <td className="vector-reflect-td-pages">—</td>
                              <td className="vector-reflect-td-status">
                                {p.modified && <span className="vector-reflect-badge modified">修正済</span>}
                                {p.in_vector ? (
                                  <span className="vector-reflect-badge reflected">反映済</span>
                                ) : (
                                  <span className="vector-reflect-badge not">未反映</span>
                                )}
                              </td>
                            </tr>
                          )
                        })}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
          <p className="vector-reflect-footer">
            未反映: {totalUnreflected}p / 文書: {documents.length}件
          </p>
        </div>
      </div>
    </div>
  )
}
