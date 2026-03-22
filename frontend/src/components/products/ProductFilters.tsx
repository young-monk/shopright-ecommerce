'use client'
import { CATEGORY_NAMES } from '@/lib/categories'

interface Filters {
  category: string
  minPrice: number
  maxPrice: number
  search: string
}

export function ProductFilters({ filters, onChange }: { filters: Filters; onChange: (f: Filters) => void }) {
  return (
    <div className="card p-4 space-y-6">
      <div>
        <h3 className="font-semibold text-gray-900 mb-3">Category</h3>
        <div className="space-y-2">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="radio"
              name="category"
              value=""
              checked={filters.category === ''}
              onChange={() => onChange({ ...filters, category: '' })}
              className="accent-primary"
            />
            <span className="text-sm">All Categories</span>
          </label>
          {CATEGORY_NAMES.map(cat => (
            <label key={cat} className="flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                name="category"
                value={cat}
                checked={filters.category === cat}
                onChange={() => onChange({ ...filters, category: cat })}
                className="accent-primary"
              />
              <span className="text-sm">{cat}</span>
            </label>
          ))}
        </div>
      </div>

      <div>
        <h3 className="font-semibold text-gray-900 mb-3">Price Range</h3>
        <div className="space-y-2">
          <div className="flex gap-2 items-center">
            <input
              type="number"
              value={filters.minPrice}
              onChange={e => onChange({ ...filters, minPrice: Number(e.target.value) })}
              className="w-full border rounded px-2 py-1 text-sm"
              placeholder="Min"
            />
            <span className="text-gray-400">-</span>
            <input
              type="number"
              value={filters.maxPrice}
              onChange={e => onChange({ ...filters, maxPrice: Number(e.target.value) })}
              className="w-full border rounded px-2 py-1 text-sm"
              placeholder="Max"
            />
          </div>
        </div>
      </div>
    </div>
  )
}
