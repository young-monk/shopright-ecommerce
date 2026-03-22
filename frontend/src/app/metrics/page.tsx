'use client'
import { useState, useEffect, useCallback } from 'react'
import {
  LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts'

// ── Types ─────────────────────────────────────────────────────────────────────

interface InfraData {
  summary: { total_requests: number; total_sessions: number; error_rate_pct: number; p95_latency_ms: number; avg_latency_ms: number }
  daily: { date: string; requests: number; sessions: number; error_rate_pct: number; p95_latency_ms: number }[]
}

interface ModelData {
  summary: { total_cost_usd: number; unanswered_rate_pct: number; avg_rag_confidence: number; p95_ttft_ms: number; hallucination_rate_pct: number }
  daily: { date: string; cost_usd: number; avg_ttft_ms: number; unanswered_rate_pct: number; avg_rag_confidence: number }[]
  catalog_gaps: { user_message: string; category: string; frequency: number }[]
  category_performance: { category: string; requests: number; unanswered_rate_pct: number }[]
}

interface BusinessData {
  satisfaction_summary: { avg_stars: number; total_reviews: number; positive_rate_pct: number }
  feedback_summary: { thumbs_up: number; thumbs_down: number; positive_rate_pct: number }
  satisfaction_trend: { date: string; avg_stars: number; review_count: number }[]
  conversion_trend: { date: string; chip_clicks: number; sessions_with_clicks: number }[]
  top_clicked_products: { product_name: string; clicks: number }[]
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <p className="text-xs text-gray-500 uppercase tracking-wide">{label}</p>
      <p className="text-2xl font-bold text-gray-900 mt-1">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
    </div>
  )
}

function SectionHeader({ title, sub }: { title: string; sub: string }) {
  return (
    <div className="mb-4">
      <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
      <p className="text-sm text-gray-500">{sub}</p>
    </div>
  )
}

function Empty({ msg }: { msg: string }) {
  return <div className="text-sm text-gray-400 text-center py-10">{msg}</div>
}

const COLORS = { primary: '#2563eb', green: '#16a34a', red: '#dc2626', amber: '#d97706', purple: '#7c3aed' }

// ── Tab: Infra ────────────────────────────────────────────────────────────────

