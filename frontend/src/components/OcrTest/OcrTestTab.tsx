/**
 * OCR 테스트 탭: 이미지 업로드 → Upstage OCR / 구조化JSON 입력 → 필드 클릭 시 해당 영역 하이라이트
 */
import { useState, useRef, useCallback, useEffect, useMemo } from 'react'
import { ocrTestApi, type OcrTestResponse, type OcrWord } from '@/api/client'
import './OcrTestTab.css'

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

/** 구조화 JSON에서 leaf 문자열만 path/key/value 로 평탄화; _bbox 있으면 bbox 포함 */
export type StructuredField = {
  path: string
  key: string
  value: string
  bbox?: { left: number; top: number; width: number; height: number }
}

function flattenStructuredJson(obj: unknown, prefix = ''): StructuredField[] {
  const out: StructuredField[] = []
  if (obj === null || obj === undefined) return out
  if (typeof obj === 'string') {
    if (prefix) {
      const lastDot = prefix.lastIndexOf('.')
      const path = lastDot >= 0 ? prefix.slice(0, lastDot) : prefix
      const key = lastDot >= 0 ? prefix.slice(lastDot + 1) : prefix
      out.push({ path, key, value: obj })
    }
    return out
  }
  if (Array.isArray(obj)) {
    obj.forEach((item, i) => {
      out.push(...flattenStructuredJson(item, `${prefix}[${i}]`))
    })
    return out
  }
  if (typeof obj === 'object') {
    for (const [k, v] of Object.entries(obj)) {
      const nextPrefix = prefix ? `${prefix}.${k}` : k
      out.push(...flattenStructuredJson(v, nextPrefix))
    }
    return out
  }
  return out
}

/** API 구조화 결과용: _bbox 키를 해당 필드에 붙여서 평탄화 (_page_bbox 등 제외) */
function flattenWithBbox(obj: unknown, prefix = '', parentObj?: Record<string, unknown>): StructuredField[] {
  const out: StructuredField[] = []
  if (obj === null || obj === undefined) return out
  if (typeof obj === 'string') {
    if (prefix && parentObj) {
      const lastDot = prefix.lastIndexOf('.')
      const path = lastDot >= 0 ? prefix.slice(0, lastDot) : prefix
      const key = lastDot >= 0 ? prefix.slice(lastDot + 1) : prefix
      const bboxKey = `${key}_bbox`
      const bbox = parentObj[bboxKey] as { left?: number; top?: number; width?: number; height?: number } | undefined
      const bboxVal =
        bbox && typeof bbox === 'object' && typeof bbox.left === 'number' && typeof bbox.top === 'number'
          ? { left: bbox.left, top: bbox.top, width: (bbox.width as number) ?? 0, height: (bbox.height as number) ?? 0 }
          : undefined
      out.push({ path, key, value: obj, bbox: bboxVal })
    }
    return out
  }
  if (Array.isArray(obj)) {
    obj.forEach((item, i) => {
      const nextParent = typeof item === 'object' && item && !Array.isArray(item) ? (item as Record<string, unknown>) : undefined
      out.push(...flattenWithBbox(item, `${prefix}[${i}]`, nextParent))
    })
    return out
  }
  if (typeof obj === 'object') {
    const rec = obj as Record<string, unknown>
    for (const [k, v] of Object.entries(obj)) {
      if (k === '_page_bbox' || k.endsWith('_bbox') || k === '_word_indices' || (k.startsWith('_') && k.length > 1)) continue
      const nextPrefix = prefix ? `${prefix}.${k}` : k
      out.push(...flattenWithBbox(v, nextPrefix, rec))
    }
    return out
  }
  return out
}

/** 텍스트 정규화: 공백 정리, 전각→반각 등 (매칭용) */
function normalizeForMatch(s: string): string {
  return s
    .replace(/\s+/g, ' ')
    .replace(/　/g, ' ')
    .trim()
}

