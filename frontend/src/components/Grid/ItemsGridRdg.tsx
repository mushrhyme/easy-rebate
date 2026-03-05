/**
 * React Data Grid 아이템 테이블 컴포넌트
 * 셀 편집 중 락 기능 포함
 */
import { useMemo, useState, useCallback, useRef, useEffect, forwardRef, useImperativeHandle } from 'react'
import { createPortal } from 'react-dom'
import { DataGrid, type DataGridHandle } from 'react-data-grid'
import 'react-data-grid/lib/styles.css'
import { useQueryClient } from '@tanstack/react-query'
import { useItems, useUpdateItem, useCreateItem, useDeleteItem, useAcquireLock, useReleaseLock, usePageMeta } from '@/hooks/useItems'
import { useItemLocks } from '@/hooks/useItemLocks'
import { itemsApi } from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import type { ReviewStatus } from '@/types'
import {
  type ItemsGridRdgProps,
  type ItemsGridRdgHandle,
  type BulkCheckState,
  type GridRow,
  CONDITION_AMOUNT_KEYS,
} from './types'
import { parseCellNum } from './utils'
import { ComplexFieldDetail } from './ComplexFieldDetail'
import { UnitPriceMatchModal } from './UnitPriceMatchModal'
import { AttachmentModal } from './AttachmentModal'
import { useItemsGridColumns } from './useItemsGridColumns'
import './ItemsGridRdg.css'

// 외부에서 import 가능하도록 re-export
export type { ItemsGridRdgHandle, BulkCheckState }

