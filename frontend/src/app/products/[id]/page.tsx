'use client'
import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Image from 'next/image'
import { Star, ShoppingCart, ArrowLeft } from 'lucide-react'
import { Navbar } from '@/components/layout/Navbar'
import { ProductReviews } from '@/components/products/ProductReviews'
import { useCartStore } from '@/store/cartStore'
import { api } from '@/lib/api'
import toast from 'react-hot-toast'

interface ProductDetail {
  id: string
  sku: string
  name: string
  description: string
  category: string
  brand: string
  price: number
  original_price?: number
  stock: number
  rating: number
  review_count: number
  image_url?: string
  is_featured: boolean
  specifications?: string
}

export default function ProductDetailPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const { addItem } = useCartStore()
  const [product, setProduct] = useState<ProductDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  useEffect(() => {
    api.get(`/products/${id}`)
      .then(res => setProduct(res.data))
      .catch(() => setError(true))
      .finally(() => setLoading(false))
  }, [id])

  const handleAddToCart = () => {
    if (!product) return
    addItem({
      id: product.id,
      name: product.name,
      price: product.price,
      imageUrl: product.image_url || '',
      quantity: 1,
    })
    toast.success(`${product.name} added to cart`)
  }

  const discount = product?.original_price
    ? Math.round((1 - product.price / product.original_price) * 100)
    : 0

  let specs: Record<string, string> | null = null
  if (product?.specifications) {
    try { specs = JSON.parse(product.specifications) } catch {}
  }

  return (
    <main className="min-h-screen bg-gray-50">
      <Navbar />
      <div className="max-w-7xl mx-auto px-4 py-8">
        <button
          onClick={() => router.back()}
          className="flex items-center gap-2 text-gray-600 hover:text-gray-900 mb-6"
        >
          <ArrowLeft size={16} /> Back
        </button>

        {loading && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            <div className="h-96 bg-gray-200 animate-pulse rounded-lg" />
            <div className="space-y-4">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="h-6 bg-gray-200 animate-pulse rounded" />
              ))}
            </div>
          </div>
        )}

        {error && (
          <div className="text-center py-16">
            <p className="text-gray-500">Product not found.</p>
          </div>
        )}

        {product && !loading && (
          <>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            <div className="relative h-96 bg-white rounded-lg border">
              <Image
                src={product.image_url || 'https://placehold.co/600x400'}
                alt={product.name}
                fill
                className="object-contain p-8"
              />
              {discount > 0 && (
                <span className="absolute top-4 left-4 bg-red-500 text-white text-sm font-bold px-2 py-1 rounded">
                  -{discount}%
                </span>
              )}
            </div>

            <div className="space-y-4">
              <p className="text-sm text-gray-500">{product.brand} · SKU: {product.sku}</p>
              <h1 className="text-2xl font-bold text-gray-900">{product.name}</h1>

              <div className="flex items-center gap-2">
                <div className="flex">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <Star
                      key={i}
                      size={16}
                      className={i < Math.floor(product.rating) ? 'fill-yellow-400 text-yellow-400' : 'text-gray-300'}
                    />
                  ))}
                </div>
                <span className="text-sm text-gray-500">({product.review_count} reviews)</span>
              </div>

              <div className="flex items-baseline gap-2">
                <span className="text-3xl font-bold text-gray-900">${product.price.toFixed(2)}</span>
                {product.original_price && (
                  <span className="text-lg text-gray-400 line-through">${product.original_price.toFixed(2)}</span>
                )}
              </div>

              <p className="text-sm text-gray-600">{product.description}</p>

              <p className={`text-sm font-medium ${product.stock > 0 ? 'text-green-600' : 'text-red-500'}`}>
                {product.stock > 0 ? `In stock (${product.stock} available)` : 'Out of stock'}
              </p>

              <button
                onClick={handleAddToCart}
                disabled={product.stock === 0}
                className="flex items-center gap-2 bg-primary hover:bg-primary-dark disabled:bg-gray-300 text-white px-6 py-3 rounded font-medium transition-colors"
              >
                <ShoppingCart size={18} /> Add to Cart
              </button>

              {specs && (
                <div className="border-t pt-4">
                  <h2 className="font-semibold text-gray-900 mb-2">Specifications</h2>
                  <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                    {Object.entries(specs).map(([k, v]) => (
                      <>
                        <dt key={`k-${k}`} className="text-gray-500">{k}</dt>
                        <dd key={`v-${k}`} className="text-gray-900">{v}</dd>
                      </>
                    ))}
                  </dl>
                </div>
              )}
            </div>
          </div>

          {/* Customer reviews section */}
          <ProductReviews productId={product.id} />
          </>
        )}
      </div>
    </main>
  )
}
