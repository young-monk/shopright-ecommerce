'use client'
import Link from 'next/link'
import { ShoppingCart, Search, User, Menu } from 'lucide-react'
import { useCartStore } from '@/store/cartStore'
import { useState } from 'react'
import { useRouter } from 'next/navigation'

export function Navbar() {
  const { items } = useCartStore()
  const [search, setSearch] = useState('')
  const router = useRouter()
  const itemCount = items.reduce((sum, item) => sum + item.quantity, 0)

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    router.push(`/products?search=${encodeURIComponent(search)}`)
  }

  return (
    <header className="bg-secondary text-white">
      {/* Top bar */}
      <div className="bg-primary py-1 text-center text-sm">
        Free shipping on orders over $50
      </div>
      <nav className="max-w-7xl mx-auto px-4 py-3">
        <div className="flex items-center gap-4">
          {/* Logo */}
          <Link href="/" className="text-2xl font-black text-primary shrink-0">
            ShopRight
          </Link>

          {/* Search */}
          <form onSubmit={handleSearch} className="flex-1 flex">
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search products, brands, and more..."
              className="flex-1 px-4 py-2 rounded-l text-gray-900 text-sm focus:outline-none"
            />
            <button type="submit" className="bg-primary hover:bg-primary-dark px-4 py-2 rounded-r">
              <Search size={18} />
            </button>
          </form>

          {/* Icons */}
          <div className="flex items-center gap-4">
            <Link href="/account" className="flex items-center gap-1 hover:text-primary text-sm">
              <User size={20} />
              <span className="hidden md:block">Account</span>
            </Link>
            <Link href="/cart" className="flex items-center gap-1 hover:text-primary text-sm relative">
              <ShoppingCart size={20} />
              {itemCount > 0 && (
                <span className="absolute -top-2 -right-2 bg-primary text-white text-xs rounded-full w-5 h-5 flex items-center justify-center">
                  {itemCount}
                </span>
              )}
              <span className="hidden md:block">Cart</span>
            </Link>
          </div>
        </div>

        {/* Category nav */}
        <div className="flex gap-6 mt-2 text-sm">
          {['Tools', 'Building Materials', 'Electrical', 'Plumbing', 'Paint', 'Flooring', 'Outdoor'].map(cat => (
            <Link key={cat} href={`/products?category=${cat}`} className="hover:text-primary">
              {cat}
            </Link>
          ))}
        </div>
      </nav>
    </header>
  )
}
