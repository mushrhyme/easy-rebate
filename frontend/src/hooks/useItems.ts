/**
 * 아이템 관련 React Query 훅
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { itemsApi } from '@/api/client'
import { documentsApi } from '@/api/client'
import type { ItemUpdateRequest } from '@/types'

export const useItems = (pdfFilename: string, pageNumber: number) => {
  return useQuery({
    queryKey: ['items', pdfFilename, pageNumber],
    queryFn: () => itemsApi.getByPage(pdfFilename, pageNumber),
    enabled: !!pdfFilename && !!pageNumber,
  })
}

export const usePageMeta = (pdfFilename: string, pageNumber: number) => {
  return useQuery({
    queryKey: ['pageMeta', pdfFilename, pageNumber],
    queryFn: () => documentsApi.getPageMeta(pdfFilename, pageNumber),
    enabled: !!pdfFilename && !!pageNumber,
  })
}

export const useUpdateItem = (pdfFilename?: string, pageNumber?: number) => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ itemId, request }: { itemId: number; request: ItemUpdateRequest }) =>
      itemsApi.update(itemId, request),
    onSuccess: (_, variables) => {
      // 모든 업데이트 후 invalidateQueries 호출 (편집 버튼과 동일하게)
      // pdfFilename과 pageNumber가 제공된 경우 해당 페이지의 아이템 목록 갱신
      if (pdfFilename && pageNumber) {
        queryClient.invalidateQueries({
          queryKey: ['items', pdfFilename, pageNumber],
        })
      } else {
        // pdfFilename이 item_data에 있는 경우 (하위 호환성)
        const pdfFilenameFromData = variables.request.item_data?.pdf_filename
        if (pdfFilenameFromData) {
          queryClient.invalidateQueries({
            queryKey: ['items', pdfFilenameFromData],
          })
        }
      }
    },
    onError: (error) => {
      console.error('❌ [useUpdateItem] 에러:', error)
    },
  })
}

export const useAcquireLock = () => {
  return useMutation({
    mutationFn: ({ itemId, sessionId }: { itemId: number; sessionId: string }) =>
      itemsApi.acquireLock(itemId, sessionId),
  })
}

export const useCreateItem = (pdfFilename?: string, pageNumber?: number) => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({
      itemData,
      afterItemId
    }: {
      itemData: Record<string, any>
      afterItemId?: number
    }) => {
      if (!pdfFilename || !pageNumber) {
        throw new Error('pdfFilename and pageNumber are required')
      }
      return itemsApi.create(pdfFilename, pageNumber, itemData, afterItemId)
    },
    onSuccess: () => {
      // 아이템 목록 갱신
      if (pdfFilename && pageNumber) {
        queryClient.invalidateQueries({
          queryKey: ['items', pdfFilename, pageNumber],
        })
      }
    },
    onError: (error) => {
      console.error('❌ [useCreateItem] 에러:', error)
    },
  })
}

export const useDeleteItem = (pdfFilename?: string, pageNumber?: number) => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (itemId: number) => itemsApi.delete(itemId),
    onSuccess: () => {
      // 아이템 목록 갱신
      if (pdfFilename && pageNumber) {
        queryClient.invalidateQueries({
          queryKey: ['items', pdfFilename, pageNumber],
        })
      }
    },
    onError: (error) => {
      console.error('❌ [useDeleteItem] 에러:', error)
    },
  })
}

export const useReleaseLock = () => {
  return useMutation({
    mutationFn: ({ itemId, sessionId }: { itemId: number; sessionId: string }) =>
      itemsApi.releaseLock(itemId, sessionId),
  })
}
