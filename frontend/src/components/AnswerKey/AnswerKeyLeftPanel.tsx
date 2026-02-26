/**
 * 정답지 탭 — 좌측: 페이지 네비, 이미지, OCR 영역
 */
interface AnswerKeyLeftPanelProps {
  selectedDoc: { pdf_filename: string; total_pages: number } | null
  currentPage: number
  setCurrentPage: React.Dispatch<React.SetStateAction<number>>
  imageScrollRef: React.RefObject<HTMLDivElement | null>
  imageZoomContainerRef: React.RefObject<HTMLDivElement | null>
  allImagesLoaded: boolean
  imageUrls: (string | null)[]
  imageScale: number
  imageSize: { w: number; h: number } | null
  setImageSize: React.Dispatch<React.SetStateAction<{ w: number; h: number } | null>>
  pageOcrTextQueries: Array<{ data?: { ocr_text?: string }; isLoading?: boolean }>
}

export function AnswerKeyLeftPanel({
  selectedDoc,
  currentPage,
  setCurrentPage,
  imageScrollRef,
  imageZoomContainerRef,
  allImagesLoaded,
  imageUrls,
  imageScale,
  imageSize,
  setImageSize,
  pageOcrTextQueries,
}: AnswerKeyLeftPanelProps) {
  return (
    <div className="answer-key-left">
      <div className="answer-key-page-nav">
        <button
          type="button"
          className="answer-key-nav-btn"
          onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
          disabled={currentPage <= 1}
          aria-label="前のページ"
        >
          ← 前
        </button>
        <span className="answer-key-page-info">
          {currentPage} / {selectedDoc?.total_pages ?? 0}
        </span>
        <button
          type="button"
          className="answer-key-nav-btn"
          onClick={() =>
            setCurrentPage((p) => Math.min(selectedDoc?.total_pages ?? 1, p + 1))
          }
          disabled={currentPage >= (selectedDoc?.total_pages ?? 1)}
          aria-label="次のページ"
        >
          次 →
        </button>
      </div>
      <div ref={imageScrollRef} className="answer-key-left-scroll">
        <div
          ref={imageZoomContainerRef}
          className="answer-key-page-view answer-key-page-view-zoom"
        >
          {!allImagesLoaded && <p className="answer-key-loading">画像読み込み中…</p>}
          {allImagesLoaded && imageUrls[currentPage - 1] && (
            <div
              key={`img-wrap-${currentPage}`}
              className="answer-key-image-zoom-wrapper"
              style={
                imageSize
                  ? { width: imageSize.w * imageScale, height: imageSize.h * imageScale }
                  : undefined
              }
            >
              <img
                key={currentPage}
                src={imageUrls[currentPage - 1]!}
                alt={`Page ${currentPage}`}
                className="answer-key-page-img"
                onLoad={(e) => {
                  const img = e.currentTarget
                  setImageSize({ w: img.naturalWidth, h: img.naturalHeight })
                }}
                style={
                  imageSize
                    ? {
                        width: imageSize.w * imageScale,
                        height: imageSize.h * imageScale,
                        objectFit: 'fill',
                      }
                    : undefined
                }
              />
            </div>
          )}
        </div>
        <div className="answer-key-ocr-section">
          <label className="answer-key-ocr-label">OCRテキスト</label>
          <textarea
            className="answer-key-ocr-text"
            readOnly
            value={
              pageOcrTextQueries[currentPage - 1]?.data?.ocr_text ??
              (pageOcrTextQueries[currentPage - 1]?.isLoading ? '読み込み中…' : '')
            }
            placeholder="（OCR 텍스트 없음）"
            rows={6}
          />
        </div>
      </div>
    </div>
  )
}
