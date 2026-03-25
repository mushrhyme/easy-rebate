/**
 * マッピングモーダル: 単価 | 代表スーパー。
 * 単価: ①商品（候補表に内容量・規格・参照・類似度・仕切・本部長、検索、確定）。
 * 代表スーパー: 様式01+得意先コード照合 → マスタ類似度と RAG（最大3件）を混在 → 販売ヒント・検索。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { searchApi } from '@/api/client'
import type { GridRow } from './types'

/** 代表スーパー最終入力（小売・販売コード分離。表示名は dist と得意先名） */
export interface RetailFinalForm {
  小売先コード: string
  受注先コード: string
  受注先: string // dist_master 表示名
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
  /** unit_price.csv 규격 열 */
  규격?: string | number
  시키리?: number
  본부장?: number
  JANコード?: string | number
  제품명_similarity?: number
  제품용량_similarity?: number
  _avg_similarity?: number
  similarity?: number
}

/** 単価タブ: 商品 RAG 候補 1 件 */
export interface ProductRagMatch {
  商品名: string
  商品コード: string
  仕切: number | string | null
  本部長: number | string | null
  similarity: number
}

/** 単価タブ最終候補（商品コードのみ。仕切・本部長は unit_price で自動表示） */
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

/** 確定時グリッド保存: 小売先名=得意先名、販売表示名=dist */
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
  /** 文書様式（01=様式01・得意先コード照合あり） */
  formType?: string | null
  onSelectUnitPrice: (match: { 제품코드?: string | number; 시키리?: number; 본부장?: number }) => void
  onSelectRetail: (match: RetailSelectPayload) => void | Promise<void>
  /** 代表スーパー確定保存中 */
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

/** 様式01: 得意先コードと卸小売マスタ照合の対象 */
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

