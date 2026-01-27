/**
 * 업로드 상태 관리 (Zustand)
 */
import { create } from 'zustand'
import { v4 as uuidv4 } from 'uuid'
import type { FormType } from '@/types'

interface UploadFile {
  id: string
  file: File
  status: 'pending' | 'uploading' | 'processing' | 'completed' | 'error'
  progress?: number
  message?: string
  error?: string
}

interface UploadState {
  // 세션 ID
  sessionId: string
  setSessionId: (id: string) => void

  // 업로드 파일 목록
  uploadFiles: Record<string, UploadFile[]>
  addUploadFiles: (formType: FormType, files: File[]) => void
  updateUploadFile: (
    formType: FormType,
    fileId: string,
    updates: Partial<UploadFile>
  ) => void
  clearUploadFiles: (formType: FormType) => void

  // 진행률
  processingProgress: Record<string, {
    currentPage: number
    totalPages: number
    message: string
    progress: number
  }>
  updateProgress: (
    taskId: string,
    progress: {
      currentPage: number
      totalPages: number
      message: string
      progress: number
    }
  ) => void
  clearProgress: (taskId: string) => void
}

export const useUploadStore = create<UploadState>((set) => ({
  // 세션 ID
  sessionId: uuidv4(),
  setSessionId: (id) => set({ sessionId: id }),

  // 업로드 파일 목록
  uploadFiles: {},
  addUploadFiles: (formType, files) =>
    set((state) => {
      const newFiles: UploadFile[] = files.map((file) => ({
        id: uuidv4(),
        file,
        status: 'pending',
      }))
      return {
        uploadFiles: {
          ...state.uploadFiles,
          [formType]: [
            ...(state.uploadFiles[formType] || []),
            ...newFiles,
          ],
        },
      }
    }),
  updateUploadFile: (formType, fileId, updates) =>
    set((state) => {
      const files = state.uploadFiles[formType] || []
      const updatedFiles = files.map((f) =>
        f.id === fileId ? { ...f, ...updates } : f
      )
      return {
        uploadFiles: {
          ...state.uploadFiles,
          [formType]: updatedFiles,
        },
      }
    }),
  clearUploadFiles: (formType) =>
    set((state) => {
      const newFiles = { ...state.uploadFiles }
      delete newFiles[formType]
      return { uploadFiles: newFiles }
    }),

  // 진행률
  processingProgress: {},
  updateProgress: (taskId, progress) =>
    set((state) => ({
      processingProgress: {
        ...state.processingProgress,
        [taskId]: progress,
      },
    })),
  clearProgress: (taskId) =>
    set((state) => {
      const newProgress = { ...state.processingProgress }
      delete newProgress[taskId]
      return { processingProgress: newProgress }
    }),
}))
