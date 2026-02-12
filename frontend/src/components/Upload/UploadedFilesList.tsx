/**
 * アップロード済みファイル一覧（チャネル別・様式別・削除対応）
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { documentsApi } from '@/api/client'
import type { UploadChannel } from '@/types'
import type { Document } from '@/types'
import { UPLOAD_CHANNEL_CONFIGS } from '@/config/formConfig'
import { useFormTypes } from '@/hooks/useFormTypes'
import './UploadedFilesList.css'

interface UploadedFilesListProps {
  selectedChannel: UploadChannel
  /** 날짜 필터 (업로드 블록의 년·월 선택과 연동) */
  filterYear?: number | null
  filterMonth?: number | null
  onSelectDocument?: (pdfFilename: string, totalPages: number) => void
  selectedPdfFilename?: string | null
}

function formatDate(created_at?: string, data_year?: number, data_month?: number): string {
  if (data_year && data_month) {
    return `${data_year}年${String(data_month).padStart(2, '0')}月`
  }
  if (created_at) {
    const d = new Date(created_at)
    if (!isNaN(d.getTime())) {
      return `${d.getFullYear()}年${String(d.getMonth() + 1).padStart(2, '0')}月${String(d.getDate()).padStart(2, '0')}日`
    }
  }
  return '—'
}

function getDocYearMonth(doc: Document): { year: number; month: number } {
  if (doc.data_year && doc.data_month && doc.data_year > 0 && doc.data_month >= 1 && doc.data_month <= 12) {
    return { year: doc.data_year, month: doc.data_month }
  }
  const dateString = doc.created_at || doc.upload_date
  if (dateString) {
    const d = new Date(dateString)
    if (!isNaN(d.getTime())) {
      return { year: d.getFullYear(), month: d.getMonth() + 1 }
    }
  }
  return { year: new Date().getFullYear(), month: new Date().getMonth() + 1 }
}

