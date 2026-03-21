import { Suspense } from 'react'
import { Navbar } from '@/components/layout/Navbar'
import { ProductsContent } from '@/components/products/ProductsContent'

export default function ProductsPage() {
  return (
    <main className="min-h-screen bg-gray-50">
      <Navbar />
      <div className="max-w-7xl mx-auto px-4 py-8">
        <h1 className="text-2xl font-bold text-secondary mb-6">Products</h1>
        <Suspense
          fallback={
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              {Array.from({ length: 9 }).map((_, i) => (
                <div key={i} className="card h-72 animate-pulse bg-gray-200" />
              ))}
            </div>
          }
        >
          <ProductsContent />
        </Suspense>
      </div>
    </main>
  )
}
