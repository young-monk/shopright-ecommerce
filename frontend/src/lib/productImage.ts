const CATEGORY_COLORS: Record<string, { bg: string; text: string }> = {
  'Power Tools':           { bg: 'f97316', text: 'ffffff' },
  'Hand Tools':            { bg: 'f59e0b', text: 'ffffff' },
  'Building Materials':    { bg: '6b7280', text: 'ffffff' },
  'Electrical':            { bg: 'eab308', text: '1f2937' },
  'Plumbing':              { bg: '3b82f6', text: 'ffffff' },
  'Paint & Supplies':      { bg: 'a855f7', text: 'ffffff' },
  'Flooring':              { bg: '92400e', text: 'ffffff' },
  'Outdoor & Garden':      { bg: '16a34a', text: 'ffffff' },
  'Storage & Organization':{ bg: '64748b', text: 'ffffff' },
  'Safety & Security':     { bg: 'ef4444', text: 'ffffff' },
  'Heating & Cooling':     { bg: '0ea5e9', text: 'ffffff' },
}

export function getProductImage(imageUrl: string | null | undefined, category: string): string {
  const isPicsum = imageUrl?.includes('picsum.photos')
  if (imageUrl && !isPicsum) return imageUrl

  const colors = CATEGORY_COLORS[category] ?? { bg: 'e5e7eb', text: '374151' }
  const label = encodeURIComponent(category || 'Product')
  return `https://placehold.co/400x300/${colors.bg}/${colors.text}?text=${label}`
}
