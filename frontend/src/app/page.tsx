import { Navbar } from '@/components/layout/Navbar'
import { HeroBanner } from '@/components/home/HeroBanner'
import { CategoryGrid } from '@/components/home/CategoryGrid'
import { FeaturedProducts } from '@/components/home/FeaturedProducts'
import { Footer } from '@/components/layout/Footer'
import { ChatbotWidget } from '@/components/chatbot/ChatbotWidget'

export default function HomePage() {
  return (
    <main className="min-h-screen bg-gray-50">
      <Navbar />
      <HeroBanner />
      <div className="max-w-7xl mx-auto px-4 py-8 space-y-12">
        <CategoryGrid />
        <FeaturedProducts />
      </div>
      <Footer />
      <ChatbotWidget />
    </main>
  )
}
