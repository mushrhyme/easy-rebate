/**
 * React Data Grid 아이템 테이블 컴포넌트
 * 셀 편집 중 락 기능 포함
 */
import { useMemo, useState, useCallback, useRef, useEffect, forwardRef, useImperativeHandle } from 'react'
import { createPortal } from 'react-dom'
import { DataGrid, type Column, type DataGridHandle } from 'react-data-grid'
import 'react-data-grid/lib/styles.css'
import { useQueryClient } from '@tanstack/react-query'
import { useItems, useUpdateItem, useCreateItem, useDeleteItem, useAcquireLock, useReleaseLock, usePageMeta } from '@/hooks/useItems'
import { useItemLocks } from '@/hooks/useItemLocks'
import { itemsApi } from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import type { ReviewStatus } from '@/types'
import './ItemsGridRdg.css'

interface ItemsGridRdgProps {
  pdfFilename: string
  pageNumber: number
  formType: string | null
}

export interface ItemsGridRdgHandle {
  /** Ctrl+S와 동일: 편집 중인 첫 행 저장 후 락 해제 */
  save: () => void
}

interface GridRow {
  item_id: number
  item_order: number
  first_review_checked: boolean
  second_review_checked: boolean
  [key: string]: string | number | boolean | null | undefined // item_data 필드들 (예: 商品名)
}

