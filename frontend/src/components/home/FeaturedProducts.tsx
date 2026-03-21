'use client'
import { useQuery } from '@tanstack/react-query'
import { ProductCard } from '@/components/products/ProductCard'
import { api } from '@/lib/api'

export function FeaturedProducts() {
  const { data, isLoading } = useQuery({
    queryKey: ['featured-products'],
    queryFn: () => api.get('/products?featured=true&limit=8').then(r => r.data),
  })

  return (
    <section>
      <h2 className="text-2xl font-bold text-secondary mb-6">Featured Products</h2>
      {isLoading ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="h-72 bg-gray-200 rounded-lg animate-pulse" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
          {data?.products?.map((product: any) => (
            <ProductCard key={product.id} product={product} />
          ))}
        </div>
      )}
    </section>
  )
}
