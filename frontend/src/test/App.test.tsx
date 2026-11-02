import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import App from '../App'

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
    blob: async () => new Blob(),
  } as Response
}

describe('App', () => {
  it('loads the dashboard and toggles the persisted theme', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/dashboard/stats')) {
        return jsonResponse({
          completed_interviews: 2,
          average_score: 8,
          strongest_topics: [],
          improve_topics: [],
          progress: [],
          recommended_next: 'Practice Python',
          recent: [],
        })
      }
      return jsonResponse([])
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    expect(await screen.findByText('Practice Python')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/dashboard/stats?workspace_id=local'),
      undefined,
    )

    await userEvent.click(screen.getByRole('button', { name: 'Toggle theme' }))
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark')
    await waitFor(() => expect(localStorage.getItem('theme')).toBe('dark'))
  })

  it('submits job analysis and indexes the job description', async () => {
    const requests: { url: string; init?: RequestInit }[] = []
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      requests.push({ url, init })
      if (url.includes('/dashboard/stats')) {
        return jsonResponse({
          completed_interviews: 0,
          average_score: 0,
          strongest_topics: [],
          improve_topics: [],
          progress: [],
          recommended_next: 'Start your first practice interview',
          recent: [],
        })
      }
      if (url.includes('/job/analyze')) {
        return jsonResponse({
          required_skills: ['python'],
          preferred_skills: [],
          responsibilities: [],
          experience_requirements: [],
          matched_skills: ['python'],
          missing_skills: ['react'],
          match_score: 50,
          score_label: 'Heuristic keyword overlap estimate.',
          evidence: {},
        })
      }
      if (url.includes('/rag/index')) {
        return jsonResponse({
          indexed_chunks: 2,
          unchanged: false,
          source: 'job_description',
          document_id: 'doc-1',
        })
      }
      return jsonResponse([])
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<App />)
    await user.click(screen.getByRole('button', { name: 'Prepare' }))
    const description = 'We need a Python engineer to build reliable application services.'
    await user.type(
      screen.getByPlaceholderText('Paste a job description to personalize your interview…'),
      description,
    )
    await user.click(screen.getByRole('button', { name: 'Analyze & index job description' }))

    expect(await screen.findByText('Skill-match estimate: 50%')).toBeInTheDocument()
    expect(await screen.findByText('Document indexed for this workspace. 2 chunk(s).')).toBeInTheDocument()
    await waitFor(() => expect(requests.some(request => request.url.includes('/rag/index'))).toBe(true))

    const analysis = requests.find(request => request.url.includes('/job/analyze'))
    expect(JSON.parse(String(analysis?.init?.body))).toEqual({
      description,
      resume_text: '',
    })
    const indexing = requests.find(request => request.url.includes('/rag/index'))
    expect(JSON.parse(String(indexing?.init?.body))).toEqual({
      workspace_id: 'local',
      source: 'job_description',
      text: description,
    })
  })
})
