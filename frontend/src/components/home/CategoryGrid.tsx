import Link from 'next/link'

const CATEGORIES = [
  { name: 'Power Tools',            icon: '🔩', slug: 'Power Tools' },
  { name: 'Hand Tools',             icon: '🔧', slug: 'Hand Tools' },
  { name: 'Building Materials',     icon: '🧱', slug: 'Building Materials' },
  { name: 'Electrical',             icon: '⚡', slug: 'Electrical' },
  { name: 'Plumbing',               icon: '🚿', slug: 'Plumbing' },
  { name: 'Paint & Supplies',       icon: '🎨', slug: 'Paint & Supplies' },
  { name: 'Flooring',               icon: '🪵', slug: 'Flooring' },
  { name: 'Outdoor & Garden',       icon: '🌱', slug: 'Outdoor & Garden' },
  { name: 'Storage & Organization', icon: '📦', slug: 'Storage & Organization' },
  { name: 'Safety & Security',      icon: '🔒', slug: 'Safety & Security' },
  { name: 'Heating & Cooling',      icon: '❄️', slug: 'Heating & Cooling' },
]

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
