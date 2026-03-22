'use client'
import { useEffect, useState } from 'react'
import { Star, CheckCircle, ChevronLeft, ChevronRight } from 'lucide-react'
import { api } from '@/lib/api'

interface Review {
  id: string
  stars: number
  title: string | null
  body: string | null
  author: string | null
  review_date: string | null
  verified: boolean
}

interface ReviewsData {
  reviews: Review[]
  total: number
  limit: number
  offset: number
  pages: number
  star_distribution: Record<string, number>
}

type SortOption = 'recent' | 'highest' | 'lowest'

const LIMIT = 5

function StarRow({ filled, total = 5 }: { filled: number; total?: number }) {
  return (
    <div className="flex gap-0.5">
      {Array.from({ length: total }).map((_, i) => (
        <Star
          key={i}
          size={14}
          className={i < filled ? 'fill-yellow-400 text-yellow-400' : 'text-gray-300'}
        />
      ))}
    </div>
  )
}

function DistributionBar({ stars, count, total }: { stars: number; count: number; total: number }) {
  const pct = total > 0 ? Math.round((count / total) * 100) : 0
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="w-6 text-right text-gray-500">{stars}</span>
      <Star size={12} className="fill-yellow-400 text-yellow-400 shrink-0" />
      <div className="flex-1 bg-gray-200 rounded-full h-2">
        <div className="bg-yellow-400 h-2 rounded-full transition-all" style={{ width: `${pct}%` }} />
      </div>
      <span className="w-8 text-right text-gray-500">{count}</span>
    </div>
  )
}

function ReviewSkeleton() {
  return (
    <div className="border-b pb-4 animate-pulse">
      <div className="flex gap-2 mb-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="w-3 h-3 bg-gray-200 rounded" />
        ))}
      </div>
      <div className="h-4 bg-gray-200 rounded w-2/3 mb-2" />
      <div className="space-y-1">
        <div className="h-3 bg-gray-200 rounded w-full" />
        <div className="h-3 bg-gray-200 rounded w-4/5" />
      </div>
    </div>
  )
}

export function ProductReviews({ productId }: { productId: string }) {
  const [data, setData] = useState<ReviewsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [sort, setSort] = useState<SortOption>('recent')
  const [page, setPage] = useState(0)

  useEffect(() => {
    setLoading(true)
    api
      .get(`/products/${productId}/reviews`, {
        params: { limit: LIMIT, offset: page * LIMIT, sort },
      })
      .then(res => setData(res.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [productId, sort, page])

  const totalPages = data?.pages ?? 0
  const avgRating =
    data && data.total > 0
      ? Object.entries(data.star_distribution).reduce(
          (sum, [stars, cnt]) => sum + Number(stars) * cnt,
          0
        ) / data.total
      : 0

  if (!loading && data?.total === 0) return null

  return (
    <section className="mt-10">
      <h2 className="text-xl font-bold text-gray-900 mb-6">Customer Reviews</h2>

      {/* Summary row */}
      {data && data.total > 0 && (
        <div className="flex flex-col sm:flex-row gap-8 mb-6">
          <div className="flex flex-col items-center justify-center min-w-[100px]">
            <span className="text-5xl font-bold text-gray-900">{avgRating.toFixed(1)}</span>
            <StarRow filled={Math.round(avgRating)} />
            <span className="text-sm text-gray-500 mt-1">{data.total} reviews</span>
          </div>
          <div className="flex-1 space-y-1.5 justify-center flex flex-col">
            {[5, 4, 3, 2, 1].map(s => (
              <DistributionBar
                key={s}
                stars={s}
                count={data.star_distribution[String(s)] ?? 0}
                total={data.total}
              />
            ))}
          </div>
        </div>
      )}

      {/* Sort controls */}
      <div className="flex items-center gap-2 mb-4">
        <span className="text-sm text-gray-600">Sort by:</span>
        {(['recent', 'highest', 'lowest'] as SortOption[]).map(opt => (
          <button
            key={opt}
            onClick={() => { setSort(opt); setPage(0) }}
            className={`px-3 py-1 text-sm rounded-full border transition-colors ${
              sort === opt
                ? 'bg-primary text-white border-primary'
                : 'bg-white text-gray-600 border-gray-300 hover:border-gray-400'
            }`}
          >
            {opt.charAt(0).toUpperCase() + opt.slice(1)}
          </button>
        ))}
      </div>

      {/* Review list */}
      <div className="space-y-5">
        {loading
          ? Array.from({ length: 3 }).map((_, i) => <ReviewSkeleton key={i} />)
          : data?.reviews.map(review => (
              <div key={review.id} className="border-b pb-5">
                <div className="flex items-center gap-2 mb-1">
                  <StarRow filled={review.stars} />
                  {review.verified && (
                    <span className="flex items-center gap-1 text-xs text-green-600">
                      <CheckCircle size={12} /> Verified Purchase
                    </span>
                  )}
                </div>
                {review.title && (
                  <p className="font-semibold text-gray-900 text-sm mb-1">{review.title}</p>
                )}
                {review.body && (
                  <p className="text-sm text-gray-600 leading-relaxed">{review.body}</p>
                )}
                <div className="flex gap-3 mt-2 text-xs text-gray-400">
                  {review.author && <span>{review.author}</span>}
                  {review.review_date && (
                    <span>
                      {new Date(review.review_date).toLocaleDateString('en-US', {
                        year: 'numeric', month: 'short', day: 'numeric',
                      })}
                    </span>
                  )}
                </div>
              </div>
            ))}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-6">
          <button
            onClick={() => setPage(p => p - 1)}
            disabled={page === 0}
            className="flex items-center gap-1 px-3 py-1.5 text-sm border rounded disabled:opacity-40 hover:bg-gray-50"
          >
            <ChevronLeft size={14} /> Previous
          </button>
          <span className="text-sm text-gray-500">
            Page {page + 1} of {totalPages}
          </span>
          <button
            onClick={() => setPage(p => p + 1)}
            disabled={page >= totalPages - 1}
            className="flex items-center gap-1 px-3 py-1.5 text-sm border rounded disabled:opacity-40 hover:bg-gray-50"
          >
            Next <ChevronRight size={14} />
          </button>
        </div>
      )}
    </section>
  )
}
