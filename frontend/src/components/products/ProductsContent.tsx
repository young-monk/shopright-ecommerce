'use client'
import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'next/navigation'
import { ProductCard } from '@/components/products/ProductCard'
import { ProductFilters } from '@/components/products/ProductFilters'
import { api } from '@/lib/api'

interface Filters {
  category: string
  minPrice: number
  maxPrice: number
  search: string
}

export function ProductsContent() {
  const searchParams = useSearchParams()
  const [filters, setFilters] = useState<Filters>({
    category: searchParams.get('category') ?? '',
    minPrice: 0,
    maxPrice: 10000,
    search: searchParams.get('search') ?? '',
  })

  useEffect(() => {
    setFilters((f: Filters) => ({
      ...f,
      category: searchParams.get('category') ?? '',
      search: searchParams.get('search') ?? '',
    }))
  }, [searchParams])

  const { data, isLoading } = useQuery({
    queryKey: ['products', filters],
    queryFn: async () => {
      const res = await api.get('/products', { params: filters })
      return res.data
    },
  })

  return (
    <div className="flex gap-6">
      <aside className="w-64 shrink-0">
        <ProductFilters filters={filters} onChange={setFilters} />
      </aside>
      <div className="flex-1">
        {isLoading ? (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {Array.from({ length: 9 }).map((_, i) => (
              <div key={i} className="card h-72 animate-pulse bg-gray-200" />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {data?.products?.map((product: any) => (
              <ProductCard key={product.id} product={product} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
