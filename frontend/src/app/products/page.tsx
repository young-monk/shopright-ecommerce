'use client'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Navbar } from '@/components/layout/Navbar'
import { ProductCard } from '@/components/products/ProductCard'
import { ProductFilters } from '@/components/products/ProductFilters'
import { api } from '@/lib/api'

export default function ProductsPage() {
  const [filters, setFilters] = useState({ category: '', minPrice: 0, maxPrice: 10000, search: '' })

  const { data, isLoading } = useQuery({
    queryKey: ['products', filters],
    queryFn: () => api.get('/products', { params: filters }).then(r => r.data),
  })

  return (
    <main className="min-h-screen bg-gray-50">
      <Navbar />
      <div className="max-w-7xl mx-auto px-4 py-8">
        <h1 className="text-2xl font-bold text-secondary mb-6">Products</h1>
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
      </div>
    </main>
  )
}
