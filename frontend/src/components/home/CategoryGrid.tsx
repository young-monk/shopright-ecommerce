import Link from 'next/link'
import { CATEGORIES } from '@/lib/categories'

export function CategoryGrid() {
  return (
    <section>
      <h2 className="text-2xl font-bold text-secondary mb-6">Shop by Category</h2>
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 xl:grid-cols-11 gap-4">
        {CATEGORIES.map(cat => (
          <Link
            key={cat.slug}
            href={`/products?category=${cat.slug}`}
            className="card p-4 text-center hover:shadow-lg transition-shadow group"
          >
            <div className="text-3xl mb-2">{cat.icon}</div>
            <p className="text-xs font-medium text-gray-700 group-hover:text-primary">{cat.name}</p>
          </Link>
        ))}
      </div>
    </section>
  )
}
