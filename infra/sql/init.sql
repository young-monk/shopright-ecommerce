-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Products table
CREATE TABLE IF NOT EXISTS products (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sku VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(500) NOT NULL,
    description TEXT,
    category VARCHAR(100),
    brand VARCHAR(100),
    price DECIMAL(10,2) NOT NULL,
    original_price DECIMAL(10,2),
    stock INTEGER DEFAULT 0,
    rating DECIMAL(3,2) DEFAULT 0.0,
    review_count INTEGER DEFAULT 0,
    image_url VARCHAR(500),
    is_featured BOOLEAN DEFAULT FALSE,
    specifications TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Product embeddings for RAG
CREATE TABLE IF NOT EXISTS product_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID UNIQUE REFERENCES products(id) ON DELETE CASCADE,
    name VARCHAR(500),
    description TEXT,
    category VARCHAR(100),
    brand VARCHAR(100),
    price DECIMAL(10,2),
    specifications TEXT,
    embedding vector(768),  -- text-embedding-004 dimensions
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create IVFFlat index for fast similarity search
CREATE INDEX IF NOT EXISTS product_embeddings_ivfflat
    ON product_embeddings USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    is_admin BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Orders table
CREATE TABLE IF NOT EXISTS orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    items TEXT NOT NULL,  -- JSON
    subtotal DECIMAL(10,2),
    tax DECIMAL(10,2),
    shipping DECIMAL(10,2),
    total DECIMAL(10,2),
    shipping_address TEXT,  -- JSON
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Seed sample products
INSERT INTO products (sku, name, description, category, brand, price, original_price, stock, rating, review_count, is_featured, specifications)
VALUES
  ('DWD-001', 'DEWALT 20V MAX Drill Driver Kit', 'Professional-grade cordless drill with 2 batteries, charger, and carrying case. 1/2-inch chuck, 15+1 clutch settings.', 'Tools', 'DEWALT', 149.99, 179.99, 50, 4.8, 2340, true, '{"voltage": "20V", "chuck_size": "1/2 inch", "max_torque": "300 UWO", "weight": "3.62 lbs"}'),
  ('MIL-002', 'Milwaukee M18 Circular Saw', 'Cordless circular saw with 6-1/2 inch blade. Compatible with all M18 batteries. 5,000 RPM for fast cutting.', 'Tools', 'Milwaukee', 199.99, 229.99, 30, 4.7, 1876, true, '{"blade_size": "6-1/2 inch", "no_load_rpm": "5000", "bevel": "0-50 degrees", "weight": "6.2 lbs"}'),
  ('OWC-003', 'Owen Corning R-13 Insulation Batts', 'Fiberglass insulation batts for 2x4 walls. 15-inch wide, covers 40 sq ft per bag. Pink Panther brand.', 'Building Materials', 'Owens Corning', 24.99, null, 200, 4.5, 890, false, '{"r_value": "R-13", "width": "15 inch", "coverage": "40 sq ft", "thickness": "3.5 inch"}'),
  ('LEV-004', 'Leviton Smart Outlet', 'WiFi-enabled smart plug with energy monitoring. Works with Alexa, Google Home, and Apple HomeKit. No hub required.', 'Electrical', 'Leviton', 34.99, 44.99, 150, 4.6, 3210, true, '{"voltage": "120V", "amperage": "15A", "connectivity": "WiFi 2.4GHz", "smart_home": "Alexa, Google, Apple HomeKit"}'),
  ('MOE-005', 'Moen Arbor Kitchen Faucet', 'Pull-down kitchen faucet with Reflex system for easy movement. Lifetime limited warranty. Chrome finish.', 'Plumbing', 'Moen', 189.99, 249.99, 45, 4.7, 4120, true, '{"finish": "Chrome", "type": "Pull-down", "spout_reach": "8.69 inch", "spout_height": "16.63 inch"}'),
  ('BHR-006', 'Behr Premium Plus Paint - Eggshell', 'Interior paint and primer in one. Low-VOC, mildew resistant. One coat coverage. 1 gallon.', 'Paint', 'Behr', 42.99, null, 300, 4.4, 5670, false, '{"finish": "Eggshell", "coverage": "250-400 sq ft", "dry_time": "1 hour", "voc": "Low-VOC (<50 g/L)"}'),
  ('PER-007', 'Pergo TimberCraft Laminate Flooring', 'Waterproof laminate flooring, 12mm thick. Click-lock installation, 20 mil wear layer. Per case (16.7 sq ft).', 'Flooring', 'Pergo', 67.99, 79.99, 80, 4.6, 1450, true, '{"thickness": "12mm", "wear_layer": "20 mil", "coverage": "16.7 sq ft/case", "waterproof": true}'),
  ('GRE-008', 'Green Works 40V Lawn Mower', 'Cordless electric lawn mower with 20-inch deck. Self-propelled, 40V battery included. Up to 45 min runtime.', 'Outdoor', 'Greenworks', 349.99, 399.99, 25, 4.5, 2100, true, '{"voltage": "40V", "deck_width": "20 inch", "runtime": "45 min", "self_propelled": true}')
ON CONFLICT (sku) DO NOTHING;
