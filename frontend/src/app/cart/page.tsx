'use client'
import Image from 'next/image'
import Link from 'next/link'
import { Trash2, Plus, Minus, ShoppingCart } from 'lucide-react'
import { Navbar } from '@/components/layout/Navbar'
import { useCartStore } from '@/store/cartStore'

export default function CartPage() {
  const { items, removeItem, updateQuantity, total, clearCart } = useCartStore()

  if (items.length === 0) {
    return (
      <main className="min-h-screen bg-gray-50">
        <Navbar />
        <div className="max-w-3xl mx-auto px-4 py-16 text-center">
          <ShoppingCart size={48} className="mx-auto text-gray-300 mb-4" />
          <h1 className="text-2xl font-bold text-gray-900 mb-2">Your cart is empty</h1>
          <p className="text-gray-500 mb-6">Add some products to get started.</p>
          <Link href="/products" className="bg-primary hover:bg-primary-dark text-white px-6 py-3 rounded font-medium transition-colors">
            Browse Products
          </Link>
        </div>
      </main>
    )
  }

  return (
    <main className="min-h-screen bg-gray-50">
      <Navbar />
      <div className="max-w-5xl mx-auto px-4 py-8">
        <h1 className="text-2xl font-bold text-gray-900 mb-6">Shopping Cart ({items.length} {items.length === 1 ? 'item' : 'items'})</h1>

        <div className="flex flex-col lg:flex-row gap-6">
          {/* Items list */}
          <div className="flex-1 space-y-4">
            {items.map(item => (
              <div key={item.id} className="bg-white rounded-lg border p-4 flex gap-4">
                <div className="relative w-24 h-24 shrink-0 bg-gray-100 rounded">
                  <Image
                    src={item.imageUrl || 'https://placehold.co/100x100'}
                    alt={item.name}
                    fill
                    className="object-contain p-2"
                  />
                </div>
                <div className="flex-1 min-w-0">
                  <Link href={`/products/${item.id}`} className="text-sm font-medium text-gray-900 hover:text-primary line-clamp-2">
                    {item.name}
                  </Link>
                  <p className="text-lg font-bold text-gray-900 mt-1">${item.price.toFixed(2)}</p>
                  <div className="flex items-center gap-3 mt-2">
                    <div className="flex items-center border rounded">
                      <button
                        onClick={() => updateQuantity(item.id, item.quantity - 1)}
                        className="p-1.5 hover:bg-gray-100 transition-colors"
                      >
                        <Minus size={14} />
                      </button>
                      <span className="px-3 text-sm font-medium">{item.quantity}</span>
                      <button
                        onClick={() => updateQuantity(item.id, item.quantity + 1)}
                        className="p-1.5 hover:bg-gray-100 transition-colors"
                      >
                        <Plus size={14} />
                      </button>
                    </div>
                    <button
                      onClick={() => removeItem(item.id)}
                      className="text-red-500 hover:text-red-700 transition-colors"
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <p className="font-bold text-gray-900">${(item.price * item.quantity).toFixed(2)}</p>
                </div>
              </div>
            ))}

            <button onClick={clearCart} className="text-sm text-red-500 hover:text-red-700 transition-colors">
              Remove all items
            </button>
          </div>

          {/* Order summary */}
          <div className="lg:w-80">
            <div className="bg-white rounded-lg border p-6 space-y-4 sticky top-4">
              <h2 className="text-lg font-bold text-gray-900">Order Summary</h2>
              <div className="space-y-2 text-sm">
                {items.map(item => (
                  <div key={item.id} className="flex justify-between text-gray-600">
                    <span className="line-clamp-1 flex-1 mr-2">{item.name} × {item.quantity}</span>
                    <span className="shrink-0">${(item.price * item.quantity).toFixed(2)}</span>
                  </div>
                ))}
              </div>
              <div className="border-t pt-4 flex justify-between font-bold text-gray-900">
                <span>Total</span>
                <span>${total().toFixed(2)}</span>
              </div>
              <p className="text-xs text-green-600">Free shipping on this order!</p>
              <Link href="/checkout" className="block w-full bg-primary hover:bg-primary-dark text-white py-3 rounded font-medium transition-colors text-center">
                Proceed to Checkout
              </Link>
              <Link href="/products" className="block text-center text-sm text-primary hover:underline">
                Continue Shopping
              </Link>
            </div>
          </div>
        </div>
      </div>
    </main>
  )
}
