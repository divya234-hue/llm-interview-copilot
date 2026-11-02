export const resumeService = {
  uploadResume: (file: File) =>
    fetch(`${import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api'}/resume/upload`, {
      method: 'POST',
      body: (() => {
        const form = new FormData()
        form.append('file', file)
        return form
      })(),
    }).then(async (response) => {
      if (!response.ok) {
        const body = await response.json().catch(() => null) as { detail?: string } | null
        throw new Error(body?.detail ?? `Request failed (${response.status})`)
      }
      return response.json() as Promise<{
        filename: string
        text: string
        analysis: Record<string, unknown>
      }>
    }),

  analyzeResumeText: (text: string) =>
    fetch(`${import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api'}/resume/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    }).then(async (response) => {
      if (!response.ok) {
        const body = await response.json().catch(() => null) as { detail?: string } | null
        throw new Error(body?.detail ?? `Request failed (${response.status})`)
      }
      return response.json() as Promise<Record<string, unknown>>
    }),

  analyzeJob: (description: string, resumeText: string) =>
    fetch(`${import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api'}/job/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ description, resume_text: resumeText }),
    }).then(async (response) => {
      if (!response.ok) {
        const body = await response.json().catch(() => null) as { detail?: string } | null
        throw new Error(body?.detail ?? `Request failed (${response.status})`)
      }
      return response.json() as Promise<Record<string, unknown>>
    }),

  indexDocument: (workspaceId: string, source: 'resume' | 'job_description', text: string) =>
    fetch(`${import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api'}/rag/index`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_id: workspaceId, source, text }),
    }).then(async (response) => {
      if (!response.ok) {
        const body = await response.json().catch(() => null) as { detail?: string } | null
        throw new Error(body?.detail ?? `Request failed (${response.status})`)
      }
      return response.json() as Promise<{ indexed_chunks: number; unchanged: boolean; source: string; document_id: string }>
    }),
}
