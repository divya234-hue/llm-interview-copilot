import { api } from './api'
import type { ResumeAnalysis } from '../types'

export type IndexedSource = 'resume' | 'job_description'
export type IndexResult = { indexed_chunks: number; unchanged: boolean; source: string; document_id: string }

export const resumeService = {
  uploadResume: (file: File) =>
    api.upload<{ filename: string; text: string; analysis: ResumeAnalysis }>('/resume/upload', file),

  analyzeResumeText: (text: string) =>
    api.post<ResumeAnalysis>('/resume/analyze', { text }),

  analyzeJob: (description: string, resumeText: string) =>
    api.post<Record<string, unknown>>('/job/analyze', { description, resume_text: resumeText }),

  indexDocument: (workspaceId: string, source: IndexedSource, text: string) =>
    api.post<IndexResult>('/rag/index', { workspace_id: workspaceId, source, text }),
}
