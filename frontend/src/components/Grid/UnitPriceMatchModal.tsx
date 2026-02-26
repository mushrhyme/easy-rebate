/**
 * 매핑 모달: 単価(제품) | 代表スーパー(소매처) 탭.
 * 単価: 最終候補 폼(適用 후 수정 가능) + sap_product 검색 → 確定 시 그리드 반영.
 * 代表スーパー: 1) 得意先CD→domae_retail_1, 2) retail_user 유사도, 3) domae_retail_2, 4) RAG. 最終候補는 sap_retail 검색.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { searchApi } from '@/api/client'
import type { GridRow } from './types'

/** 最終候補 입력 폼 (適用 후 수정 가능, 確定 시 이 값 사용) */
export interface RetailFinalForm {
  受注先CD: string
  受注先: string
  SAP受注先: string
  小売先CD: string
  小売先: string
  SAP小売先: string
}

const EMPTY_FINAL_FORM: RetailFinalForm = {
  受注先CD: '',
  受注先: '',
  SAP受注先: '',
  小売先CD: '',
  小売先: '',
  SAP小売先: '',
}

export interface UnitPriceMatch {
  제품코드?: string | number
  제품명?: string
  제품용량?: number | string
  시키리?: number
  본부장?: number
  JANCD?: string | number
  제품명_similarity?: number
  제품용량_similarity?: number
  _avg_similarity?: number
  similarity?: number
}

/** 単価 탭 最終候補. 商品コード만 입력. 仕切・本部長는 unit_price에서 商品コード로 자동완성（표시만） */
export interface UnitPriceFinalForm {
  商品コード: string
}

const EMPTY_UNIT_FINAL_FORM: UnitPriceFinalForm = { 商品コード: '' }

export interface RetailMatch {
  도매소매처코드?: string
  도매소매처명?: string
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
  onSelectUnitPrice: (match: { 제품코드?: string | number; 시키리?: number; 본부장?: number }) => void
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

/** 全角数字→半角変換（140 等を正しく出すため 1文字ずつ変換） */
function toHankakuNum(str: string): string {
  return str.replace(/[０-９]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0xfee0))
}

/** 商品名から「数字+単位」または「数字+単位×数字」を分離（backend と同一）. デバッグ表示用 */
function splitNameAndCapacity(name: string): { baseName: string; capacity: string | null } {
  const s = (name ?? '').trim()
  if (!s) return { baseName: s, capacity: null }
  // パターン1: 数字+単位×数字 (例: １２０ｇ×３ → 360)
  const reMul = /([０-９0-9]+\.?[０-９0-9]*)([gGｇＧmMｍＭlLリットルﾘｯﾄﾙ個コ袋])\s*[×xX]\s*([０-９0-9]+)\s*$/
  const mMul = reMul.exec(s)
  if (mMul) {
    const qty = parseFloat(toHankakuNum(mMul[1]))
    const mult = parseInt(toHankakuNum(mMul[3]), 10)
    if (!Number.isNaN(qty) && !Number.isNaN(mult)) {
      const total = Number.isInteger(qty) ? qty * mult : Math.round(qty * mult)
      const unit = mMul[2]
      const cap = unit === 'g' || unit === 'G' || unit === 'ｇ' || unit === 'Ｇ' ? String(total) : `${total}${unit}`
      return { baseName: s.slice(0, mMul.index).trim(), capacity: cap }
    }
  }
  // パターン2: 数字+単位のみ (例: チャパゲティ １４０ｇ → 140)
  const re = /([０-９0-9]+\.?[０-９0-9]*)([gGｇＧmMｍＭlLリットルﾘｯﾄﾙ個コ袋])\s*$/
  const m = re.exec(s)
  if (!m) return { baseName: s, capacity: null }
  const num = toHankakuNum(m[1])
  const unit = m[2]
  const cap = unit === 'g' || unit === 'G' || unit === 'ｇ' || unit === 'Ｇ' ? num : `${num}${unit}`
  return { baseName: s.slice(0, m.index).trim(), capacity: cap }
}

