'use client'
import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { Navbar } from '@/components/layout/Navbar'
import { useCartStore } from '@/store/cartStore'
import { api } from '@/lib/api'
import { Loader2, CheckCircle } from 'lucide-react'

interface Address {
  full_name: string
  address_line1: string
  address_line2: string
  city: string
  state: string
  zip_code: string
  country: string
}

const EMPTY_ADDRESS: Address = {
  full_name: '', address_line1: '', address_line2: '',
  city: '', state: '', zip_code: '', country: 'US',
}

export default function CheckoutPage() {
  const router = useRouter()
  const { items, total, clearCart } = useCartStore()
  const [address, setAddress] = useState<Address>(EMPTY_ADDRESS)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [orderId, setOrderId] = useState<string | null>(null)

  const subtotal = total()
  const shipping = subtotal >= 50 ? 0 : 9.99
  const tax = Math.round(subtotal * 0.08 * 100) / 100
  const orderTotal = Math.round((subtotal + shipping + tax) * 100) / 100

  const field = (key: keyof Address) => ({
    value: address[key],
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
      setAddress(prev => ({ ...prev, [key]: e.target.value })),
  })

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      const { data } = await api.post('/orders', {
        user_id: 'guest',
        items: items.map(i => ({
          product_id: i.id,
          name: i.name,
          quantity: i.quantity,
          price: i.price,
        })),
        shipping_address: address,
      })
      clearCart()
      setOrderId(data.id)
    } catch {
      setError('Failed to place order. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  if (items.length === 0 && !orderId) {
    return (
      <main className="min-h-screen bg-gray-50">
        <Navbar />
        <div className="max-w-3xl mx-auto px-4 py-16 text-center">
          <p className="text-gray-500 mb-4">Your cart is empty.</p>
          <Link href="/products" className="bg-primary text-white px-6 py-3 rounded font-medium">Browse Products</Link>
        </div>
      </main>
    )
  }

  if (orderId) {
    return (
      <main className="min-h-screen bg-gray-50">
        <Navbar />
        <div className="max-w-lg mx-auto px-4 py-16 text-center">
          <CheckCircle size={56} className="mx-auto text-green-500 mb-4" />
          <h1 className="text-2xl font-bold text-gray-900 mb-2">Order Placed!</h1>
          <p className="text-gray-500 mb-1">Thank you for your order.</p>
          <p className="text-sm text-gray-400 mb-8">Order ID: <span className="font-mono">{orderId}</span></p>
          <Link href="/products" className="bg-primary hover:bg-primary-dark text-white px-6 py-3 rounded font-medium transition-colors">
            Continue Shopping
          </Link>
        </div>
      </main>
    )
  }

  return (
    <main className="min-h-screen bg-gray-50">
      <Navbar />
      <div className="max-w-5xl mx-auto px-4 py-8">
        <h1 className="text-2xl font-bold text-gray-900 mb-6">Checkout</h1>

        <form onSubmit={handleSubmit} className="flex flex-col lg:flex-row gap-6">
          {/* Shipping form */}
          <div className="flex-1 bg-white rounded-lg border p-6 space-y-4">
            <h2 className="text-lg font-semibold text-gray-900">Shipping Address</h2>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Full name</label>
              <input required className="w-full border rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary" {...field('full_name')} />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Address line 1</label>
              <input required className="w-full border rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary" {...field('address_line1')} />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Address line 2 <span className="text-gray-400">(optional)</span></label>
              <input className="w-full border rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary" {...field('address_line2')} />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">City</label>
                <input required className="w-full border rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary" {...field('city')} />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">State</label>
                <input required maxLength={2} placeholder="e.g. CA" className="w-full border rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary" {...field('state')} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">ZIP code</label>
                <input required className="w-full border rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary" {...field('zip_code')} />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Country</label>
                <select className="w-full border rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary" {...field('country')}>
                  <option value="US">United States</option>
                  <option value="CA">Canada</option>
                  <option value="GB">United Kingdom</option>
                </select>
              </div>
            </div>

            {error && <p className="text-red-500 text-sm">{error}</p>}
          </div>

          {/* Order summary */}
          <div className="lg:w-80">
            <div className="bg-white rounded-lg border p-6 space-y-4 sticky top-4">
              <h2 className="text-lg font-semibold text-gray-900">Order Summary</h2>
              <div className="space-y-2 text-sm">
                {items.map(item => (
                  <div key={item.id} className="flex justify-between text-gray-600">
                    <span className="line-clamp-1 flex-1 mr-2">{item.name} × {item.quantity}</span>
                    <span className="shrink-0">${(item.price * item.quantity).toFixed(2)}</span>
                  </div>
                ))}
              </div>
              <div className="border-t pt-4 space-y-1 text-sm">
                <div className="flex justify-between text-gray-600">
                  <span>Subtotal</span><span>${subtotal.toFixed(2)}</span>
                </div>
                <div className="flex justify-between text-gray-600">
                  <span>Shipping</span>
                  <span>{shipping === 0 ? <span className="text-green-600">Free</span> : `$${shipping.toFixed(2)}`}</span>
                </div>
                <div className="flex justify-between text-gray-600">
                  <span>Tax (8%)</span><span>${tax.toFixed(2)}</span>
                </div>
                <div className="flex justify-between font-bold text-gray-900 pt-2 border-t">
                  <span>Total</span><span>${orderTotal.toFixed(2)}</span>
                </div>
              </div>
              <button
                type="submit"
                disabled={submitting}
                className="w-full bg-primary hover:bg-primary-dark text-white py-3 rounded font-medium transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {submitting ? <><Loader2 size={16} className="animate-spin" /> Placing order...</> : 'Place Order'}
              </button>
              <Link href="/cart" className="block text-center text-sm text-primary hover:underline">
                Back to cart
              </Link>
            </div>
          </div>
        </form>
      </div>
    </main>
  )
}