/** 값 문자열이 OCR 단어 어디에 해당하는지 찾아 bbox(union) 반환. 페이지 픽셀 좌표. */
function findValueBbox(
  value: string,
  words: OcrWord[],
  pageWidth: number,
  pageHeight: number
): { left: number; top: number; width: number; height: number } | null {
  const norm = normalizeForMatch(value)
  if (!norm || !words.length) return null

  const withRect = words
    .map((w) => {
      const rect = w.boundingBox?.vertices ? verticesToRect(w.boundingBox.vertices) : null
      return { word: w, rect }
    })
    .filter((x): x is { word: OcrWord; rect: NonNullable<ReturnType<typeof verticesToRect>> } => x.rect != null)

  if (!withRect.length) return null

  const normValueNoSpace = norm.replace(/\s/g, '')
  let best: { start: number; end: number } | null = null

  for (let start = 0; start < withRect.length; start++) {
    let acc = ''
    for (let end = start; end < withRect.length; end++) {
      acc += normalizeForMatch(withRect[end].word.text).replace(/\s/g, '')
      if (acc.length > normValueNoSpace.length * 3) break
      if (
        acc === normValueNoSpace ||
        (normValueNoSpace.length >= 1 && (acc.includes(normValueNoSpace) || normValueNoSpace.includes(acc)))
      ) {
        const candidate = { start, end }
        if (!best || end - start < best.end - best.start) best = candidate
        break
      }
    }
  }
  if (!best && normValueNoSpace.length >= 2) {
    const fullNoSpace = withRect.map((x) => normalizeForMatch(x.word.text).replace(/\s/g, '')).join('')
    if (fullNoSpace.includes(normValueNoSpace)) {
      const idx = fullNoSpace.indexOf(normValueNoSpace)
      let charCount = 0
      let start = 0
      let end = 0
      for (let i = 0; i < withRect.length; i++) {
        const len = normalizeForMatch(withRect[i].word.text).replace(/\s/g, '').length
        if (charCount <= idx && idx < charCount + len) start = i
        if (charCount < idx + normValueNoSpace.length && idx + normValueNoSpace.length <= charCount + len) {
          end = i
          break
        }
        charCount += len
      }
      best = { start, end }
    }
  }
  if (!best) return null

  const subset = withRect.slice(best.start, best.end + 1)
  const left = Math.min(...subset.map((s) => s.rect.left))
  const top = Math.min(...subset.map((s) => s.rect.top))
  const right = Math.max(...subset.map((s) => s.rect.left + s.rect.width))
  const bottom = Math.max(...subset.map((s) => s.rect.top + s.rect.height))
  return { left, top, width: right - left, height: bottom - top }
}

type HighlightRect = { left: number; top: number; width: number; height: number }

