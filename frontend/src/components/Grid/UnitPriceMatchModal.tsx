/**
 * 매핑 모달: 単価(제품) | 代表スーパー(소매처) 탭.
 * 代表スーパー: 1) 得意先CD→domae_retail_1, 2) retail_user 유사도, 3) domae_retail_2 소매처명 유사도.
 */
import { useEffect, useState } from 'react'
import { searchApi } from '@/api/client'
import type { GridRow } from './types'

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

export interface RetailMatch {
  소매처코드: string
  소매처명: string
  판매처코드: string
  판매처명: string
  similarity: number
}

type TabId = 'unit_price' | 'retail'

interface UnitPriceMatchModalProps {
  open: boolean
  onClose: () => void
  row: GridRow | null
  onSelectUnitPrice: (match: { 시키리?: number; 본부장?: number }) => void
  onSelectRetail: (match: { 판매처코드: string; 소매처코드: string }) => void
}

function getCustomerName(row: GridRow | null): string {
  if (!row) return ''
  const v = row['得意先'] ?? row['得意先名'] ?? row['customer']
  return String(v ?? '').trim()
}

function getCustomerCode(row: GridRow | null): string {
  if (!row) return ''
  const v = row['得意先CD']
  return v != null ? String(v).trim() : ''
}

function RetailTable({
  matches,
  onSelectToFinal,
}: {
  matches: RetailMatch[]
  onSelectToFinal: (m: RetailMatch) => void
}) {
  if (matches.length === 0) return null
  return (
    <table className="unit-price-match-table">
      <thead>
        <tr>
          <th>소매처코드</th>
          <th>소매처명</th>
          <th>판매처코드</th>
          <th>판매처명</th>
          <th>類似度</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {matches.map((m, i) => (
          <tr key={i}>
            <td>{m.소매처코드}</td>
            <td>{m.소매처명}</td>
            <td>{m.판매처코드}</td>
            <td>{m.판매처명}</td>
            <td>{(m.similarity * 100).toFixed(1)}%</td>
            <td>
              <button type="button" onClick={() => onSelectToFinal(m)}>
                適用
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function UnitPriceMatchModal({
  open,
  onClose,
  row,
  onSelectUnitPrice,
  onSelectRetail,
}: UnitPriceMatchModalProps) {
  const [activeTab, setActiveTab] = useState<TabId>('unit_price')

  const productName = row ? String(row['商品名'] ?? '').trim() : ''
  const customerName = getCustomerName(row)
  const customerCode = getCustomerCode(row)

  // 단가 탭
  const [unitMatches, setUnitMatches] = useState<UnitPriceMatch[]>([])
  const [unitLoading, setUnitLoading] = useState(false)
  const [unitError, setUnitError] = useState<string | null>(null)

  // 소매처 탭: 3가지 기준
  const [byCode, setByCode] = useState<{
    match: RetailMatch | null
    skippedReason: string | null
    loading: boolean
    error: string | null
  }>({ match: null, skippedReason: null, loading: false, error: null })
  const [byRetailUser, setByRetailUser] = useState<{
    matches: RetailMatch[]
    loading: boolean
    error: string | null
  }>({ matches: [], loading: false, error: null })
  const [byShopName, setByShopName] = useState<{
    matches: RetailMatch[]
    skippedReason: string | null
    loading: boolean
    error: string | null
  }>({ matches: [], skippedReason: null, loading: false, error: null })

  /** 適用で選んだ 최종 후보（확정 클릭 시 그리드에 반영） */
  const [finalCandidate, setFinalCandidate] = useState<RetailMatch | null>(null)
  useEffect(() => {
    if (!open) setFinalCandidate(null)
    else if (customerName) setSapQuery(customerName)
  }, [open, customerName])

  /** sap_retail 수동 검색 */
  const [sapQuery, setSapQuery] = useState('')
  const [sapMatches, setSapMatches] = useState<RetailMatch[]>([])
  const [sapLoading, setSapLoading] = useState(false)
  const [sapError, setSapError] = useState<string | null>(null)
  useEffect(() => {
    if (!open) {
      setSapMatches([])
      setSapError(null)
      setSapQuery('')
    }
  }, [open])
  useEffect(() => {
    if (!open || !productName) {
      setUnitMatches([])
      setUnitError(null)
      return
    }
    setUnitLoading(true)
    setUnitError(null)
    searchApi
      .getUnitPriceByProduct(productName, { topK: 15, minSimilarity: 0.2 })
      .then((res) => setUnitMatches(res.matches ?? []))
      .catch((e: any) => setUnitError(e?.response?.data?.detail ?? e?.message ?? '検索に失敗しました'))
      .finally(() => setUnitLoading(false))
  }, [open, productName])

  useEffect(() => {
    if (!open) {
      setByCode({ match: null, skippedReason: null, loading: false, error: null })
      setByRetailUser({ matches: [], loading: false, error: null })
      setByShopName({ matches: [], skippedReason: null, loading: false, error: null })
      return
    }

    const hasCode = customerCode.length > 0
    const hasName = customerName.length > 0

    if (!hasCode && !hasName) {
      setByCode({ match: null, skippedReason: null, loading: false, error: null })
      setByRetailUser({ matches: [], loading: false, error: null })
      setByShopName({ matches: [], skippedReason: null, loading: false, error: null })
      return
    }

    if (hasCode) {
      setByCode((p) => ({ ...p, loading: true, error: null }))
      searchApi
        .getRetailByCustomerCode(customerCode)
        .then((res) => {
          if (res.match) {
            setByCode({
              match: res.match as RetailMatch,
              skippedReason: res.skipped_reason ?? null,
              loading: false,
              error: null,
            })
          } else {
            setByCode({
              match: null,
              skippedReason: res.skipped_reason ?? null,
              loading: false,
              error: null,
            })
          }
        })
        .catch((e: any) =>
          setByCode({
            match: null,
            skippedReason: null,
            loading: false,
            error: e?.response?.data?.detail ?? e?.message ?? null,
          })
        )
    } else {
      setByCode({
        match: null,
        skippedReason: '該当する列がないため適用していません',
        loading: false,
        error: null,
      })
    }

    if (hasName) {
      setByRetailUser((p) => ({ ...p, loading: true, error: null }))
      setByShopName((p) => ({ ...p, loading: true, error: null }))
      Promise.all([
        searchApi.getRetailCandidatesByCustomer(customerName, { topK: 5, minSimilarity: 0.0 }),
        searchApi.getRetailCandidatesByShopName(customerName, { topK: 5, minSimilarity: 0.0 }),
      ])
        .then(([res1, res2]) => {
          setByRetailUser({
            matches: (res1.matches ?? []) as RetailMatch[],
            loading: false,
            error: null,
          })
          setByShopName({
            matches: (res2.matches ?? []) as RetailMatch[],
            skippedReason: res2.skipped_reason ?? null,
            loading: false,
            error: null,
          })
        })
        .catch((err) => {
          setByRetailUser((p) => ({
            ...p,
            loading: false,
            error: err?.response?.data?.detail ?? err?.message ?? null,
          }))
          setByShopName((p) => ({
            ...p,
            loading: false,
            error: err?.response?.data?.detail ?? err?.message ?? null,
          }))
        })
    } else {
      setByRetailUser({ matches: [], loading: false, error: null })
      setByShopName({
        matches: [],
        skippedReason: null,
        loading: false,
        error: null,
      })
    }
  }, [open, customerCode, customerName])

  const handleSelectUnit = (m: UnitPriceMatch) => {
    onSelectUnitPrice({ 시키리: m.시키리, 본부장: m.본부장 })
    onClose()
  }

  /** 適用 → 최종 후보에만 반영. 확정 버튼에서 그리드 반영 */
  const handleSelectToFinal = (m: RetailMatch) => setFinalCandidate(m)
  const handleConfirmRetail = () => {
    if (!finalCandidate) return
    onSelectRetail({ 판매처코드: finalCandidate.판매처코드, 소매처코드: finalCandidate.소매처코드 })
    onClose()
  }

  const runSapSearch = () => {
    const q = sapQuery.trim()
    if (!q) return
    setSapLoading(true)
    setSapError(null)
    searchApi
      .getRetailCandidatesBySapRetail(q, { topK: 10, minSimilarity: 0.0 })
      .then((res) => {
        setSapMatches((res.matches ?? []) as RetailMatch[])
        if (res.skipped_reason) setSapError(res.skipped_reason)
      })
      .catch((e: any) => setSapError(e?.response?.data?.detail ?? e?.message ?? '検索に失敗しました'))
      .finally(() => setSapLoading(false))
  }

  if (!open) return null

  return (
    <div className="unit-price-match-modal-overlay" onClick={onClose}>
      <div
        className="unit-price-match-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="マッピング"
      >
        <div className="unit-price-match-modal-header">
          <h3>マッピング</h3>
          <button type="button" className="unit-price-match-modal-close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="mapping-modal-tabs">
          <button
            type="button"
            className={`mapping-modal-tab ${activeTab === 'unit_price' ? 'active' : ''}`}
            onClick={() => setActiveTab('unit_price')}
          >
            単価
          </button>
          <button
            type="button"
            className={`mapping-modal-tab ${activeTab === 'retail' ? 'active' : ''}`}
            onClick={() => setActiveTab('retail')}
          >
            代表スーパー
          </button>
        </div>
        <div className="unit-price-match-modal-body">
          {activeTab === 'unit_price' && (
            <>
              <p className="mapping-modal-subtitle">商品名: {productName || '—'}</p>
              {unitLoading && <p className="unit-price-match-modal-loading">検索中…</p>}
              {unitError && <p className="unit-price-match-modal-error">{unitError}</p>}
              {!unitLoading && !unitError && unitMatches.length === 0 && (
                <p className="unit-price-match-modal-empty">該当する候補がありません。</p>
              )}
              {!unitLoading && !unitError && unitMatches.length > 0 && (
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
                    {unitMatches.map((m, i) => (
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
                          <button type="button" onClick={() => handleSelectUnit(m)}>
                            適用
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}
          {activeTab === 'retail' && (
            <>
              <p className="mapping-modal-subtitle">
                得意先: {customerName || '—'}
                {customerCode ? ` / 得意先CD: ${customerCode}` : ''}
              </p>

              <section className="retail-final-section">
                <h4 className="retail-mapping-section-title">最終候補</h4>
                <div className="retail-final-box">
                  {finalCandidate ? (
                    <div className="retail-final-fields">
                      <span>代表スーパー: {finalCandidate.소매처코드} / {finalCandidate.소매처명}</span>
                      <span>受注先: {finalCandidate.판매처코드} / {finalCandidate.판매처명}</span>
                    </div>
                  ) : (
                    <p className="unit-price-match-modal-empty">下で「適用」を押すとここに表示されます。</p>
                  )}
                  <button
                    type="button"
                    className="retail-confirm-btn"
                    disabled={!finalCandidate}
                    onClick={handleConfirmRetail}
                  >
                    確定
                  </button>
                </div>
              </section>

              <section className="retail-mapping-section">
                <h4 className="retail-mapping-section-title">1) 得意先CD基準（domae_retail_1）</h4>
                {byCode.loading && <p className="unit-price-match-modal-loading">検索中…</p>}
                {byCode.error && <p className="unit-price-match-modal-error">{byCode.error}</p>}
                {!byCode.loading && !byCode.error && byCode.skippedReason && (
                  <p className="unit-price-match-modal-empty">{byCode.skippedReason}</p>
                )}
                {!byCode.loading && !byCode.error && !byCode.skippedReason && !byCode.match && (
                  <p className="unit-price-match-modal-empty">該当する候補がありません。</p>
                )}
                {!byCode.loading && !byCode.error && byCode.match && (
                  <RetailTable matches={[byCode.match]} onSelectToFinal={handleSelectToFinal} />
                )}
              </section>

              <section className="retail-mapping-section">
                <h4 className="retail-mapping-section-title">2) 代表スーパー名類似度（retail_user）</h4>
                {byRetailUser.loading && <p className="unit-price-match-modal-loading">検索中…</p>}
                {byRetailUser.error && <p className="unit-price-match-modal-error">{byRetailUser.error}</p>}
                {!byRetailUser.loading && !byRetailUser.error && byRetailUser.matches.length === 0 && (
                  <p className="unit-price-match-modal-empty">該当する候補がありません。</p>
                )}
                {!byRetailUser.loading && !byRetailUser.error && byRetailUser.matches.length > 0 && (
                  <RetailTable matches={byRetailUser.matches} onSelectToFinal={handleSelectToFinal} />
                )}
              </section>

              <section className="retail-mapping-section">
                <h4 className="retail-mapping-section-title">3) 小売先名類似度（domae_retail_2）</h4>
                {byShopName.loading && <p className="unit-price-match-modal-loading">検索中…</p>}
                {byShopName.skippedReason && (
                  <p className="unit-price-match-modal-empty">{byShopName.skippedReason}</p>
                )}
                {byShopName.error && <p className="unit-price-match-modal-error">{byShopName.error}</p>}
                {!byShopName.loading && !byShopName.error && !byShopName.skippedReason && byShopName.matches.length === 0 && (
                  <p className="unit-price-match-modal-empty">該当する候補がありません。</p>
                )}
                {!byShopName.loading && !byShopName.error && byShopName.matches.length > 0 && (
                  <RetailTable matches={byShopName.matches} onSelectToFinal={handleSelectToFinal} />
                )}
              </section>

              <section className="retail-mapping-section">
                <h4 className="retail-mapping-section-title">4) SAP小売先（sap_retail・手動検索）</h4>
                <div className="retail-sap-search-row">
                  <input
                    type="text"
                    className="retail-sap-input"
                    value={sapQuery}
                    onChange={(e) => setSapQuery(e.target.value)}
                    placeholder="検索語を入力"
                  />
                  <button type="button" className="retail-sap-search-btn" onClick={runSapSearch} disabled={sapLoading}>
                    {sapLoading ? '検索中…' : '検索'}
                  </button>
                </div>
                {sapError && <p className="unit-price-match-modal-error">{sapError}</p>}
                {!sapLoading && !sapError && sapMatches.length === 0 && sapQuery.trim() && (
                  <p className="unit-price-match-modal-empty">該当する候補がありません。</p>
                )}
                {!sapLoading && !sapError && sapMatches.length > 0 && (
                  <RetailTable matches={sapMatches} onSelectToFinal={handleSelectToFinal} />
                )}
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
