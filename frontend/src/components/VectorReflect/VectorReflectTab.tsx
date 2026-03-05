/**
 * ベクターDB反映専用画面
 * - 文書一覧に 反映済/未反映 を表示
 * - 未反映の文書を選択して一括でベクターDBに登録
 */
import { useState, useMemo, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { documentsApi, ragAdminApi } from '@/api/client'
import './VectorReflectTab.css'

interface DocRow {
  pdf_filename: string
  total_pages: number
  in_vector: boolean
}

export function VectorReflectTab() {
  const queryClient = useQueryClient()
  const [selectedPdfs, setSelectedPdfs] = useState<Set<string>>(new Set())

  const { data: docsData, isLoading: docsLoading, error: docsError } = useQuery({
    queryKey: ['documents', 'vector-reflect'],
    queryFn: () => documentsApi.getList(undefined, { exclude_img_seed: true }),
  })
  const { data: vectorData } = useQuery({
    queryKey: ['documents', 'in-vector-index'],
    queryFn: () => documentsApi.getInVectorIndex(),
  })

  const inVectorSet = useMemo(
    () => new Set((vectorData?.pdf_filenames ?? []).map((f) => (f ?? '').trim().toLowerCase())),
    [vectorData?.pdf_filenames]
  )

  const rows: DocRow[] = useMemo(() => {
    const list = docsData?.documents ?? []
    return list.map((d: { pdf_filename?: string; total_pages?: number }) => ({
      pdf_filename: d.pdf_filename ?? '',
      total_pages: d.total_pages ?? 0,
      in_vector: inVectorSet.has((d.pdf_filename ?? '').trim().toLowerCase()),
    }))
  }, [docsData?.documents, inVectorSet])

  const toggleSelect = useCallback((pdf: string, inVector: boolean) => {
    if (inVector) return
    setSelectedPdfs((prev) => {
      const next = new Set(prev)
      if (next.has(pdf)) next.delete(pdf)
      else next.add(pdf)
      return next
    })
  }, [])

  const selectAllUnreflected = useCallback(() => {
    const unreflected = rows.filter((r) => !r.in_vector).map((r) => r.pdf_filename)
    setSelectedPdfs((prev) => {
      const next = new Set(prev)
      unreflected.forEach((p) => next.add(p))
      return next
    })
  }, [rows])

  const clearSelection = useCallback(() => setSelectedPdfs(new Set()), [])

  const reflectMutation = useMutation({
    mutationFn: async (pdfs: string[]) => {
      const docMap = new Map(rows.map((r) => [r.pdf_filename, r.total_pages]))
      for (const pdf of pdfs) {
        const total = docMap.get(pdf) ?? 0
        for (let p = 1; p <= total; p++) {
          await ragAdminApi.setLearningFlag({ pdf_filename: pdf, page_number: p, selected: true })
        }
      }
      return ragAdminApi.buildFromLearningPages(undefined)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents', 'in-vector-index'] })
      queryClient.invalidateQueries({ queryKey: ['rag-admin', 'learning-pages'] })
      queryClient.invalidateQueries({ queryKey: ['rag-admin', 'status'] })
      setSelectedPdfs(new Set())
    },
  })

  const handleReflect = useCallback(() => {
    const pdfs = Array.from(selectedPdfs).filter((pdf) => {
      const r = rows.find((x) => x.pdf_filename === pdf)
      return r && !r.in_vector
    })
    if (pdfs.length === 0) return
    reflectMutation.mutate(pdfs)
  }, [selectedPdfs, rows, reflectMutation])

  const canReflect = selectedPdfs.size > 0 && !reflectMutation.isPending
  const unreflectedCount = rows.filter((r) => !r.in_vector).length

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

  return (
    <div className="vector-reflect-tab">
      <div className="vector-reflect-header">
        <h2 className="vector-reflect-title">ベクターDB反映</h2>
        <p className="vector-reflect-desc">
          未反映の文書を選択し、一括でベクターDBに登録します。反映済の文書は編集・解答作成の内容が学習に使われた状態です。
        </p>
      </div>

      <div className="vector-reflect-actions">
        <button
          type="button"
          className="vector-reflect-btn vector-reflect-btn-primary"
          onClick={handleReflect}
          disabled={!canReflect}
          title={selectedPdfs.size > 0 ? `${selectedPdfs.size}件をベクターDBに反映します` : '未反映の文書を選択してください'}
        >
          {reflectMutation.isPending ? '反映中…' : `選択をベクターDBに反映（${selectedPdfs.size}件）`}
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

      <div className="vector-reflect-table-wrap">
        <table className="vector-reflect-table">
          <thead>
            <tr>
              <th className="vector-reflect-th-check">選択</th>
              <th>文書名</th>
              <th className="vector-reflect-th-pages">p</th>
              <th className="vector-reflect-th-status">状態</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={4} className="vector-reflect-empty">
                  文書がありません。
                </td>
              </tr>
            )}
            {rows.map((row) => (
              <tr key={row.pdf_filename} className={row.in_vector ? 'vector-reflect-row-reflected' : ''}>
                <td className="vector-reflect-td-check">
                  {row.in_vector ? (
                    <span className="vector-reflect-check-disabled">—</span>
                  ) : (
                    <input
                      type="checkbox"
                      checked={selectedPdfs.has(row.pdf_filename)}
                      onChange={() => toggleSelect(row.pdf_filename, row.in_vector)}
                      aria-label={`${row.pdf_filename}を選択`}
                    />
                  )}
                </td>
                <td className="vector-reflect-td-name">{row.pdf_filename}</td>
                <td className="vector-reflect-td-pages">{row.total_pages}p</td>
                <td className="vector-reflect-td-status">
                  {row.in_vector ? (
                    <span className="vector-reflect-badge reflected">反映済</span>
                  ) : (
                    <span className="vector-reflect-badge not">未反映</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="vector-reflect-footer">
        未反映: {unreflectedCount}件 / 全体: {rows.length}件
      </p>
    </div>
  )
}