/** 1번 API match에 도매소매처코드가 빠져있을 수 있으므로 得意先CD로 보정 */
function normalizeByCodeMatch(m: RetailMatch, customerCode: string): RetailMatch {
  return {
    ...m,
    도매소매처코드: m.도매소매처코드 ?? customerCode,
  }
}

/** 1번=도매소매처코드만, 3번=도매소매처명만, 2번=도매 컬럼 없음, 4번=得意先만(비교 기준) */
type DomaeColumn = 'code' | 'name' | null
type RetailKeyHeader = 'domae_code' | 'retail_name' | 'domae_name' | 'tokuisaki' | null

function RetailTable({
  matches,
  onSelectToFinal,
  domaeColumn = null,
  keyHeader = null,
  showSimilarity = true,
}: {
  matches: RetailMatch[]
  onSelectToFinal: (m: RetailMatch) => void
  /** 1번: 'code'만, 3번: 'name'만, 4번: keyHeader='tokuisaki'일 때 得意先 열 */
  domaeColumn?: DomaeColumn
  keyHeader?: RetailKeyHeader
  /** 1번은 코드 정확 매칭이라 유사도 없음 → false 시 類似度 열 숨김 */
  showSimilarity?: boolean
}) {
  if (matches.length === 0) return null
  const showTokuisaki = keyHeader === 'tokuisaki'
  return (
    <table className="unit-price-match-table">
      <thead>
        <tr>
          {showTokuisaki && (
            <th className="key-column">得意先</th>
          )}
          {domaeColumn === 'code' && (
            <th className={keyHeader === 'domae_code' ? 'key-column' : undefined}>得意先CD</th>
          )}
          {domaeColumn === 'name' && (
            <th className={keyHeader === 'domae_name' ? 'key-column' : undefined}>卸小売先名</th>
          )}
          <th>小売先CD</th>
          <th className={keyHeader === 'retail_name' ? 'key-column' : undefined}>小売先名</th>
          <th>受注先CD</th>
          <th>受注先名</th>
          {showSimilarity && <th>類似度</th>}
          <th></th>
        </tr>
      </thead>
      <tbody>
        {matches.map((m, i) => (
          <tr key={i}>
            {showTokuisaki && (
              <td>{(m as { 得意先?: string }).得意先 ?? m.도매소매처명 ?? ''}</td>
            )}
            {domaeColumn === 'code' && <td>{m.도매소매처코드 ?? ''}</td>}
            {domaeColumn === 'name' && <td>{m.도매소매처명 ?? ''}</td>}
            <td>{m.소매처코드}</td>
            <td>{m.소매처명}</td>
            <td>{m.판매처코드}</td>
            <td>{m.판매처명}</td>
            {showSimilarity && <td>{(m.similarity * 100).toFixed(1)}%</td>}
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

  // 단가 탭: 후보 목록 + 最終候補 폼（適用 후 수정 가능, 確定 시 그리드 반영）
  const [unitMatches, setUnitMatches] = useState<UnitPriceMatch[]>([])
  const [unitLoading, setUnitLoading] = useState(false)
  const [unitError, setUnitError] = useState<string | null>(null)
  const [unitFinalForm, setUnitFinalForm] = useState<UnitPriceFinalForm>(EMPTY_UNIT_FINAL_FORM)
  /** 商品コード로 unit_price 조회한 仕切・本部長（자동완성, 수정 불가） */
  const [unitPriceAutoFill, setUnitPriceAutoFill] = useState<{ 仕切: number | null; 本部長: number | null }>({ 仕切: null, 本部長: null })
  const [sapProductQuery, setSapProductQuery] = useState('')
  const [sapProductMatches, setSapProductMatches] = useState<Array<{ 제품코드: string; 제품명: string }>>([])
  const [sapProductLoading, setSapProductLoading] = useState(false)
  const sapProductDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

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
  const [byRagAnswer, setByRagAnswer] = useState<{
    matches: RetailMatch[]
    skippedReason: string | null
    loading: boolean
    error: string | null
  }>({ matches: [], skippedReason: null, loading: false, error: null })

  /** 最終候補 입력 폼（適用で 채워지고 수정 가능, 確定 시 이 값으로 그리드 반영） */
  const [finalForm, setFinalForm] = useState<RetailFinalForm>(EMPTY_FINAL_FORM)
  const lastSapFetchedRef = useRef<string | null>(null)
  useEffect(() => {
    if (!open) {
      setFinalForm(EMPTY_FINAL_FORM)
      setUnitFinalForm(EMPTY_UNIT_FINAL_FORM)
      setUnitPriceAutoFill({ 仕切: null, 本部長: null })
      lastSapFetchedRef.current = null
    }
  }, [open, customerName])

  /** 商品コード가 바뀌면 unit_price에서 仕切・本部長 조회해 자동완성 */
  useEffect(() => {
    const code = unitFinalForm.商品コード.trim()
    if (!code || !open || activeTab !== 'unit_price') {
      if (!code) setUnitPriceAutoFill({ 仕切: null, 本部長: null })
      return
    }
    searchApi
      .getUnitPriceByProductCode(code)
      .then((res) => {
        if (res.row) {
          setUnitPriceAutoFill({ 仕切: res.row.仕切, 本部長: res.row.本部長 })
        } else {
          setUnitPriceAutoFill({ 仕切: null, 本部長: null })
        }
      })
      .catch(() => setUnitPriceAutoFill({ 仕切: null, 本部長: null }))
  }, [open, activeTab, unitFinalForm.商品コード])

  /** sap_product 검색: 単価 最終候補 검색 필드 원천 */
  useEffect(() => {
    const q = sapProductQuery.trim()
    if (!q) {
      setSapProductMatches([])
      return
    }
    if (sapProductDebounceRef.current) clearTimeout(sapProductDebounceRef.current)
    sapProductDebounceRef.current = setTimeout(() => {
      setSapProductLoading(true)
      searchApi
        .getProductCandidatesBySapProduct(q, { topK: 10, minSimilarity: 0 })
        .then((res) => setSapProductMatches(res.matches ?? []))
        .catch(() => setSapProductMatches([]))
        .finally(() => {
          setSapProductLoading(false)
          sapProductDebounceRef.current = null
        })
    }, 300)
    return () => {
      if (sapProductDebounceRef.current) clearTimeout(sapProductDebounceRef.current)
    }
  }, [sapProductQuery])

  /** 小売先CD가 있는데 SAP 필드가 비어 있으면 sap_retail 조회로 채움 (適用 후 누락 방지) */
  useEffect(() => {
    if (!open || activeTab !== 'retail') return
    const rc = finalForm.小売先CD.trim()
    if (!rc) return
    const needSap = !finalForm.SAP受注先.trim() || !finalForm.SAP小売先.trim()
    if (!needSap || lastSapFetchedRef.current === rc) return
    lastSapFetchedRef.current = rc
    searchApi
      .getSapRetailRowByRetailCode(rc)
      .then((res) => {
        if (res.row) {
          setFinalForm((prev) => ({
            ...prev,
            SAP受注先: prev.SAP受注先.trim() || res.row!.판매처명,
            SAP小売先: prev.SAP小売先.trim() || res.row!.소매처명,
          }))
        }
      })
      .catch(() => {})
  }, [open, activeTab, finalForm.小売先CD, finalForm.SAP受注先, finalForm.SAP小売先])

  useEffect(() => {
    if (!open || !productName) {
      setUnitMatches([])
      setUnitError(null)
      return
    }
    setUnitLoading(true)
    setUnitError(null)
    searchApi
      .getUnitPriceByProduct(productName, { topK: 5 })
      .then((res) => setUnitMatches(res.matches ?? []))
      .catch((e: any) => setUnitError(e?.response?.data?.detail ?? e?.message ?? '検索に失敗しました'))
      .finally(() => setUnitLoading(false))
  }, [open, productName])

  useEffect(() => {
    if (!open) {
      setByCode({ match: null, skippedReason: null, loading: false, error: null })
      setByRetailUser({ matches: [], loading: false, error: null })
      setByShopName({ matches: [], skippedReason: null, loading: false, error: null })
      setByRagAnswer({ matches: [], skippedReason: null, loading: false, error: null })
      return
    }

    const hasCode = customerCode.length > 0
    const hasName = customerName.length > 0

    if (!hasCode && !hasName) {
      setByCode({ match: null, skippedReason: null, loading: false, error: null })
      setByRetailUser({ matches: [], loading: false, error: null })
      setByShopName({ matches: [], skippedReason: null, loading: false, error: null })
      setByRagAnswer({ matches: [], skippedReason: null, loading: false, error: null })
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
      setByRagAnswer((p) => ({ ...p, loading: true, error: null }))
      Promise.all([
        searchApi.getRetailCandidatesByCustomer(customerName, { topK: 5, minSimilarity: 0.0 }),
        searchApi.getRetailCandidatesByShopName(customerName, { topK: 5, minSimilarity: 0.0 }),
        searchApi.getRetailCandidatesByRagAnswer(customerName, { topK: 5, minSimilarity: 0.0 }),
      ])
        .then(([res1, res2, res3]) => {
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
          setByRagAnswer({
            matches: (res3.matches ?? []) as RetailMatch[],
            skippedReason: res3.skipped_reason ?? null,
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
          setByRagAnswer((p) => ({
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
      setByRagAnswer({ matches: [], skippedReason: null, loading: false, error: null })
    }
  }, [open, customerCode, customerName])

  /** 単価 후보 테이블에서 適用 → 最終候補에 商品コード만 반영（仕切・本部長는 unit_price 자동완성） */
  const handleSelectUnitToFinal = (m: UnitPriceMatch) => {
    setUnitFinalForm({ 商品コード: m.제품코드 != null ? String(m.제품코드) : '' })
  }

  /** 単価 最終候補 確定 → 그리드 반영 후 모달 닫기 */
  const handleConfirmUnitPrice = () => {
    const code = unitFinalForm.商品コード.trim()
    if (!code) return
    onSelectUnitPrice({
      제품코드: code,
      시키리: unitPriceAutoFill.仕切 ?? undefined,
      본부장: unitPriceAutoFill.本部長 ?? undefined,
    })
    onClose()
  }

  /** 검색에서 선택 시 商品コード만 최종후보에 반영（仕切・本部長는 商品コード로 자동 조회） */
  const applySapProductMatchToForm = useCallback((m: { 제품코드: string; 제품명: string }) => {
    setUnitFinalForm({ 商品コード: m.제품코드 ?? '' })
    setSapProductQuery('')
    setSapProductMatches([])
  }, [])

  /** 適用 → 폼에 반영. sap_retail에서 SAP受注先・SAP小売先 조회 후 한 번에 폼 설정 (비어있지 않도록) */
  const handleSelectToFinal = useCallback(
    (m: RetailMatch) => {
      const baseForm: RetailFinalForm = {
        受注先CD: m.판매처코드 ?? '',
        受注先: m.판매처명 ?? '',
        小売先CD: m.소매처코드 ?? '',
        小売先: m.소매처명 ?? '',
        SAP受注先: '',
        SAP小売先: '',
      }
      const retailCode = (m.소매처코드 ?? '').trim()
      if (!retailCode) {
        setFinalForm(baseForm)
        return
      }
      lastSapFetchedRef.current = retailCode
      setFinalForm(baseForm)
      searchApi
        .getSapRetailRowByRetailCode(retailCode)
        .then((res) => {
          if (res.row) {
            setFinalForm((prev) => ({
              ...prev,
              SAP受注先: res.row!.판매처명,
              SAP小売先: res.row!.소매처명,
            }))
          }
        })
        .catch(() => {})
    },
    []
  )

  const handleConfirmRetail = () => {
    const dc = finalForm.受注先CD.trim()
    const rc = finalForm.小売先CD.trim()
    if (!dc || !rc) return
    onSelectRetail({ 판매처코드: dc, 소매처코드: rc })
    onClose()
  }

  /** SAP検索 자동완성: 입력 시 후보 조회, 선택 시 폼 전체 채움 */
  const [sapFinalQuery, setSapFinalQuery] = useState('')
  const [sapFinalMatches, setSapFinalMatches] = useState<RetailMatch[]>([])
  const [sapFinalLoading, setSapFinalLoading] = useState(false)
  const sapFinalDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    const q = sapFinalQuery.trim()
    if (!q) {
      setSapFinalMatches([])
      return
    }
    if (sapFinalDebounceRef.current) clearTimeout(sapFinalDebounceRef.current)
    sapFinalDebounceRef.current = setTimeout(() => {
      setSapFinalLoading(true)
      searchApi
        .getRetailCandidatesBySapRetail(q, { topK: 10, minSimilarity: 0 })
        .then((res) => setSapFinalMatches((res.matches ?? []) as RetailMatch[]))
        .catch(() => setSapFinalMatches([]))
        .finally(() => {
          setSapFinalLoading(false)
          sapFinalDebounceRef.current = null
        })
    }, 300)
    return () => {
      if (sapFinalDebounceRef.current) clearTimeout(sapFinalDebounceRef.current)
    }
  }, [sapFinalQuery])

  const applySapMatchToForm = useCallback((m: RetailMatch) => {
    setFinalForm({
      受注先CD: m.판매처코드 ?? '',
      受注先: m.판매처명 ?? '',
      SAP受注先: m.판매처명 ?? '',
      小売先CD: m.소매처코드 ?? '',
      小売先: m.소매처명 ?? '',
      SAP小売先: m.소매처명 ?? '',
    })
    setSapFinalQuery('')
    setSapFinalMatches([])
  }, [])

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
              <p className="mapping-modal-subtitle">
                商品名: {productName || '—'}
                {productName && (() => {
                  const { baseName, capacity } = splitNameAndCapacity(productName)
                  return (
                    <span className="mapping-modal-subtitle-split">
                      {' → '}商品名（分離）: {baseName || '—'} / 内容量（分離）: {capacity ?? '—'}
                    </span>
                  )
                })()}
              </p>

              <section className="retail-final-section">
                <h4 className="retail-mapping-section-title">最終候補</h4>
                <div className="retail-final-box">
                  <p className="unit-price-match-modal-hint">検索は商品名でsap_productから。商品コードのみ入力。仕切・本部長はunit_priceで自動表示。</p>
                  <div className="retail-final-form">
                    <label className="retail-final-label">
                      <span>商品コード</span>
                      <input
                        type="text"
                        className="retail-final-input"
                        value={unitFinalForm.商品コード}
                        onChange={(e) => setUnitFinalForm((f) => ({ ...f, 商品コード: e.target.value }))}
                        placeholder="商品コード"
                      />
                    </label>
                    {(unitPriceAutoFill.仕切 != null || unitPriceAutoFill.本部長 != null) && (
                      <p className="unit-price-match-modal-hint" style={{ marginTop: 4 }}>
                        仕切: {unitPriceAutoFill.仕切 != null ? Number(unitPriceAutoFill.仕切).toLocaleString() : '—'} / 本部長: {unitPriceAutoFill.本部長 != null ? Number(unitPriceAutoFill.本部長).toLocaleString() : '—'}
                      </p>
                    )}
                  </div>
                  <div className="retail-final-sap-search">
                    <label className="retail-final-label">
                      <span>検索（商品名・sap_product）</span>
                      <input
                        type="text"
                        className="retail-final-input"
                        value={sapProductQuery}
                        onChange={(e) => setSapProductQuery(e.target.value)}
                        placeholder="商品名で検索"
                      />
                    </label>
                    {sapProductLoading && <p className="unit-price-match-modal-loading">検索中…</p>}
                    {!sapProductLoading && sapProductMatches.length > 0 && (
                      <ul className="retail-final-sap-list">
                        {sapProductMatches.map((m, i) => (
                          <li key={i}>
                            <button
                              type="button"
                              className="retail-final-sap-item"
                              onClick={() => applySapProductMatchToForm(m)}
                            >
                              {m.제품코드} / {m.제품명}
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <button
                    type="button"
                    className="retail-confirm-btn"
                    disabled={!unitFinalForm.商品コード.trim()}
                    onClick={handleConfirmUnitPrice}
                  >
                    確定
                  </button>
                </div>
              </section>

              <section className="retail-mapping-section">
                <h4 className="retail-mapping-section-title">候補（商品名類似度・unit_price）</h4>
                {unitLoading && <p className="unit-price-match-modal-loading">検索中…</p>}
                {unitError && <p className="unit-price-match-modal-error">{unitError}</p>}
                {!unitLoading && !unitError && unitMatches.length === 0 && (
                  <p className="unit-price-match-modal-empty">該当する候補がありません。</p>
                )}
                {!unitLoading && !unitError && unitMatches.length > 0 && (
                  <table className="unit-price-match-table">
                    <thead>
                      <tr>
                        <th>商品コード</th>
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
                          <td>{m.제품코드 != null ? String(m.제품코드) : '—'}</td>
                          <td>{String(m.제품명 ?? '')}</td>
                          <td>{String(m.제품용량 ?? '')}</td>
                          <td>{m._avg_similarity != null ? m._avg_similarity.toFixed(2) : (m.similarity != null ? m.similarity.toFixed(2) : '—')}</td>
                          <td>{m.시키리 != null ? Number(m.시키리).toLocaleString() : '—'}</td>
                          <td>{m.본부장 != null ? Number(m.본부장).toLocaleString() : '—'}</td>
                          <td>
                            <button type="button" onClick={() => handleSelectUnitToFinal(m)}>
                              適用
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </section>
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
                  <p className="unit-price-match-modal-hint">下で「適用」で候補を反映。反映後も入力で修正できます。</p>
                  <div className="retail-final-form">
                    <label className="retail-final-label">
                      <span>受注先CD</span>
                      <input
                        type="text"
                        className="retail-final-input"
                        value={finalForm.受注先CD}
                        onChange={(e) => setFinalForm((f) => ({ ...f, 受注先CD: e.target.value }))}
                        placeholder="受注先CD"
                      />
                    </label>
                    <label className="retail-final-label">
                      <span>受注先</span>
                      <input
                        type="text"
                        className="retail-final-input"
                        value={finalForm.受注先}
                        onChange={(e) => setFinalForm((f) => ({ ...f, 受注先: e.target.value }))}
                        placeholder="受注先"
                      />
                    </label>
                    <label className="retail-final-label">
                      <span>SAP受注先</span>
                      <input
                        type="text"
                        className="retail-final-input"
                        value={finalForm.SAP受注先}
                        onChange={(e) => setFinalForm((f) => ({ ...f, SAP受注先: e.target.value }))}
                        placeholder="SAPの受注先"
                      />
                    </label>
                    <label className="retail-final-label">
                      <span>小売先CD</span>
                      <input
                        type="text"
                        className="retail-final-input"
                        value={finalForm.小売先CD}
                        onChange={(e) => setFinalForm((f) => ({ ...f, 小売先CD: e.target.value }))}
                        placeholder="小売先CD"
                      />
                    </label>
                    <label className="retail-final-label">
                      <span>小売先</span>
                      <input
                        type="text"
                        className="retail-final-input"
                        value={finalForm.小売先}
                        onChange={(e) => setFinalForm((f) => ({ ...f, 小売先: e.target.value }))}
                        placeholder="小売先"
                      />
                    </label>
                    <label className="retail-final-label">
                      <span>SAP小売先</span>
                      <input
                        type="text"
                        className="retail-final-input"
                        value={finalForm.SAP小売先}
                        onChange={(e) => setFinalForm((f) => ({ ...f, SAP小売先: e.target.value }))}
                        placeholder="SAPの小売先"
                      />
                    </label>
                  </div>
                  <div className="retail-final-sap-search">
                    <label className="retail-final-label">
                      <span>検索</span>
                      <input
                        type="text"
                        className="retail-final-input"
                        value={sapFinalQuery}
                        onChange={(e) => setSapFinalQuery(e.target.value)}
                        placeholder="販売店名または小売店名を検索してください"
                      />
                    </label>
                    {sapFinalLoading && <p className="unit-price-match-modal-loading">検索中…</p>}
                    {!sapFinalLoading && sapFinalMatches.length > 0 && (
                      <ul className="retail-final-sap-list">
                        {sapFinalMatches.map((m, i) => (
                          <li key={i}>
                            <button
                              type="button"
                              className="retail-final-sap-item"
                              onClick={() => applySapMatchToForm(m)}
                            >
                              {m.소매처코드} / {m.소매처명} — {m.판매처코드} / {m.판매처명}
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <button
                    type="button"
                    className="retail-confirm-btn"
                    disabled={!finalForm.受注先CD.trim() || !finalForm.小売先CD.trim()}
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
                  <RetailTable
                    matches={[normalizeByCodeMatch(byCode.match, customerCode)]}
                    onSelectToFinal={handleSelectToFinal}
                    domaeColumn="code"
                    keyHeader="domae_code"
                    showSimilarity={false}
                  />
                )}
              </section>

              <section className="retail-mapping-section">
                <h4 className="retail-mapping-section-title">2) 代表スーパー名類似度（retail_user&dist_retail）</h4>
                {byRetailUser.loading && <p className="unit-price-match-modal-loading">検索中…</p>}
                {byRetailUser.error && <p className="unit-price-match-modal-error">{byRetailUser.error}</p>}
                {!byRetailUser.loading && !byRetailUser.error && byRetailUser.matches.length === 0 && (
                  <p className="unit-price-match-modal-empty">該当する候補がありません。</p>
                )}
                {!byRetailUser.loading && !byRetailUser.error && byRetailUser.matches.length > 0 && (
                  <RetailTable
                    matches={byRetailUser.matches}
                    onSelectToFinal={handleSelectToFinal}
                    keyHeader="retail_name"
                  />
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
                  <RetailTable
                    matches={byShopName.matches}
                    onSelectToFinal={handleSelectToFinal}
                    domaeColumn="name"
                    keyHeader="domae_name"
                  />
                )}
              </section>

              <section className="retail-mapping-section">
                <h4 className="retail-mapping-section-title">4) 得意先 RAG 정답지 類似度</h4>
                {byRagAnswer.loading && <p className="unit-price-match-modal-loading">検索中…</p>}
                {byRagAnswer.skippedReason && (
                  <p className="unit-price-match-modal-empty">{byRagAnswer.skippedReason}</p>
                )}
                {byRagAnswer.error && <p className="unit-price-match-modal-error">{byRagAnswer.error}</p>}
                {!byRagAnswer.loading && !byRagAnswer.error && !byRagAnswer.skippedReason && byRagAnswer.matches.length === 0 && (
                  <p className="unit-price-match-modal-empty">該当する候補がありません。</p>
                )}
                {!byRagAnswer.loading && !byRagAnswer.error && byRagAnswer.matches.length > 0 && (
                  <RetailTable
                    matches={byRagAnswer.matches}
                    onSelectToFinal={handleSelectToFinal}
                    keyHeader="tokuisaki"
                  />
                )}
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
