import React, { Suspense, lazy, useCallback, useEffect, useState } from 'react'
import {
  ArrowDownToLine, ArrowRight, BarChart3, BriefcaseBusiness, Check, ChevronRight,
  CircleHelp, FileText, History, LayoutDashboard, LoaderCircle, Menu, Moon, Plus,
  Send, Sparkles, Sun, Trash2, Trophy, UploadCloud, X,
} from 'lucide-react'
import { api } from './services/api'
import type { DashboardStats, Evaluation, InterviewItem, ResumeAnalysis } from './types'

const SkillChart = lazy(() => import('./components/SkillChart'))

type View = 'dashboard' | 'prepare' | 'interview' | 'history'
type QuestionAnswerResponse = { evaluation: Evaluation; next_question: string | null; question_number: number; total_questions: number }
type SessionState = { id: string; question: string; questionNumber: number; total: number; nextQuestion?: string; nextQuestionNumber?: number; sources: string[] }
type InterviewReport = {
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
type IndexedSource = 'resume' | 'job_description'
type IndexStatus = { state: 'idle' | 'indexing' | 'indexed' | 'error'; message?: string; chunks?: number }

const modes = ['mixed', 'technical', 'hr', 'python', 'programming', 'dsa', 'ml', 'nlp_llm_rag', 'projects', 'behavioral', 'system_design']

function getWorkspaceId(): string {
  const key = 'interview-copilot-workspace-id'
  const existing = localStorage.getItem(key)
  if (existing) return existing
  const workspaceId = 'local'
  localStorage.setItem(key, workspaceId)
  return workspaceId
}

function App() {
  const [view, setView] = useState<View>('dashboard')
  const [dark, setDark] = useState(() => localStorage.getItem('theme') === 'dark')
  const [mobileNav, setMobileNav] = useState(false)
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [history, setHistory] = useState<InterviewItem[]>([])
  const [workspaceId] = useState(getWorkspaceId)
  const [report, setReport] = useState<InterviewReport | null>(null)
  const [resumeText, setResumeText] = useState('')
  const [resumeAnalysis, setResumeAnalysis] = useState<ResumeAnalysis | null>(null)
  const [jobDescription, setJobDescription] = useState('')
  const [jobAnalysis, setJobAnalysis] = useState<Record<string, unknown> | null>(null)
  const [indexStatus, setIndexStatus] = useState<Record<IndexedSource, IndexStatus>>({
    resume: { state: 'idle' },
    job_description: { state: 'idle' },
  })
  const [mode, setMode] = useState('mixed')
  const [difficulty, setDifficulty] = useState('intermediate')
  const [experienceLevel, setExperienceLevel] = useState('intermediate')
  const [count, setCount] = useState(5)
  const [timerMinutes, setTimerMinutes] = useState(0)
  const [session, setSession] = useState<SessionState | null>(null)
  const [answer, setAnswer] = useState('')
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const [dashboard, items] = await Promise.all([
        api.get<DashboardStats>(`/dashboard/stats?workspace_id=${workspaceId}`),
        api.get<InterviewItem[]>(`/interviews/history?workspace_id=${workspaceId}`),
      ])
      setStats(dashboard)
      setHistory(items)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not load dashboard data.')
    }
  }, [workspaceId])

  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
    localStorage.setItem('theme', dark ? 'dark' : 'light')
  }, [dark])

  const run = async (action: () => Promise<void>) => {
    setBusy(true)
    setError('')
    try { await action() } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Something went wrong.')
    } finally { setBusy(false) }
  }

  const indexDocument = async (source: IndexedSource, text: string) => {
    setIndexStatus(previous => ({ ...previous, [source]: { state: 'indexing' } }))
    try {
      const result = await api.post<{ indexed_chunks: number; unchanged: boolean }>('/rag/index', {
        workspace_id: workspaceId,
        source,
        text,
      })
      setIndexStatus(previous => ({
        ...previous,
        [source]: {
          state: 'indexed',
          chunks: result.indexed_chunks,
          message: result.unchanged ? 'No document changes; existing index reused.' : 'Document indexed for this workspace.',
        },
      }))
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : 'Document indexing failed.'
      setIndexStatus(previous => ({ ...previous, [source]: { state: 'error', message } }))
      throw new Error(`Could not index ${source === 'resume' ? 'resume' : 'job description'}: ${message}`)
    }
  }

  const uploadResume = (file?: File) => {
    if (!file) return
    void run(async () => {
      const result = await api.upload<{ text: string; analysis: ResumeAnalysis }>('/resume/upload', file)
      setResumeText(result.text)
      setResumeAnalysis(result.analysis)
      await indexDocument('resume', result.text)
    })
  }

  const analyzeJob = () => run(async () => {
    const result = await api.post<Record<string, unknown>>('/job/analyze', { description: jobDescription, resume_text: resumeText })
    setJobAnalysis(result)
    await indexDocument('job_description', jobDescription)
  })

  const startInterview = () => run(async () => {
    const result = await api.post<{ session_id: string; question: string; question_number: number; total_questions: number; source_snippets: string[] }>('/interviews/start', {
      title: `${mode.replaceAll('_', ' ')} practice`,
      workspace_id: workspaceId,
      resume_text: resumeText,
      job_description: jobDescription,
      experience_level: experienceLevel,
      interview_type: mode,
      difficulty,
      count,
    })
    setSession({ id: result.session_id, question: result.question, questionNumber: result.question_number, total: result.total_questions, sources: result.source_snippets })
    setEvaluation(null)
    setAnswer('')
    setView('interview')
  })

  const submitAnswer = () => {
    if (!session) return
    void run(async () => {
      const result = await api.post<QuestionAnswerResponse>(`/interviews/${session.id}/answer`, { answer })
      setEvaluation(result.evaluation)
      setSession({ ...session, nextQuestion: result.next_question ?? undefined, nextQuestionNumber: result.question_number, total: result.total_questions })
      setAnswer('')
    })
  }

  const finishInterview = () => {
    if (!session) return
    void run(async () => {
      await api.post(`/interviews/${session.id}/finish`, {})
      setSession(null)
      setEvaluation(null)
      setView('history')
      await refresh()
    })
  }

  const deleteInterview = (id: string) => void run(async () => {
    await api.delete(`/interviews/${id}`)
    await refresh()
  })

  const showReport = (id: string) => void run(async () => {
    setReport(await api.get<InterviewReport>(`/interviews/${id}/report`))
  })

  const exportReport = (format: 'json' | 'pdf') => {
    if (!report) return
    void run(async () => {
      const blob = await api.download(`/interviews/${report.id}/export?format=${format}`)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `interview-${report.id}.${format}`
      link.click()
      URL.revokeObjectURL(url)
    })
  }

  const advanceInterview = () => {
    if (!session?.nextQuestion) {
      finishInterview()
      return
    }
    setSession({
      ...session,
      question: session.nextQuestion,
      questionNumber: session.nextQuestionNumber ?? session.questionNumber + 1,
      nextQuestion: undefined,
      nextQuestionNumber: undefined,
    })
    setEvaluation(null)
  }

  const nav = [
    { id: 'dashboard' as const, label: 'Dashboard', icon: LayoutDashboard },
    { id: 'prepare' as const, label: 'Prepare', icon: BriefcaseBusiness },
    { id: 'interview' as const, label: 'Mock interview', icon: CircleHelp },
    { id: 'history' as const, label: 'Interview history', icon: History },
  ]

  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileNav ? 'sidebar-open' : ''}`}>
        <div className="brand"><div className="brand-mark"><Sparkles size={19} /></div><span>interview<span className="brand-light">copilot</span></span></div>
        <div className="workspace-label">WORKSPACE</div>
        <nav className="nav-list">
          {nav.map(({ id, label, icon: Icon }) => (
            <button key={id} className={`nav-item ${view === id ? 'active' : ''}`} onClick={() => { setView(id); setMobileNav(false) }}>
              <Icon size={18} /><span>{label}</span>{id === 'history' && history.length > 0 && <span className="nav-count">{history.length}</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="local-card"><span className="status-dot" /><div><b>Private by design</b><small>AI runs on your machine</small></div></div>
          <button className="profile-button"><div className="avatar">AI</div><div><b>Practice workspace</b><small>Local session</small></div><ChevronRight size={15} /></button>
        </div>
      </aside>
      {mobileNav && <button className="nav-scrim" aria-label="Close menu" onClick={() => setMobileNav(false)} />}
      <main className="main-area">
        <header className="topbar">
          <button className="icon-button mobile-menu" aria-label="Open menu" onClick={() => setMobileNav(true)}><Menu size={19} /></button>
          <div className="breadcrumbs">Workspace <ChevronRight size={14} /> <b>{nav.find(item => item.id === view)?.label}</b></div>
          <div className="top-actions"><span className="local-badge"><span className="status-dot" /> Local AI</span><button className="icon-button" aria-label="Toggle theme" onClick={() => setDark(!dark)}>{dark ? <Sun size={18} /> : <Moon size={18} />}</button><div className="avatar top-avatar">AI</div></div>
        </header>
        <div className="page-content">
          {error && <div className="alert"><CircleHelp size={17} /><span>{error}</span><button onClick={() => setError('')} aria-label="Dismiss error"><X size={15} /></button></div>}
          {busy && <div className="busy-line"><LoaderCircle size={16} className="spin" /> Working with your local services…</div>}
          {view === 'dashboard' && <Dashboard stats={stats} history={history} onStart={() => setView('prepare')} onReport={showReport} />}
          {view === 'prepare' && <section>
            <PageHeading eyebrow="GET INTERVIEW-READY" title="Build your practice session" subtitle="Add a resume and job description to make questions more relevant to your goals." />
            <div className="setup-grid">
              <div className="panel document-panel">
                <div className="panel-heading"><div className="icon-tile violet"><FileText size={18} /></div><div><h3>Your resume</h3><p>PDF or DOCX · up to 10 MB</p></div></div>
                <label className="upload-zone"><UploadCloud size={23} /><b>{resumeText ? 'Upload a different resume' : 'Choose a resume file'}</b><span>PDF or DOCX from your device</span><input type="file" accept=".pdf,.docx" onChange={event => uploadResume(event.target.files?.[0])} /></label>
                {resumeAnalysis && <div className="analysis-box"><div className="analysis-title"><Check size={16} /> Resume analyzed</div><div className="chip-list">{resumeAnalysis.skills.map(skill => <span className="chip" key={skill}>{skill}</span>)}</div><div className="match-columns"><div><b>Sections found</b><p>{resumeAnalysis.sections_found.join(', ') || 'No recognized sections'}</p></div><div><b>Sections not found</b><p>{resumeAnalysis.sections_not_found.join(', ') || 'None'}</p></div></div>{resumeAnalysis.strengths.length > 0 && <p className="analysis-detail"><b>Signals found:</b> {resumeAnalysis.strengths.join(' ')}</p>}{resumeAnalysis.suggestions.map((suggestion, index) => <p className="analysis-detail" key={index}><b>Suggestion:</b> {suggestion}</p>)}<small>{resumeAnalysis.notice}</small></div>}
                <IndexStatus status={indexStatus.resume} />
                <label className="field-label">Or paste resume text</label><textarea className="text-area compact-area" value={resumeText} onChange={event => { setResumeText(event.target.value); setIndexStatus(previous => ({ ...previous, resume: { state: 'idle' } })) }} placeholder="Paste resume text here…" />
                <button className="button button-secondary full-button" disabled={!resumeText || busy} onClick={() => void run(async () => { const result = await api.post<ResumeAnalysis>('/resume/analyze', { text: resumeText }); setResumeAnalysis(result); await indexDocument('resume', resumeText) })}>Analyze &amp; index resume</button>
              </div>
              <div className="panel document-panel">
                <div className="panel-heading"><div className="icon-tile blue"><BriefcaseBusiness size={18} /></div><div><h3>Job description</h3><p>Compare your skills with the role requirements</p></div></div>
                <label className="field-label">Paste the job description</label><textarea className="text-area jd-area" value={jobDescription} onChange={event => { setJobDescription(event.target.value); setIndexStatus(previous => ({ ...previous, job_description: { state: 'idle' } })) }} placeholder="Paste a job description to personalize your interview…" />
                <button className="button button-secondary full-button" disabled={jobDescription.length < 30 || busy} onClick={analyzeJob}>Analyze &amp; index job description</button>
                <IndexStatus status={indexStatus.job_description} />
                {jobAnalysis && <div className="analysis-box"><div className="analysis-title"><BarChart3 size={16} /> Skill-match estimate: {String(jobAnalysis.match_score)}%</div><small>{String(jobAnalysis.score_label)}</small><div className="match-columns"><div><b>Found</b><p>{(jobAnalysis.matched_skills as string[]).join(', ') || 'No overlap detected'}</p></div><div><b>To practice</b><p>{(jobAnalysis.missing_skills as string[]).join(', ') || 'No missing keywords detected'}</p></div></div>{(jobAnalysis.experience_requirements as string[]).length > 0 && <div className="analysis-detail"><b>Experience requirements:</b> {(jobAnalysis.experience_requirements as string[]).join(' · ')}</div>}{(jobAnalysis.responsibilities as string[]).length > 0 && <div className="analysis-detail"><b>Responsibilities:</b> {(jobAnalysis.responsibilities as string[]).join(' · ')}</div>}{Object.entries(jobAnalysis.evidence as Record<string, string>).length > 0 && <div className="evidence-list"><b>Evidence from your resume</b>{Object.entries(jobAnalysis.evidence as Record<string, string>).map(([skill, snippet]) => <p key={skill}><strong>{skill}:</strong> “{snippet}”</p>)}</div>}</div>}
              </div>
            </div>
            <div className="panel config-panel"><div className="config-title"><div><span className="eyebrow">SESSION SETUP</span><h3>Choose your focus</h3></div><div className="step-pill">01 <span>/</span> 02</div></div>
              <div className="config-fields"><label><span>Interview type</span><select value={mode} onChange={event => setMode(event.target.value)}>{modes.map(item => <option value={item} key={item}>{item.replaceAll('_', ' ').replace(/\b\w/g, char => char.toUpperCase())}</option>)}</select></label><label><span>Experience level</span><select value={experienceLevel} onChange={event => setExperienceLevel(event.target.value)}>{['beginner', 'intermediate', 'advanced'].map(item => <option key={item}>{item}</option>)}</select></label><label><span>Difficulty</span><select value={difficulty} onChange={event => setDifficulty(event.target.value)}>{['beginner', 'intermediate', 'advanced'].map(item => <option key={item}>{item}</option>)}</select></label><label><span>Questions</span><select value={count} onChange={event => setCount(Number(event.target.value))}>{[3, 5, 7, 10].map(item => <option key={item} value={item}>{item} questions</option>)}</select></label><label><span>Timer (optional)</span><select value={timerMinutes} onChange={event => setTimerMinutes(Number(event.target.value))}>{[0, 15, 30, 45].map(item => <option key={item} value={item}>{item ? `${item} minutes` : 'No timer'}</option>)}</select></label></div>
              <div className="config-footer"><p><Sparkles size={16} /> Questions are generated privately by your local model.</p><button className="button button-primary" disabled={busy} onClick={startInterview}>Start practice <ArrowRight size={16} /></button></div>
            </div>
          </section>}
          {view === 'interview' && <InterviewRoom session={session} answer={answer} setAnswer={setAnswer} evaluation={evaluation} busy={busy} timerMinutes={timerMinutes} onSubmit={submitAnswer} onNext={advanceInterview} onFinish={finishInterview} onStart={() => setView('prepare')} />}
          {view === 'history' && <HistoryPage history={history} onDelete={deleteInterview} onReport={showReport} onStart={() => setView('prepare')} />}
        </div>
        {report && <ReportModal report={report} onClose={() => setReport(null)} onExport={exportReport} />}
      </main>
    </div>
  )
}

function PageHeading({ eyebrow, title, subtitle }: { eyebrow: string; title: string; subtitle: string }) {
  return <div className="page-heading"><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{subtitle}</p></div>
}

function Dashboard({ stats, history, onStart, onReport }: { stats: DashboardStats | null; history: InterviewItem[]; onStart: () => void; onReport: (id: string) => void }) {
  return <section>
    <div className="welcome-row"><PageHeading eyebrow="YOUR PRACTICE SPACE" title="Good to see you." subtitle="Every practice session brings you one step closer to interview-ready." /><button className="button button-primary" onClick={onStart}><Plus size={17} /> New interview</button></div>
    <div className="stat-grid">
      <StatCard label="Completed interviews" value={stats?.completed_interviews ?? 0} icon={<BriefcaseBusiness size={18} />} note="Keep building your rhythm" />
      <StatCard label="Average practice score" value={`${stats?.average_score ?? 0}`} icon={<BarChart3 size={18} />} note="Out of 10 · practice feedback only" />
      <StatCard label="Strongest topic" value={stats?.strongest_topics?.[0]?.topic ?? '—'} icon={<Trophy size={18} />} note={stats?.strongest_topics?.[0] ? `${stats.strongest_topics[0].score}/10 average` : 'Scores appear after practice'} />
    </div>
    <div className="dashboard-grid">
      <div className="panel chart-panel"><div className="section-title"><div><h3>Skill progress</h3><p>Average practice scores by topic</p></div><span className="chart-label">LAST SESSIONS</span></div>
        {stats?.progress?.length ? <Suspense fallback={<div className="chart-loading">Loading progress chart…</div>}><SkillChart data={stats.progress} /></Suspense> : <EmptyState icon={<BarChart3 size={20} />} title="Your progress will show up here" text="Complete a mock interview to see topic-by-topic insights." />}
      </div>
      <div className="panel recommendation-panel"><div className="section-title"><div><h3>Recommended next</h3><p>A small nudge for your next session</p></div><div className="recommend-icon"><Sparkles size={18} /></div></div><div className="recommend-body"><span className="recommend-tag">PERSONALIZED PRACTICE</span><h2>{stats?.recommended_next ?? 'Start your first practice interview'}</h2><p>{stats?.improve_topics?.[0] ? `Focus on this area to strengthen your interview confidence.` : 'Your practice insights will help tailor future sessions.'}</p><button className="text-button" onClick={onStart}>Set up a session <ArrowRight size={15} /></button></div><div className="recommend-footer"><span>Designed for steady progress</span><span className="sparkle-small"><Sparkles size={14} /></span></div></div>
    </div>
    <div className="panel recent-panel"><div className="section-title"><div><h3>Recent interviews</h3><p>Your latest practice sessions</p></div><button className="text-button" onClick={() => onStart()}>Practice again <ArrowRight size={15} /></button></div>{history.length ? <div className="history-list">{history.slice(0, 4).map(item => <HistoryRow key={item.id} item={item} onReport={onReport} />)}</div> : <EmptyState icon={<History size={20} />} title="No interviews yet" text="Start a practice session and your reports will be saved here." />}</div>
  </section>
}

function StatCard({ label, value, icon, note }: { label: string; value: string | number; icon: React.ReactNode; note: string }) {
  return <div className="panel stat-card"><div className="stat-top"><span>{label}</span><div className="stat-icon">{icon}</div></div><strong>{value}</strong><small>{note}</small></div>
}

function EmptyState({ icon, title, text }: { icon: React.ReactNode; title: string; text: string }) {
  return <div className="empty-state"><div className="empty-icon">{icon}</div><b>{title}</b><p>{text}</p></div>
}

function IndexStatus({ status }: { status: IndexStatus }) {
  if (status.state === 'idle') return null
  const label = status.state === 'indexing'
    ? 'Chunking and indexing locally…'
    : status.state === 'indexed'
      ? `${status.message} ${status.chunks ?? 0} chunk(s).`
      : status.message
  return <div className={`index-status ${status.state}`} role={status.state === 'error' ? 'alert' : 'status'}>
    {status.state === 'indexing' && <LoaderCircle size={14} className="spin" />}
    {status.state === 'indexed' && <Check size={14} />}
    {status.state === 'error' && <CircleHelp size={14} />}
    <span>{label}</span>
    {status.state === 'error' && <small>Check the RAG dependencies and embedding model, then retry.</small>}
  </div>
}

function HistoryRow({ item, onReport }: { item: InterviewItem; onReport: (id: string) => void }) {
  return <div className="history-row"><div className="history-type-icon"><FileText size={17} /></div><div className="history-name"><b>{item.title}</b><small>{new Date(item.created_at).toLocaleDateString()} · {item.mode.replaceAll('_', ' ')}</small></div><span className={`status-tag ${item.status}`}>{item.status}</span><b className="score-value">{item.average_score == null ? '—' : `${item.average_score}/10`}</b><button className="icon-button row-action" aria-label="Download interview report" onClick={() => onReport(item.id)}><ArrowDownToLine size={17} /></button></div>
}

function HistoryPage({ history, onDelete, onReport, onStart }: { history: InterviewItem[]; onDelete: (id: string) => void; onReport: (id: string) => void; onStart: () => void }) {
  return <section><div className="welcome-row"><PageHeading eyebrow="YOUR PRACTICE JOURNEY" title="Interview history" subtitle="Review completed sessions and revisit your practice reports." /><button className="button button-primary" onClick={onStart}><Plus size={17} /> New interview</button></div><div className="panel recent-panel"><div className="section-title"><div><h3>All sessions</h3><p>{history.length} saved practice sessions</p></div></div>{history.length ? <div className="history-list">{history.map(item => <div className="history-row" key={item.id}><div className="history-type-icon"><FileText size={17} /></div><div className="history-name"><b>{item.title}</b><small>{new Date(item.created_at).toLocaleString()} · {item.mode.replaceAll('_', ' ')}</small></div><span className={`status-tag ${item.status}`}>{item.status}</span><b className="score-value">{item.average_score == null ? '—' : `${item.average_score}/10`}</b><button className="icon-button row-action" aria-label="Download report" onClick={() => onReport(item.id)}><ArrowDownToLine size={17} /></button><button className="icon-button row-action delete-action" aria-label="Delete interview" onClick={() => onDelete(item.id)}><Trash2 size={16} /></button></div>)}</div> : <EmptyState icon={<History size={20} />} title="Your history is waiting" text="Completed interviews and feedback reports will appear in this list." />}</div></section>
}

function InterviewRoom({ session, answer, setAnswer, evaluation, busy, timerMinutes, onSubmit, onNext, onFinish, onStart }: { session: SessionState | null; answer: string; setAnswer: (value: string) => void; evaluation: Evaluation | null; busy: boolean; timerMinutes: number; onSubmit: () => void; onNext: () => void; onFinish: () => void; onStart: () => void }) {
  const [remainingSeconds, setRemainingSeconds] = useState(timerMinutes * 60)
  useEffect(() => {
    setRemainingSeconds(timerMinutes * 60)
    if (!session || timerMinutes === 0) return
    const timer = window.setInterval(() => {
      setRemainingSeconds(current => {
        if (current <= 1) window.clearInterval(timer)
        return Math.max(0, current - 1)
      })
    }, 1000)
    return () => window.clearInterval(timer)
  }, [session?.id, timerMinutes])
  if (!session) return <section><PageHeading eyebrow="MOCK INTERVIEW" title="Practice out loud. Get better." subtitle="Your AI interviewer asks one question at a time and shares feedback after each answer." /><div className="panel interview-empty"><div className="empty-icon large"><CircleHelp size={25} /></div><h2>Ready when you are</h2><p>Set up your resume, target role, and preferred difficulty to begin.</p><button className="button button-primary" onClick={onStart}>Set up interview <ArrowRight size={16} /></button></div></section>
  return <section><div className="interview-head"><div><span className="eyebrow">LIVE PRACTICE SESSION</span><h1>Mock interview</h1><p>Take your time. Thoughtful answers matter more than speed.</p></div><div className="interview-controls">{timerMinutes > 0 && <span className={`timer-badge ${remainingSeconds === 0 ? 'timer-expired' : ''}`}>{remainingSeconds === 0 ? "Time's up" : `${String(Math.floor(remainingSeconds / 60)).padStart(2, '0')}:${String(remainingSeconds % 60).padStart(2, '0')} remaining`}</span>}<button className="button button-secondary" onClick={onFinish}><X size={16} /> End interview</button></div></div><div className="interview-layout"><div className="panel conversation-panel"><div className="interview-progress"><div><span>QUESTION {Math.min(session.questionNumber, session.total)} OF {session.total}</span><b>{Math.min(100, Math.round((session.questionNumber / session.total) * 100))}%</b></div><div className="progress-track"><div style={{ width: `${Math.min(100, (session.questionNumber / session.total) * 100)}%` }} /></div></div>{session.question ? <><div className="question-card"><div className="bot-avatar"><Sparkles size={17} /></div><div><span className="message-label">YOUR INTERVIEWER</span><h2>{session.question}</h2>{session.sources.length > 0 && <div className="question-sources"><b>Supporting document snippets</b>{session.sources.map((snippet, index) => <p key={index}>“{snippet}”</p>)}</div>}</div></div>{evaluation && <EvaluationCard evaluation={evaluation} />}{!evaluation && <div className="answer-box"><label htmlFor="candidate-answer">YOUR ANSWER</label><textarea id="candidate-answer" value={answer} onChange={event => setAnswer(event.target.value)} placeholder="Share your answer here. You can mention examples, trade-offs, or how you approached the problem…" /><div className="answer-footer"><span>{answer.length} / 10000</span><button className="button button-primary" disabled={!answer.trim() || busy} onClick={onSubmit}>Submit answer <Send size={15} /></button></div></div>}{evaluation && <div className="answer-footer evaluation-actions"><span>Practice feedback only · not an authoritative assessment</span><button className="button button-primary" onClick={onNext}>{session.nextQuestion ? 'Next question' : 'Finish review'} <ArrowRight size={16} /></button></div>}</> : <EmptyState icon={<Check size={20} />} title="All questions answered" text="Finish the session to save your report and practice scores." />}</div><aside className="panel session-aside"><div className="section-title"><div><h3>Session guide</h3><p>Make the most of your practice</p></div></div><div className="guide-item"><span className="guide-number">01</span><div><b>Think it through</b><p>Take a moment to structure your thoughts before answering.</p></div></div><div className="guide-item"><span className="guide-number">02</span><div><b>Be specific</b><p>Use concrete examples from work, study, or projects you actually did.</p></div></div><div className="guide-item"><span className="guide-number">03</span><div><b>Learn from feedback</b><p>Scores are for practice; use the notes to guide what you study next.</p></div></div><div className="privacy-note"><span className="status-dot" /><span>Local AI session</span></div></aside></div></section>
}

function EvaluationCard({ evaluation }: { evaluation: Evaluation }) {
  return <div className="evaluation-card"><div className="evaluation-top"><div><span className="message-label">FEEDBACK</span><h3>Good work — here's what to build on</h3></div><div className="score-circle"><b>{evaluation.overall_score}</b><small>/ 10</small></div></div><div className="category-scores">{Object.entries(evaluation.category_scores).map(([name, score]) => <div key={name}><span>{name.replaceAll('_', ' ')}</span><b>{score}/10</b></div>)}</div><div className="feedback-columns"><div><b className="feedback-heading positive">What went well</b><ul>{evaluation.strengths.map((item, index) => <li key={index}>{item}</li>)}</ul></div><div><b className="feedback-heading">Consider adding</b><ul>{evaluation.missing_concepts.map((item, index) => <li key={index}>{item}</li>)}</ul></div></div>{evaluation.unsupported_statements.length > 0 && <div className="unsupported"><b>Check these statements</b><p>{evaluation.unsupported_statements.join(' · ')}</p></div>}<div className="sample-answer"><b>One possible stronger answer</b><p>{evaluation.improved_answer}</p></div>{evaluation.follow_up_question && <div className="follow-up"><b>Suggested follow-up question</b><p>{evaluation.follow_up_question}</p></div>}{evaluation.source_snippets.length > 0 && <div className="source-snippets"><b>Supporting source snippets</b>{evaluation.source_snippets.map((item, index) => <p key={index}>“{item}”</p>)}</div>}</div>
}

function ReportModal({ report, onClose, onExport }: { report: InterviewReport; onClose: () => void; onExport: (format: 'json' | 'pdf') => void }) {
  return <div className="modal-backdrop" role="presentation" onClick={onClose}><section className="report-modal panel" role="dialog" aria-modal="true" aria-label="Interview report" onClick={event => event.stopPropagation()}><div className="report-modal-head"><div><span className="eyebrow">PRACTICE REPORT</span><h2>{report.title}</h2><p>{report.mode.replaceAll('_', ' ')} · {report.difficulty} · {report.average_score ?? '—'}/10 average</p></div><button className="icon-button" aria-label="Close report" onClick={onClose}><X size={18} /></button></div><div className="report-answers">{report.answers.length ? report.answers.map((item, index) => <article className="report-answer" key={`${index}-${item.question}`}><span className="message-label">QUESTION {index + 1}</span><h3>{item.question}</h3><p className="candidate-answer"><b>Your answer</b><br />{item.answer}</p><EvaluationCard evaluation={item.evaluation} /></article>) : <EmptyState icon={<History size={20} />} title="No answers submitted" text="This session ended before any answers were submitted." />}</div><div className="report-modal-footer"><small>{report.score_notice}</small><div className="report-downloads"><button className="button button-secondary" onClick={() => onExport('json')}><ArrowDownToLine size={15} /> JSON</button><button className="button button-primary" disabled={report.status !== 'completed'} title={report.status !== 'completed' ? 'Finish the interview to export a PDF.' : undefined} onClick={() => onExport('pdf')}><ArrowDownToLine size={15} /> Download PDF</button></div></div></section></div>
}

export default App
