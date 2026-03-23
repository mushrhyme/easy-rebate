/**
 * 검토 탭 그리드: 컬럼 순서 병합·재정렬 유틸.
 * 서버(DB)가 주 저장소이며, load/save/clear는 예전 localStorage → DB 마이그레이션·오프라인 폴백용.
 */
import type { Column } from 'react-data-grid'

const STORAGE_PREFIX = 'easy-rebate:review-grid-flex-columns:v1' // 키 예: ...:v1:42

/** 로그인 user_id별로 순서 분리 (동일 PC에서 계정 전환 대응) */
export function reviewGridColumnStorageKey(userId: number | null): string {
  const id = userId != null ? String(userId) : 'anon' // userId: number | null → 스토리지 세그먼트
  return `${STORAGE_PREFIX}:${id}`
}

export class ReviewGridColumnOrderStorage {
  /** 저장된 flex 컬럼 키 배열, 없거나 파싱 실패 시 null — 예: ['得意先','金額', ...] */
  static load(userId: number | null): string[] | null {
    if (typeof window === 'undefined') return null
    try {
      const raw = localStorage.getItem(reviewGridColumnStorageKey(userId))
      if (!raw) return null
      const parsed = JSON.parse(raw) as unknown
      if (!Array.isArray(parsed) || !parsed.every((x) => typeof x === 'string')) return null
      return parsed as string[]
    } catch {
      return null
    }
  }

  /** 오프라인 폴백용 저장 — flex 컬럼 key만 */
  static save(userId: number | null, keys: string[]): void {
    if (typeof window === 'undefined') return
    try {
      localStorage.setItem(reviewGridColumnStorageKey(userId), JSON.stringify(keys))
    } catch {
      /* quota 등 무시 */
    }
  }

  /** 마이그레이션 후 로컬 제거 */
  static clear(userId: number | null): void {
    if (typeof window === 'undefined') return
    try {
      localStorage.removeItem(reviewGridColumnStorageKey(userId))
    } catch {
      /* ignore */
    }
  }
}

/**
 * 저장된 순서와 현재 문서의 flex 키 목록을 합침.
 * @param saved 이전에 저장된 순서 (없으면 null)
 * @param defaultFlexKeys 현재 그리드 기본 순서의 flex 키들
 * @returns 병합된 키 배열 — 예: saved에 없는 신규 컬럼은 default 순서로 뒤에 붙음
 */
export function mergeFlexColumnOrder(saved: string[] | null, defaultFlexKeys: string[]): string[] {
  if (!saved?.length) return [...defaultFlexKeys]
  const used = new Set<string>()
  const out: string[] = []
  for (const k of saved) {
    if (defaultFlexKeys.includes(k) && !used.has(k)) {
      out.push(k)
      used.add(k)
    }
  }
  for (const k of defaultFlexKeys) {
    if (!used.has(k)) out.push(k)
  }
  return out
}

/**
 * 드롭 시 source를 target 앞(왼쪽)으로 이동 — RDG onColumnsReorder 시그니처와 동일한 의미
 */
export function reorderFlexKeys(order: string[], sourceKey: string, targetKey: string): string[] {
  if (sourceKey === targetKey) return order
  const si = order.indexOf(sourceKey)
  const ti = order.indexOf(targetKey)
  if (si === -1 || ti === -1) return order
  const next = order.filter((k) => k !== sourceKey)
  const newTi = next.indexOf(targetKey)
  next.splice(newTi, 0, sourceKey)
  return next
}

/**
 * 동결 컬럼은 그대로 두고 flex만 flexOrder 순으로 재배열 — Column<GridRow>[]
 */
export function applyFlexOrderToColumns<TRow>(
  baseColumns: Column<TRow>[],
  flexOrder: string[]
): Column<TRow>[] {
  const frozen = baseColumns.filter((c) => c.frozen)
  const flexByKey = new Map(
    baseColumns.filter((c) => !c.frozen).map((c) => [String(c.key), c] as const)
  )
  const flex: Column<TRow>[] = []
  for (const k of flexOrder) {
    const col = flexByKey.get(k)
    if (col) flex.push(col)
  }
  return [...frozen, ...flex]
}
