import axios from 'axios'

// withCredentials ensures the httpOnly auth_token cookie is sent on every request.
// The token is never accessible to JavaScript — set and cleared by the server only.
export const api = axios.create({
  baseURL: '/api-proxy',
  headers: { 'Content-Type': 'application/json' },
  withCredentials: true,
})

api.interceptors.response.use(
  response => response,
  error => {
    if (error.response?.status === 401) {
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)
