/**
 * 단가(unit_price) 후보 선택 모달.
 * 그리드 셀 우클릭 시 해당 행의 商品名으로 유사도 매칭 후보를 보여주고, 선택 시 시키리/본부장 적용.
 */
import { useEffect, useState } from 'react'
import { searchApi } from '@/api/client'

export interface UnitPriceMatch {
  제품코드?: string | number
  제품명?: string
  제품용량?: number | string
  시키리?: number
  본부장?: number
  JANCD?: string | number
  제품명_similarity?: number
  제품용량_similarity?: number
  similarity?: number
}

interface UnitPriceMatchModalProps {
  open: boolean
  onClose: () => void
  /** 현재 행의 商品名 (조회용) */
  productName: string
  /** 후보 선택 시: { 시키리, 본부장 } 적용 */
  onSelect: (match: { 시키리?: number; 본부장?: number }) => void
}

export function UnitPriceMatchModal({
  open,
  onClose,
  productName,
  onSelect,
}: UnitPriceMatchModalProps) {
  const [matches, setMatches] = useState<UnitPriceMatch[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open || !productName?.trim()) {
      setMatches([])
      setError(null)
      return
    }
    setLoading(true)
    setError(null)
    searchApi
      .getUnitPriceByProduct(productName.trim(), { topK: 15, minSimilarity: 0.2 })
      .then((res) => setMatches(res.matches ?? []))
      .catch((e: any) => setError(e?.response?.data?.detail ?? e?.message ?? '検索に失敗しました'))
      .finally(() => setLoading(false))
  }, [open, productName])

  const handleSelect = (m: UnitPriceMatch) => {
    onSelect({ 시키리: m.시키리, 본부장: m.본부장 })
    onClose()
  }

  if (!open) return null

  return (
    <div className="unit-price-match-modal-overlay" onClick={onClose}>
      <div
        className="unit-price-match-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="単価候補を選択"
      >
        <div className="unit-price-match-modal-header">
          <h3>単価候補 (商品名: {productName || '—'})</h3>
          <button type="button" className="unit-price-match-modal-close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="unit-price-match-modal-body">
          {loading && <p className="unit-price-match-modal-loading">検索中…</p>}
          {error && <p className="unit-price-match-modal-error">{error}</p>}
          {!loading && !error && matches.length === 0 && (
            <p className="unit-price-match-modal-empty">該当する候補がありません。</p>
          )}
          {!loading && !error && matches.length > 0 && (
            <table className="unit-price-match-table">
              <thead>
                <tr>
                  <th>商品名</th>
                  <th>内容量</th>
                  <th>類似度</th>
                  <th>仕切</th>
                  <th>本部長</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {matches.map((m, i) => (
                  <tr key={i}>
                    <td>{String(m.제품명 ?? '')}</td>
                    <td>{String(m.제품용량 ?? '')}</td>
                    <td>
                      {(m.제품명_similarity ?? m.similarity ?? 0).toFixed(2)}
                      {(m.제품용량_similarity != null && ` / ${m.제품용량_similarity.toFixed(2)}`) || ''}
                    </td>
                    <td>{m.시키리 != null ? Number(m.시키리).toLocaleString() : '—'}</td>
                    <td>{m.본부장 != null ? Number(m.본부장).toLocaleString() : '—'}</td>
                    <td>
                      <button type="button" onClick={() => handleSelect(m)}>
                        適用
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}