function InfraTab({ days }: { days: number }) {
  const [data, setData] = useState<InfraData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    fetch(`/analytics-proxy/analytics/infra?days=${days}`)
      .then(r => r.json())
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [days])

  if (loading) return <div className="text-center py-20 text-gray-400">Loading...</div>
  if (!data || data.summary == null) return <Empty msg="No infrastructure data yet. Send some chat messages first." />

  const s = data.summary
  return (
    <div className="space-y-8">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <StatCard label="Total Requests" value={s.total_requests?.toLocaleString() ?? '—'} />
        <StatCard label="Unique Sessions" value={s.total_sessions?.toLocaleString() ?? '—'} />
        <StatCard label="Error Rate" value={`${s.error_rate_pct ?? 0}%`} sub="LLM errors / total" />
        <StatCard label="p95 Latency" value={s.p95_latency_ms ? `${s.p95_latency_ms}ms` : '—'} />
        <StatCard label="Avg Latency" value={s.avg_latency_ms ? `${s.avg_latency_ms}ms` : '—'} />
      </div>

      <div>
        <SectionHeader title="Daily Request Volume" sub="Total requests and sessions per day" />
        {data.daily.length === 0 ? <Empty msg="No daily data" /> : (
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={data.daily}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="requests" stroke={COLORS.primary} dot={false} name="Requests" />
              <Line type="monotone" dataKey="sessions" stroke={COLORS.green} dot={false} name="Sessions" />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      <div>
        <SectionHeader title="Latency Trend (p95)" sub="95th percentile end-to-end latency in ms" />
        {data.daily.length === 0 ? <Empty msg="No latency data" /> : (
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={data.daily}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} unit="ms" />
              <Tooltip />
              <Line type="monotone" dataKey="p95_latency_ms" stroke={COLORS.amber} dot={false} name="p95 ms" />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      <div>
        <SectionHeader title="Error Rate" sub="Percentage of requests with LLM errors" />
        {data.daily.length === 0 ? <Empty msg="No error data" /> : (
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={data.daily}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} unit="%" />
              <Tooltip />
              <Bar dataKey="error_rate_pct" fill={COLORS.red} name="Error %" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}

// ── Tab: Model ────────────────────────────────────────────────────────────────

function ModelTab({ days }: { days: number }) {
  const [data, setData] = useState<ModelData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    fetch(`/analytics-proxy/analytics/model?days=${days}`)
      .then(r => r.json())
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [days])

  if (loading) return <div className="text-center py-20 text-gray-400">Loading...</div>
  if (!data || data.summary == null) return <Empty msg="No model data yet. Send some chat messages first." />

  const s = data.summary
  return (
    <div className="space-y-8">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <StatCard label="Total LLM Cost" value={`$${s.total_cost_usd?.toFixed(4) ?? '0'}`} sub="Gemini 2.5 Flash" />
        <StatCard label="Unanswered Rate" value={`${s.unanswered_rate_pct ?? 0}%`} sub="No catalog match" />
        <StatCard label="Avg RAG Confidence" value={s.avg_rag_confidence != null ? s.avg_rag_confidence.toFixed(3) : '—'} sub="Lower = better" />
        <StatCard label="p95 TTFT" value={s.p95_ttft_ms ? `${s.p95_ttft_ms}ms` : '—'} sub="Time to first token" />
        <StatCard label="Hallucination Flag" value={`${s.hallucination_rate_pct ?? 0}%`} sub="Sources not mentioned" />
      </div>

      <div>
        <SectionHeader title="Daily LLM Cost" sub="Estimated spend on Gemini API per day (USD)" />
        {data.daily.length === 0 ? <Empty msg="No cost data" /> : (
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={data.daily}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} tickFormatter={v => `$${v.toFixed(4)}`} />
              <Tooltip formatter={(v: number) => [`$${v.toFixed(6)}`, 'Cost']} />
              <Bar dataKey="cost_usd" fill={COLORS.purple} name="Cost USD" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        <div>
          <SectionHeader title="Unanswered Rate" sub="% queries the bot couldn't answer" />
          {data.daily.length === 0 ? <Empty msg="No data" /> : (
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={data.daily}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} unit="%" />
                <Tooltip />
                <Line type="monotone" dataKey="unanswered_rate_pct" stroke={COLORS.red} dot={false} name="Unanswered %" />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>

        <div>
          <SectionHeader title="RAG Confidence" sub="Avg vector distance (lower = better match)" />
          {data.daily.length === 0 ? <Empty msg="No data" /> : (
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={data.daily}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} domain={[0, 1]} />
                <Tooltip />
                <Line type="monotone" dataKey="avg_rag_confidence" stroke={COLORS.green} dot={false} name="Avg Distance" />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        <div>
          <SectionHeader title="Catalog Gaps" sub="Unanswered queries — products missing from catalog" />
          {data.catalog_gaps.length === 0 ? <Empty msg="No unanswered queries" /> : (
            <div className="overflow-auto max-h-64 rounded-lg border border-gray-200">
              <table className="w-full text-xs">
                <thead className="bg-gray-50 sticky top-0">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium text-gray-600">Query</th>
                    <th className="px-3 py-2 text-left font-medium text-gray-600">Category</th>
                    <th className="px-3 py-2 text-right font-medium text-gray-600">Count</th>
                  </tr>
                </thead>
                <tbody>
                  {data.catalog_gaps.map((g, i) => (
                    <tr key={i} className="border-t border-gray-100">
                      <td className="px-3 py-1.5 text-gray-700 max-w-[240px] truncate">{g.user_message}</td>
                      <td className="px-3 py-1.5 text-gray-500">{g.category}</td>
                      <td className="px-3 py-1.5 text-right font-medium">{g.frequency}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div>
          <SectionHeader title="Category Performance" sub="Request volume and unanswered rate per category" />
          {data.category_performance.length === 0 ? <Empty msg="No category data" /> : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={data.category_performance} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis type="number" tick={{ fontSize: 10 }} />
                <YAxis dataKey="category" type="category" tick={{ fontSize: 10 }} width={120} />
                <Tooltip />
                <Bar dataKey="requests" fill={COLORS.primary} name="Requests" radius={[0, 3, 3, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Tab: Business ─────────────────────────────────────────────────────────────

function BusinessTab({ days }: { days: number }) {
  const [data, setData] = useState<BusinessData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    fetch(`/analytics-proxy/analytics/business?days=${days}`)
      .then(r => r.json())
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [days])

  if (loading) return <div className="text-center py-20 text-gray-400">Loading...</div>
  if (!data) return <Empty msg="No business data yet." />

  const ss = data.satisfaction_summary
  const fs = data.feedback_summary
  return (
    <div className="space-y-8">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Avg Session Rating" value={ss?.avg_stars ? `${ss.avg_stars} ⭐` : '—'} sub={`${ss?.total_reviews ?? 0} reviews`} />
        <StatCard label="Satisfaction Rate" value={ss?.positive_rate_pct != null ? `${ss.positive_rate_pct}%` : '—'} sub="4+ stars" />
        <StatCard label="Thumbs Up Rate" value={fs?.positive_rate_pct != null ? `${fs.positive_rate_pct}%` : '—'} sub={`${fs?.thumbs_up ?? 0} up / ${fs?.thumbs_down ?? 0} down`} />
        <StatCard label="Total Chip Clicks" value={data.conversion_trend.reduce((s, d) => s + (d.chip_clicks ?? 0), 0).toLocaleString()} sub="Product card clicks" />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        <div>
          <SectionHeader title="Session Satisfaction" sub="Average star rating per day (1–5)" />
          {data.satisfaction_trend.length === 0 ? <Empty msg="No ratings yet" /> : (
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={data.satisfaction_trend}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} domain={[1, 5]} />
                <Tooltip />
                <Line type="monotone" dataKey="avg_stars" stroke={COLORS.amber} dot={false} name="Avg Stars" />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>

        <div>
          <SectionHeader title="Product Chip Clicks" sub="Daily clicks on product cards in chat" />
          {data.conversion_trend.length === 0 ? <Empty msg="No clicks yet" /> : (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={data.conversion_trend}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="chip_clicks" fill={COLORS.green} name="Chip Clicks" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      <div>
        <SectionHeader title="Top Clicked Products" sub="Most clicked product cards from chat recommendations" />
        {data.top_clicked_products.length === 0 ? <Empty msg="No product clicks yet" /> : (
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={data.top_clicked_products} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis type="number" tick={{ fontSize: 10 }} />
              <YAxis dataKey="product_name" type="category" tick={{ fontSize: 10 }} width={200} />
              <Tooltip />
              <Bar dataKey="clicks" fill={COLORS.primary} name="Clicks" radius={[0, 3, 3, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

const TABS = ['Infra', 'Model', 'Business'] as const
type Tab = typeof TABS[number]

const DAY_OPTIONS = [7, 14, 30]

export default function MetricsPage() {
  const [tab, setTab] = useState<Tab>('Infra')
  const [days, setDays] = useState(14)

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-6xl mx-auto px-4 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">ShopRight Metrics</h1>
            <p className="text-sm text-gray-500 mt-1">Infrastructure · Model · Business</p>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-500">Last</span>
            {DAY_OPTIONS.map(d => (
              <button
                key={d}
                onClick={() => setDays(d)}
                className={`px-3 py-1.5 text-sm rounded-lg transition-colors ${
                  days === d ? 'bg-primary text-white' : 'bg-white border border-gray-200 text-gray-600 hover:border-gray-300'
                }`}
              >
                {d}d
              </button>
            ))}
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 bg-white border border-gray-200 rounded-xl p-1 mb-6 w-fit">
          {TABS.map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-5 py-2 text-sm font-medium rounded-lg transition-colors ${
                tab === t ? 'bg-primary text-white' : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              {t}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          {tab === 'Infra'     && <InfraTab    days={days} />}
          {tab === 'Model'     && <ModelTab    days={days} />}
          {tab === 'Business'  && <BusinessTab days={days} />}
        </div>
      </div>
    </div>
  )
}
