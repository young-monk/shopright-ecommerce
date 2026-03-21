export function Footer() {
  return (
    <footer className="bg-secondary text-gray-300 py-12 mt-16">
      <div className="max-w-7xl mx-auto px-4 grid grid-cols-2 md:grid-cols-4 gap-8">
        <div>
          <h3 className="text-white font-bold mb-4">ShopRight</h3>
          <p className="text-sm">Your one-stop shop for home improvement projects.</p>
        </div>
        <div>
          <h3 className="text-white font-bold mb-4">Customer Service</h3>
          <ul className="space-y-2 text-sm">
            <li><a href="#" className="hover:text-primary">Order Status</a></li>
            <li><a href="#" className="hover:text-primary">Returns</a></li>
            <li><a href="#" className="hover:text-primary">FAQ</a></li>
          </ul>
        </div>
        <div>
          <h3 className="text-white font-bold mb-4">Company</h3>
          <ul className="space-y-2 text-sm">
            <li><a href="#" className="hover:text-primary">About Us</a></li>
            <li><a href="#" className="hover:text-primary">Careers</a></li>
            <li><a href="#" className="hover:text-primary">Store Locator</a></li>
          </ul>
        </div>
        <div>
          <h3 className="text-white font-bold mb-4">Connect</h3>
          <ul className="space-y-2 text-sm">
            <li><a href="#" className="hover:text-primary">Twitter</a></li>
            <li><a href="#" className="hover:text-primary">Facebook</a></li>
            <li><a href="#" className="hover:text-primary">Instagram</a></li>
          </ul>
        </div>
      </div>
      <div className="max-w-7xl mx-auto px-4 mt-8 pt-8 border-t border-gray-700 text-sm text-center">
        © 2024 ShopRight. All rights reserved.
      </div>
    </footer>
  )
}