export function UploadedFilesList({ selectedChannel, filterYear, filterMonth, onSelectDocument, selectedPdfFilename }: UploadedFilesListProps) {
  const queryClient = useQueryClient()
  const channelLabel = UPLOAD_CHANNEL_CONFIGS[selectedChannel]?.name ?? selectedChannel
  const { options: formTypeOptions, formTypeLabel } = useFormTypes()
  /** 様式 필터 (null = 全て) */
  const [formTypeFilter, setFormTypeFilter] = useState<string | null>(null)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['documents', 'upload_channel', selectedChannel],
    queryFn: () => documentsApi.getList(selectedChannel),
  })

  const deleteMutation = useMutation({
    mutationFn: (pdfFilename: string) => documentsApi.delete(pdfFilename),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents', 'upload_channel', selectedChannel] })
      queryClient.invalidateQueries({ queryKey: ['documents', 'all'] })
    },
    onError: (err: unknown) => {
      const msg = err && typeof err === 'object' && 'response' in err
        ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        : null
      window.alert(msg ? `削除に失敗しました: ${msg}` : '削除に失敗しました。')
    },
  })

  const updateFormTypeMutation = useMutation({
    mutationFn: ({ pdfFilename, formType }: { pdfFilename: string; formType: string }) =>
      documentsApi.updateFormType(pdfFilename, formType),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents', 'upload_channel', selectedChannel] })
      queryClient.invalidateQueries({ queryKey: ['documents', 'all'] })
      queryClient.invalidateQueries({ queryKey: ['form-types'] })
    },
    onError: (err: unknown) => {
      const msg = err && typeof err === 'object' && 'response' in err
        ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        : null
      window.alert(msg ? `様式の更新に失敗しました: ${msg}` : '様式の更新に失敗しました。')
    },
  })

  const allDocuments = data?.documents ?? []
  const byYearMonth =
    filterYear != null && filterMonth != null
      ? allDocuments.filter((doc) => {
          const { year, month } = getDocYearMonth(doc)
          return year === filterYear && month === filterMonth
        })
      : allDocuments
  const documents = formTypeFilter != null
    ? byYearMonth.filter((doc) => doc.form_type === formTypeFilter)
    : byYearMonth
  const total = documents.length

  return (
    <section className="uploaded-files-list">
      <div className="uploaded-files-list-header">
        <h2 className="uploaded-files-list-title">
          アップロード済みファイル <span className="uploaded-files-list-channel">— {channelLabel}</span>
        </h2>
      </div>

      {/* 様式 필터 */}
      {!isLoading && !isError && allDocuments.length > 0 && (
        <div className="uploaded-files-list-filters">
          <label className="uploaded-files-list-filter-label">
            様式
            <select
              value={formTypeFilter ?? ''}
              onChange={(e) => setFormTypeFilter(e.target.value === '' ? null : e.target.value)}
              className="uploaded-files-list-form-type-select"
              aria-label="様式で絞り込み"
            >
              <option value="">全て</option>
              {formTypeOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </label>
        </div>
      )}

      {isLoading && (
        <div className="uploaded-files-list-loading">読み込み中...</div>
      )}
      {isError && (
        <div className="uploaded-files-list-error">一覧の取得に失敗しました。</div>
      )}
      {!isLoading && !isError && documents.length === 0 && (
        <div className="uploaded-files-list-empty">
          {formTypeFilter != null
            ? `選択した様式（${formTypeLabel(formTypeFilter)}）に該当するファイルはありません。`
            : filterYear != null && filterMonth != null
              ? `選択した年月（${filterYear}年${String(filterMonth).padStart(2, '0')}月）にアップロード済みファイルはありません。`
              : 'このチャネルにはアップロード済みファイルがありません。'}
        </div>
      )}
      {!isLoading && !isError && documents.length > 0 && (
        <>
          <div className="uploaded-files-list-summary">
            {total}件
          </div>
          <div className="uploaded-files-list-table-wrap">
            <table className="uploaded-files-list-table">
              <thead>
                <tr>
                  <th>ファイル名</th>
                  <th>様式</th>
                  <th>日付</th>
                  <th>ページ数</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {documents.map((doc: Document) => (
                  <tr
                    key={doc.pdf_filename}
                    className={selectedPdfFilename === doc.pdf_filename ? 'uploaded-files-list-row-selected' : ''}
                    onClick={() => onSelectDocument?.(doc.pdf_filename, doc.total_pages)}
                    role={onSelectDocument ? 'button' : undefined}
                    tabIndex={onSelectDocument ? 0 : undefined}
                    onKeyDown={(e) => onSelectDocument && (e.key === 'Enter' || e.key === ' ') && onSelectDocument(doc.pdf_filename, doc.total_pages)}
                  >
                    <td className="uploaded-files-list-cell-filename">{doc.pdf_filename}</td>
                    <td className="uploaded-files-list-cell-form-type" onClick={(e) => e.stopPropagation()}>
                      <select
                        className="uploaded-files-list-form-type-edit"
                        value={doc.form_type ?? ''}
                        onChange={(e) => {
                          const v = e.target.value
                          if (v) updateFormTypeMutation.mutate({ pdfFilename: doc.pdf_filename, formType: v })
                        }}
                        disabled={updateFormTypeMutation.isPending}
                        aria-label="様式を変更"
                        title="様式を変更"
                      >
                        <option value="">—</option>
                        {formTypeOptions.map((opt) => (
                          <option key={opt.value} value={opt.value}>{opt.label}</option>
                        ))}
                      </select>
                    </td>
                    <td className="uploaded-files-list-cell-date">
                      {formatDate(doc.created_at, doc.data_year, doc.data_month)}
                    </td>
                    <td className="uploaded-files-list-cell-pages">{doc.total_pages}ページ</td>
                    <td className="uploaded-files-list-cell-actions">
                      <button
                        type="button"
                        className="uploaded-files-list-delete"
                        onClick={(e) => {
                          e.stopPropagation()
                          if (window.confirm(`「${doc.pdf_filename}」を削除しますか？`)) {
                            deleteMutation.mutate(doc.pdf_filename)
                          }
                        }}
                        disabled={deleteMutation.isPending}
                        aria-label="削除"
                      >
                        削除
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  )
}