export function OcrTestTab() {
  const [file, setFile] = useState<File | null>(null)
  const [imagePreviewUrl, setImagePreviewUrl] = useState<string | null>(null)
  const [ocrResult, setOcrResult] = useState<OcrTestResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [structureLoading, setStructureLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [structuredJsonText, setStructuredJsonText] = useState<string>('')
  const [structuredFromApi, setStructuredFromApi] = useState<Record<string, unknown> | null>(null)
  const [highlightRect, setHighlightRect] = useState<HighlightRect | null>(null)
  const imageContainerRef = useRef<HTMLDivElement>(null)

  const page = ocrResult?.pages?.[0]
  const words = page?.words ?? []
  const pageWidth = page?.width ?? 1
  const pageHeight = page?.height ?? 1

  const structuredFields = useMemo(() => {
    if (structuredFromApi) return flattenWithBbox(structuredFromApi)
    if (!structuredJsonText.trim()) return []
    try {
      const obj = JSON.parse(structuredJsonText) as unknown
      return flattenStructuredJson(obj)
    } catch {
      return []
    }
  }, [structuredFromApi, structuredJsonText])

  const hasStructure = structuredFields.length > 0

  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (imagePreviewUrl) URL.revokeObjectURL(imagePreviewUrl)
    setFile(f ?? null)
    setImagePreviewUrl(f ? URL.createObjectURL(f) : null)
    setOcrResult(null)
    setStructuredFromApi(null)
    setHighlightRect(null)
    setError(null)
  }, [imagePreviewUrl])

  const runOcr = useCallback(async () => {
    if (!file) return
    setLoading(true)
    setError(null)
    setStructuredFromApi(null)
    try {
      const result = await ocrTestApi.ocrImage(file)
      setOcrResult(result)
      setHighlightRect(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'OCR failed')
    } finally {
      setLoading(false)
    }
  }, [file])

  const runStructure = useCallback(async () => {
    if (!page?.text || !words.length) return
    setStructureLoading(true)
    setError(null)
    try {
      const result = await ocrTestApi.structure({
        ocr_text: page.text,
        words,
        page_width: pageWidth,
        page_height: pageHeight,
        form_type: '04',
      })
      setStructuredFromApi(result as Record<string, unknown>)
      setStructuredJsonText('')
      setHighlightRect(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : '構造化 failed')
    } finally {
      setStructureLoading(false)
    }
  }, [page, words, pageWidth, pageHeight])

  const handleStructuredFieldClick = useCallback(
    (field: StructuredField) => {
      const bbox = field.bbox ?? findValueBbox(field.value, words, pageWidth, pageHeight)
      setHighlightRect(bbox)
      if (bbox && imageContainerRef.current) {
        const container = imageContainerRef.current
        const img = container.querySelector('img')
        if (img) {
          const scaleX = img.offsetWidth / pageWidth
          const scaleY = img.offsetHeight / pageHeight
          const centerY = (bbox.top + bbox.height / 2) * scaleY
          const centerX = (bbox.left + bbox.width / 2) * scaleX
          container.scrollTop = Math.max(0, centerY - container.clientHeight / 2)
          container.scrollLeft = Math.max(0, centerX - container.clientWidth / 2)
        }
      }
    },
    [words, pageWidth, pageHeight]
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
    return () => {
      if (imagePreviewUrl) URL.revokeObjectURL(imagePreviewUrl)
    }
  }, [imagePreviewUrl])

  return (
    <div className="ocr-test-tab">
      <div className="ocr-test-header">
        <h2 className="ocr-test-title">OCRテスト（Upstage・構造ハイライト）</h2>
        <p className="ocr-test-desc">
          画像をアップロード → OCR実行 → 「構造化（座標付き）」でLLMが座標付きで構造化（DB保存なし・テスト用）。またはJSONを貼り付けてフィールドクリックでハイライト。
        </p>
      </div>

      <div className="ocr-test-upload-row">
        <input
          type="file"
          accept="image/*"
          onChange={handleFileChange}
          className="ocr-test-file-input"
        />
        <button
          type="button"
          onClick={runOcr}
          disabled={!file || loading}
          className="ocr-test-run-btn"
        >
          {loading ? 'OCR実行中...' : 'OCR実行'}
        </button>
        <button
          type="button"
          onClick={runStructure}
          disabled={!page?.text || !words.length || structureLoading}
          className="ocr-test-run-btn"
        >
          {structureLoading ? '構造化中...' : '構造化（座標付き）'}
        </button>
      </div>

      {error && <div className="ocr-test-error">{error}</div>}

      <div className="ocr-test-main">
        <div className="ocr-test-image-panel">
          <div
            ref={imageContainerRef}
            className="ocr-test-image-container"
          >
            {imagePreviewUrl && (
              <div className="ocr-test-image-wrapper">
                <img src={imagePreviewUrl} alt="Preview" />
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
          <div className="ocr-test-structured-section">
            <div className="ocr-test-words-label">構造化JSON（分析結果を貼り付け）</div>
            <textarea
              className="ocr-test-json-input"
              placeholder='{"document_meta": {...}, "party": {...}, ...}'
              value={structuredJsonText}
              onChange={(e) => {
                setStructuredJsonText(e.target.value)
                setStructuredFromApi(null)
                setHighlightRect(null)
              }}
              rows={4}
            />
          </div>

          {hasStructure && (
            <>
              <div className="ocr-test-words-label">フィールドをクリック → 画像上でハイライト</div>
              <div className="ocr-test-structure-list">
                {structuredFields.map((field, index) => (
                  <button
                    key={`${field.path}.${field.key}-${index}`}
                    type="button"
                    className="ocr-test-structure-row"
                    onClick={() => handleStructuredFieldClick(field)}
                  >
                    <span className="ocr-test-structure-key">{field.key}:</span>
                    <span className="ocr-test-structure-value">{field.value}</span>
                  </button>
                ))}
              </div>
            </>
          )}

          {page?.text && (
            <div className="ocr-test-full-text">
              <div className="ocr-test-full-text-label">OCR全文</div>
              <pre className="ocr-test-full-text-content">{page.text}</pre>
            </div>
          )}

          {!page && ocrResult && <div className="ocr-test-no-words">OCRデータがありません</div>}
          {!ocrResult && !loading && file && <div className="ocr-test-hint">「OCR実行」を押してください</div>}
        </div>
      </div>
    </div>
  )
}
