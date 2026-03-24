/**
 * 매핑 모달: 単価(제품) | 代表スーパー(소매처) 탭.
 * 単価: 最終候補 폼(適用 후 수정 가능) + sap_product 검색 → 確定 시 그리드 반영.
 * 代表スーパー: 様式01+得意先コード→domae → retail_master → dist 힌트 → RAG. 검색: retail_master / dist_master.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { searchApi } from '@/api/client'
import type { GridRow } from './types'

/** 代表スーパー 最終候補 — 판매·소매 코드 분리, 표시명은 dist_master·得意先名 */
export interface RetailFinalForm {
  小売先コード: string
  受注先コード: string
  受注先: string // dist_master 판매처명
}

const EMPTY_FINAL_FORM: RetailFinalForm = {
  小売先コード: '',
  受注先コード: '',
  受注先: '',
}

export interface UnitPriceMatch {
  제품코드?: string | number
  제품명?: string
  제품용량?: number | string
  시키리?: number
  본부장?: number
  JANコード?: string | number
  제품명_similarity?: number
  제품용량_similarity?: number
  _avg_similarity?: number
  similarity?: number
}

/** 제품 RAG 정답지 검색 결과 1건 (単価 탭 RAG 후보) */
export interface ProductRagMatch {
  商品名: string
  商品コード: string
  仕切: number | string | null
  本部長: number | string | null
  similarity: number
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

/** 確定 시 그리드 저장: 소매처명=得意先名(청구서), 판매처명=dist 표시 */
export interface RetailSelectPayload {
  판매처코드: string
  소매처코드: string
  판매처명?: string
  소매처명?: string // 得意先名
}

interface UnitPriceMatchModalProps {
  open: boolean
  onClose: () => void
  row: GridRow | null
  /** 문서様式 (01=1번 양식지 → 得意先コード×domae 우선) */
  formType?: string | null
  onSelectUnitPrice: (match: { 제품코드?: string | number; 시키리?: number; 본부장?: number }) => void
  onSelectRetail: (match: RetailSelectPayload) => void | Promise<void>
  /** 代表スーパー 確定 저장 중 (확정 시 API 저장으로 모달은 부모가 닫음) */
  retailSaving?: boolean
}

function getCustomerName(row: GridRow | null): string {
  if (!row) return ''
  const v = row['得意先'] ?? row['得意先名'] ?? row['customer']
  return String(v ?? '').trim()
}

function getCustomerCode(row: GridRow | null): string {
  if (!row) return ''
  const v = row['得意先コード']
  return v != null ? String(v).trim() : ''
}

/** 様式01(1번 양식지) — 도매소매처코드 매칭 대상 */
function isFormType01(formType: string | null | undefined): boolean {
  const s = (formType ?? '').trim()
  if (!s) return false
  return s === '01' || s === '1' || /^0*1$/.test(s)
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

/** 1번 API match에 도매소매처코드가 빠져있을 수 있으므로 得意先コード로 보정 */
function normalizeByCodeMatch(m: RetailMatch, customerCode: string): RetailMatch {
  return {
    ...m,
    도매소매처코드: m.도매소매처코드 ?? customerCode,
  }
}

/** 1번=得意先만(RAG), 2번=도매소매처코드만, 3번=도매 컬럼 없음, 4번=도매소매처명만 */
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
  /** 1번: keyHeader='tokuisaki' 得意先, 2번: 'code'만, 4번: 'name'만 */
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
            <th className={keyHeader === 'domae_code' ? 'key-column' : undefined}>得意先コード</th>
          )}
          {domaeColumn === 'name' && (
            <th className={keyHeader === 'domae_name' ? 'key-column' : undefined}>卸小売先名</th>
          )}
          <th>小売先コード</th>
          <th className={keyHeader === 'retail_name' ? 'key-column' : undefined}>小売先名</th>
          <th>受注先コード</th>
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
  formType = null,
  onSelectUnitPrice,
  onSelectRetail,
  retailSaving = false,
}: UnitPriceMatchModalProps) {
  const [activeTab, setActiveTab] = useState<TabId>('unit_price')

  const productName = row ? String(row['商品名'] ?? '').trim() : ''
  const customerName = getCustomerName(row)
  const customerCode = getCustomerCode(row)

  /** 商品コード 입력이 숫자(전각/반각)인지 판별 */
  const isProductCodeLike = (v: string): boolean => /^[0-9０-９]+$/.test((v ?? '').trim())

  // 단가 탭: 후보 목록 + 最終候補 폼（適用 후 수정 가능, 確定 시 그리드 반영）
  const [unitMatches, setUnitMatches] = useState<UnitPriceMatch[]>([])
  const [unitLoading, setUnitLoading] = useState(false)
  const [unitError, setUnitError] = useState<string | null>(null)
  const [unitByRagAnswer, setUnitByRagAnswer] = useState<{
    matches: ProductRagMatch[]
    skippedReason: string | null
    loading: boolean
    error: string | null
  }>({ matches: [], skippedReason: null, loading: false, error: null })
  const [unitFinalForm, setUnitFinalForm] = useState<UnitPriceFinalForm>(EMPTY_UNIT_FINAL_FORM)
  /** 商品コード로 unit_price 조회한 仕切・本部長（자동완성, 수정 불가） */
  const [unitPriceAutoFill, setUnitPriceAutoFill] = useState<{ 仕切: number | null; 本部長: number | null }>({ 仕切: null, 本部長: null })
  /** 商品コード 변경 후 unit_price 자동 조회 중 */
  const [unitPriceAutoLoading, setUnitPriceAutoLoading] = useState(false)
  const [sapProductQuery, setSapProductQuery] = useState('')
  const [sapProductMatches, setSapProductMatches] = useState<Array<{ 제품코드: string; 제품명: string }>>([])
  const [sapProductLoading, setSapProductLoading] = useState(false)
  const sapProductDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // 代表スーパー: domae(様式01+コード) / retail_master / RAG
  const [byCode, setByCode] = useState<{
    match: RetailMatch | null
    skippedReason: string | null
    loading: boolean
    error: string | null
  }>({ match: null, skippedReason: null, loading: false, error: null })
  const [byRetailMaster, setByRetailMaster] = useState<{
    matches: Array<{ 소매처코드: string; 소매처명: string; similarity: number }>
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
  /** dist_retail_master 기반 판매처 힌트 (소매처코드 확정 후) */
  const [vendorHints, setVendorHints] = useState<{
    matches: Array<{ 판매처코드: string; 판매처명: string }>
    skippedReason: string | null
    loading: boolean
  }>({ matches: [], skippedReason: null, loading: false })

  const [finalForm, setFinalForm] = useState<RetailFinalForm>(EMPTY_FINAL_FORM)
  const lastHintRetailRef = useRef<string | null>(null)
  const [retailMasterSearchQuery, setRetailMasterSearchQuery] = useState('')
  const [retailMasterSearchMatches, setRetailMasterSearchMatches] = useState<
    Array<{ 소매처코드: string; 소매처명: string; similarity: number }>
  >([])
  const [retailMasterSearchLoading, setRetailMasterSearchLoading] = useState(false)
  const retailSearchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [distMasterQuery, setDistMasterQuery] = useState('')
  const [distMasterMatches, setDistMasterMatches] = useState<
    Array<{ 판매처코드: string; 판매처명: string; similarity: number }>
  >([])
  const [distMasterLoading, setDistMasterLoading] = useState(false)
  const distMasterDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!open) {
      setFinalForm(EMPTY_FINAL_FORM)
      setUnitFinalForm(EMPTY_UNIT_FINAL_FORM)
      setUnitPriceAutoFill({ 仕切: null, 本部長: null })
      setUnitPriceAutoLoading(false)
    } else if (row) {
      const dc = row['受注先コード'] != null ? String(row['受注先コード']).trim() : ''
      const rc = row['小売先コード'] != null ? String(row['小売先コード']).trim() : ''
      const jName = row['受注先'] != null ? String(row['受注先']).trim() : ''
      if (dc || rc || jName) {
        setFinalForm((prev) => ({
          小売先コード: rc || prev.小売先コード,
          受注先コード: dc || prev.受注先コード,
          受注先: jName || prev.受注先,
        }))
      }
    }
  }, [open, customerName, row])

  /** 商品コード가 바뀌면 unit_price에서 仕切・本部長 조회 + sap_product에서 제품명 조회해 検索 필드·자동완성 */
  useEffect(() => {
    const raw = unitFinalForm.商品コード.trim()
    if (!raw || !open || activeTab !== 'unit_price') {
      if (!raw) {
        setUnitPriceAutoFill({ 仕切: null, 本部長: null })
        setSapProductQuery('')
      }
      setUnitPriceAutoLoading(false)
      return
    }
    // 商品コード 칸에 문자를 입력한 경우에는 unit_price 자동조회는 스킵합니다.
    // (候補 검색은 sapProductQuery/useEffect가 담당)
    if (!isProductCodeLike(raw)) {
      setUnitPriceAutoFill({ 仕切: null, 本部長: null })
      setUnitPriceAutoLoading(false)
      return
    }
    const code = toHankakuNum(raw)
    setUnitPriceAutoLoading(true)
    Promise.all([
      searchApi.getUnitPriceByProductCode(code),
      searchApi.getProductNameByCode(code),
    ])
      .then(([priceRes, nameRes]) => {
        if (priceRes.row) {
          setUnitPriceAutoFill({ 仕切: priceRes.row.仕切, 本部長: priceRes.row.本部長 })
        } else {
          setUnitPriceAutoFill({ 仕切: null, 本部長: null })
        }
        if (nameRes.제품명) setSapProductQuery(nameRes.제품명)
      })
      .catch(() => {
        setUnitPriceAutoFill({ 仕切: null, 本部長: null })
      })
      .finally(() => setUnitPriceAutoLoading(false))
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

  /** 単価 탭: 商品名 기준 unit_price 유사도 + 제품 RAG 정답지 병렬 조회 */
  useEffect(() => {
    if (!open || !productName) {
      setUnitMatches([])
      setUnitError(null)
      setUnitByRagAnswer({ matches: [], skippedReason: null, loading: false, error: null })
      return
    }
    setUnitLoading(true)
    setUnitError(null)
    setUnitByRagAnswer((p) => ({ ...p, loading: true, error: null }))
    Promise.all([
      searchApi.getUnitPriceByProduct(productName, { topK: 5 }),
      searchApi.getProductCandidatesByRagAnswer(productName, { topK: 5, minSimilarity: 0 }),
    ])
      .then(([unitRes, ragRes]) => {
        setUnitMatches(unitRes.matches ?? [])
        setUnitByRagAnswer({
          matches: (ragRes.matches ?? []) as ProductRagMatch[],
          skippedReason: ragRes.skipped_reason ?? null,
          loading: false,
          error: null,
        })
      })
      .catch((e: any) => {
        setUnitError(e?.response?.data?.detail ?? e?.message ?? '検索に失敗しました')
        setUnitByRagAnswer({
          matches: [],
          skippedReason: null,
          loading: false,
          error: e?.response?.data?.detail ?? e?.message ?? null,
        })
      })
      .finally(() => setUnitLoading(false))
  }, [open, productName])

  useEffect(() => {
    if (!open) {
      setByCode({ match: null, skippedReason: null, loading: false, error: null })
      setByRetailMaster({ matches: [], skippedReason: null, loading: false, error: null })
      setByRagAnswer({ matches: [], skippedReason: null, loading: false, error: null })
      setVendorHints({ matches: [], skippedReason: null, loading: false })
      return
    }

    const hasCode = customerCode.length > 0
    const hasName = customerName.length > 0
    const useDomaeCode = isFormType01(formType) && hasCode

    if (!hasCode && !hasName) {
      setByCode({ match: null, skippedReason: null, loading: false, error: null })
      setByRetailMaster({ matches: [], skippedReason: null, loading: false, error: null })
      setByRagAnswer({ matches: [], skippedReason: null, loading: false, error: null })
      return
    }

    if (useDomaeCode) {
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
        skippedReason: hasCode
          ? isFormType01(formType)
            ? null
            : '様式01以外のため、得意先コード→domae はスキップしました'
          : '得意先コードがありません',
        loading: false,
        error: null,
      })
    }

    if (hasName) {
      setByRetailMaster((p) => ({ ...p, loading: true, error: null }))
      setByRagAnswer((p) => ({ ...p, loading: true, error: null }))
      Promise.all([
        searchApi.getRetailCandidatesByRetailMaster(customerName, { topK: 10, minSimilarity: 0 }),
        searchApi.getRetailCandidatesByRagAnswer(customerName, { topK: 10, minSimilarity: 0 }),
      ])
        .then(([resRm, resRag]) => {
          setByRetailMaster({
            matches: resRm.matches ?? [],
            skippedReason: resRm.skipped_reason ?? null,
            loading: false,
            error: null,
          })
          setByRagAnswer({
            matches: (resRag.matches ?? []) as RetailMatch[],
            skippedReason: resRag.skipped_reason ?? null,
            loading: false,
            error: null,
          })
        })
        .catch((err) => {
          const msg = err?.response?.data?.detail ?? err?.message ?? null
          setByRetailMaster((p) => ({ ...p, loading: false, error: msg }))
          setByRagAnswer((p) => ({ ...p, loading: false, error: msg }))
        })
    } else {
      setByRetailMaster({ matches: [], skippedReason: null, loading: false, error: null })
      setByRagAnswer({ matches: [], skippedReason: null, loading: false, error: null })
    }
  }, [open, customerCode, customerName, formType])

  /** 소매처코드 확정 시 dist_retail_master → 판매처 힌트 */
  useEffect(() => {
    if (!open || activeTab !== 'retail') return
    const rc = finalForm.小売先コード.trim()
    if (!rc) {
      lastHintRetailRef.current = null
      setVendorHints({ matches: [], skippedReason: null, loading: false })
      return
    }
    if (lastHintRetailRef.current === rc) return
    lastHintRetailRef.current = rc
    setVendorHints((p) => ({ ...p, loading: true }))
    searchApi
      .getVendorHintsByRetailCode(rc, { topK: 10 })
      .then((res) => {
        setVendorHints({
          matches: res.matches ?? [],
          skippedReason: res.skipped_reason ?? null,
          loading: false,
        })
      })
      .catch(() => setVendorHints({ matches: [], skippedReason: null, loading: false }))
  }, [open, activeTab, finalForm.小売先コード])

  /** 소매 코드 비우면 판매 코드·명도 비움 */
  useEffect(() => {
    if (!open || activeTab !== 'retail') return
    if (finalForm.小売先コード.trim()) return
    setFinalForm((prev) => ({ ...prev, 受注先コード: '', 受注先: '' }))
  }, [open, activeTab, finalForm.小売先コード])

  /** dist_retail 힌트 로드 후 1件目を販売欄に自動反映 */
  useEffect(() => {
    if (!open || activeTab !== 'retail') return
    if (vendorHints.loading) return
    const rc = finalForm.小売先コード.trim()
    if (!rc || vendorHints.matches.length === 0) return
    const first = vendorHints.matches[0]
    setFinalForm((prev) => ({
      ...prev,
      受注先コード: first.판매처코드,
      受注先: first.판매처명,
    }))
  }, [open, activeTab, vendorHints.loading, vendorHints.matches, finalForm.小売先コード])

  /** retail_master 手入力検索 */
  useEffect(() => {
    const q = retailMasterSearchQuery.trim()
    if (!q) {
      setRetailMasterSearchMatches([])
      return
    }
    if (retailSearchDebounceRef.current) clearTimeout(retailSearchDebounceRef.current)
    retailSearchDebounceRef.current = setTimeout(() => {
      setRetailMasterSearchLoading(true)
      searchApi
        .getRetailCandidatesByRetailMaster(q, { topK: 10, minSimilarity: 0 })
        .then((res) => setRetailMasterSearchMatches(res.matches ?? []))
        .catch(() => setRetailMasterSearchMatches([]))
        .finally(() => {
          setRetailMasterSearchLoading(false)
          retailSearchDebounceRef.current = null
        })
    }, 300)
    return () => {
      if (retailSearchDebounceRef.current) clearTimeout(retailSearchDebounceRef.current)
    }
  }, [retailMasterSearchQuery])

  /** dist_master 手入力検索 */
  useEffect(() => {
    const q = distMasterQuery.trim()
    if (!q) {
      setDistMasterMatches([])
      return
    }
    if (distMasterDebounceRef.current) clearTimeout(distMasterDebounceRef.current)
    distMasterDebounceRef.current = setTimeout(() => {
      setDistMasterLoading(true)
      searchApi
        .getDistCandidatesByDistMaster(q, { topK: 10, minSimilarity: 0 })
        .then((res) => setDistMasterMatches(res.matches ?? []))
        .catch(() => setDistMasterMatches([]))
        .finally(() => {
          setDistMasterLoading(false)
          distMasterDebounceRef.current = null
        })
    }, 300)
    return () => {
      if (distMasterDebounceRef.current) clearTimeout(distMasterDebounceRef.current)
    }
  }, [distMasterQuery])

  /** 単価 후보 테이블에서 適用 → 最終候補에 商品コード만 반영（仕切・本部長는 unit_price 자동완성） */
  const handleSelectUnitToFinal = (m: UnitPriceMatch) => {
    setUnitFinalForm({ 商品コード: m.제품코드 != null ? String(m.제품코드) : '' })
  }

  /** 商品名 RAG 정답지 후보 適用 → 最終候補에 商品コード만 반영 */
  const handleSelectProductRagToFinal = (m: ProductRagMatch) => {
    setUnitFinalForm({ 商品コード: m.商品コード || '' })
    // 2) 방법(두번째): RAG는 매핑(상품코드)만 담당하고,
    // 仕切・本部長는 항상 unit_price 자동 조회 결과만 사용한다.
    setUnitPriceAutoFill({ 仕切: null, 本部長: null })
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

  /** 검색에서 선택 시 商品コード를 최종후보에 반영, 검색 필드에는 선택한 제품명 표시（仕切・本部長는 商品コード로 자동 조회） */
  const applySapProductMatchToForm = useCallback((m: { 제품코드?: string; 제품명?: string; 商品コード?: string; 商品名?: string }) => {
    const code = m.제품코드 ?? m.商品コード ?? ''
    setUnitFinalForm({ 商品コード: code })
    // 선택 후에는 후보 목록을 정리
    setSapProductQuery('')
    setSapProductMatches([])
  }, [])

  /** RAG 행 適用 — 소매·판매 코드·명 일괄 (정답지) */
  const handleSelectRagToFinal = useCallback((m: RetailMatch) => {
    setFinalForm({
      小売先コード: m.소매처코드 ?? '',
      受注先コード: m.판매처코드 ?? '',
      受注先: m.판매처명 ?? '',
    })
  }, [])

  const applyRetailMasterRowToForm = useCallback((m: { 소매처코드: string; 소매처명: string }) => {
    setFinalForm((prev) => ({ ...prev, 小売先コード: m.소매처코드 }))
  }, [])

  const applyVendorHintToForm = useCallback((m: { 판매처코드: string; 판매처명: string }) => {
    setFinalForm((prev) => ({
      ...prev,
      受注先コード: m.판매처코드,
      受注先: m.판매처명,
    }))
  }, [])

  const handleConfirmRetail = () => {
    const dc = finalForm.受注先コード.trim()
    const rc = finalForm.小売先コード.trim()
    if (!dc || !rc) return
    onSelectRetail({
      판매처코드: dc,
      소매처코드: rc,
      판매처명: finalForm.受注先.trim() || undefined,
      소매처명: customerName || undefined,
    })
  }

  const applyDistMasterToForm = useCallback((m: { 판매처코드: string; 판매처명: string }) => {
    setFinalForm((prev) => ({
      ...prev,
      受注先コード: m.판매처코드,
      受注先: m.판매처명,
    }))
    setDistMasterQuery('')
    setDistMasterMatches([])
  }, [])

  /** to_do 매핑 화면: domae 1건 우선 → retail_master 순（소매처코드 중복 제거しない, 最大10行） */
  const retailPickList = useMemo(() => {
    const out: Array<{
      소매처코드: string
      소매처명: string
      similarity?: number
      source: 'domae' | 'retail_master'
    }> = []
    if (byCode.match) {
      const nm = normalizeByCodeMatch(byCode.match, customerCode)
      const c = (nm.소매처코드 ?? '').trim()
      if (c) {
        out.push({
          소매처코드: c,
          소매처명: (nm.소매처명 ?? '').trim(),
          similarity: nm.similarity,
          source: 'domae',
        })
      }
    }
    for (const m of byRetailMaster.matches) {
      if (out.length >= 10) break
      const c = (m.소매처코드 ?? '').trim()
      if (!c) continue
      out.push({
        소매처코드: c,
        소매처명: m.소매처명,
        similarity: m.similarity,
        source: 'retail_master',
      })
    }
    return out
  }, [byCode.match, byRetailMaster.matches, customerCode])

  const vendorPickList = useMemo(() => vendorHints.matches.slice(0, 10), [vendorHints.matches])

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
                  <p className="unit-price-match-modal-hint">この「商品コード」欄に商品名(文字)または商品コード(数字)を入力すると sap_product から候補を探します。仕切・本部長は unit_price で自動表示。</p>
                  <div className="retail-final-form">
                    <label className="retail-final-label">
                      <span>商品コード</span>
                      <input
                        type="text"
                        className="retail-final-input"
                        value={unitFinalForm.商品コード}
                        onChange={(e) => {
                          const nextRaw = e.target.value
                          const nextTrim = (nextRaw ?? '').trim()
                          const normalized = isProductCodeLike(nextTrim) ? toHankakuNum(nextTrim) : nextRaw
                          setUnitFinalForm({ 商品コード: normalized })

                          if (!nextTrim) {
                            setSapProductQuery('')
                            setSapProductMatches([])
                            return
                          }
                          if (isProductCodeLike(nextTrim)) {
                            // 숫자=상품코드 → unit_price 자동조회만 사용
                            setSapProductQuery('')
                            setSapProductMatches([])
                          } else {
                            // 문자=상품명 → sap_product 후보 검색
                            setSapProductQuery(nextTrim)
                          }
                        }}
                        placeholder="商品コード"
                      />
                    </label>
                    {(unitPriceAutoFill.仕切 != null || unitPriceAutoFill.本部長 != null) && (
                      <p className="unit-price-match-modal-hint" style={{ marginTop: 4 }}>
                        仕切: {unitPriceAutoFill.仕切 != null ? Number(unitPriceAutoFill.仕切).toLocaleString() : '—'} / 本部長: {unitPriceAutoFill.本部長 != null ? Number(unitPriceAutoFill.本部長).toLocaleString() : '—'}
                      </p>
                    )}
                    {sapProductLoading && <p className="unit-price-match-modal-loading">検索中…</p>}
                    {!sapProductLoading && sapProductMatches.length > 0 && (
                      <ul className="retail-final-sap-list">
                        {sapProductMatches.map((m, i) => (
                          <li key={i}>
                            <button type="button" className="retail-final-sap-item" onClick={() => applySapProductMatchToForm(m)}>
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
                    disabled={!isProductCodeLike(unitFinalForm.商品コード.trim()) || unitPriceAutoLoading}
                    onClick={handleConfirmUnitPrice}
                  >
                    確定
                  </button>
                </div>
              </section>

              <section className="retail-mapping-section">
                <h4 className="retail-mapping-section-title">1) 商品名 RAG 정답지（벡터 DB）</h4>
                {unitByRagAnswer.loading && <p className="unit-price-match-modal-loading">検索中…</p>}
                {unitByRagAnswer.skippedReason && !unitByRagAnswer.loading && (
                  <p className="unit-price-match-modal-empty">{unitByRagAnswer.skippedReason}</p>
                )}
                {unitByRagAnswer.error && (
                  <p className="unit-price-match-modal-error">{unitByRagAnswer.error}</p>
                )}
                {!unitByRagAnswer.loading &&
                  !unitByRagAnswer.error &&
                  unitByRagAnswer.matches.length === 0 &&
                  !unitByRagAnswer.skippedReason && (
                    <p className="unit-price-match-modal-empty">該当する候補がありません。</p>
                  )}
                {!unitByRagAnswer.loading && unitByRagAnswer.matches.length > 0 && (
                  <table className="unit-price-match-table">
                    <thead>
                      <tr>
                        <th>商品名</th>
                        <th>商品コード</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {unitByRagAnswer.matches.map((m, i) => (
                        <tr key={i}>
                          <td>{m.商品名 || '—'}</td>
                          <td>{m.商品コード || '—'}</td>
                          <td>
                            <button type="button" onClick={() => handleSelectProductRagToFinal(m)}>
                              適用
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </section>

              <section className="retail-mapping-section">
                <h4 className="retail-mapping-section-title">2) 候補（商品名類似度・unit_price）</h4>
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
                {customerCode ? ` · 得意先コード: ${customerCode}` : ''}
                {formType ? ` · 様式: ${formType}` : ''}
              </p>
              <p className="unit-price-match-modal-hint retail-map-spec-intro">
                下の「①小売」→「②販売」の順でコードを埋め、候補の <strong>適用</strong> で上の入力欄に反映します。確定時、小売先名は請求書の得意先名が保存されます。
              </p>

              {/* to_do.md: 소매처명·소매처코드·추천·검색 */}
              <section className="retail-map-spec-block retail-map-spec-block--retail">
                <h4 className="retail-map-spec-block-title">① 小売（소매）</h4>
                <div className="retail-map-spec-row">
                  <span className="retail-map-spec-label">소매처명</span>
                  <div className="retail-map-spec-value">
                    <span className="retail-map-spec-eq">＝ 得意先名</span>
                    <input
                      type="text"
                      className="retail-final-input retail-map-readonly"
                      readOnly
                      value={customerName}
                      title="確定時に 小売先 列へ保存"
                    />
                  </div>
                </div>
                <div className="retail-map-spec-row">
                  <span className="retail-map-spec-label">소매처코드</span>
                  <div className="retail-map-spec-field">
                    <input
                      type="text"
                      className="retail-final-input"
                      value={finalForm.小売先コード}
                      onChange={(e) => setFinalForm((f) => ({ ...f, 小売先コード: e.target.value }))}
                      placeholder="小売先コード"
                      aria-label="小売先コード"
                    />
                    {retailPickList[0] && (
                      <span className="retail-map-rank1-hint">
                        1位候補: {retailPickList[0].소매처코드}
                        {retailPickList[0].source === 'domae' ? '（domae）' : '（retail_master）'}
                      </span>
                    )}
                  </div>
                </div>
                <p className="retail-map-spec-subhead">候補一覧（小売先コード · 小売先名）</p>
                {(byCode.loading || byRetailMaster.loading) && <p className="unit-price-match-modal-loading">候補を検索中…</p>}
                {!byCode.loading && !byRetailMaster.loading && retailPickList.length === 0 && (
                  <p className="unit-price-match-modal-empty">候補がありません。下の検索を使うか、手入力してください。</p>
                )}
                {retailPickList.length > 0 && (
                  <table className="unit-price-match-table retail-map-pick-table">
                    <thead>
                      <tr>
                        <th className="retail-map-col-n">#</th>
                        <th>小売先コード</th>
                        <th>小売先名（マスタ）</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {retailPickList.map((row, i) => (
                        <tr key={`${row.소매처코드}-${i}`}>
                          <td className="retail-map-col-n">{i + 1}</td>
                          <td>{row.소매처코드}</td>
                          <td>
                            {row.소매처명}
                            {row.similarity != null && row.source === 'retail_master' && (
                              <span className="retail-map-sim">（{(row.similarity * 100).toFixed(0)}%）</span>
                            )}
                          </td>
                          <td>
                            <button
                              type="button"
                              onClick={() => applyRetailMasterRowToForm({ 소매처코드: row.소매처코드, 소매처명: row.소매처명 })}
                            >
                              適用
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                <p className="retail-map-spec-subhead">検索（retail_master）</p>
                <label className="retail-final-label retail-map-search-label">
                  <span>検索語</span>
                  <input
                    type="text"
                    className="retail-final-input"
                    value={retailMasterSearchQuery}
                    onChange={(e) => setRetailMasterSearchQuery(e.target.value)}
                    placeholder="小売先名で検索 → 結果から適用"
                  />
                </label>
                {retailMasterSearchLoading && <p className="unit-price-match-modal-loading">検索中…</p>}
                {!retailMasterSearchLoading && retailMasterSearchMatches.length > 0 && (
                  <ul className="retail-final-sap-list">
                    {retailMasterSearchMatches.map((m, i) => (
                      <li key={i}>
                        <button
                          type="button"
                          className="retail-final-sap-item"
                          onClick={() => {
                            applyRetailMasterRowToForm(m)
                            setRetailMasterSearchQuery('')
                            setRetailMasterSearchMatches([])
                          }}
                        >
                          {m.소매처코드} / {m.소매처명}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              {/* to_do.md: 판매처코드·추천·검색 */}
              <section className="retail-map-spec-block retail-map-spec-block--vendor">
                <h4 className="retail-map-spec-block-title">② 販売（판매처）</h4>
                <div className="retail-map-spec-row">
                  <span className="retail-map-spec-label">판매처코드</span>
                  <div className="retail-map-spec-field">
                    <input
                      type="text"
                      className="retail-final-input"
                      value={finalForm.受注先コード}
                      onChange={(e) => setFinalForm((f) => ({ ...f, 受注先コード: e.target.value }))}
                      placeholder="受注先コード"
                      aria-label="受注先コード"
                    />
                    {vendorPickList[0] && (
                      <span className="retail-map-rank1-hint">1位候補: {vendorPickList[0].판매처코드}（dist_retail組合）</span>
                    )}
                  </div>
                </div>
                <div className="retail-map-spec-row">
                  <span className="retail-map-spec-label">판매처명</span>
                  <input
                    type="text"
                    className="retail-final-input"
                    value={finalForm.受注先}
                    onChange={(e) => setFinalForm((f) => ({ ...f, 受注先: e.target.value }))}
                    placeholder="dist_master の表示名"
                  />
                </div>
                <p className="retail-map-spec-subhead">候補一覧（판매처코드 · 판매처명）</p>
                {!finalForm.小売先コード.trim() && (
                  <p className="unit-price-match-modal-empty">先に ① で小売先コードを入れてください（組合せヒントのため）。</p>
                )}
                {!!finalForm.小売先コード.trim() && vendorHints.loading && (
                  <p className="unit-price-match-modal-loading">販売候補を検索中…</p>
                )}
                {!!finalForm.小売先コード.trim() && !vendorHints.loading && vendorPickList.length === 0 && !vendorHints.skippedReason && (
                  <p className="unit-price-match-modal-empty">組合せヒントがありません。検索で指定してください。</p>
                )}
                {!!finalForm.小売先コード.trim() && !vendorHints.loading && vendorPickList.length > 0 && (
                  <table className="unit-price-match-table retail-map-pick-table">
                    <thead>
                      <tr>
                        <th className="retail-map-col-n">#</th>
                        <th>受注先コード</th>
                        <th>受注先名</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {vendorPickList.map((m, i) => (
                        <tr key={`${m.판매처코드}-${i}`}>
                          <td className="retail-map-col-n">{i + 1}</td>
                          <td>{m.판매처코드}</td>
                          <td>{m.판매처명}</td>
                          <td>
                            <button type="button" onClick={() => applyVendorHintToForm(m)}>
                              適用
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                <p className="retail-map-spec-subhead">検索（dist_master）</p>
                <label className="retail-final-label retail-map-search-label">
                  <span>検索語</span>
                  <input
                    type="text"
                    className="retail-final-input"
                    value={distMasterQuery}
                    onChange={(e) => setDistMasterQuery(e.target.value)}
                    placeholder="販売店名・コードで検索 → 適用"
                  />
                </label>
                {distMasterLoading && <p className="unit-price-match-modal-loading">検索中…</p>}
                {!distMasterLoading && distMasterMatches.length > 0 && (
                  <ul className="retail-final-sap-list">
                    {distMasterMatches.map((m, i) => (
                      <li key={i}>
                        <button type="button" className="retail-final-sap-item" onClick={() => applyDistMasterToForm(m)}>
                          {m.판매처코드} / {m.판매처명}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <div className="retail-map-confirm-wrap">
                <button
                  type="button"
                  className="retail-confirm-btn retail-map-confirm-btn"
                  disabled={!finalForm.受注先コード.trim() || !finalForm.小売先コード.trim() || retailSaving}
                  onClick={handleConfirmRetail}
                >
                  {retailSaving ? '保存中…' : '確定'}
                </button>
              </div>

              <details className="retail-map-details">
                <summary className="retail-map-details-summary">その他の候補ソース（RAG）</summary>

              <section className="retail-mapping-section">
                <h4 className="retail-mapping-section-title">得意先 RAG（벡터 DB・参考）</h4>
                {byRagAnswer.loading && <p className="unit-price-match-modal-loading">検索中…</p>}
                {byRagAnswer.skippedReason && (
                  <p className="unit-price-match-modal-empty">{byRagAnswer.skippedReason}</p>
                )}
                {byRagAnswer.error && <p className="unit-price-match-modal-error">{byRagAnswer.error}</p>}
                {!byRagAnswer.loading && !byRagAnswer.error && !byRagAnswer.skippedReason && byRagAnswer.matches.length === 0 && (
                  <p className="unit-price-match-modal-empty">該当する候補がありません。</p>
                )}
                {!byRagAnswer.loading && !byRagAnswer.error && byRagAnswer.matches.length > 0 && (
                  <RetailTable matches={byRagAnswer.matches} onSelectToFinal={handleSelectRagToFinal} keyHeader="tokuisaki" />
                )}
              </section>
              </details>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
