'use client'
import { useState, useRef, useEffect } from 'react'
import { MessageSquare, X, Send, Loader2, ThumbsUp, ThumbsDown } from 'lucide-react'
import axios from 'axios'
import ReactMarkdown from 'react-markdown'

const CHATBOT_URL = process.env.NEXT_PUBLIC_CHATBOT_URL || 'http://localhost:8004'

interface ProductSource {
  id: string
  name: string
  price: number
}

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: ProductSource[]
  timestamp: Date
  isUnanswered?: boolean
  rating?: 1 | -1
  userMessage?: string
}

export function ChatbotWidget() {
  const [isOpen, setIsOpen] = useState(false)
  const [messages, setMessages] = useState<Message[]>([
    {
      id: '0',
      role: 'assistant',
      content: "Hi! I'm ShopRight's AI assistant. I can help you find products, answer questions about home improvement, and provide expert advice. How can I help you today?",
      timestamp: new Date(),
    },
  ])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [sessionId] = useState(() => crypto.randomUUID())
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const sendMessage = async () => {
    if (!input.trim() || isLoading) return

    const userText = input
    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: userText,
      timestamp: new Date(),
    }
    setMessages(prev => [...prev, userMessage])
    setInput('')
    setIsLoading(true)

    try {
      const response = await axios.post(`${CHATBOT_URL}/chat`, {
        message: userText,
        session_id: sessionId,
        history: messages.slice(-6).map(m => ({ role: m.role, content: m.content })),
      })

      const assistantMessage: Message = {
        id: response.data.message_id,
        role: 'assistant',
        content: response.data.response,
        sources: response.data.sources,
        timestamp: new Date(),
        isUnanswered: response.data.is_unanswered,
        userMessage: userText,
      }
      setMessages(prev => [...prev, assistantMessage])
    } catch {
      setMessages(prev => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: 'Sorry, I encountered an error. Please try again.',
          timestamp: new Date(),
        },
      ])
    } finally {
      setIsLoading(false)
    }
  }

  const submitRating = async (msg: Message, rating: 1 | -1) => {
    setMessages(prev =>
      prev.map(m => (m.id === msg.id ? { ...m, rating } : m))
    )
    try {
      await axios.post(`${CHATBOT_URL}/feedback`, {
        message_id: msg.id,
        session_id: sessionId,
        rating,
        user_message: msg.userMessage || '',
        assistant_response: msg.content,
      })
    } catch {
      // non-critical
    }
  }

  return (
    <>
      {/* FAB */}
      <button
        onClick={() => setIsOpen(true)}
        className={`fixed bottom-6 right-6 bg-primary hover:bg-primary-dark text-white rounded-full p-4 shadow-lg transition-all z-50 ${isOpen ? 'hidden' : 'flex'}`}
      >
        <MessageSquare size={24} />
      </button>

      {/* Chat window */}
      {isOpen && (
        <div className="fixed bottom-6 right-6 w-96 h-[600px] bg-white rounded-xl shadow-2xl flex flex-col z-50 border border-gray-200">
          {/* Header */}
          <div className="bg-primary text-white p-4 rounded-t-xl flex items-center justify-between">
            <div>
              <h3 className="font-bold">ShopRight Assistant</h3>
              <p className="text-xs opacity-80">Powered by AI • Always here to help</p>
            </div>
            <button onClick={() => setIsOpen(false)} className="hover:bg-primary-dark rounded-full p-1">
              <X size={18} />
            </button>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {messages.map(msg => (
              <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className="max-w-[80%] space-y-1">
                  <div
                    className={`rounded-lg px-3 py-2 text-sm ${
                      msg.role === 'user'
                        ? 'bg-primary text-white'
                        : msg.isUnanswered
                        ? 'bg-amber-50 text-gray-800 border border-amber-200'
                        : 'bg-gray-100 text-gray-800'
                    }`}
                  >
                    {msg.role === 'user' ? (
                      <p>{msg.content}</p>
                    ) : (
                      <ReactMarkdown
                        components={{
                          p: ({ children }) => <p className="mb-1 last:mb-0">{children}</p>,
                          ul: ({ children }) => <ul className="list-disc pl-4 space-y-0.5 my-1">{children}</ul>,
                          ol: ({ children }) => <ol className="list-decimal pl-4 space-y-0.5 my-1">{children}</ol>,
                          li: ({ children }) => <li className="text-sm">{children}</li>,
                          strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
                        }}
                      >
                        {msg.content}
                      </ReactMarkdown>
                    )}
                    {msg.isUnanswered && (
                      <p className="text-xs text-amber-600 mt-1">
                        ⚠ Couldn't find a match in our catalog
                      </p>
                    )}
                  </div>
                  {msg.sources && msg.sources.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-1.5 pl-1">
                      {msg.sources.map(source => (
                        <a
                          key={source.id}
                          href={`/products/${source.id}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-xs bg-white border border-primary/30 text-primary rounded-full px-2.5 py-1 hover:bg-primary/5 transition-colors"
                        >
                          {source.name} · <span className="font-medium">${source.price.toFixed(2)}</span>
                        </a>
                      ))}
                    </div>
                  )}
                  {/* Rating buttons — only on assistant messages (not the greeting) */}
                  {msg.role === 'assistant' && msg.id !== '0' && (
                    <div className="flex gap-1 pl-1">
                      <button
                        onClick={() => submitRating(msg, 1)}
                        className={`p-1 rounded transition-colors ${
                          msg.rating === 1 ? 'text-green-600' : 'text-gray-400 hover:text-green-600'
                        }`}
                        title="Helpful"
                      >
                        <ThumbsUp size={13} />
                      </button>
                      <button
                        onClick={() => submitRating(msg, -1)}
                        className={`p-1 rounded transition-colors ${
                          msg.rating === -1 ? 'text-red-500' : 'text-gray-400 hover:text-red-500'
                        }`}
                        title="Not helpful"
                      >
                        <ThumbsDown size={13} />
                      </button>
                    </div>
                  )}
                </div>
              </div>
            ))}
            {isLoading && (
              <div className="flex justify-start">
                <div className="bg-gray-100 rounded-lg px-3 py-2">
                  <Loader2 size={16} className="animate-spin text-primary" />
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Input */}
          <div className="p-4 border-t border-gray-200">
            <div className="flex gap-2">
              <input
                type="text"
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && sendMessage()}
                placeholder="Ask me anything..."
                className="flex-1 border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
              />
              <button
                onClick={sendMessage}
                disabled={!input.trim() || isLoading}
                className="bg-primary hover:bg-primary-dark text-white rounded-lg p-2 disabled:opacity-50 transition-colors"
              >
                <Send size={16} />
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
