import Link from 'next/link'

export function HeroBanner() {
  return (
    <div className="bg-secondary text-white py-16 px-4">
      <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center gap-8">
        <div className="flex-1">
          <h1 className="text-4xl font-black mb-4">
            Everything for Your <span className="text-primary">Home Project</span>
          </h1>
          <p className="text-gray-300 text-lg mb-6">
            From tools to materials, find everything you need. Ask our AI assistant for expert advice.
          </p>
          <div className="flex gap-4">
            <Link href="/products" className="btn-primary text-lg px-8 py-3">
              Shop Now
            </Link>
            <Link href="/projects" className="border border-white text-white px-8 py-3 rounded hover:bg-white hover:text-secondary transition-colors">
              Get Inspired
            </Link>
          </div>
        </div>
        <div className="flex-1 flex justify-center">
          <div className="w-80 h-60 bg-primary/20 rounded-xl flex items-center justify-center border border-primary/30">
            <span className="text-6xl">🏠</span>
          </div>
        </div>
      </div>
    </div>
  )
}
