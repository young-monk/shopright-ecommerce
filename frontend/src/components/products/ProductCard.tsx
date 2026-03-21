'use client'
import Image from 'next/image'
import Link from 'next/link'
import { Star, ShoppingCart } from 'lucide-react'
import { useCartStore } from '@/store/cartStore'
import { getProductImage } from '@/lib/productImage'
import toast from 'react-hot-toast'

interface Product {
  id: string
  name: string
  price: number
  originalPrice?: number
  rating: number
  reviewCount: number
  imageUrl: string
  brand: string
  sku: string
  category?: string
}

export function ProductCard({ product }: { product: Product }) {
  const { addItem } = useCartStore()

  const handleAddToCart = (e: React.MouseEvent) => {
    e.preventDefault()
    addItem({ id: product.id, name: product.name, price: product.price, imageUrl: product.imageUrl, quantity: 1 })
    toast.success(`${product.name} added to cart`)
  }

  const discount = product.originalPrice
    ? Math.round((1 - product.price / product.originalPrice) * 100)
    : 0

  return (
    <Link href={`/products/${product.id}`} className="card group hover:shadow-lg transition-shadow">
      <div className="relative h-48 bg-gray-100">
        <Image
          src={getProductImage(product.imageUrl, product.category ?? '')}
          alt={product.name}
          fill
          className="object-contain p-4"
        />
        {discount > 0 && (
          <span className="absolute top-2 left-2 bg-red-500 text-white text-xs font-bold px-2 py-1 rounded">
            -{discount}%
          </span>
        )}
      </div>
      <div className="p-4">
        <p className="text-xs text-gray-500 mb-1">{product.brand}</p>
        <h3 className="text-sm font-medium text-gray-900 line-clamp-2 mb-2 group-hover:text-primary">
          {product.name}
        </h3>
        <div className="flex items-center gap-1 mb-2">
          <div className="flex">
            {Array.from({ length: 5 }).map((_, i) => (
              <Star
                key={i}
                size={12}
                className={i < Math.floor(product.rating) ? 'fill-yellow-400 text-yellow-400' : 'text-gray-300'}
              />
            ))}
          </div>
          <span className="text-xs text-gray-500">({product.reviewCount})</span>
        </div>
        <div className="flex items-center justify-between">
          <div>
            <span className="text-lg font-bold text-gray-900">${product.price.toFixed(2)}</span>
            {product.originalPrice && (
              <span className="text-sm text-gray-400 line-through ml-1">${product.originalPrice.toFixed(2)}</span>
            )}
          </div>
          <button
            onClick={handleAddToCart}
            className="bg-primary hover:bg-primary-dark text-white p-2 rounded transition-colors"
          >
            <ShoppingCart size={16} />
          </button>
        </div>
      </div>
    </Link>
  )
}
