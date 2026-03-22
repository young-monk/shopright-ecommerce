export interface Category {
  name: string
  slug: string
  icon: string
}

export const CATEGORIES: Category[] = [
  { name: 'Power Tools',            slug: 'Power Tools',            icon: '🔩' },
  { name: 'Hand Tools',             slug: 'Hand Tools',             icon: '🔧' },
  { name: 'Building Materials',     slug: 'Building Materials',     icon: '🧱' },
  { name: 'Electrical',             slug: 'Electrical',             icon: '⚡' },
  { name: 'Plumbing',               slug: 'Plumbing',               icon: '🚿' },
  { name: 'Paint & Supplies',       slug: 'Paint & Supplies',       icon: '🎨' },
  { name: 'Flooring',               slug: 'Flooring',               icon: '🪵' },
  { name: 'Outdoor & Garden',       slug: 'Outdoor & Garden',       icon: '🌱' },
  { name: 'Storage & Organization', slug: 'Storage & Organization', icon: '📦' },
  { name: 'Safety & Security',      slug: 'Safety & Security',      icon: '🔒' },
  { name: 'Heating & Cooling',      slug: 'Heating & Cooling',      icon: '❄️' },
]

export const CATEGORY_NAMES = CATEGORIES.map(c => c.name)
