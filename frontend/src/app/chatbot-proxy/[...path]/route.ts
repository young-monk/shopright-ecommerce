import { NextRequest } from 'next/server'

const BASE = process.env.CHATBOT_SERVICE_URL || 'http://chatbot:8004'

async function proxy(req: NextRequest, params: Promise<{ path: string[] }>) {
  const { path } = await params
  const url = `${BASE}/${path.join('/')}${req.nextUrl.search}`
  const headers = new Headers(req.headers)
  headers.delete('host')

  const upstream = await fetch(url, {
    method: req.method,
    headers,
    body: ['GET', 'HEAD'].includes(req.method) ? undefined : req.body,
    // @ts-expect-error — Node 18+ duplex required for streaming body
    duplex: 'half',
  })

  return new Response(upstream.body, {
    status: upstream.status,
    headers: upstream.headers,
  })
}

export const GET     = (req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) => proxy(req, params)
export const POST    = (req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) => proxy(req, params)
export const PUT     = (req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) => proxy(req, params)
export const DELETE  = (req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) => proxy(req, params)
export const PATCH   = (req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) => proxy(req, params)
