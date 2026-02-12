/**
 * OCR 테스트 탭: 이미지 업로드 → Upstage OCR / 구조化JSON 입력 → 필드 클릭 시 해당 영역 하이라이트
 */
import { useState, useRef, useCallback, useEffect, useMemo } from 'react'
import { ocrTestApi, type OcrTestResponse, type OcrWord, type OcrSuggestRow } from '@/api/client'
import './OcrTestTab.css'

/** キーイン対象フィールド（固定） */
const KEYIN_FIELDS = ['受注先', 'スーパー'] as const

function verticesToRect(vertices: Array<{ x: number; y: number }>) {
  if (!vertices?.length) return null
  const xs = vertices.map((v) => v.x)
  const ys = vertices.map((v) => v.y)
  const left = Math.min(...xs)
  const top = Math.min(...ys)
  const right = Math.max(...xs)
  const bottom = Math.max(...ys)
  return { left, top, width: right - left, height: bottom - top }
}

type HighlightRect = { left: number; top: number; width: number; height: number }

export function OcrTestTab() {
  const [file, setFile] = useState<File | null>(null)
  const [pdfUploadId, setPdfUploadId] = useState<string | null>(null)
  const [numPages, setNumPages] = useState(0)
  const [currentPage, setCurrentPage] = useState(1)
  const [ocrResultByPage, setOcrResultByPage] = useState<Record<number, OcrTestResponse>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [highlightRect, setHighlightRect] = useState<HighlightRect | null>(null)
  const [selectedWordIndex, setSelectedWordIndex] = useState<number | null>(null)
  const [showWordBoxes, setShowWordBoxes] = useState(true)
  const [selectedFieldKey, setSelectedFieldKey] = useState<string | null>(null)
  const [keyedValues, setKeyedValues] = useState<Record<string, string>>({})
  const [appendMode, setAppendMode] = useState(false)
  /** どのフィールドの「保存」でコード候補を表示中か */
  const [suggestFieldKey, setSuggestFieldKey] = useState<string | null>(null)
  /** 今回の検索に使ったキーワード（モーダル・マッチ結果表示用） */
  const [suggestKeyword, setSuggestKeyword] = useState<string>('')
  const [suggestLoading, setSuggestLoading] = useState(false)
  const [suggestions, setSuggestions] = useState<OcrSuggestRow[]>([])
  /** master_codeから選択したペア（B列→受注先, D列→スーパー）を一覧表示用 */
  const [lastMatchedPair, setLastMatchedPair] = useState<{
    keyword: string
    field: string
    b: string
    d: string
  } | null>(null)
  const imageContainerRef = useRef<HTMLDivElement>(null)

  const ocrResult = ocrResultByPage[currentPage] ?? null
  const page = ocrResult?.pages?.[0]
  const words = page?.words ?? []
  const pageWidth = page?.width ?? 1
  const pageHeight = page?.height ?? 1

  const pageImageUrl = pdfUploadId && numPages >= 1
    ? ocrTestApi.getPdfPageImageUrl(pdfUploadId, currentPage)
    : null

  /** OCR 단어별 bbox (페이지 좌표). 이미지에 박스 그리기·클릭 시 텍스트 표시용 */
  const wordRects = useMemo(() => {
    return words
      .map((w) => {
        const rect = w.boundingBox?.vertices ? verticesToRect(w.boundingBox.vertices) : null
        return rect ? { word: w, rect } : null
      })
      .filter((x): x is { word: OcrWord; rect: NonNullable<ReturnType<typeof verticesToRect>> } => x != null)
  }, [words])

  const handleFileChange = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    setFile(f ?? null)
    setPdfUploadId(null)
    setNumPages(0)
    setCurrentPage(1)
    setOcrResultByPage({})
    setHighlightRect(null)
    setSelectedWordIndex(null)
    setKeyedValues({})
    setSelectedFieldKey(null)
    setSuggestFieldKey(null)
    setSuggestKeyword('')
    setSuggestions([])
    setLastMatchedPair(null)
    setError(null)
    if (!f || !f.name.toLowerCase().endsWith('.pdf')) return
    setLoading(true)
    setError(null)
    try {
      const { upload_id, num_pages } = await ocrTestApi.uploadPdf(f)
      setPdfUploadId(upload_id)
      setNumPages(num_pages)
      setCurrentPage(1)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'PDFアップロードに失敗しました')
    } finally {
      setLoading(false)
    }
  }, [])

  const runOcr = useCallback(async () => {
    if (!pdfUploadId) return
    setLoading(true)
    setError(null)
    try {
      const result = await ocrTestApi.ocrPdfPage(pdfUploadId, currentPage)
      setOcrResultByPage((prev) => ({ ...prev, [currentPage]: result }))
      setHighlightRect(null)
      setSelectedWordIndex(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'OCRに失敗しました')
    } finally {
      setLoading(false)
    }
  }, [pdfUploadId, currentPage])

  /** 画像のボックスをクリック: フィールド選択中ならそのフィールドにキーイン（追加モード時はつなげる） */
  const handleWordBoxClick = useCallback(
    (index: number, rect: HighlightRect) => {
      setSelectedWordIndex(index)
      setHighlightRect(rect)
      const text = words[index]?.text ?? ''
      if (selectedFieldKey && text) {
        if (appendMode) {
          setKeyedValues((prev) => ({
            ...prev,
            [selectedFieldKey]: (prev[selectedFieldKey] ?? '') + text,
          }))
        } else {
          setKeyedValues((prev) => ({ ...prev, [selectedFieldKey]: text }))
        }
      }
    },
    [words, selectedFieldKey, appendMode]
  )

  /** 行の「保存」クリック → 検索キーワード保存 → master_codeから類似3件取得 → モーダル表示 */
  const handleSaveForField = useCallback(
    async (fieldKey: string) => {
      const value = keyedValues[fieldKey] ?? ''
      setSuggestFieldKey(fieldKey)
      setSuggestKeyword(value)
      setSuggestLoading(true)
      setSuggestions([])
      try {
        const { suggestions: list } = await ocrTestApi.suggestCodes(value, fieldKey)
        setSuggestions(list ?? [])
      } catch (e) {
        setSuggestions([])
        setError(e instanceof Error ? e.message : 'コード候補の取得に失敗しました')
      } finally {
        setSuggestLoading(false)
      }
    },
    [keyedValues]
  )

  /** 候補行を選択: B列→受注先・D列→スーパーを反映し、マッチ結果を記録 */
  const handleSelectSuggestion = useCallback(
    (row: OcrSuggestRow) => {
      if (suggestFieldKey) {
        setKeyedValues((prev) => ({
          ...prev,
          [suggestFieldKey]: row.b,
          'スーパー': row.d || prev['スーパー'],
        }))
        setLastMatchedPair({
          keyword: suggestKeyword,
          field: suggestFieldKey,
          b: row.b,
          d: row.d,
        })
        setSuggestFieldKey(null)
        setSuggestKeyword('')
        setSuggestions([])
      }
    },
    [suggestFieldKey, suggestKeyword]
  )

  useEffect(() => {
    if (!highlightRect || !imageContainerRef.current) return
    const container = imageContainerRef.current
    const img = container.querySelector('img')
    if (!img) return
    const scaleX = img.offsetWidth / pageWidth
    const scaleY = img.offsetHeight / pageHeight
    const centerY = (highlightRect.top + highlightRect.height / 2) * scaleY
    const centerX = (highlightRect.left + highlightRect.width / 2) * scaleX
    container.scrollTop = Math.max(0, centerY - container.clientHeight / 2)
    container.scrollLeft = Math.max(0, centerX - container.clientWidth / 2)
  }, [highlightRect, pageWidth, pageHeight])

  useEffect(() => {
    setHighlightRect(null)
    setSelectedWordIndex(null)
  }, [currentPage])

  return (
    <div className="ocr-test-tab">
      <div className="ocr-test-header">
        <h2 className="ocr-test-title">OCRテスト（キーイン・保存）</h2>
        <p className="ocr-test-desc">
          PDFをアップロード → ページ移動・OCR実行でボックス表示。右でフィールドを選択してから画像のボックスをクリックでキーイン → 保存（入力はページを替えても維持）。
        </p>
      </div>

      <div className="ocr-test-upload-row">
        <input
          type="file"
          accept=".pdf,application/pdf"
          onChange={handleFileChange}
          className="ocr-test-file-input"
        />
        <button
          type="button"
          onClick={runOcr}
          disabled={!pdfUploadId || loading}
          className="ocr-test-run-btn"
        >
          {loading ? 'OCR実行中...' : 'OCR実行'}
        </button>
      </div>

      {error && <div className="ocr-test-error">{error}</div>}

      <div className="ocr-test-main">
        <div className="ocr-test-image-panel">
          {pdfUploadId && numPages >= 1 && (
            <div className="ocr-test-page-nav">
              <button
                type="button"
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                disabled={currentPage <= 1}
                className="ocr-test-nav-btn"
              >
                ‹
              </button>
              <span className="ocr-test-page-info">
                {currentPage} / {numPages}
              </span>
              <button
                type="button"
                onClick={() => setCurrentPage((p) => Math.min(numPages, p + 1))}
                disabled={currentPage >= numPages}
                className="ocr-test-nav-btn"
              >
                ›
              </button>
            </div>
          )}
          <div
            ref={imageContainerRef}
            className="ocr-test-image-container"
          >
            {pageImageUrl && (
              <div className="ocr-test-image-wrapper">
                <img src={pageImageUrl} alt={`Page ${currentPage}`} />
                {page && showWordBoxes && wordRects.length > 0 && (
                  <div className="ocr-test-boxes-overlay" aria-hidden>
                    {wordRects.map(({ word, rect }, index) => (
                      <button
                        key={word.id ?? index}
                        type="button"
                        className={`ocr-test-word-box ${selectedWordIndex === index ? 'ocr-test-word-box-selected' : ''}`}
                        style={{
                          left: `${(rect.left / pageWidth) * 100}%`,
                          top: `${(rect.top / pageHeight) * 100}%`,
                          width: `${(rect.width / pageWidth) * 100}%`,
                          height: `${(rect.height / pageHeight) * 100}%`,
                        }}
                        onClick={(e) => {
                          e.stopPropagation()
                          handleWordBoxClick(index, rect)
                        }}
                        title={word.text}
                      />
                    ))}
                  </div>
                )}
                {page && highlightRect && (
                  <div className="ocr-test-overlay">
                    <div
                      className="ocr-test-highlight"
                      style={{
                        left: `${(highlightRect.left / pageWidth) * 100}%`,
                        top: `${(highlightRect.top / pageHeight) * 100}%`,
                        width: `${(highlightRect.width / pageWidth) * 100}%`,
                        height: `${(highlightRect.height / pageHeight) * 100}%`,
                      }}
                    />
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        <div className="ocr-test-words-panel">
          {pdfUploadId && numPages >= 1 && (
            <>
              <div className="ocr-test-words-label">キーイン（ページを替えても維持）・保存でmaster_codeから類似候補を選択</div>
              <div className="ocr-test-keyin-fields">
                {KEYIN_FIELDS.map((key) => (
                  <div key={key} className="ocr-test-keyin-row">
                    <button
                      type="button"
                      className={`ocr-test-keyin-key ${selectedFieldKey === key ? 'ocr-test-keyin-key-selected' : ''}`}
                      onClick={() => setSelectedFieldKey(key)}
                    >
                      {key}
                    </button>
                    <span className="ocr-test-keyin-value">{keyedValues[key] ?? '—'}</span>
                    <button
                      type="button"
                      onClick={() => handleSaveForField(key)}
                      disabled={suggestLoading && suggestFieldKey === key}
                      className="ocr-test-save-btn-inline"
                      title={key === 'スーパー' ? 'master_code D列から類似3件' : 'master_code B列から類似3件'}
                    >
                      {suggestLoading && suggestFieldKey === key ? '...' : '保存'}
                    </button>
                  </div>
                ))}
              </div>
              {suggestFieldKey && (
                <div className="ocr-test-suggest-modal" role="dialog" aria-label="コード候補">
                  <div className="ocr-test-suggest-modal-inner">
                    <div className="ocr-test-suggest-modal-title">
                      {suggestFieldKey}：master_code A~F列（{suggestFieldKey === 'スーパー' ? 'D列' : 'B列'}基準で類似・選択でB列→受注先・D列→スーパーに反映）
                    </div>
                    <div className="ocr-test-suggest-keyword">
                      検索キーワード: <strong>{suggestKeyword || '—'}</strong>
                      <span className="ocr-test-suggest-keyword-hint">
                        （{suggestFieldKey === 'スーパー' ? 'D列' : 'B列'}でマッチ）
                      </span>
                    </div>
                    {suggestLoading ? (
                      <div className="ocr-test-suggest-loading">取得中...</div>
                    ) : suggestions.length === 0 ? (
                      <div className="ocr-test-suggest-empty">候補がありません</div>
                    ) : (
                      <div className="ocr-test-suggest-table-wrap">
                        <table className="ocr-test-suggest-table">
                          <thead>
                            <tr>
                              <th>A</th>
                              <th>B</th>
                              <th>C</th>
                              <th>D</th>
                              <th>E</th>
                              <th>F</th>
                            </tr>
                          </thead>
                          <tbody>
                            {suggestions.map((row, i) => (
                              <tr
                                key={i}
                                className="ocr-test-suggest-row"
                                onClick={() => handleSelectSuggestion(row)}
                              >
                                <td>{row.a}</td>
                                <td>{row.b}</td>
                                <td>{row.c}</td>
                                <td>{row.d}</td>
                                <td>{row.e}</td>
                                <td>{row.f}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                    <button
                      type="button"
                      className="ocr-test-suggest-cancel"
                      onClick={() => { setSuggestFieldKey(null); setSuggestions([]) }}
                    >
                      キャンセル
                    </button>
                  </div>
                </div>
              )}
              {lastMatchedPair && (
                <div className="ocr-test-matched-result">
                  <div className="ocr-test-matched-result-title">マッチ結果（master_codeから選択したペア）</div>
                  <div className="ocr-test-matched-result-keyword">
                    検索に使用: <strong>{lastMatchedPair.keyword || '—'}</strong>
                    <span className="ocr-test-matched-result-hint">
                      （{lastMatchedPair.field === 'スーパー' ? 'D列' : 'B列'}でマッチ）
                    </span>
                  </div>
                  <div className="ocr-test-matched-result-pair">
                    <span className="ocr-test-matched-result-b">B列 → 受注先: {lastMatchedPair.b}</span>
                    <span className="ocr-test-matched-result-d">D列 → スーパー: {lastMatchedPair.d}</span>
                  </div>
                </div>
              )}
              <div className="ocr-test-divider" />
              <div className="ocr-test-words-label">フィールドを選択 → 画像のボックスをクリックで値を設定（ページを替えても入力可能）</div>
              <label className="ocr-test-show-boxes-label">
                <input
                  type="checkbox"
                  checked={showWordBoxes}
                  onChange={(e) => setShowWordBoxes(e.target.checked)}
                />
                画像にボックスを表示
              </label>
              <label className="ocr-test-show-boxes-label">
                <input
                  type="checkbox"
                  checked={appendMode}
                  onChange={(e) => setAppendMode(e.target.checked)}
                />
                複数選択で連結（クリックした順に文字をつなげる）
              </label>
              {page && selectedWordIndex != null && words[selectedWordIndex] && (
                <div className="ocr-test-selected-word">
                  <span className="ocr-test-selected-word-label">クリックしたテキスト:</span>
                  <span className="ocr-test-selected-word-value">{words[selectedWordIndex].text}</span>
                </div>
              )}
              <div className="ocr-test-divider" />
            </>
          )}

          {!pdfUploadId && <div className="ocr-test-hint">PDFをアップロードしてください</div>}
          {pdfUploadId && !page && !loading && (
            <div className="ocr-test-hint">このページで「OCR実行」を押してください</div>
          )}
        </div>
      </div>
    </div>
  )
}
