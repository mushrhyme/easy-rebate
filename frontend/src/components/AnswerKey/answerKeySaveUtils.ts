/**
 * 解答作成タブ: 保存用 pages 組み立ての共通ロジック
 * handleSaveGrid 用の pages 組み立て共通化
 */
import type { GridRow } from './answerKeyTabConstants'
import { PAGE_META_DELETE_SENTINEL } from './answerKeyTabConstants'

const EXCLUDE_FROM_ITEM_DATA = ['item_id', 'page_number', 'item_order', 'version', '_displayIndex']

export type PagePayload = {
  page_number: number
  page_role: string
  page_meta: Record<string, unknown>
  items: Array<Record<string, unknown>>
}

/**
 * 1文書分の pages 配列を組み立て（item_data_list + page_role + page_meta）
 * getPageRole / getPageMeta は呼び出し元で answerJson または pageMetaQueries 由来を切り替え可能
 */
export function buildPagesPayload(
  totalPages: number,
  latestRows: GridRow[],
  pageMetaFlatEdits: Record<number, Record<string, string>>,
  getPageRole: (p: number) => string,
  getPageMeta: (p: number) => Record<string, unknown>
): PagePayload[] {
  const pages: PagePayload[] = []
  for (let p = 1; p <= totalPages; p++) {
    const pageRows = latestRows.filter((r) => r.page_number === p)
    const item_data_list = pageRows
      .sort((a, b) => Number(a.item_order ?? 0) - Number(b.item_order ?? 0))
      .map((row) => {
        const item_data: Record<string, unknown> = {}
        Object.keys(row).forEach((k) => {
          if (!EXCLUDE_FROM_ITEM_DATA.includes(k)) item_data[k] = row[k]
        })
        return item_data
      })
    const edits = pageMetaFlatEdits[p] ?? {}
    Object.entries(edits).forEach(([path, value]) => {
      if (value === PAGE_META_DELETE_SENTINEL) return
      const m = /^items\[(\d+)\]\.(.+)$/.exec(path)
      if (m) {
        const idx = parseInt(m[1], 10)
        const field = m[2]
        if (idx >= 0 && idx < item_data_list.length) item_data_list[idx][field] = value
      }
    })
    const page_role = getPageRole(p)
    const page_meta = getPageMeta(p)
    pages.push({ page_number: p, page_role, page_meta, items: item_data_list })
  }
  return pages
}

const VALID_PAGE_ROLES = ['cover', 'detail', 'summary', 'reply']

export function normalizePageRole(raw: string): string {
  return VALID_PAGE_ROLES.includes(raw) ? raw : 'detail'
}

/** 画面表示済み OCR を queryClient キャッシュから取り出し pages に付与（ベクター登録で再抽出しない） */
export function attachOcrToPages(
  pages: PagePayload[],
  pdfFilename: string,
  queryClient: { getQueryData: <T>(key: unknown[]) => T | undefined }
): void {
  for (const page of pages) {
    const cached = queryClient.getQueryData<{ ocr_text?: string }>([
      'page-ocr-text',
      pdfFilename,
      page.page_number,
    ])
    if (cached?.ocr_text && String(cached.ocr_text).trim()) {
      (page as Record<string, unknown>).ocr_text = String(cached.ocr_text).trim()
    }
  }
}