export const ItemsGridRdg = forwardRef<ItemsGridRdgHandle, ItemsGridRdgProps>(function ItemsGridRdg({
  pdfFilename,
  pageNumber,
  formType,
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

  // 행 데이터 변환 (초기 데이터)
  const initialRows = useMemo<GridRow[]>(() => {
    const gridRows = items.map((item) => {
      const row: GridRow = {
        item_id: item.item_id,
        item_order: item.item_order,
        first_review_checked: item.review_status?.first_review?.checked || false,
        second_review_checked: item.review_status?.second_review?.checked || false,
      }

      if (item.item_data) {
        Object.keys(item.item_data).forEach((key) => {
          row[key] = item.item_data[key]
        })
      }

      return row
    })
    return gridRows
  }, [items])

  // rows 상태 관리 (편집 중 변경사항 추적)
  const [rows, setRows] = useState<GridRow[]>(initialRows)
  const remoteUpdatedItemsRef = useRef<Set<number>>(new Set()) // WebSocket으로 업데이트된 아이템 ID 추적
  const remoteUpdatedValuesRef = useRef<Map<number, { first: boolean; second: boolean }>>(new Map()) // WebSocket으로 받은 체크박스 값 저장
  const prevItemsLengthRef = useRef(items.length) // 이전 items 길이 저장
  const prevItemIdsRef = useRef<string>(items.map(i => i.item_id).join(',')) // 이전 item_id 목록 저장
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
      }

      if (item.item_data) {
        Object.keys(item.item_data).forEach((key) => {
          row[key] = item.item_data[key]
        })
      }

      return row
    })
    
    setRows((prevRows) => {
      // 새로운 initialRows와 기존 rows를 병합
      const newRows = newInitialRows.map((newRow) => {
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

  // 검토 탭 컬럼 순서: API의 item_data_keys(RAG key_order) 우선 사용, 없으면 첫 행 item_data 키 순서
  const itemDataKeysFromApi = data?.item_data_keys && data.item_data_keys.length > 0 ? data.item_data_keys : null

  // 컬럼 정의 + 행 높이 자동 계산 함수
  const { columns, getRowHeight } = useMemo<{
    columns: Column<GridRow>[]
    getRowHeight: (row: GridRow) => number
  }>(() => {
    // items가 비어있어도 기본 컬럼은 표시

    // items가 비어있을 때 기본 컬럼만 사용
    let itemDataKeys: string[] = []
    let orderedKeys: string[] = []
    
    if (hasItems) {
      const firstItem = items[0]
      // DB에 실제로 존재하는 키만 수집 (없는 컬럼 표시 방지)
      const keysInDb = new Set<string>()
      items.forEach((item) => {
        if (item.item_data) {
          Object.keys(item.item_data).forEach((key) => keysInDb.add(key))
        }
      })

      // 정렬 순서: API item_data_keys(RAG key_order) 우선, 없으면 첫 행 키 순서
      if (itemDataKeysFromApi) {
        itemDataKeys = [...itemDataKeysFromApi]
      } else {
        itemDataKeys = firstItem.item_data ? Object.keys(firstItem.item_data) : []
      }

      // 키 이름 정규화:
      // - LLM / RAG 설정에서는 '得意先名' 으로 나오는데,
      //   DB에는 '得意先' 으로 저장된 경우가 있어 순서가 밀리는 문제를 방지
      const normalizeKey = (key: string): string => {
        // customer 계열 필드: DB에 존재하는 쪽 이름으로 맞춘다
        if ((key === '得意先名' || key === '得意先') && keysInDb.has('得意先')) {
          return '得意先'
        }
        if ((key === '得意先名' || key === '得意先') && keysInDb.has('得意先名')) {
          return '得意先名'
        }
        return key
      }

      const normalizedItemDataKeys = itemDataKeys.map(normalizeKey)

      // key_order 순서를 유지하되, DB에 있는 키만 표시
      const orderedFromApi = normalizedItemDataKeys.filter((key) => keysInDb.has(key))
      const extraKeys = Array.from(keysInDb).filter((key) => !normalizedItemDataKeys.includes(key))
      orderedKeys = [...orderedFromApi, ...extraKeys]

      // 디버깅용: 참조 문서의 전체 key_order와 실제 컬럼 순서를 모두 출력
      console.log('🔵 [ItemsGridRdg] itemDataKeysFromApi(API에서 받은 전체 key_order)=', itemDataKeysFromApi)
      console.log('🔵 [ItemsGridRdg] normalizedItemDataKeys(정규화된 key_order)=', normalizedItemDataKeys)
      console.log('🔵 [ItemsGridRdg] keysInDb(DB에 실제 존재하는 키 전체)=', Array.from(keysInDb))
      console.log('🔵 [ItemsGridRdg] orderedFromApi(API 순서를 따른 실제 사용 키)=', orderedFromApi)
      console.log('🔵 [ItemsGridRdg] extraKeys(API에는 없지만 DB에만 있는 키)=', extraKeys)
      console.log('🔵 [ItemsGridRdg] orderedKeys(그리드에 표시되는 최종 컬럼 순서 전체)=', orderedKeys)
    }

    // 컬럼 너비: 컬럼명 길이 vs 데이터 최대 길이 중 큰 쪽 기준 (일본어 헤더가 한 줄에 들어가도록 글자당 여유)
    const CHAR_PX = 11   // 일본어·한글 글자당 픽셀 (컬럼명 한 줄 표시용)
    const PADDING_PX = 18
    const COL_WIDTH_MIN = 78  // 4글자 컬럼명(数量単位 등) 한 줄 최소
    const COL_WIDTH_MAX = 280

    const calculateColumnWidth = (key: string, name: string): number => {
      const headerWidth = name.length * CHAR_PX + PADDING_PX
      let maxDataLength = 0
      if (hasItems) {
        items.forEach((item) => {
          const value = item.item_data?.[key]
          if (value != null) {
            const len = String(value).length
            if (len > maxDataLength) maxDataLength = len
          }
        })
      }
      const dataWidth = maxDataLength * CHAR_PX + PADDING_PX
      const rawWidth = Math.max(headerWidth, dataWidth, COL_WIDTH_MIN)
      return Math.min(rawWidth, COL_WIDTH_MAX)
    }

    const cols: Column<GridRow>[] = [
      {
        key: 'item_order',
        name: '行',
        width: 34,
        minWidth: 34,
        frozen: true,
        resizable: false,
        renderCell: ({ row }) => (
          <div className="rdg-cell-no" title={`No. ${row.item_order}`}>
            {row.item_order}
          </div>
        ),
      },
    ]

    // items가 있을 때만 편집 및 검토 컬럼 추가
    if (hasItems) {
      // 통합 액션 컬럼 (편집/추가/삭제) - ヘッダ短縮で幅を最小化
      cols.push({
        key: 'actions',
        name: '編',
        width: 34,
        minWidth: 34,
        frozen: true,
        resizable: false,
        renderCell: ({ row }) => {
          const itemId = row.item_id
          const isEditing = editingItemIds.has(itemId)
          const isLocked = isItemLocked(itemId)
          const lockedBy = getLockedBy(itemId)
          const isLockedByMe = lockedBy === sessionId
          const isLockedByOthers = isLocked && !isLockedByMe
          const isHovered = hoveredRowId === itemId

          return (
            <ActionCellWithMenu
              isHovered={isHovered}
              isEditing={isEditing}
              isLockedByOthers={isLockedByOthers}
              lockedBy={lockedBy}
              onMouseEnter={() => setHoveredRowId(itemId)}
              onMouseLeave={() => setHoveredRowId(null)}
              onAdd={() => handleAddRow(itemId)}
              onDelete={() => handleDeleteRow(itemId)}
              createItemPending={createItem.isPending}
              deleteItemPending={deleteItem.isPending}
            />
          )
        },
      })

      cols.push({
        key: 'first_review_checked',
        name: '1次',
        width: 40,
        minWidth: 40,
        frozen: true,
        resizable: false,
        editable: false, // 그리드 편집 기능 비활성화
        renderCell: ({ row }) => {
          const isChecked = row.first_review_checked || false
          return (
            <div 
              style={{ 
                display: 'flex', 
                justifyContent: 'center', 
                alignItems: 'center', 
                height: '100%',
                width: '100%'
              }}
            >
              <button
                type="button"
                onClick={(e) => {
                  console.log('🔵 [체크박스] 1次 버튼 클릭:', { item_id: row.item_id, 현재상태: isChecked, 변경될상태: !isChecked })
                  e.stopPropagation() // 그리드 셀 클릭 이벤트 방지
                  e.preventDefault() // 기본 동작 방지
                  // 버튼 클릭 시 바로 저장 (편집 모드와 무관)
                  handleCheckboxUpdate(row.item_id, 'first_review_checked', !isChecked)
                }}
                onMouseDown={(e) => {
                  e.stopPropagation() // 그리드 셀 선택 방지
                }}
                style={{ 
                  cursor: 'pointer',
                  width: '20px',
                  height: '20px',
                  border: '2px solid',
                  borderColor: isChecked ? '#667eea' : '#999',
                  borderRadius: '3px',
                  backgroundColor: isChecked ? '#667eea' : '#fff',
                  color: isChecked ? '#fff' : 'transparent',
                  fontSize: '14px',
                  fontWeight: 'bold',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  padding: 0,
                  margin: 0,
                  lineHeight: 1,
                  transition: 'all 0.2s ease'
                }}
                title={isChecked ? '1次レビュー完了' : '1次レビュー未完了'}
              >
                {isChecked ? '✓' : ''}
              </button>
            </div>
          )
        },
      })
      
      cols.push({
        key: 'second_review_checked',
        name: '2次',
        width: 40,
        minWidth: 40,
        frozen: true,
        resizable: false,
        editable: false, // 그리드 편집 기능 비활성화
        renderCell: ({ row }) => {
          const isChecked = row.second_review_checked || false
          return (
            <div 
              style={{ 
                display: 'flex', 
                justifyContent: 'center', 
                alignItems: 'center', 
                height: '100%',
                width: '100%'
              }}
            >
              <button
                type="button"
                onClick={(e) => {
                  console.log('🔵 [체크박스] 2次 버튼 클릭:', { item_id: row.item_id, 현재상태: isChecked, 변경될상태: !isChecked })
                  e.stopPropagation() // 그리드 셀 클릭 이벤트 방지
                  e.preventDefault() // 기본 동작 방지
                  // 버튼 클릭 시 바로 저장 (편집 모드와 무관)
                  handleCheckboxUpdate(row.item_id, 'second_review_checked', !isChecked)
                }}
                onMouseDown={(e) => {
                  e.stopPropagation() // 그리드 셀 선택 방지
                }}
                style={{ 
                  cursor: 'pointer',
                  width: '20px',
                  height: '20px',
                  border: '2px solid',
                  borderColor: isChecked ? '#667eea' : '#999',
                  borderRadius: '3px',
                  backgroundColor: isChecked ? '#667eea' : '#fff',
                  color: isChecked ? '#fff' : 'transparent',
                  fontSize: '14px',
                  fontWeight: 'bold',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  padding: 0,
                  margin: 0,
                  lineHeight: 1,
                  transition: 'all 0.2s ease'
                }}
                title={isChecked ? '2次レビュー完了' : '2次レビュー未完了'}
              >
                {isChecked ? '✓' : ''}
              </button>
            </div>
          )
        },
      })
      
      // タイプ 컬럼 추가 (2차 컬럼 옆에 고정)
      cols.push({
        key: 'タイプ',
        name: 'タイプ',
        width: 100,
        minWidth: 100,
        frozen: true,
        resizable: false,
        editable: false,
        renderCell: ({ row }) => {
          const currentValue = row['タイプ'] || null
          const isEditing = editingItemIds.has(row.item_id)
          
          if (isEditing) {
            const selectValue =
              typeof currentValue === 'string' || typeof currentValue === 'number'
                ? currentValue
                : ''
            return (
              <select
                value={selectValue}
                onChange={(e) => {
                  const newValue = e.target.value === '' ? null : e.target.value
                  handleCellChange(row.item_id, 'タイプ', newValue)
                }}
                style={{ 
                  width: '100%', 
                  border: '1px solid #ccc', 
                  padding: '4px',
                  borderRadius: '4px',
                  fontSize: '13px'
                }}
                onClick={(e) => e.stopPropagation()}
              >
                <option value="">Null</option>
                <option value="条件">条件</option>
                <option value="販促費8%">販促費8%</option>
                <option value="販促費10%">販促費10%</option>
                <option value="CF8%">CF8%</option>
                <option value="CF10%">CF10%</option>
                <option value="非課税">非課税</option>
              </select>
            )
          }
          return <span>{currentValue || 'Null'}</span>
        },
      })
    }

    // item_data 필드들을 DB 순서대로 추가 (자동 너비 계산)
    // items가 있을 때만 item_data 필드 추가
    if (hasItems) {
      orderedKeys.forEach((key) => {
        // customer, タイプ는 별도 처리. 商品名 등은 item_data 키로 그대로 표시
        if (key !== 'customer' && key !== 'タイプ') {
          // 복잡한 구조(객체/배열) 필드는 그리드에 표시하지 않음 (배지로 표시)
          // 첫 번째 아이템의 값으로 타입 확인
          const firstValue = items[0]?.item_data?.[key]
          const isComplexType = firstValue !== null && 
            firstValue !== undefined && 
            (typeof firstValue === 'object' || Array.isArray(firstValue))
          
          if (isComplexType) {
            // 복잡한 구조는 그리드에 표시하지 않음 (배지로 표시)
            return
          }
          
          const dataBasedWidth = calculateColumnWidth(key, key)
          cols.push({
            key,
            name: key,
            width: dataBasedWidth,
            minWidth: Math.max(dataBasedWidth, COL_WIDTH_MIN),
            resizable: true,
            renderCell: ({ row }) => {
              const isEditing = editingItemIds.has(row.item_id)
              const value = row[key] ?? ''
              if (isEditing) {
                return (
                  <input
                    type="text"
                    value={String(value)}
                    onChange={(e) => handleCellChange(row.item_id, key, e.target.value)}
                    style={{ width: '100%', border: 'none', padding: '4px' }}
                    onClick={(e) => e.stopPropagation()}
                  />
                )
              }
              return <span>{String(value)}</span>
            },
          })
        }
      })
    }

    // 공통 필드 추가 (customer는 별도 컬럼, 商品名 등은 item_data 키로 표시됨)
    // 하지만 별도 컬럼으로도 표시할 수 있음 (필요시)
    // 현재는 item_data에 있는 필드만 사용

    // 컬럼 너비: 데이터/헤더 길이 기준 유지 (minWidth 보장, 가로 스크롤로 전체 확인)
    const getColWidth = (col: Column<GridRow>): number => {
      const w = col.width
      if (typeof w === 'number') return w
      if (typeof w === 'string') return parseInt(w, 10) || COL_WIDTH_MIN
      return COL_WIDTH_MIN
    }
    const adjustedCols: Column<GridRow>[] = cols.map((col) => {
      const w = getColWidth(col)
      const existingMin = col.minWidth
      const minW = existingMin != null ? existingMin : (col.frozen ? w : Math.max(w, COL_WIDTH_MIN))
      return { ...col, width: w, minWidth: minW }
    })

    // 전체 컬럼 너비가 컨테이너보다 좁으면,
    // 고정(frozen) 컬럼은 그대로 두고, 나머지 컬럼들을 스케일업해서 오른쪽 여백을 최대한 제거
    const totalWidth = adjustedCols.reduce((sum, col) => sum + getColWidth(col), 0)
    const availableWidth = containerWidth || totalWidth
    let scaledCols: Column<GridRow>[] | null = null

    if (availableWidth > 0 && totalWidth < availableWidth) {
      const frozenCols = adjustedCols.filter((col) => col.frozen)
      const flexibleCols = adjustedCols.filter((col) => !col.frozen)

      const frozenWidth = frozenCols.reduce((sum, col) => sum + getColWidth(col), 0)
      const flexibleWidth = flexibleCols.reduce((sum, col) => sum + getColWidth(col), 0)

      const targetFlexibleWidth = Math.max(flexibleWidth, availableWidth - frozenWidth)

      if (flexibleWidth > 0 && targetFlexibleWidth > flexibleWidth) {
        const scale = targetFlexibleWidth / flexibleWidth
        let remaining = availableWidth - frozenWidth

        scaledCols = adjustedCols.map((col, idx) => {
          if (col.frozen) {
            return col
          }
          const w = getColWidth(col)
          let newWidth = Math.max(col.minWidth ?? COL_WIDTH_MIN, Math.floor(w * scale))

          // 마지막 flexible 컬럼에 남은 여유를 몰아서 줘서 합이 딱 맞도록 조정
          const isLastFlexible = adjustedCols
            .slice(idx + 1)
            .every((nextCol) => nextCol.frozen)

          if (isLastFlexible) {
            newWidth = Math.max(newWidth, remaining)
          }

          remaining -= newWidth
          return { ...col, width: newWidth }
        })
      }
    }

    const finalCols = scaledCols ?? adjustedCols

    // 행 높이 자동 계산: 줄바꿈 가능 컬럼(商品名, 条件備考 등) 너비로 필요한 줄 수 추정 → 잘림 방지
    const WIDE_KEYS = new Set(['得意先', '得意先名', '商品名', '備考', '条件備考'])
    const wrapColumnWidths: Record<string, number> = {}
    finalCols.forEach((col) => {
      if (WIDE_KEYS.has(col.key)) wrapColumnWidths[col.key] = getColWidth(col)
    })
    // 일본어·한글은 글자당 폭이 커서 PX_PER_CHAR를 크게 잡아 한 줄당 글자 수를 적게 → 줄 수를 넉넉히 추정
    const PX_PER_CHAR = 16
    const LINE_HEIGHT_PX = 22 // line-height + 여유 (폰트에 따라 잘림 방지)
    const CELL_PADDING_V = 12
    const ROW_HEIGHT_BUFFER = 8 // 세로 잘림 방지
    const MIN_ROW_HEIGHT = 36

    const getRowHeight = (row: GridRow): number => {
      let maxLines = 1
      for (const [key, width] of Object.entries(wrapColumnWidths)) {
        const val = row[key]
        if (val == null) continue
        const str = String(val)
        const charsPerLine = Math.max(1, Math.floor(width / PX_PER_CHAR))
        const lines = Math.ceil(str.length / charsPerLine)
        if (lines > maxLines) maxLines = lines
      }
      const contentHeight = CELL_PADDING_V + maxLines * LINE_HEIGHT_PX + ROW_HEIGHT_BUFFER
      return Math.max(MIN_ROW_HEIGHT, contentHeight)
    }

    return { columns: finalCols, getRowHeight }
  }, [items, itemDataKeysFromApi, editingItemIds, handleCellChange, handleCheckboxUpdate, containerWidth, isItemLocked, getLockedBy, sessionId])


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
    const row: GridRow | undefined = args?.row
    if (!row) return

    const itemId = row.item_id
    if (typeof itemId !== 'number') return

    // 기존 편집 버튼과 동일한 로직 사용
    void handleEdit(itemId)
  }
  
  /**
   * 저장 및 락 해제: 현재 rowData를 저장한 후 락 해제
   */
  const handleSaveAndUnlock = async (itemId: number) => {
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

    // item_data 추출 (공통 필드 제외)
    const itemData: any = {}
    Object.keys(rowData).forEach((key) => {
      if (
        key !== 'item_id' &&
        key !== 'item_order' &&
        key !== 'customer' &&
        key !== 'first_review_checked' &&
        key !== 'second_review_checked'
      ) {
        itemData[key] = rowData[key]
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
      
      // 편집 모드 종료 (저장 성공했으므로)
      setEditingItemIds((prev) => {
        const next = new Set(prev)
        next.delete(itemId)
        return next
      })
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

  // 행 추가 핸들러 (맨 아래에 추가)
  const handleAddRow = useCallback(async (afterItemId?: number) => {
    if (!pdfFilename || !pageNumber) return

    try {
      // 빈 행 데이터로 새 아이템 생성
      const emptyItemData: Record<string, any> = {}

      // 기존 아이템들의 필드를 기반으로 빈 값들 추가
      if (items.length > 0) {
        const firstItem = items[0]
        if (firstItem.item_data) {
          Object.keys(firstItem.item_data).forEach(key => {
            const value = firstItem.item_data[key]
            // 기본값 설정
            if (typeof value === 'string') {
              emptyItemData[key] = ''
            } else if (typeof value === 'number') {
              emptyItemData[key] = 0
            } else if (typeof value === 'boolean') {
              emptyItemData[key] = false
            } else {
              emptyItemData[key] = null
            }
          })
        }
      }

      await createItem.mutateAsync({
        itemData: emptyItemData,
        customer: '',
        afterItemId: afterItemId,
      })

    } catch (error: any) {
      console.error('❌ [handleAddRow] 행 추가 실패:', error)
      const errorMessage = error?.response?.data?.detail || error?.message || '행 추가에 실패했습니다'
      console.error('❌ [handleAddRow] 에러 상세:', {
        status: error?.response?.status,
        detail: error?.response?.data?.detail,
        fullError: error,
      })
      alert(`행 추가에 실패했습니다: ${errorMessage}`)
    }
  }, [pdfFilename, pageNumber, items, createItem])

  // 행 삭제 핸들러
  const handleDeleteRow = useCallback(async (itemId: number) => {
    console.log('🔵 [handleDeleteRow] 시작:', { itemId, type: typeof itemId })
    
    // 현재 행 데이터 확인
    const currentRow = rows.find(r => r.item_id === itemId)
    console.log('🔵 [handleDeleteRow] 현재 행 데이터:', { currentRow, allRows: rows.map(r => ({ item_id: r.item_id, item_order: r.item_order })) })
    
    if (!confirm('정말로 이 행을 삭제하시겠습니까?')) return

    try {
      console.log('🔵 [handleDeleteRow] deleteItem.mutateAsync 호출:', itemId)
      await deleteItem.mutateAsync(itemId)
      console.log('✅ [handleDeleteRow] 삭제 성공')
    } catch (error) {
      console.error('❌ [handleDeleteRow] 행 삭제 실패:', error)
      alert('행 삭제에 실패했습니다')
    }
  }, [deleteItem, rows])

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

  // 중첩 객체를 flatten하는 함수 - hooks는 조건부 return 이전에 호출되어야 함
  const flattenObject = useCallback((obj: any, prefix = ''): Array<{ key: string; value: any }> => {
    const result: Array<{ key: string; value: any }> = []
    
    if (obj === null || obj === undefined) {
      return [{ key: prefix || 'null', value: 'null' }]
    }
    
    if (Array.isArray(obj)) {
      obj.forEach((item, index) => {
        if (typeof item === 'object' && item !== null) {
          result.push(...flattenObject(item, prefix ? `${prefix}[${index}]` : `[${index}]`))
        } else {
          result.push({ key: prefix ? `${prefix}[${index}]` : `[${index}]`, value: String(item) })
        }
      })
    } else if (typeof obj === 'object') {
      Object.keys(obj).forEach((key) => {
        const newKey = prefix ? `${prefix}.${key}` : key
        const value = obj[key]
        
        if (value === null || value === undefined) {
          result.push({ key: newKey, value: 'null' })
        } else if (typeof value === 'object' || Array.isArray(value)) {
          result.push(...flattenObject(value, newKey))
        } else {
          result.push({ key: newKey, value: String(value) })
        }
      })
    } else {
      result.push({ key: prefix || 'value', value: String(obj) })
    }
    
    return result
  }, [])

  // items가 비어있으면 그리드 숨김 (cover 페이지 등)
  const isEmpty = !hasItems
  const isCoverPage = pageMetaData?.page_role === 'cover'
  
  // 디버깅: cover 페이지 및 page_meta 확인 - hooks는 조건부 return 이전에 호출되어야 함
  useEffect(() => {
    if (isCoverPage) {
      console.log('🔵 [ItemsGridRdg] Cover 페이지 감지:', {
        isCoverPage,
        pageMetaData,
        pageMetaFields: pageMetaFields.length,
        isEmpty,
      })
    }
  }, [isCoverPage, pageMetaData, pageMetaFields.length, isEmpty])

  // 페이지 전환 또는 PDF 변경 시, 선택된 복잡 필드 상세 화면 초기화
  useEffect(() => {
    setSelectedComplexField(null)
  }, [pdfFilename, pageNumber])

  // Ctrl+S / Cmd+S 로 현재 편집 중인 행 저장
  useEffect(() => {
    if (typeof window === 'undefined') return

    const handleKeyDown = (event: KeyboardEvent) => {
      const isSaveShortcut =
        (event.ctrlKey || event.metaKey) &&
        (event.key === 's' || event.key === 'S')

      if (!isSaveShortcut) return

      // 브라우저 기본 저장 단축키 막기
      event.preventDefault()

      const editingIds = Array.from(editingItemIdsRef.current.values())
      if (editingIds.length === 0) return

      const firstEditingId = editingIds[0]
      if (typeof firstEditingId === 'number') {
        void handleSaveAndUnlock(firstEditingId)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [handleSaveAndUnlock])

  // 부모에서 저장 버튼 등으로 호출할 수 있도록 노출 (Ctrl+S와 동일 동작)
  useImperativeHandle(ref, () => ({
    save() {
      const editingIds = Array.from(editingItemIdsRef.current.values())
      if (editingIds.length === 0) return
      const firstEditingId = editingIds[0]
      if (typeof firstEditingId === 'number') {
        void handleSaveAndUnlock(firstEditingId)
      }
    },
  }), [handleSaveAndUnlock])

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
      {/* 복잡한 구조 필드 배지 영역 (좌측) */}
      {/* cover 페이지인 경우 page_meta의 최상위 키들을 배지로 표시 */}
      {isCoverPage && pageMetaFields.length > 0 && (
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
      
      {/* items가 비어있고 cover 페이지도 아닐 때 메시지 표시 */}
      {isEmpty && !isCoverPage && (
        <div className="grid-empty-message">
          <p>このページにはアイテムがありません。</p>
        </div>
      )}

      {/* 복잡한 필드 상세 테이블 (배지 아래 빈 화면에 표시) */}
      {selectedComplexField && (
        <div className="complex-field-detail">
          <div className="complex-field-detail-header">
            <h3>{selectedComplexField.key}</h3>
            <button 
              className="complex-field-detail-close"
              onClick={() => setSelectedComplexField(null)}
            >
              ×
            </button>
          </div>
          <div className="complex-field-detail-content">
            <table className="complex-field-table">
              <thead>
                <tr>
                  <th>キー</th>
                  <th>値</th>
                </tr>
              </thead>
              <tbody>
                {flattenObject(selectedComplexField.value).map((item, index) => (
                  <tr key={index}>
                    <td className="complex-field-key">{item.key}</td>
                    <td className="complex-field-value">{item.value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
})

/**
 * 액션 메뉴가 있는 셀 컴포넌트
 * 메뉴 위치를 동적으로 계산하여 버튼 아래에 정확히 표시
 */
interface ActionCellWithMenuProps {
  isHovered: boolean
  isEditing: boolean
  isLockedByOthers: boolean
  lockedBy: string | null
  onMouseEnter: () => void
  onMouseLeave: () => void
  onAdd: () => void
  onDelete: () => void
  createItemPending: boolean
  deleteItemPending: boolean
}

const ActionCellWithMenu = ({
  isHovered,
  isEditing,
  isLockedByOthers,
  lockedBy,
  onMouseEnter,
  onMouseLeave,
  onAdd,
  onDelete,
  createItemPending,
  deleteItemPending,
}: ActionCellWithMenuProps) => {
  const buttonRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const [menuPosition, setMenuPosition] = useState<{ top: number; left: number } | null>(null)

  // 메뉴 위치 계산 (우측 배치, 버튼 세로 중앙 정렬)
  useEffect(() => {
    if (isHovered && buttonRef.current) {
      const updatePosition = () => {
        if (!buttonRef.current) return
        
        const buttonRect = buttonRef.current.getBoundingClientRect()
        
        // 메뉴가 이미 렌더링되어 있으면 정확한 높이로 계산
        if (menuRef.current) {
          const menuHeight = menuRef.current.offsetHeight
          const buttonCenterY = buttonRect.top + buttonRect.height / 2
          setMenuPosition({
            top: buttonCenterY - menuHeight / 2, // 버튼 중앙에 메뉴 중앙 맞춤
            left: buttonRect.right - 4, // 버튼 우측에 -4px (겹침 허용)
          })
        } else {
          // 메뉴가 아직 렌더링되지 않았으면 대략적인 위치 설정
          setMenuPosition({
            top: buttonRect.top + buttonRect.height / 2 - 60, // 대략적인 중앙 위치 (메뉴 높이 약 120px 가정)
            left: buttonRect.right - 4, // 버튼 우측에 -4px (겹침 허용)
          })
          
          // 메뉴가 렌더링된 후 위치 재조정
          setTimeout(() => {
            if (menuRef.current && buttonRef.current) {
              const menuHeight = menuRef.current.offsetHeight
              const buttonRect = buttonRef.current.getBoundingClientRect()
              const buttonCenterY = buttonRect.top + buttonRect.height / 2
              setMenuPosition({
                top: buttonCenterY - menuHeight / 2,
                left: buttonRect.right - 4, // 버튼 우측에 -4px (겹침 허용)
              })
            }
          }, 0)
        }
      }
      
      updatePosition()
    } else {
      setMenuPosition(null)
    }
  }, [isHovered])

  const menuContent = isHovered && menuPosition ? (
    <div
      ref={menuRef}
      className="action-menu"
      style={{
        position: 'fixed',
        top: `${menuPosition.top}px`,
        left: `${menuPosition.left}px`,
        zIndex: 99999,
      }}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
          {/* 행 추가 버튼 */}
          <button
            onClick={(e) => {
              e.preventDefault()
              e.stopPropagation()
              onAdd()
            }}
            className="action-menu-item action-menu-add"
            disabled={isEditing || isLockedByOthers || createItemPending}
            title={isLockedByOthers ? `編集中: ${lockedBy}` : 'この行の下に行を追加'}
          >
            ➕ 追加
          </button>

          {/* 삭제 버튼 */}
          <button
            onClick={(e) => {
              e.preventDefault()
              e.stopPropagation()
              onDelete()
            }}
            className="action-menu-item action-menu-delete"
            disabled={isEditing || isLockedByOthers || deleteItemPending}
            title={isLockedByOthers ? `編集中: ${lockedBy}` : '行を削除'}
          >
            🗑️ 削除
          </button>
    </div>
  ) : null

  return (
    <>
      <div
        className="action-cell-container"
        onMouseEnter={onMouseEnter}
        onMouseLeave={onMouseLeave}
      >
        {/* 기본: 연필 / 編集中 or 他ユーザーがロック: 鍵 */}
        <button
          ref={buttonRef}
          className={`btn-action-main ${(isEditing || isLockedByOthers) ? 'btn-action-main-locked' : ''}`}
          title={isLockedByOthers ? `編集中: ${lockedBy ?? ''}` : isEditing ? '編集中' : '操作メニュー'}
        >
          {isEditing || isLockedByOthers ? '🔒' : '✏️'}
        </button>
      </div>
      {/* 호버 메뉴를 Portal로 body에 렌더링 */}
      {typeof document !== 'undefined' && menuContent && createPortal(menuContent, document.body)}
    </>
  )
}
