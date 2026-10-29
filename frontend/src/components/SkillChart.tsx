import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

type Props = { data: { topic: string; score: number }[] }

export default function SkillChart({ data }: Props) {
  return (
    <div className="chart-wrap">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data}>
          <defs>
            <linearGradient id="scoreFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#6757e8" stopOpacity={0.22} />
              <stop offset="95%" stopColor="#6757e8" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--line)" />
          <XAxis dataKey="topic" axisLine={false} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 11 }} />
          <YAxis domain={[0, 10]} axisLine={false} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 11 }} />
          <Tooltip contentStyle={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 12, color: 'var(--text)' }} />
          <Area type="monotone" dataKey="score" stroke="#6757e8" strokeWidth={2.5} fill="url(#scoreFill)" />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
