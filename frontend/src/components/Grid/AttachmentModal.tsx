/**
 * 첨부 파일 모달: PDF 업로드, 목록 표시, 클릭 시 새 탭에서 열기
 * 저장 경로: static/attachments/{pdf_filename}/
 */
import { useEffect, useRef, useState } from 'react'
import { attachmentsApi } from '@/api/client'

interface AttachmentModalProps {
  open: boolean
  onClose: () => void
  pdfFilename: string
}

export function AttachmentModal({ open, onClose, pdfFilename }: AttachmentModalProps) {
  const [files, setFiles] = useState<Array<{ name: string; url: string }>>([])
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [deletingName, setDeletingName] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const fetchList = async () => {
    if (!pdfFilename) return
    setLoading(true)
    setError(null)
    try {
      const res = await attachmentsApi.list(pdfFilename)
      setFiles(res.files ?? [])
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(msg)
      setFiles([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open && pdfFilename) void fetchList()
  }, [open, pdfFilename])

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file || !file.name.toLowerCase().endsWith('.pdf')) return
    setUploading(true)
    setError(null)
    try {
      await attachmentsApi.upload(pdfFilename, file)
      await fetchList()
      e.target.value = ''
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(msg)
    } finally {
      setUploading(false)
    }
  }

  const openInNewTab = (url: string) => {
    const base = typeof window !== 'undefined' ? window.location.origin : ''
    window.open(`${base}${url}`, '_blank', 'noopener,noreferrer')
  }

  const handleDelete = async (fileName: string) => {
    if (!window.confirm(`「${fileName}」を削除しますか？`)) return
    setDeletingName(fileName)
    setError(null)
    try {
      await attachmentsApi.delete(pdfFilename, fileName)
      await fetchList()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(msg)
    } finally {
      setDeletingName(null)
    }
  }

  if (!open) return null

  return (
    <div className="attachment-modal-overlay" onClick={onClose}>
      <div
        className="attachment-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="添付ファイル"
      >
        <div className="attachment-modal-header">
          <h3>添付ファイル（PDF）</h3>
          <button type="button" className="attachment-modal-close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="attachment-modal-body">
          <div className="attachment-modal-upload">
            <input
              ref={inputRef}
              type="file"
              accept=".pdf,application/pdf"
              onChange={handleFileChange}
              disabled={uploading}
              style={{ display: 'none' }}
            />
            <button
              type="button"
              className="attachment-modal-btn-upload"
              disabled={uploading}
              onClick={() => inputRef.current?.click()}
            >
              {uploading ? 'アップロード中...' : 'PDFを選択してアップロード'}
            </button>
          </div>
          {error && <p className="attachment-modal-error">{error}</p>}
          <div className="attachment-modal-list-wrap">
            {loading ? (
              <p className="attachment-modal-message">読み込み中...</p>
            ) : files.length === 0 ? (
              <p className="attachment-modal-message">添付ファイルはありません。</p>
            ) : (
              <ul className="attachment-modal-list">
                {files.map((f) => (
                  <li key={f.name} className="attachment-modal-list-row">
                    <button
                      type="button"
                      className="attachment-modal-file-item"
                      onClick={() => openInNewTab(f.url)}
                    >
                      📄 {f.name}
                    </button>
                    <button
                      type="button"
                      className="attachment-modal-btn-delete"
                      title="削除"
                      disabled={deletingName === f.name}
                      onClick={(e) => {
                        e.stopPropagation()
                        handleDelete(f.name)
                      }}
                    >
                      {deletingName === f.name ? '...' : '削除'}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
