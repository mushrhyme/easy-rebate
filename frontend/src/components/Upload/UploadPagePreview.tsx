/**
 * 업로드 목록에서 선택한 PDF 1페이지 미리보기
 */
import { useQuery } from '@tanstack/react-query'
import { searchApi } from '@/api/client'
import { getApiBaseUrl } from '@/utils/apiConfig'
import './UploadPagePreview.css'

interface UploadPagePreviewProps {
  pdfFilename: string | null
  pageNumber?: number
}

export function UploadPagePreview({ pdfFilename, pageNumber = 1 }: UploadPagePreviewProps) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['page-image', pdfFilename, pageNumber],
    queryFn: () => searchApi.getPageImage(pdfFilename!, pageNumber),
    enabled: !!pdfFilename && pageNumber >= 1,
  })

  if (!pdfFilename) {
    return (
      <div className="upload-page-preview upload-page-preview-empty">
        一覧からファイルをクリックしてプレビュー
      </div>
    )
  }

  return (
    <div className="upload-page-preview">
      {isLoading && <div className="upload-page-preview-loading">画像読み込み中...</div>}
      {error && (
        <div className="upload-page-preview-error">
          画像の読み込みに失敗しました
        </div>
      )}
      {data && (
        <div className="upload-page-preview-image-wrap">
          <img
            src={data.image_url.startsWith('http') ? data.image_url : `${getApiBaseUrl()}${data.image_url}`}
            alt={`Page ${pageNumber}`}
            className="upload-page-preview-image"
          />
        </div>
      )}
    </div>
  )
}
