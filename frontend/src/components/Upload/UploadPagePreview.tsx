/**
 * 업로드 목록에서 선택한 PDF 1페이지 미리보기
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { searchApi, documentsApi } from '@/api/client'
import { getPageImageAbsoluteUrl } from '@/utils/apiConfig'
import './UploadPagePreview.css'

interface UploadPagePreviewProps {
  pdfFilename: string | null
  pageNumber?: number
}

export function UploadPagePreview({ pdfFilename, pageNumber = 1 }: UploadPagePreviewProps) {
  const queryClient = useQueryClient()
  const { data, isLoading, error } = useQuery({
    queryKey: ['page-image', pdfFilename, pageNumber],
    queryFn: () => searchApi.getPageImage(pdfFilename!, pageNumber),
    enabled: !!pdfFilename && pageNumber >= 1,
  })

  const generateImagesMutation = useMutation({
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

  const noImage = data && !data.image_url && !isLoading && !error

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
      {data && data.image_url && (() => {
        const src = getPageImageAbsoluteUrl(data.image_url)
        return src ? (
        <div className="upload-page-preview-image-wrap">
          <img
            src={src}
            alt={`Page ${pageNumber}`}
            className="upload-page-preview-image"
          />
        </div>
        ) : null
      })()}
      {noImage && (
        <div className="upload-page-preview-no-image">
          <p className="upload-page-preview-no-image-message">画像がまだ生成されていません</p>
          <p className="upload-page-preview-no-image-hint">
            PDFがサーバーのimgフォルダ等に残っていれば、下のボタンで画像を生成できます。
          </p>
          <button
            type="button"
            className="upload-page-preview-generate-btn"
            onClick={() => generateImagesMutation.mutate(pdfFilename)}
            disabled={generateImagesMutation.isPending}
          >
            {generateImagesMutation.isPending ? '生成中...' : 'ページ画像を生成'}
          </button>
          {generateImagesMutation.isSuccess && (
            <p className="upload-page-preview-generate-success">生成しました。プレビューを更新しています。</p>
          )}
        </div>
      )}
    </div>
  )
}
