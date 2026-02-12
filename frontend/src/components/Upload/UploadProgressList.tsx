/**
 * 오른쪽 패널에 표시하는 업로드 중 파일 목록 (선택된 채널만)
 */
import type { UploadChannel } from '@/types'
import { UPLOAD_CHANNEL_CONFIGS } from '@/config/formConfig'
import './UploadProgressList.css'

export interface UploadProgressItem {
  status: 'pending' | 'processing' | 'completed' | 'error'
  message?: string
  progress?: number
  currentPage?: number
  totalPages?: number
}

interface UploadProgressListProps {
  channel: UploadChannel
  fileNames: string[]
  progress: Record<string, UploadProgressItem>
  isUploading: boolean
  onRemove: (fileName: string) => void
}

function getStatusMessage(progress: UploadProgressItem | undefined): string {
  if (!progress) return ''
  switch (progress.status) {
    case 'pending':
      return '待機中'
    case 'processing':
      if (progress.currentPage != null && progress.totalPages != null) {
        return `処理中: ${progress.currentPage}/${progress.totalPages} - ${progress.message || ''}`
      }
      return progress.message || '処理中...'
    case 'completed':
      return progress.message || '完了'
    case 'error':
      return progress.message || 'エラー'
    default:
      return ''
  }
}

export function UploadProgressList({
  channel,
  fileNames,
  progress,
  isUploading,
  onRemove,
}: UploadProgressListProps) {
  const channelLabel = UPLOAD_CHANNEL_CONFIGS[channel]?.name ?? channel

  if (fileNames.length === 0) return null

  return (
    <section className="upload-progress-list">
      <div className="upload-progress-list-header">
        <h3 className="upload-progress-list-title">
          アップロード中 <span className="upload-progress-list-channel">— {channelLabel}</span>
        </h3>
      </div>
      <div className="upload-progress-list-summary">{fileNames.length}件</div>
      <div className="upload-progress-list-table-wrap">
        <table className="upload-progress-list-table">
          <thead>
            <tr>
              <th>ファイル名</th>
              <th>状態</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {fileNames.map((fileName) => {
              const p = progress[fileName]
              const statusMessage = getStatusMessage(p)
              const isProcessing = p?.status === 'processing'
              const isCompleted = p?.status === 'completed'
              const isError = p?.status === 'error'

              return (
                <tr key={fileName}>
                  <td className="upload-progress-list-cell-filename">{fileName}</td>
                  <td className="upload-progress-list-cell-status">
                    {statusMessage && (
                      <span
                        className={`upload-progress-item-status ${
                          isCompleted
                            ? 'upload-progress-status-completed'
                            : isError
                              ? 'upload-progress-status-error'
                              : isProcessing
                                ? 'upload-progress-status-processing'
                                : 'upload-progress-status-pending'
                        }`}
                      >
                        {statusMessage}
                        {isProcessing && p?.progress != null && (
                          <div className="upload-progress-bar">
                            <div
                              className="upload-progress-fill"
                              style={{ width: `${p.progress * 100}%` }}
                            />
                          </div>
                        )}
                      </span>
                    )}
                  </td>
                  <td className="upload-progress-list-cell-actions">
                    {!isUploading && (
                      <button
                        type="button"
                        onClick={() => onRemove(fileName)}
                        className="upload-progress-list-delete"
                        title="ファイルを削除"
                      >
                        削除
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}