export const ItemsGridRdg = forwardRef<ItemsGridRdgHandle, ItemsGridRdgProps>(function ItemsGridRdg({
  pdfFilename,
  pageNumber,
  formType: _formType,
  onBulkCheckStateChange,
  readOnly = false,
}, ref) {
  const { data, isLoading, error } = useItems(pdfFilename, pageNumber)
  const { data: pageMetaData, isLoading: pageMetaLoading, error: pageMetaError } = usePageMeta(pdfFilename, pageNumber) // page_meta 조회

  // 디버깅: page_meta 데이터 확인
  useEffect(() => {
    console.log('🔵 [ItemsGridRdg] pageMetaData:', {
      pageMetaData,
      pageMetaLoading,
      pageMetaError,
      pdfFilename,
      pageNumber,
    })
  }, [pageMetaData, pageMetaLoading, pageMetaError, pdfFilename, pageNumber])
  const updateItem = useUpdateItem(pdfFilename, pageNumber) // pdfFilename과 pageNumber 전달
  const createItem = useCreateItem(pdfFilename, pageNumber)
  const deleteItem = useDeleteItem(pdfFilename, pageNumber)
  const acquireLock = useAcquireLock()
  const releaseLock = useReleaseLock()
  const queryClient = useQueryClient() // 쿼리 무효화를 위한 queryClient
  const { sessionId } = useAuth() // 실제 로그인 세션 ID 사용 (useUploadStore의 랜덤 UUID가 아님)
  const [editingItemIds, setEditingItemIds] = useState<Set<number>>(new Set())
  const [containerWidth, setContainerWidth] = useState<number>(1200) // 기본값
  const gridRef = useRef<DataGridHandle>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [selectedComplexField, setSelectedComplexField] = useState<{ key: string; value: unknown; itemId: number } | null>(null) // 모달에 표시할 복잡한 필드
  const [hoveredRowId, setHoveredRowId] = useState<number | null>(null) // 호버된 행 ID
  const [reviewTooltip, setReviewTooltip] = useState<{ text: string; x: number; y: number } | null>(null) // 1次/2次 증빙 툴팁
  const [unitPriceModalRow, setUnitPriceModalRow] = useState<GridRow | null>(null) // 단가 후보 모달
  const [attachmentModalOpen, setAttachmentModalOpen] = useState(false) // 첨부 파일 모달
  
  // 컨테이너 너비 측정
  useEffect(() => {
    const updateWidth = () => {
      if (containerRef.current) {
        setContainerWidth(containerRef.current.offsetWidth - 20) // 패딩/보더 고려
      } else if (typeof window !== 'undefined') {
        setContainerWidth(window.innerWidth - 200) // 여유 공간 고려
      }
    }
    
    updateWidth()
    window.addEventListener('resize', updateWidth)
    return () => window.removeEventListener('resize', updateWidth)
  }, [])

  // WebSocket을 통한 실시간 락 상태 구독 및 review_status 업데이트 처리
  const { isItemLocked, getLockedBy } = useItemLocks({
    pdfFilename,
    pageNumber,
    enabled: !!pdfFilename && !!pageNumber,
    onReviewStatusUpdate: useCallback((itemId: number, reviewStatus: ReviewStatus) => {
      console.log('🔵 [ItemsGridRdg] onReviewStatusUpdate 호출:', {
        itemId,
        reviewStatus,
        pdfFilename,
        pageNumber,
      })
      
      const newFirst = reviewStatus?.first_review?.checked || false
      const newSecond = reviewStatus?.second_review?.checked || false
      
      // 원격 업데이트된 아이템 ID와 값 기록 (다른 탭에서 온 업데이트)
      remoteUpdatedItemsRef.current.add(itemId)
      remoteUpdatedValuesRef.current.set(itemId, { first: newFirst, second: newSecond })
      
      // rows 상태 즉시 업데이트 (낙관적 업데이트)
      // 상태가 같으면 업데이트하지 않음 (불필요한 리렌더링 방지)
      setRows((prevRows) => {
        const updated = prevRows.map((r) => {
          if (r.item_id === itemId) {
            // 상태가 같으면 업데이트하지 않음
            if (r.first_review_checked === newFirst && r.second_review_checked === newSecond) {
              return r
            }
            
            console.log('🔵 [ItemsGridRdg] rows 업데이트:', {
              item_id: r.item_id,
              이전: {
                first: r.first_review_checked,
                second: r.second_review_checked,
              },
              이후: {
                first: newFirst,
                second: newSecond,
              },
            })
            return {
              ...r,
              first_review_checked: newFirst,
              second_review_checked: newSecond,
            }
          }
          return r
        })
        return updated
      })
      
      // 데이터 갱신 (다른 탭 동기화) - 서버 반영 시간을 고려하여 지연
      setTimeout(() => {
        queryClient.invalidateQueries({
          queryKey: ['items', pdfFilename, pageNumber],
        })
      }, 500) // 서버 반영 시간 고려하여 0.5초 후 갱신
      
      console.log('✅ [ItemsGridRdg] onReviewStatusUpdate 완료')
    }, [queryClient, pdfFilename, pageNumber]),
  })

  const items = data?.items || []
  const hasItems = items.length > 0 // items 존재 여부

  // 행 데이터 변환 (초기 데이터, 증빙용 reviewed_at/reviewed_by 포함)
  const initialRows = useMemo<GridRow[]>(() => {
    const gridRows = items.map((item) => {
      const row: GridRow = {
        item_id: item.item_id,
        item_order: item.item_order,
        first_review_checked: item.review_status?.first_review?.checked || false,
        second_review_checked: item.review_status?.second_review?.checked || false,
        first_review_reviewed_at: item.review_status?.first_review?.reviewed_at ?? null,
        first_review_reviewed_by: item.review_status?.first_review?.reviewed_by ?? null,
        second_review_reviewed_at: item.review_status?.second_review?.reviewed_at ?? null,
        second_review_reviewed_by: item.review_status?.second_review?.reviewed_by ?? null,
      }

      if (item.item_data) {
        Object.keys(item.item_data).forEach((key) => {
          row[key] = item.item_data[key]
        })
      }
      // 검토 탭 frozen: 受注先コード/小売先コード/商品コード → item_data 원천만 사용 (타입과 동일)

      return row
    })
    return gridRows
  }, [items])

  // rows 상태 관리 (편집 중 변경사항 추적)
  const [rows, setRows] = useState<GridRow[]>(initialRows)
  const rowsRef = useRef<GridRow[]>(rows) // 일괄 체크 시 최신 rows 참조용
  useEffect(() => {
    rowsRef.current = rows
  }, [rows])

  // 부모 체크박스용: 현재 페이지 전체/일부 체크 상태 알림 (값이 바뀐 경우에만 호출해 불필요한 부모 리렌더 감소)
  const lastBulkStateRef = useRef<BulkCheckState | null>(null)
  useEffect(() => {
    if (!onBulkCheckStateChange || rows.length === 0) return
    const allFirstChecked = rows.every((r) => r.first_review_checked)
    const allSecondChecked = rows.every((r) => r.second_review_checked)
    const someFirstChecked = rows.some((r) => r.first_review_checked)
    const someSecondChecked = rows.some((r) => r.second_review_checked)
    const next: BulkCheckState = {
      allFirstChecked,
      allSecondChecked,
      someFirstChecked,
      someSecondChecked,
    }
    const prev = lastBulkStateRef.current
    if (
      prev &&
      prev.allFirstChecked === next.allFirstChecked &&
      prev.allSecondChecked === next.allSecondChecked &&
      prev.someFirstChecked === next.someFirstChecked &&
      prev.someSecondChecked === next.someSecondChecked
    ) {
      return
    }
    lastBulkStateRef.current = next
    onBulkCheckStateChange(next)
  }, [rows, onBulkCheckStateChange])

  const remoteUpdatedItemsRef = useRef<Set<number>>(new Set()) // WebSocket으로 업데이트된 아이템 ID 추적
  const remoteUpdatedValuesRef = useRef<Map<number, { first: boolean; second: boolean }>>(new Map()) // WebSocket으로 받은 체크박스 값 저장
  const editingItemIdsRef = useRef(editingItemIds) // 편집 중인 아이템 ID 참조 저장

  // editingItemIds 변경 시 ref 업데이트
  useEffect(() => {
    editingItemIdsRef.current = editingItemIds
  }, [editingItemIds])

  // items가 변경되면 rows 업데이트 (체크박스 상태는 항상 서버 값으로 동기화)
  useEffect(() => {
    // items가 비어있으면 업데이트하지 않음
    if (items.length === 0) {
      return
    }
    
    // initialRows를 직접 계산 (서버에서 가져온 최신 값 사용)
    const newInitialRows: GridRow[] = items.map((item) => {
      const row: GridRow = {
        item_id: item.item_id,
        item_order: item.item_order,
        first_review_checked: item.review_status?.first_review?.checked || false,
        second_review_checked: item.review_status?.second_review?.checked || false,
        first_review_reviewed_at: item.review_status?.first_review?.reviewed_at ?? null,
        first_review_reviewed_by: item.review_status?.first_review?.reviewed_by ?? null,
        second_review_reviewed_at: item.review_status?.second_review?.reviewed_at ?? null,
        second_review_reviewed_by: item.review_status?.second_review?.reviewed_by ?? null,
      }

      if (item.item_data) {
        Object.keys(item.item_data).forEach((key) => {
          row[key] = item.item_data[key]
        })
      }
      // 검토 탭 frozen: item_data 원천만 사용

      return row
    })
    
    setRows((prevRows) => {
      // 새로운 initialRows와 기존 rows를 병합
      const newRows = newInitialRows.map((newRow: GridRow) => {
        const existingRow = prevRows.find((r) => r.item_id === newRow.item_id)
        if (existingRow) {
          // WebSocket으로 업데이트된 아이템인 경우 WebSocket으로 받은 값 사용 (다른 탭에서 업데이트)
          // 서버 값이 아직 반영되지 않았을 수 있으므로 WebSocket 값 우선 사용
          if (remoteUpdatedItemsRef.current.has(newRow.item_id)) {
            const remoteValue = remoteUpdatedValuesRef.current.get(newRow.item_id)
            if (remoteValue) {
              // WebSocket으로 받은 값이 서버 값과 다르면 WebSocket 값 사용
              // 서버 값과 같으면 서버 값 사용 (이미 동기화됨)
              const serverFirst = newRow.first_review_checked
              const serverSecond = newRow.second_review_checked
              
              if (serverFirst === remoteValue.first && serverSecond === remoteValue.second) {
                // 서버 값과 같으면 서버 값 사용하고 보호 해제
                remoteUpdatedItemsRef.current.delete(newRow.item_id)
                remoteUpdatedValuesRef.current.delete(newRow.item_id)
                return newRow
              } else {
                // 서버 값과 다르면 WebSocket 값 사용 (서버 반영 전)
                return {
                  ...newRow,
                  first_review_checked: remoteValue.first,
                  second_review_checked: remoteValue.second,
                }
              }
            } else {
              // 값이 없으면 서버 값 사용하고 보호 해제
              remoteUpdatedItemsRef.current.delete(newRow.item_id)
              return newRow
            }
          }
          
          // 편집 중인 경우에만 item_data 필드만 기존 값 유지
          // 체크박스는 항상 서버 값 사용
          if (editingItemIdsRef.current.has(newRow.item_id)) {
            return {
              ...newRow,
              // 편집 중이어도 체크박스는 서버 값 사용
              first_review_checked: newRow.first_review_checked,
              second_review_checked: newRow.second_review_checked,
            }
          }
          
          // 편집 중이 아니면 서버 값 사용
          return newRow
        }
        // 새로운 행인 경우 그대로 반환
        return newRow
      })
      
      // 체크박스 상태 변경도 감지하여 항상 업데이트
      const hasChanges = newRows.length !== prevRows.length ||
        newRows.some((newRow, idx) => {
          const prevRow = prevRows[idx]
          if (!prevRow || prevRow.item_id !== newRow.item_id) return true
          // 체크박스 상태 비교 추가
          if (prevRow.first_review_checked !== newRow.first_review_checked ||
              prevRow.second_review_checked !== newRow.second_review_checked) {
            return true
          }
          // 주요 필드 비교 (상품명은 row['商品名'] 등 동적 키로 있음)
          const newData = { ...newRow } as Record<string, unknown>
          const prevData = { ...prevRow } as Record<string, unknown>
          delete newData.item_data
          delete prevData.item_data
          return JSON.stringify(newData) !== JSON.stringify(prevData)
        })
      
      return hasChanges ? newRows : prevRows
    })
  }, [items]) // items 변경 시 항상 체크박스 상태 동기화

  // 셀 값 업데이트 핸들러 (즉시 rows 상태 업데이트)
  const handleCellChange = useCallback((itemId: number, field: string, value: any) => {
    setRows((prevRows) =>
      prevRows.map((r) =>
        r.item_id === itemId ? { ...r, [field]: value } : r
      )
    )
  }, [])

  /**
   * 체크박스만 업데이트: review_status만 저장 (락 없이, 편집 모드와 무관)
   * 버전 충돌 시 최신 데이터를 가져와서 자동 재시도
   */
  const handleCheckboxUpdate = useCallback(async (
    itemId: number, 
    field: 'first_review_checked' | 'second_review_checked', 
    checked: boolean,
    retryCount: number = 0 // 재시도 횟수
  ) => {
    console.log('🔵 [체크박스] 클릭 시작:', { itemId, field, checked, retryCount, sessionId })
    
    // sessionId 확인
    if (!sessionId) {
      console.error('❌ [체크박스] sessionId가 없습니다!')
      alert('セッションIDがありません。ページを再読み込みしてください。')
      return
    }
    
    // 항상 최신 데이터 가져오기 (버전 충돌 방지)
    let latestItems
    try {
      latestItems = await queryClient.fetchQuery({
        queryKey: ['items', pdfFilename, pageNumber],
        queryFn: () => itemsApi.getByPage(pdfFilename, pageNumber),
        staleTime: 0, // 항상 최신 데이터 가져오기
      })
    } catch (error: any) {
      console.error('❌ [체크박스] 최신 데이터 가져오기 실패:', error)
      alert('データの取得に失敗しました。ページを再読み込みしてください。')
      return
    }
    
    // 아이템 정보 찾기 (최신 데이터에서)
    const updatedItem = latestItems.items.find((i: any) => i.item_id === itemId)
    if (!updatedItem) {
      console.error('❌ [체크박스] Item not found:', itemId, 'available items:', latestItems.items.map((i: any) => i.item_id))
      alert(`アイテムが見つかりません (ID: ${itemId})`)
      return
    }
    
    console.log('🔵 [체크박스] 아이템 찾음:', { 
      item_id: updatedItem.item_id, 
      version: updatedItem.version,
      retryCount,
      currentFirstChecked: updatedItem.review_status?.first_review?.checked,
      currentSecondChecked: updatedItem.review_status?.second_review?.checked,
      item_data: updatedItem.item_data,
    })

    // 서버의 최신 review_status 사용 (다른 체크박스 값도 서버에서 가져오기)
    const currentFirstChecked = updatedItem.review_status?.first_review?.checked || false
    const currentSecondChecked = updatedItem.review_status?.second_review?.checked || false
    
    // rows 상태 먼저 업데이트 (낙관적 업데이트)
    setRows((prevRows) =>
      prevRows.map((r) =>
        r.item_id === itemId
          ? { ...r, [field]: checked }
          : r
      )
    )

    // review_status만 업데이트 (서버의 최신 상태 기반)
    const reviewStatus: ReviewStatus = {
      first_review: {
        checked: field === 'first_review_checked' ? checked : currentFirstChecked,
      },
      second_review: {
        checked: field === 'second_review_checked' ? checked : currentSecondChecked,
      },
    }

    // 요청 데이터 검증
    const requestData = {
      item_data: updatedItem.item_data || {}, // 기존 item_data 유지
      review_status: reviewStatus,
      expected_version: updatedItem.version, // 최신 버전 사용
      session_id: sessionId,
    }
    
    console.log('🔵 [체크박스] 서버 저장 시작:', {
      itemId: updatedItem.item_id,
      requestData,
      retryCount,
    })
    
    // 요청 데이터 검증
    if (!requestData.session_id) {
      console.error('❌ [체크박스] session_id가 없습니다!')
      alert('セッションIDがありません。ページを再読み込みしてください。')
      return
    }
    
    if (requestData.expected_version === undefined || requestData.expected_version === null) {
      console.error('❌ [체크박스] expected_version이 없습니다!', updatedItem)
      alert('バージョン情報がありません。ページを再読み込みしてください。')
      return
    }
    
    try {
      // 비동기로 서버에 저장
      const result = await updateItem.mutateAsync({
        itemId: updatedItem.item_id,
        request: requestData,
      })
      
      console.log('✅ [체크박스] 서버 저장 성공:', result)
      
      // useUpdateItem의 onSuccess에서 invalidateQueries가 호출됨
      // 추가로 호출할 필요 없음
    } catch (error: any) {
      const errorStatus = error?.response?.status
      const errorDetail = error?.response?.data?.detail || error?.message
      const errorData = error?.response?.data
      
      console.error('❌ [체크박스 업데이트 실패]', {
        itemId,
        field,
        checked,
        status: errorStatus,
        detail: errorDetail,
        errorData: errorData,
        fullError: error,
        retryCount,
      })
      
      if (errorStatus === 409) {
        // 버전 충돌: 최신 데이터로 자동 재시도 (최대 2번)
        if (retryCount < 2) {
          console.log('🔄 [체크박스] 버전 충돌 - 자동 재시도:', retryCount + 1)
          // 최신 데이터를 가져온 후 재시도
          await queryClient.invalidateQueries({
            queryKey: ['items', pdfFilename, pageNumber],
          })
          // 짧은 딜레이 후 재시도
          await new Promise(resolve => setTimeout(resolve, 100))
          // 재시도 (재귀 호출)
          return handleCheckboxUpdate(itemId, field, checked, retryCount + 1)
        } else {
          // 최대 재시도 횟수 초과: 상태 롤백 및 알림
          setRows((prevRows) =>
            prevRows.map((r) =>
              r.item_id === itemId
                ? { ...r, [field]: !checked }
                : r
            )
          )
          queryClient.invalidateQueries({
            queryKey: ['items', pdfFilename, pageNumber],
          })
          alert(`他のユーザーが編集中です。しばらくしてからもう一度お試しください。\n\nエラー詳細: ${errorDetail}`)
        }
      } else {
        // 다른 에러: 상태 롤백 및 상세 에러 메시지 표시
        setRows((prevRows) =>
          prevRows.map((r) =>
            r.item_id === itemId
              ? { ...r, [field]: !checked }
              : r
          )
        )
        const errorMessage = errorDetail 
          ? `チェックボックスの更新に失敗しました。\n\nエラー: ${errorDetail}\nステータス: ${errorStatus || '不明'}`
          : `チェックボックスの更新に失敗しました。\n\nステータス: ${errorStatus || '不明'}`
        alert(errorMessage)
      }
    }
  }, [updateItem, sessionId, queryClient, pdfFilename, pageNumber])

  /** 일괄 검토 체크: 최신 데이터 1회 fetch 후 모든 항목 병렬 PATCH (CancelledError 방지) */
  type BulkReviewUpdate = { itemId: number; field: 'first_review_checked' | 'second_review_checked'; checked: boolean }
  const bulkUpdateReviewStatus = useCallback(async (updates: BulkReviewUpdate[]) => {
    if (updates.length === 0) return
    if (!sessionId) {
      alert('セッションIDがありません。ページを再読み込みしてください。')
      return
    }
    // 낙관적 업데이트: 한 번에 반영
    setRows((prev) =>
      prev.map((r) => {
        const u = updates.find((x) => x.itemId === r.item_id)
        if (!u) return r
        return {
          ...r,
          first_review_checked: u.field === 'first_review_checked' ? u.checked : r.first_review_checked,
          second_review_checked: u.field === 'second_review_checked' ? u.checked : r.second_review_checked,
        }
      })
    )
    let latestItems: { items: any[] }
    try {
      latestItems = await queryClient.fetchQuery({
        queryKey: ['items', pdfFilename, pageNumber],
        queryFn: () => itemsApi.getByPage(pdfFilename, pageNumber),
        staleTime: 0,
      })
    } catch (err: any) {
      const isCancelled = err?.name === 'CancelledError' || /cancel/i.test(String(err?.message))
      if (isCancelled) {
        setRows((prev) =>
          prev.map((r) => {
            const u = updates.find((x) => x.itemId === r.item_id)
            if (!u) return r
            return {
              ...r,
              first_review_checked: u.field === 'first_review_checked' ? !u.checked : r.first_review_checked,
              second_review_checked: u.field === 'second_review_checked' ? !u.checked : r.second_review_checked,
            }
          })
        )
        queryClient.invalidateQueries({ queryKey: ['items', pdfFilename, pageNumber] })
        return
      }
      console.error('❌ [일괄 체크] 최신 데이터 가져오기 실패:', err)
      alert('データの取得に失敗しました。ページを再読み込みしてください。')
      setRows((prev) =>
        prev.map((r) => {
          const u = updates.find((x) => x.itemId === r.item_id)
          if (!u) return r
          return {
            ...r,
            first_review_checked: u.field === 'first_review_checked' ? !u.checked : r.first_review_checked,
            second_review_checked: u.field === 'second_review_checked' ? !u.checked : r.second_review_checked,
          }
        })
      )
      return
    }
    const payloads: { itemId: number; request: any }[] = []
    const skipIds = new Set<number>()
    for (const u of updates) {
      const item = latestItems.items.find((i: any) => i.item_id === u.itemId)
      if (!item || item.version === undefined || item.version === null) {
        skipIds.add(u.itemId)
        continue
      }
      const curFirst = item.review_status?.first_review?.checked ?? false
      const curSecond = item.review_status?.second_review?.checked ?? false
      payloads.push({
        itemId: item.item_id,
        request: {
          item_data: item.item_data ?? {},
          review_status: {
            first_review: { checked: u.field === 'first_review_checked' ? u.checked : curFirst },
            second_review: { checked: u.field === 'second_review_checked' ? u.checked : curSecond },
          },
          expected_version: item.version,
          session_id: sessionId,
        },
      })
    }
    if (skipIds.size) {
      setRows((prev) =>
        prev.map((r) => {
          if (!skipIds.has(r.item_id)) return r
          const u = updates.find((x) => x.itemId === r.item_id)
          if (!u) return r
          return {
            ...r,
            first_review_checked: u.field === 'first_review_checked' ? !u.checked : r.first_review_checked,
            second_review_checked: u.field === 'second_review_checked' ? !u.checked : r.second_review_checked,
          }
        })
      )
    }
    const results = await Promise.allSettled(
      payloads.map((p) => updateItem.mutateAsync({ itemId: p.itemId, request: p.request }))
    )
    const failed = results
      .map((r, i) => (r.status === 'rejected' ? payloads[i].itemId : null))
      .filter((id): id is number => id != null)
    if (failed.length > 0) {
      setRows((prev) =>
        prev.map((r) => {
          if (!failed.includes(r.item_id)) return r
          const u = updates.find((x) => x.itemId === r.item_id)
          if (!u) return r
          return {
            ...r,
            first_review_checked: u.field === 'first_review_checked' ? !u.checked : r.first_review_checked,
            second_review_checked: u.field === 'second_review_checked' ? !u.checked : r.second_review_checked,
          }
        })
      )
      queryClient.invalidateQueries({ queryKey: ['items', pdfFilename, pageNumber] })
      const firstRejected = results.find((r) => r.status === 'rejected') as PromiseRejectedResult | undefined
      const msg = firstRejected?.reason?.response?.data?.detail ?? firstRejected?.reason?.message ?? '不明'
      alert(`${failed.length}件の更新に失敗しました。\n\n例: ${msg}`)
    } else {
      queryClient.invalidateQueries({ queryKey: ['items', pdfFilename, pageNumber] })
    }
  }, [sessionId, queryClient, pdfFilename, pageNumber, updateItem])

  // 행 추가/삭제는 useItemsGridColumns에서 사용하므로 먼저 정의
  const handleAddRow = useCallback(async (afterItemId?: number) => {
    if (!pdfFilename || !pageNumber) return
    try {
      const emptyItemData: Record<string, unknown> = {}
      if (items.length > 0 && items[0].item_data) {
        Object.keys(items[0].item_data).forEach((key) => {
          const value = items[0].item_data![key]
          if (typeof value === 'string') emptyItemData[key] = ''
          else if (typeof value === 'number') emptyItemData[key] = 0
          else if (typeof value === 'boolean') emptyItemData[key] = false
          else emptyItemData[key] = null
        })
      }
      await createItem.mutateAsync({
        itemData: emptyItemData,
        afterItemId,
      })
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string }; status?: number }; message?: string }
      const msg = err?.response?.data?.detail ?? err?.message ?? '행 추가에 실패했습니다'
      alert(`행 추가에 실패했습니다: ${msg}`)
    }
  }, [pdfFilename, pageNumber, items, createItem])

  const handleDeleteRow = useCallback(async (itemId: number) => {
    if (!confirm('정말로 이 행을 삭제하시겠습니까?')) return
    try {
      await deleteItem.mutateAsync(itemId)
    } catch {
      alert('행 삭제에 실패했습니다')
    }
  }, [deleteItem])

  const itemDataKeysFromApi = data?.item_data_keys?.length ? data.item_data_keys : null
  const kuMapping = useMemo(() => {
    const meta = pageMetaData?.page_meta
    const raw = meta?.区_mapping ?? meta?.['区_mapping']
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
    const entries = Object.entries(raw).filter(([, v]) => v != null && typeof v === 'string') as [string, string][]
    if (entries.length === 0) return null
    return Object.fromEntries(entries.map(([k, v]) => [String(k).trim(), v]))
  }, [pageMetaData?.page_meta])
  const getKuLabel = useCallback(
    (value: unknown): string | null => {
      if (!kuMapping || value == null) return null
      const s = String(value).trim()
      return s ? (kuMapping[s] ?? kuMapping[String(Number(s))] ?? null) : null
    },
    [kuMapping]
  )

  const { columns, getRowHeight } = useItemsGridColumns({
    items,
    itemDataKeysFromApi,
    containerWidth,
    editingItemIds,
    hoveredRowId,
    setHoveredRowId,
    setReviewTooltip,
    handleCellChange,
    handleCheckboxUpdate,
    handleAddRow,
    handleDeleteRow,
    isItemLocked,
    getLockedBy,
    sessionId,
    getKuLabel,
    createItemPending: createItem.isPending,
    deleteItemPending: deleteItem.isPending,
    onOpenUnitPriceModal: setUnitPriceModalRow,
    onOpenAttachments: () => setAttachmentModalOpen(true),
    readOnly,
    pageRole: pageMetaData?.page_role ?? null,
  })

  // 행 편집 시작 (락 획득)
  const handleEdit = async (itemId: number) => {
    // 이미 편집 중이면 무시
    if (editingItemIds.has(itemId)) return
    
    // sessionId 확인
    if (!sessionId) {
      // SessionId is missing는 사용자에게 alert로 표시되므로 콘솔 로그 제거
      alert('セッションIDがありません。ページを再読み込みしてください。')
      return
    }
    
    // 다른 사용자가 락을 걸었는지 확인
    const isLocked = isItemLocked(itemId)
    const lockedBy = getLockedBy(itemId)
    const isLockedByMe = lockedBy === sessionId
    
    if (isLocked && !isLockedByMe) {
      alert(`編集中: ${lockedBy}`)
      return
    }
    
    try {
      // 백엔드에 락 획득 요청
      await acquireLock.mutateAsync({ itemId, sessionId })
      // 편집 모드 진입
      setEditingItemIds((prev) => {
        const next = new Set(prev)
        next.add(itemId)
        return next
      })
    } catch (error: any) {
      const errorMessage = error?.response?.data?.detail || error?.message || 'Unknown error'
      console.error('❌ [handleEdit] 락 획득 실패:', {
        itemId,
        errorMessage,
        status: error?.response?.status,
        sessionId: sessionId?.substring(0, 20) + '...'
      })
      
      // 세션 에러 감지 및 처리
      if (
        typeof errorMessage === 'string' && 
        (errorMessage.includes('Session expired') || 
         errorMessage.includes('세션') ||
         errorMessage.includes('Session not found') ||
         errorMessage.includes('Session expired or invalid'))
      ) {
        console.warn('⚠️ [세션 에러] 세션이 유효하지 않습니다. localStorage 정리')
        localStorage.removeItem('sessionId')
        alert('セッションが無効です。再度ログインしてください。')
        return
      }
      
      if (error?.response?.status === 409) {
        alert(`編集を開始できませんでした: ${errorMessage}`)
      } else if (error?.response?.status === 422) {
        alert('リクエストが無効です。ページを再読み込みしてください。')
      } else {
        alert('編集を開始できませんでした。他のユーザーが編集中の可能性があります。')
      }
    }
  }

  // 셀 더블클릭으로 해당 행 편집 모드 진입
  const handleCellDoubleClick = (args: any) => {
    if (readOnly) return
    const row: GridRow | undefined = args?.row
    if (!row) return

    const itemId = row.item_id
    if (typeof itemId !== 'number') return

    // 기존 편집 버튼과 동일한 로직 사용
    void handleEdit(itemId)
  }
  
  /**
   * 저장 및 락 해제: 현재 rowData를 저장한 후 락 해제
   * @param skipClearEditing true면 편집 해제는 호출자가 처리 (일괄 저장 시 사용)
   */
  const handleSaveAndUnlock = async (itemId: number, opts?: { skipClearEditing?: boolean }) => {
    // sessionId 확인
    if (!sessionId) {
      console.error('❌ [handleSaveAndUnlock] sessionId가 없습니다!')
      alert('セッションIDがありません。再度ログインしてください。')
      return
    }
    
    // 현재 rows 상태에서 해당 행 찾기
    const rowData = rows.find((row) => row.item_id === itemId)
    if (!rowData) {
      console.error('❌ [handleSaveAndUnlock] rowData를 찾을 수 없습니다:', itemId)
      alert('行データが見つかりません。')
      return
    }

    // 아이템 정보 찾기
    const updatedItem = items.find((i) => i.item_id === itemId)
    if (!updatedItem) {
      console.error('❌ [handleSaveAndUnlock] updatedItem을 찾을 수 없습니다:', itemId)
      alert('アイテムが見つかりません。')
      return
    }
    
    console.log('🔵 [handleSaveAndUnlock] 저장 시작:', {
      itemId,
      sessionId: sessionId.substring(0, 20) + '...',
      version: updatedItem.version
    })

    // item_data 추출 (공통·표시전용 필드 제외). タイプ null/빈값 → '条件'
    const itemData: any = {}
    Object.keys(rowData).forEach((key) => {
      if (
        key !== 'item_id' &&
        key !== 'item_order' &&
        key !== 'customer' &&
        key !== 'first_review_checked' &&
        key !== 'second_review_checked'
      ) {
        let val = rowData[key]
        if (key === 'タイプ' && (val == null || String(val).trim() === '')) val = '条件'
        itemData[key] = val
      }
    })

    try {
      // 변경사항 저장
      await updateItem.mutateAsync({
        itemId: updatedItem.item_id,
        request: {
          item_data: itemData,
          review_status: {
            first_review: {
              checked: rowData.first_review_checked || false,
            },
            second_review: {
              checked: rowData.second_review_checked || false,
            },
          },
          expected_version: updatedItem.version,
          session_id: sessionId,
        },
      })

      console.log('✅ [handleSaveAndUnlock] 저장 성공, 락 해제 시도')
      
      // 저장 성공 후 락 해제 (락이 이미 없어도 무시)
      try {
        await releaseLock.mutateAsync({ itemId, sessionId })
        console.log('✅ [handleSaveAndUnlock] 락 해제 성공')
      } catch (lockError: any) {
        // 락 해제 실패는 경고만 출력 (저장은 이미 성공했으므로 치명적이지 않음)
        const lockErrorMessage = lockError?.response?.data?.detail || lockError?.message || 'Unknown error'
        if (lockErrorMessage.includes('Lock not found') || lockErrorMessage.includes('already released')) {
          console.warn('⚠️ [handleSaveAndUnlock] 락이 이미 해제되었거나 없음 (무시):', lockErrorMessage)
        } else {
          console.error('⚠️ [handleSaveAndUnlock] 락 해제 실패 (저장은 성공):', lockErrorMessage)
        }
      }
      
      // 편집 모드 종료 (일괄 저장 시에는 호출자가 한 번에 제거)
      if (!opts?.skipClearEditing) {
        setEditingItemIds((prev) => {
          const next = new Set(prev)
          next.delete(itemId)
          return next
        })
      }
      // rows는 items가 업데이트되면 자동으로 초기화됨 (useEffect)
    } catch (error: any) {
      const errorMessage = error?.response?.data?.detail || error?.message || 'Unknown error'
      console.error('❌ [handleSaveAndUnlock] 저장 실패:', {
        itemId,
        errorMessage,
        status: error?.response?.status,
        sessionId: sessionId?.substring(0, 20) + '...',
        fullError: error
      })
      
      // 세션 에러 감지
      if (
        typeof errorMessage === 'string' && 
        (errorMessage.includes('Session expired') || 
         errorMessage.includes('세션') ||
         errorMessage.includes('Session not found') ||
         errorMessage.includes('Session expired or invalid'))
      ) {
        console.warn('⚠️ [세션 에러] 세션이 유효하지 않습니다. localStorage 정리')
        localStorage.removeItem('sessionId')
        alert('セッションが無効です。再度ログインしてください。')
        return
      }
      
      // 에러 메시지 표시
      if (error?.response?.status === 409) {
        alert(`保存に失敗しました: ${errorMessage}`)
      } else if (error?.response?.status === 422) {
        alert(`保存に失敗しました: リクエストが無効です`)
      } else {
        alert(`保存に失敗しました: ${errorMessage}`)
      }
    }
  }

  // 셀 변경 핸들러 (react-data-grid의 기본 편집 기능은 사용하지 않음)
  const onRowsChange = useCallback(
    (updatedRows: GridRow[]) => {
      // rows는 이미 setRows로 직접 업데이트되므로 여기서는 그대로 사용
      setRows(updatedRows)
    },
    []
  )

  // 복잡한 구조 필드 수집 (배지로 표시할 필드들) - hooks는 조건부 return 이전에 호출되어야 함
  // items의 복잡한 필드들
  const complexFields = useMemo(() => {
    if (!hasItems) return []
    
    const fields: Array<{ key: string; itemId: number; value: any }> = []
    items.forEach((item) => {
      if (item.item_data) {
        Object.keys(item.item_data).forEach((key) => {
          if (key !== 'customer') {
            const value = item.item_data[key]
            const isComplexType = value !== null && 
              value !== undefined && 
              (typeof value === 'object' || Array.isArray(value))
            
            if (isComplexType) {
              fields.push({ key, itemId: item.item_id, value })
            }
          }
        })
      }
    })
    return fields
  }, [items, hasItems])

  // page_meta의 최상위 키들을 배지로 표시 (cover 페이지용)
  const pageMetaFields = useMemo(() => {
    if (!pageMetaData?.page_meta) {
      console.log('🔵 [pageMetaFields] page_meta 없음:', pageMetaData)
      return []
    }
    
    const fields: Array<{ key: string; value: any }> = []
    const pageMeta = pageMetaData.page_meta
    
    console.log('🔵 [pageMetaFields] page_meta 구조:', {
      pageMeta,
      keys: Object.keys(pageMeta),
      keysLength: Object.keys(pageMeta).length,
    })
    
    Object.keys(pageMeta).forEach((key) => {
      const value = pageMeta[key]
      console.log(`🔵 [pageMetaFields] 키 확인: ${key}`, {
        value,
        type: typeof value,
        isObject: typeof value === 'object',
        isArray: Array.isArray(value),
        isNull: value === null,
        isUndefined: value === undefined,
      })
      
      // 최상위 키만 배지로 표시 (객체/배열인 경우)
      if (value !== null && value !== undefined && (typeof value === 'object' || Array.isArray(value))) {
        fields.push({ key, value })
        console.log(`✅ [pageMetaFields] 필드 추가: ${key}`)
      }
    })
    
    console.log('🔵 [pageMetaFields] 최종 필드:', fields)
    return fields
  }, [pageMetaData])

  // items가 비어있으면 그리드 숨김 (cover/summary 페이지 등)
  const isEmpty = !hasItems
  const isCoverPage = pageMetaData?.page_role === 'cover'
  // summary 페이지도 page_meta(totals, recipient 등) 배지를 표시
  const isSummaryPage = pageMetaData?.page_role === 'summary'
  const showPageMetaBadges = isCoverPage || isSummaryPage

  // 디버깅: cover/summary 페이지 및 page_meta 확인 - hooks는 조건부 return 이전에 호출되어야 함
  useEffect(() => {
    if (showPageMetaBadges) {
      console.log('🔵 [ItemsGridRdg] Cover/Summary 페이지 감지:', {
        isCoverPage,
        isSummaryPage,
        pageMetaData,
        pageMetaFields: pageMetaFields.length,
        isEmpty,
      })
    }
  }, [showPageMetaBadges, isCoverPage, isSummaryPage, pageMetaData, pageMetaFields.length, isEmpty])

  // 페이지 전환 또는 PDF 변경 시, 선택된 복잡 필드 상세 화면 초기화
  useEffect(() => {
    setSelectedComplexField(null)
  }, [pdfFilename, pageNumber])

  /** 편집 중인 모든 행을 병렬 저장 후 성공한 행만 한 번에 편집 해제 (저장 버튼 / Ctrl+S 공통) */
  const saveAllEditingRows = useCallback(async () => {
    const editingIds = Array.from(editingItemIdsRef.current.values()).filter(
      (id): id is number => typeof id === 'number'
    )
    if (editingIds.length === 0) return
    const results = await Promise.allSettled(
      editingIds.map((id) => handleSaveAndUnlock(id, { skipClearEditing: true }))
    )
    const succeeded = editingIds.filter((_, i) => results[i].status === 'fulfilled')
    if (succeeded.length > 0) {
      setEditingItemIds((prev) => {
        const next = new Set(prev)
        succeeded.forEach((id) => next.delete(id))
        return next
      })
    }
  }, [handleSaveAndUnlock])

  // Ctrl+S / Cmd+S 로 편집 중인 모든 행 저장
  useEffect(() => {
    if (typeof window === 'undefined') return

    const handleKeyDown = (event: KeyboardEvent) => {
      const isSaveShortcut =
        (event.ctrlKey || event.metaKey) &&
        (event.key === 's' || event.key === 'S')

      if (!isSaveShortcut) return

      event.preventDefault()

      const editingIds = Array.from(editingItemIdsRef.current.values())
      if (editingIds.length === 0) return

      void saveAllEditingRows()
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [saveAllEditingRows])

  // 부모에서 저장·일괄 체크 호출용 노출 (1회 fetch + 병렬 PATCH로 한 번에 처리)
  useImperativeHandle(ref, () => ({
    save() {
      void saveAllEditingRows()
    },
    async checkAllFirst() {
      const currentRows = rowsRef.current
      const updates = currentRows
        .filter((r) => !r.first_review_checked)
        .map((r) => ({ itemId: r.item_id, field: 'first_review_checked' as const, checked: true }))
      await bulkUpdateReviewStatus(updates)
    },
    async checkAllSecond() {
      const currentRows = rowsRef.current
      const updates = currentRows
        .filter((r) => !r.second_review_checked)
        .map((r) => ({ itemId: r.item_id, field: 'second_review_checked' as const, checked: true }))
      await bulkUpdateReviewStatus(updates)
    },
    async uncheckAllFirst() {
      const currentRows = rowsRef.current
      const updates = currentRows
        .filter((r) => r.first_review_checked)
        .map((r) => ({ itemId: r.item_id, field: 'first_review_checked' as const, checked: false }))
      await bulkUpdateReviewStatus(updates)
    },
    async uncheckAllSecond() {
      const currentRows = rowsRef.current
      const updates = currentRows
        .filter((r) => r.second_review_checked)
        .map((r) => ({ itemId: r.item_id, field: 'second_review_checked' as const, checked: false }))
      await bulkUpdateReviewStatus(updates)
    },
  }), [saveAllEditingRows, bulkUpdateReviewStatus])

  const handleUnitPriceSelect = useCallback(
    async (match: { 제품코드?: string | number; 시키리?: number; 본부장?: number }) => {
      if (!unitPriceModalRow || !sessionId || !pdfFilename || pageNumber == null) return
      const itemId = unitPriceModalRow.item_id
      let updatedRow: GridRow = {
        ...unitPriceModalRow,
        仕切: match.시키리 ?? unitPriceModalRow['仕切'],
        本部長: match.본부장 ?? unitPriceModalRow['本部長'],
        商品コード: match.제품코드 != null ? String(match.제품코드) : unitPriceModalRow['商品コード'],
      }
      // FINET 01 + 数量単位=CS → 仕切・本部長 *= 入数 (매핑 모달에서 단가 적용 시에도 동일 계산)
      if (data?.form_type === '01' && data?.upload_channel === 'finet' && String(unitPriceModalRow['数量単位'] ?? '').trim() === 'CS') {
        const irisu = parseCellNum(unitPriceModalRow['入数'])
        if (irisu != null && irisu > 0) {
          const shikiri = parseCellNum(updatedRow['仕切'])
          const honbu = parseCellNum(updatedRow['本部長'])
          if (shikiri != null) updatedRow = { ...updatedRow, 仕切: Math.round(shikiri * irisu * 100) / 100 }
          if (honbu != null) updatedRow = { ...updatedRow, 本部長: Math.round(honbu * irisu * 100) / 100 }
        }
      }
      setRows((prev) =>
        prev.map((r) => (r.item_id === itemId ? updatedRow : r))
      )
      setUnitPriceModalRow(null)

      const item = items.find((i) => i.item_id === itemId)
      if (!item) return
      const itemData: Record<string, unknown> = {}
      Object.keys(updatedRow).forEach((key) => {
        if (
          key !== 'item_id' &&
          key !== 'item_order' &&
          key !== 'customer' &&
          key !== 'first_review_checked' &&
          key !== 'second_review_checked'
        ) {
          let val = updatedRow[key]
          if (key === 'タイプ' && (val == null || String(val).trim() === '')) val = '条件'
          itemData[key] = val
        }
      })
      try {
        await updateItem.mutateAsync({
          itemId,
          request: {
            item_data: itemData,
            review_status: {
              first_review: { checked: Boolean(updatedRow.first_review_checked) },
              second_review: { checked: Boolean(updatedRow.second_review_checked) },
            },
            expected_version: item.version,
            session_id: sessionId,
          },
        })
      } catch (err: unknown) {
        const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? (err as Error)?.message
        console.error('❌ [단가 적용 저장 실패]', msg)
        alert(`保存に失敗しました: ${msg}`)
      }
    },
    [unitPriceModalRow, sessionId, pdfFilename, pageNumber, items, updateItem, data?.form_type, data?.upload_channel]
  )

  /** 동일 得意先コード or 得意先인 행을 그룹 키로 식별 (페이지 내 일괄 적용용) */
  const getRetailGroupKey = useCallback((r: GridRow): string => {
    const code = r['得意先コード'] != null ? String(r['得意先コード']).trim() : ''
    if (code) return `code:${code}`
    const name = String(r['得意先'] ?? r['得意先名'] ?? r['customer'] ?? '').trim()
    return `name:${name}`
  }, [])

  const handleRetailSelect = useCallback(
    (match: { 판매처코드: string; 소매처코드: string }) => {
      if (!unitPriceModalRow) return
      const groupKey = getRetailGroupKey(unitPriceModalRow)
      setRows((prev) =>
        prev.map((r) =>
          getRetailGroupKey(r) === groupKey
            ? { ...r, 受注先コード: match.판매처코드, 小売先コード: match.소매처코드 }
            : r
        )
      )
      setUnitPriceModalRow(null)
    },
    [unitPriceModalRow, getRetailGroupKey]
  )

  if (isLoading || pageMetaLoading) {
    return <div className="grid-loading">読み込み中...</div>
  }

  if (error) {
    return <div className="grid-error">エラー: {error instanceof Error ? error.message : 'Unknown error'}</div>
  }

  // page_meta 에러는 경고만 표시 (필수는 아님)
  if (pageMetaError) {
    console.warn('⚠️ [ItemsGridRdg] page_meta 조회 에러:', pageMetaError)
  }

  return (
    <div className="items-grid-rdg">
      {/* 매핑 모달: 単価 | 代表スーパー 탭 */}
      <UnitPriceMatchModal
        open={!!unitPriceModalRow}
        onClose={() => setUnitPriceModalRow(null)}
        row={unitPriceModalRow}
        onSelectUnitPrice={handleUnitPriceSelect}
        onSelectRetail={handleRetailSelect}
      />
      <AttachmentModal
        open={attachmentModalOpen}
        onClose={() => setAttachmentModalOpen(false)}
        pdfFilename={pdfFilename}
      />
      {/* 복잡한 구조 필드 배지 영역 (좌측) */}
      {/* cover/summary 페이지인 경우 page_meta의 최상위 키들을 배지로 표시 (totals, recipient 등) */}
      {showPageMetaBadges && pageMetaFields.length > 0 && (
        <div className="complex-fields-badges">
          {pageMetaFields.map((field) => (
            <button
              key={field.key}
              className="complex-field-badge"
              onClick={() => {
                setSelectedComplexField({ key: field.key, value: field.value, itemId: 0 })
              }}
              title={`${field.key}をクリックして詳細を表示`}
            >
              {field.key}
            </button>
          ))}
        </div>
      )}
      
      {/* items의 복잡한 필드 배지 (detail 페이지 등) */}
      {!isCoverPage && complexFields.length > 0 && (
        <div className="complex-fields-badges">
          {Array.from(new Set(complexFields.map(f => f.key))).map((key) => {
            const firstField = complexFields.find(f => f.key === key)
            return (
              <button
                key={key}
                className="complex-field-badge"
                onClick={() => {
                  if (firstField) {
                    setSelectedComplexField(firstField)
                  }
                }}
                title={`${key}をクリックして詳細を表示`}
              >
                {key}
              </button>
            )
          })}
        </div>
      )}
      
      {/* React Data Grid - items가 있을 때만 표시 */}
      {!isEmpty && (
        <div className="rdg-container" ref={containerRef}>
          <DataGrid
            ref={gridRef}
            columns={columns}
            rows={rows}
            rowHeight={getRowHeight}
            onRowsChange={onRowsChange}
            onCellDoubleClick={handleCellDoubleClick}
            rowKeyGetter={(row: GridRow) => row.item_id} // 행 고유 키 지정
            rowClass={(row: GridRow) => {
              // 편집 모드인 행에 클래스 추가
              let classes = editingItemIds.has(row.item_id) ? 'row-editing' : ''
              // 체크박스가 체크된 행에 클래스 추가 (1次 또는 2次 중 하나라도 체크되면)
              if (row.first_review_checked || row.second_review_checked) {
                classes = classes ? `${classes} row-checked` : 'row-checked'
              }
              // NET < 本部長 이면 행 전체 노란색 음영 (条件金額: 単価|条件|対象数量又は金額 중 첫 유효값)
              const condNum = CONDITION_AMOUNT_KEYS.map((k) => parseCellNum(row[k])).find((n) => n != null) ?? null
              const shikiriNum = parseCellNum(row['仕切'])
              const honbuchoNum = parseCellNum(row['本部長'])
              if (condNum != null && shikiriNum != null && honbuchoNum != null) {
                const net = shikiriNum - condNum
                if (net < honbuchoNum) {
                  classes = classes ? `${classes} row-net-warning` : 'row-net-warning'
                }
              }
              return classes.trim()
            }}
            defaultColumnOptions={{
              resizable: true,
              sortable: false,
            }}
            className="rdg-theme"
            style={{ width: '100%', minWidth: '100%', height: '100%' }}
          />
        </div>
      )}
      
      {/* items가 비어있고 page_meta 배지도 없을 때만 메시지 표시 */}
      {isEmpty && !showPageMetaBadges && (
        <div className="grid-empty-message">
          <p>このページにはアイテムがありません。</p>
        </div>
      )}

      {selectedComplexField && (
        <ComplexFieldDetail
          keyName={selectedComplexField.key}
          value={selectedComplexField.value}
          onClose={() => setSelectedComplexField(null)}
        />
      )}

      {/* 1次/2次 체크 증빙 툴팁 (마우스 오버 시 바로 표시) */}
      {typeof document !== 'undefined' && reviewTooltip && createPortal(
        <div
          className="items-grid-review-tooltip"
          style={{
            position: 'fixed',
            left: reviewTooltip.x,
            top: reviewTooltip.y - 4,
            transform: 'translate(-50%, -100%)',
            zIndex: 99999,
            pointerEvents: 'none',
          }}
        >
          {reviewTooltip.text}
        </div>,
        document.body
      )}
    </div>
  )
})
