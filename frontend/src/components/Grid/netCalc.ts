import { parseCellNum } from './utils'
import type { GridRow } from './types'

export interface NetCalcResult {
  net: number | null // number|null; 예: 1840.5 | null
  base: number | null // number|null; 예: 차감 기준값(조건합/단가/미수조건합)
  source: 'cond' | 'tanka' | 'mishu' | null // string|null; 예: 'cond'
}

function parseYenValue(v: unknown): number | null {
  const normalized = typeof v === 'string' ? v.replace(/[円¥￥]/g, '').trim() : v // string|unknown; 예: "3,700円" -> "3,700"
  return parseCellNum(normalized)
}

function sumNullable(a: number | null, b: number | null): number | null {
  if (a == null && b == null) return null
  return (a ?? 0) + (b ?? 0) // number; 예: null + 29 -> 29
}

function normalizeFormType(formType: string | null | undefined): string {
  return String(formType ?? '').trim().replace(/^0+/, '') // string; 예: "03" -> "3"
}

function normalizeUnitToCs(unit: unknown): string {
  const unitRaw = String(unit ?? '').trim()
  return unitRaw.replace('\uFF23', 'C').replace('\uFF33', 'S').toUpperCase() // string; 예: "ＣＳ" -> "CS"
}

export function calcNetByForm(row: GridRow, formType: string | null | undefined): NetCalcResult {
  const ft = normalizeFormType(formType)
  const shikiri = parseCellNum(row['仕切'])
  if (shikiri == null) return { net: null, base: null, source: null }

  const cond1 = parseYenValue(row['条件'])
  const cond2 = parseYenValue(row['条件2'])
  const condSum = sumNullable(cond1, cond2) // number|null; 예: 126 + 29

  if (ft === '1') {
    if (condSum == null) return { net: null, base: null, source: 'cond' }
    const unitNorm = normalizeUnitToCs(row['数量単位'])
    const irisu = parseCellNum(row['入数'])
    const base = unitNorm === 'CS' && irisu != null && irisu > 0 ? condSum / irisu : condSum // number; 예: (126+29)/10
    return { net: shikiri - base, base, source: 'cond' }
  }

  if (ft === '2') {
    if (condSum == null) return { net: null, base: null, source: 'cond' }
    return { net: shikiri - condSum, base: condSum, source: 'cond' }
  }

  if (ft === '3') {
    const tanka = parseYenValue(row['単価'])
    const hasCond = condSum != null
    const base = hasCond ? condSum : tanka // number|null; 예: cond 비어있으면 単価 사용
    if (base == null) return { net: null, base: null, source: null }
    return { net: shikiri - base, base, source: hasCond ? 'cond' : 'tanka' }
  }

  if (ft === '4') {
    const misu1 = parseCellNum(row['未収条件'])
    const misu2 = parseCellNum(row['未収条件2'])
    const base = sumNullable(misu1, misu2)
    if (base == null) return { net: null, base: null, source: 'mishu' }
    return { net: shikiri - base, base, source: 'mishu' }
  }

  if (ft === '5') {
    const irisu = parseCellNum(row['入数'])
    if (condSum == null || irisu == null || irisu <= 0) return { net: null, base: null, source: 'cond' }
    const base = condSum / irisu // number; 예: (条件+条件2)/入数
    return { net: shikiri - base, base, source: 'cond' }
  }

  return { net: null, base: null, source: null }
}
