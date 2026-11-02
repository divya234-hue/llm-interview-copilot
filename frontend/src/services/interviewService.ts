import { api } from './api'
import type { DashboardStats, Evaluation, InterviewItem } from '../types'

export type QuestionAnswerResponse = {
  evaluation: Evaluation
  next_question: string | null
  question_number: number
  total_questions: number
}

export type SessionState = {
  id: string
  question: string
  questionNumber: number
  total: number
  nextQuestion?: string
  nextQuestionNumber?: number
  sources: string[]
}

export type InterviewReport = {
  id: string
  title: string
  mode: string
  difficulty: string
  status: string
  average_score: number | null
  questions: { text: string; topic: string }[]
  answers: { question: string; answer: string; evaluation: Evaluation }[]
  score_notice: string
}

export type StartInterviewRequest = {
  title: string
  workspace_id: string
  resume_text: string
  job_description: string
  experience_level: string
  interview_type: string
  difficulty: string
  count: number
}

export type StartInterviewResponse = {
  session_id: string
  question: string
  question_number: number
  total_questions: number
  source_snippets: string[]
}

export async function loadWorkspaceData(workspaceId: string): Promise<[DashboardStats, InterviewItem[]]> {
  return Promise.all([
    api.get<DashboardStats>(`/dashboard/stats?workspace_id=${workspaceId}`),
    api.get<InterviewItem[]>(`/interviews/history?workspace_id=${workspaceId}`),
  ])
}

export function startInterview(input: StartInterviewRequest): Promise<StartInterviewResponse> {
  return api.post('/interviews/start', input)
}

export function submitAnswer(sessionId: string, answer: string): Promise<QuestionAnswerResponse> {
  return api.post(`/interviews/${sessionId}/answer`, { answer })
}

export function finishInterview(sessionId: string): Promise<void> {
  return api.post(`/interviews/${sessionId}/finish`, {})
}

export function deleteInterview(id: string): Promise<void> {
  return api.delete(`/interviews/${id}`)
}

export function getInterviewReport(id: string): Promise<InterviewReport> {
  return api.get(`/interviews/${id}/report`)
}

export function downloadInterviewReport(id: string, format: 'json' | 'pdf'): Promise<Blob> {
  return api.download(`/interviews/${id}/export?format=${format}`)
}
