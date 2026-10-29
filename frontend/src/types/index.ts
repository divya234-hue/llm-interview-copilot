export type Evaluation = {
  overall_score: number
  category_scores: Record<string, number>
  strengths: string[]
  missing_concepts: string[]
  unsupported_statements: string[]
  improved_answer: string
  follow_up_question: string
  source_snippets: string[]
}

export type InterviewItem = {
  id: string
  title: string
  mode: string
  status: string
  average_score: number | null
  created_at: string
}

export type DashboardStats = {
  completed_interviews: number
  average_score: number
  strongest_topics: { topic: string; score: number }[]
  improve_topics: { topic: string; score: number }[]
  progress: { topic: string; score: number }[]
  recommended_next: string
  recent: InterviewItem[]
}

export type ResumeAnalysis = {
  skills: string[]
  sections_found: string[]
  sections_not_found: string[]
  strengths: string[]
  suggestions: string[]
  notice: string
}
