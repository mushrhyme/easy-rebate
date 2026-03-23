/**
 * 첨부 파일 모달: 행(item_id) 단위 PDF 업로드·목록
 * 저장: static/attachments/{safe_doc}/items/{item_id}/
 * 레거시(문서 루트 PDF)는 1行目で「この行に移動」で 이행 가능
 */
import { useEffect, useRef, useState } from 'react'
import { attachmentsApi } from '@/api/client'

interface AttachmentModalProps {
  open: boolean
  onClose: () => void
  pdfFilename: string
  /** 열린 행의 item_id */
  itemId: number
  /** true: 旧ページ単位の残りをこの行に取り込める（通常は先頭行のみ） */
  canClaimLegacy: boolean
}

export function AttachmentModal({
  open,
  onClose,
  pdfFilename,
  itemId,
  canClaimLegacy,
}: AttachmentModalProps) {
  const [files, setFiles] = useState<Array<{ name: string; url: string }>>([])
  const [legacyFiles, setLegacyFiles] = useState<Array<{ name: string; url: string }>>([])
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [claiming, setClaiming] = useState(false)
  const [deletingName, setDeletingName] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const fetchList = async () => {
    if (!pdfFilename || !itemId) return
    setLoading(true)
    setError(null)
    try {
      const res = await attachmentsApi.list(pdfFilename, itemId) // 행 단위 목록
      setFiles(res.files ?? [])
      // legacy-list 실패(404 등)는 본문 목록에 영향 없음
      if (canClaimLegacy) {
        try {
          const leg = await attachmentsApi.legacyList(pdfFilename)
          setLegacyFiles(leg.files ?? [])
        } catch {
          setLegacyFiles([])
        }
      } else {
        setLegacyFiles([])
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(msg)
      setFiles([])
      setLegacyFiles([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open && pdfFilename && itemId) void fetchList()
  }, [open, pdfFilename, itemId, canClaimLegacy])

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file || !file.name.toLowerCase().endsWith('.pdf')) return
    setUploading(true)
    setError(null)
    try {
      await attachmentsApi.upload(pdfFilename, itemId, file)
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
      await attachmentsApi.delete(pdfFilename, itemId, fileName)
      await fetchList()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(msg)
    } finally {
      setDeletingName(null)
    }
  }

  const handleClaimLegacy = async () => {
    if (!canClaimLegacy || legacyFiles.length === 0) return
    if (!window.confirm('ページ単位で保存されていた添付を、この行（先頭行）に移しますか？')) return
    setClaiming(true)
    setError(null)
    try {
      await attachmentsApi.claimLegacy(pdfFilename, itemId)
      await fetchList()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(msg)
    } finally {
      setClaiming(false)
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
          <h3>添付ファイル（PDF）— 行単位</h3>
          <button type="button" className="attachment-modal-close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="attachment-modal-body">
          {canClaimLegacy && legacyFiles.length > 0 && (
            <div
              className="attachment-modal-legacy-banner"
              style={{
                marginBottom: 12,
                padding: '8px 10px',
                background: 'var(--legacy-banner-bg, #2a2418)',
                border: '1px solid var(--legacy-banner-border, #5c4d2a)',
                borderRadius: 6,
                fontSize: 13,
              }}
            >
              <p style={{ margin: '0 0 8px' }}>
                旧保存（ページ共有）のPDFが {legacyFiles.length} 件あります。先頭行に取り込みます。
              </p>
              <button
                type="button"
                className="attachment-modal-btn-upload"
                disabled={claiming}
                onClick={() => void handleClaimLegacy()}
              >
                {claiming ? '移動中...' : 'この行に移動（先頭行）'}
              </button>
            </div>
          )}
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