/** API 応答で卸小売コードが欠ける場合に得意先コードで補う */
function normalizeByCodeMatch(m: RetailMatch, customerCode: string): RetailMatch {
  return {
    ...m,
    도매소매처코드: m.도매소매처코드 ?? customerCode,
  }
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

  /** 商品コード欄が数字（全角・半角）のみか */
  const isProductCodeLike = (v: string): boolean => /^[0-9０-９]+$/.test((v ?? '').trim())

  // 単価タブ: 候補 + 最終候補フォーム
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
  /** 商品コードに対する unit_price の仕切・本部長（自動表示） */
  const [unitPriceAutoFill, setUnitPriceAutoFill] = useState<{ 仕切: number | null; 本部長: number | null }>({ 仕切: null, 本部長: null })
  /** unit_price 自動取得中 */
  const [unitPriceAutoLoading, setUnitPriceAutoLoading] = useState(false)
  const [sapProductQuery, setSapProductQuery] = useState('')
  const [sapProductMatches, setSapProductMatches] = useState<Array<{ 제품코드: string; 제품명: string }>>([])
  const [sapProductLoading, setSapProductLoading] = useState(false)
  const sapProductDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // 代表スーパー: コード照合 / マスタ / RAG
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
  /** 小売先コード確定後の販売ヒント */
  const [vendorHints, setVendorHints] = useState<{
    matches: Array<{ 판매처코드: string; 판매처명: string }>
    skippedReason: string | null
    loading: boolean
  }>({ matches: [], skippedReason: null, loading: false })

  const [finalForm, setFinalForm] = useState<RetailFinalForm>(EMPTY_FINAL_FORM)
  /** 直近で販売ヒントを取得した小売コード（モーダル再オープン時はリセットして再取得する） */
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
      lastHintRetailRef.current = null
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

  /** 商品コード変更時: unit_price で仕切・本部長のみ取得（検索語はユーザー入力専用 — 適用後に埋めない） */
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
    // 商品コード欄に非数字を入れた場合は unit_price 自動取得しない（候補は sap_product 側）
    if (!isProductCodeLike(raw)) {
      setUnitPriceAutoFill({ 仕切: null, 本部長: null })
      setUnitPriceAutoLoading(false)
      return
    }
    const code = toHankakuNum(raw)
    setUnitPriceAutoLoading(true)
    searchApi
      .getUnitPriceByProductCode(code)
      .then((priceRes) => {
        if (priceRes.row) {
          setUnitPriceAutoFill({ 仕切: priceRes.row.仕切, 本部長: priceRes.row.本部長 })
        } else {
          setUnitPriceAutoFill({ 仕切: null, 本部長: null })
        }
      })
      .catch(() => {
        setUnitPriceAutoFill({ 仕切: null, 本部長: null })
      })
      .finally(() => setUnitPriceAutoLoading(false))
  }, [open, activeTab, unitFinalForm.商品コード])

  /** sap_product 検索（単価の検索語） */
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

  /** 単価タブ: unit_price 類似度 + 商品 RAG を並列取得 */
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
      searchApi.getUnitPriceByProduct(productName, { topK: 10, minSimilarity: 0 }),
      searchApi.getProductCandidatesByRagAnswer(productName, { topK: 3, minSimilarity: 0 }),
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
      lastHintRetailRef.current = null
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
            : '様式01以外のため、得意先コードによる照合は行いませんでした'
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
        searchApi.getRetailCandidatesByRagAnswer(customerName, { topK: 3, minSimilarity: 0 }),
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
          setByRetailMaster((p) => ({ ...p, loading: false, error: msg, matches: [] }))
          setByRagAnswer((p) => ({ ...p, loading: false, error: msg, matches: [] }))
        })
    } else {
      setByRetailMaster({ matches: [], skippedReason: null, loading: false, error: null })
      setByRagAnswer({ matches: [], skippedReason: null, loading: false, error: null })
    }
  }, [open, customerCode, customerName, formType])

  /** 小売先コード確定で販売ヒント取得 */
  useEffect(() => {
    if (!open || activeTab !== 'retail') return
    const rc = finalForm.小売先コード.trim()
    if (!rc) {
      lastHintRetailRef.current = null
      setVendorHints({ matches: [], skippedReason: null, loading: false })
      return
    }
    const prevRc = lastHintRetailRef.current
    if (prevRc === rc) return
    // 小売コードが変わったら（前回取得済みの別コードからの遷移）販売欄をクリアしてから再取得
    if (prevRc !== null && prevRc !== rc) {
      setFinalForm((prev) => ({ ...prev, 受注先コード: '', 受注先: '' }))
    }
    lastHintRetailRef.current = rc
    setVendorHints((p) => ({ ...p, loading: true }))
    searchApi
      .getVendorHintsByRetailCode(rc)
      .then((res) => {
        setVendorHints({
          matches: res.matches ?? [],
          skippedReason: res.skipped_reason ?? null,
          loading: false,
        })
      })
      .catch(() => setVendorHints({ matches: [], skippedReason: null, loading: false }))
  }, [open, activeTab, finalForm.小売先コード])

  /** 小売コードを空にしたら販売欄もクリア */
  useEffect(() => {
    if (!open || activeTab !== 'retail') return
    if (finalForm.小売先コード.trim()) return
    setFinalForm((prev) => ({ ...prev, 受注先コード: '', 受注先: '' }))
  }, [open, activeTab, finalForm.小売先コード])

  // 販売候補の自動入力はしない（誤適用防止のため、必ずユーザーが選択/入力）

  /** 小売マスタの手入力検索 */
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

  /** 販売マスタの手入力検索 */
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

  /** 単価候補の適用: 商品コードのみ反映（仕切・本部長は自動） */
  const handleSelectUnitToFinal = (m: UnitPriceMatch) => {
    setUnitFinalForm({ 商品コード: m.제품코드 != null ? String(m.제품코드) : '' })
  }

  /** 商品 RAG 候補の適用: 商品コードのみ（仕切・本部長は unit_price のみ） */
  const handleSelectProductRagToFinal = (m: ProductRagMatch) => {
    setUnitFinalForm({ 商品コード: m.商品コード || '' })
    setUnitPriceAutoFill({ 仕切: null, 本部長: null })
  }

  /** 単価確定でグリッド反映しモーダルを閉じる */
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

  /** sap 検索から選択: 商品コード反映し一覧を閉じる */
  const applySapProductMatchToForm = useCallback((m: { 제품코드?: string; 제품명?: string; 商品コード?: string; 商品名?: string }) => {
    const code = m.제품코드 ?? m.商品コード ?? ''
    setUnitFinalForm({ 商品コード: code })
    setSapProductQuery('')
    setSapProductMatches([])
  }, [])

  /** RAG 行の適用: 小売・販売をまとめて反映 */
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

  /** ①小売候補: domae / RAG(max3) / retail_master を類似度で混ぜ、ソート上位10件（コード重複は保持） */
  const retailPickList = useMemo(() => {
    type PickRow = {
      소매처코드: string
      소매처명: string
      similarity: number
      source: 'domae' | 'retail_master' | 'rag'
      ragMatch?: RetailMatch
    }
    const domaeSortSim = (_nm: RetailMatch): number => 0.99 // number; コード照合は常に 99% 扱い(0.99)
    const pool: PickRow[] = []
    if (byCode.match) {
      const nm = normalizeByCodeMatch(byCode.match, customerCode)
      const c = (nm.소매처코드 ?? '').trim()
      if (c) {
        pool.push({
          소매처코드: c,
          소매처명: (nm.소매처명 ?? '').trim(),
          similarity: domaeSortSim(nm),
          source: 'domae',
        })
      }
    }
    for (const m of byRagAnswer.matches) {
      const c = (m.소매처코드 ?? '').trim()
      if (!c) continue
      pool.push({
        소매처코드: c,
        소매처명: (m.소매처명 ?? '').trim(),
        similarity: typeof m.similarity === 'number' ? m.similarity : 0,
        source: 'rag',
        ragMatch: m,
      })
    }
    for (const m of byRetailMaster.matches) {
      const c = (m.소매처코드 ?? '').trim()
      if (!c) continue
      pool.push({
        소매처코드: c,
        소매처명: m.소매처명,
        similarity: typeof m.similarity === 'number' ? m.similarity : 0,
        source: 'retail_master',
      })
    }
    return pool.sort((a, b) => b.similarity - a.similarity).slice(0, 10) // PickRow[]; 동일 소매처코드라도 source별 행 유지
  }, [byCode.match, byRetailMaster.matches, byRagAnswer.matches, customerCode])

  const vendorPickList = useMemo(() => vendorHints.matches, [vendorHints.matches]) // Array<{판매처코드:string;판매처명:string}>; 선택된 소매코드의 전체 판매처 후보

  /** ①候補APIのいずれかのエラー（ロード完了後のみ表示用） */
  const retailPickApiError = useMemo(() => {
    if (byCode.loading || byRetailMaster.loading || byRagAnswer.loading) return null
    const parts = [byCode.error, byRetailMaster.error, byRagAnswer.error].filter(
      (x): x is string => Boolean(x && String(x).trim()),
    )
    if (parts.length === 0) return null
    return [...new Set(parts)].join(' ')
  }, [
    byCode.loading,
    byCode.error,
    byRetailMaster.loading,
    byRetailMaster.error,
    byRagAnswer.loading,
    byRagAnswer.error,
  ])

  /** ①商品候補: RAG(max3 API) + unit_price を類似度で混ぜ、同一商品コードは高い方のみ、上位10件 */
  const unitPickList = useMemo(() => {
    type UnitPickRow = {
      商品コード: string
      商品名: string
      内容量: string
      規格: string
      similarity: number
      source: 'rag' | 'unit_price'
      仕切: number | string | null
      本部長: number | string | null
      ragMatch?: ProductRagMatch
      unitMatch?: UnitPriceMatch
    }
    const dash = '—'
    const fmtCap = (v: unknown) => (v != null && String(v).trim() !== '' ? String(v) : dash)
    const unitSim = (m: UnitPriceMatch): number => {
      const s = m._avg_similarity ?? m.similarity
      if (typeof s === 'number' && !Number.isNaN(s) && s > 0) {
        return s > 1 ? s / 100 : s
      }
      return 0
    }
    const pool: UnitPickRow[] = []
    for (const m of unitByRagAnswer.matches) {
      const code = (m.商品コード ?? '').trim()
      if (!code) continue
      pool.push({
        商品コード: code,
        商品名: (m.商品名 ?? '').trim(),
        内容量: dash,
        規格: dash,
        similarity: typeof m.similarity === 'number' ? m.similarity : 0,
        source: 'rag',
        仕切: m.仕切 ?? null,
        本部長: m.本部長 ?? null,
        ragMatch: m,
      })
    }
    for (const m of unitMatches) {
      const code = m.제품코드 != null ? String(m.제품코드).trim() : ''
      if (!code) continue
      pool.push({
        商品コード: code,
        商品名: String(m.제품명 ?? ''),
        内容量: fmtCap(m.제품용량),
        規格: fmtCap(m.규격),
        similarity: unitSim(m),
        source: 'unit_price',
        仕切: m.시키리 ?? null,
        本部長: m.본부장 ?? null,
        unitMatch: m,
      })
    }
    pool.sort((a, b) => b.similarity - a.similarity)
    const bestByCode = new Map<string, UnitPickRow>()
    for (const row of pool) {
      const prev = bestByCode.get(row.商品コード)
      if (!prev || row.similarity > prev.similarity) {
        bestByCode.set(row.商品コード, row)
      }
    }
    return [...bestByCode.values()].sort((a, b) => b.similarity - a.similarity).slice(0, 10)
  }, [unitByRagAnswer.matches, unitMatches])

  const unitPickApiError = useMemo(() => {
    if (unitLoading || unitByRagAnswer.loading) return null
    const parts = [unitError, unitByRagAnswer.error].filter(
      (x): x is string => Boolean(x && String(x).trim()),
    )
    if (parts.length === 0) return null
    return [...new Set(parts)].join(' ')
  }, [unitLoading, unitError, unitByRagAnswer.loading, unitByRagAnswer.error])

  /** 候補テーブル: 仕切・本部長表示用 */
  const fmtShikiriHonbu = (v: unknown) => {
    if (v == null || v === '') return '—'
    const n = Number(v)
    return Number.isFinite(n) ? n.toLocaleString() : String(v)
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
              <p className="unit-price-match-modal-hint retail-map-spec-intro">
                候補一覧の <strong>適用</strong> で商品コードを反映します。数字のみの商品コードを入力すると unit_price から仕切・本部長を自動表示します。確定でグリッドに保存します。
              </p>

              <section className="retail-map-spec-block retail-map-spec-block--retail">
                <h4 className="retail-map-spec-block-title">① 商品</h4>
                <div className="retail-map-spec-row">
                  <span className="retail-map-spec-label">商品名</span>
                  <div className="retail-map-spec-value">
                    <span className="retail-map-spec-eq">＝ 行の商品名</span>
                    <input
                      type="text"
                      className="retail-final-input retail-map-readonly"
                      readOnly
                      value={productName}
                      title="請求書・グリッドの商品名"
                    />
                  </div>
                </div>
                <div className="retail-map-spec-row">
                  <span className="retail-map-spec-label">商品コード</span>
                  <div className="retail-map-spec-field">
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
                          setSapProductQuery('')
                          setSapProductMatches([])
                        }
                      }}
                      placeholder="商品コード"
                      aria-label="商品コード"
                    />
                    {unitPickList[0] && (
                      <span className="retail-map-rank1-hint">1位候補: {unitPickList[0].商品コード}</span>
                    )}
                  </div>
                </div>
                {(unitPriceAutoFill.仕切 != null || unitPriceAutoFill.本部長 != null) && (
                  <p className="unit-price-match-modal-hint" style={{ marginTop: 4 }}>
                    入力コードの単価: 仕切 {unitPriceAutoFill.仕切 != null ? Number(unitPriceAutoFill.仕切).toLocaleString() : '—'}{' '}
                    / 本部長 {unitPriceAutoFill.本部長 != null ? Number(unitPriceAutoFill.本部長).toLocaleString() : '—'}
                  </p>
                )}

                <p className="retail-map-spec-subhead">候補一覧</p>
                {(unitLoading || unitByRagAnswer.loading) && (
                  <p className="unit-price-match-modal-loading">候補を検索中…</p>
                )}
                {unitByRagAnswer.skippedReason && !unitByRagAnswer.loading && (
                  <p className="unit-price-match-modal-empty">{unitByRagAnswer.skippedReason}</p>
                )}
                {unitPickApiError && (
                  <p className="unit-price-match-modal-error" role="alert">
                    {unitPickApiError}
                  </p>
                )}
                {!unitLoading &&
                  !unitByRagAnswer.loading &&
                  !unitPickApiError &&
                  unitPickList.length === 0 &&
                  !unitByRagAnswer.skippedReason && (
                    <p className="unit-price-match-modal-empty">候補がありません。下の検索を使うか、手入力してください。</p>
                  )}
                {unitPickList.length > 0 && (
                  <div className="unit-price-pick-table-scroll">
                    <table className="unit-price-match-table retail-map-pick-table">
                      <thead>
                        <tr>
                          <th className="retail-map-col-n">#</th>
                          <th>商品コード</th>
                          <th>商品名</th>
                          <th>内容量</th>
                          <th>規格</th>
                          <th>参照</th>
                          <th>類似度</th>
                          <th>仕切</th>
                          <th>本部長</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {unitPickList.map((row, i) => (
                          <tr key={`${row.source}-${row.商品コード}-${i}`}>
                            <td className="retail-map-col-n">{i + 1}</td>
                            <td>{row.商品コード}</td>
                            <td>{row.商品名}</td>
                            <td>{row.内容量}</td>
                            <td>{row.規格}</td>
                            <td>{row.source === 'rag' ? '学習' : 'エクセル'}</td>
                            <td>
                              {row.similarity != null
                                ? row.similarity <= 1 && row.similarity >= 0
                                  ? `${(row.similarity * 100).toFixed(0)}%`
                                  : String(row.similarity)
                                : '—'}
                            </td>
                            <td>{fmtShikiriHonbu(row.仕切)}</td>
                            <td>{fmtShikiriHonbu(row.本部長)}</td>
                            <td>
                              <button
                                type="button"
                                onClick={() =>
                                  row.source === 'rag' && row.ragMatch
                                    ? handleSelectProductRagToFinal(row.ragMatch)
                                    : row.unitMatch
                                      ? handleSelectUnitToFinal(row.unitMatch)
                                      : undefined
                                }
                              >
                                適用
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                <p className="retail-map-spec-subhead">検索</p>
                <label className="retail-final-label retail-map-search-label">
                  <span>検索語</span>
                  <input
                    type="text"
                    className="retail-final-input"
                    value={sapProductQuery}
                    onChange={(e) => setSapProductQuery(e.target.value)}
                    placeholder="商品名で検索 → 結果から適用"
                  />
                </label>
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

                <div className="retail-map-confirm-wrap">
                  <button
                    type="button"
                    className="retail-confirm-btn retail-map-confirm-btn"
                    disabled={!isProductCodeLike(unitFinalForm.商品コード.trim()) || unitPriceAutoLoading}
                    onClick={handleConfirmUnitPrice}
                  >
                    確定
                  </button>
                </div>
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

              <section className="retail-map-spec-block retail-map-spec-block--retail">
                <h4 className="retail-map-spec-block-title">① 小売</h4>
                <div className="retail-map-spec-row">
                  <span className="retail-map-spec-label">小売先名</span>
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
                  <span className="retail-map-spec-label">小売先コード</span>
                  <div className="retail-map-spec-field">
                    <input
                      type="text"
                      className="retail-final-input"
                      value={finalForm.小売先コード}
                      onChange={(e) => setFinalForm((f) => ({ ...f, 小売先コード: e.target.value }))}
                      placeholder="小売先コード"
                      aria-label="小売先コード"
                    />
                  </div>
                </div>
                <p className="retail-map-spec-subhead">候補一覧</p>
                {(byCode.loading || byRetailMaster.loading || byRagAnswer.loading) && (
                  <p className="unit-price-match-modal-loading">候補を検索中…</p>
                )}
                {retailPickApiError && (
                  <p className="unit-price-match-modal-error" role="alert">
                    {retailPickApiError}
                  </p>
                )}
                {!byCode.loading && !byRetailMaster.loading && !byRagAnswer.loading && retailPickList.length === 0 && (
                  <p className="unit-price-match-modal-empty">候補がありません。下の検索を使うか、手入力してください。</p>
                )}
                {retailPickList.length > 0 && (
                  <table className="unit-price-match-table retail-map-pick-table">
                    <thead>
                      <tr>
                        <th className="retail-map-col-n">#</th>
                        <th>小売先コード</th>
                        <th>小売先名（マスタ）</th>
                        <th>参照</th>
                        <th>類似度</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {retailPickList.map((row, i) => (
                        <tr key={`${row.source}-${row.소매처코드}-${i}`}>
                          <td className="retail-map-col-n">{i + 1}</td>
                          <td>{row.소매처코드}</td>
                          <td>{row.소매처명}</td>
                          <td>
                            {row.source === 'rag' ? '学習' : row.source === 'domae' ? 'コード照合' : 'エクセル'}
                          </td>
                          <td>
                            {row.similarity != null ? `${(row.similarity * 100).toFixed(0)}%` : '—'}
                          </td>
                          <td>
                            <button
                              type="button"
                              onClick={() =>
                                row.source === 'rag' && row.ragMatch
                                  ? handleSelectRagToFinal(row.ragMatch)
                                  : applyRetailMasterRowToForm({ 소매처코드: row.소매처코드, 소매처명: row.소매처명 })
                              }
                            >
                              適用
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                <p className="retail-map-spec-subhead">検索</p>
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

              <section className="retail-map-spec-block retail-map-spec-block--vendor">
                <h4 className="retail-map-spec-block-title">② 販売</h4>
                <div className="retail-map-spec-row">
                  <span className="retail-map-spec-label">受注先コード</span>
                  <div className="retail-map-spec-field">
                    <input
                      type="text"
                      className="retail-final-input"
                      value={finalForm.受注先コード}
                      onChange={(e) => setFinalForm((f) => ({ ...f, 受注先コード: e.target.value }))}
                      placeholder="受注先コード"
                      aria-label="受注先コード"
                    />
                  </div>
                </div>
                <div className="retail-map-spec-row">
                  <span className="retail-map-spec-label">受注先名</span>
                  <input
                    type="text"
                    className="retail-final-input"
                    value={finalForm.受注先}
                    onChange={(e) => setFinalForm((f) => ({ ...f, 受注先: e.target.value }))}
                    placeholder="表示名"
                  />
                </div>
                <p className="retail-map-spec-subhead">候補一覧</p>
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
                <p className="retail-map-spec-subhead">検索</p>
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
            </>
          )}
        </div>
      </div>
    </div>
  )
}
