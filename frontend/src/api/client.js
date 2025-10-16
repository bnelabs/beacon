import axios from 'axios'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

// Create axios instance
const apiClient = axios.create({
  baseURL: `${API_BASE_URL}/api/v1`,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor
apiClient.interceptors.request.use(
  (config) => {
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// Response interceptor
apiClient.interceptors.response.use(
  (response) => {
    return response
  },
  (error) => {
    // Extract user-friendly error message
    let message = 'An unexpected error occurred'
    if (error.response?.data?.detail) {
      const detail = error.response.data.detail
      if (typeof detail === 'object' && detail.user_friendly) {
        message = detail.user_friendly
      } else if (typeof detail === 'string') {
        message = detail
      }
    } else if (error.message) {
      message = error.message
    }

    // Attach user-friendly message to error
    error.userFriendlyMessage = message
    return Promise.reject(error)
  }
)

// API methods
export const api = {
  // Data Sources
  dataSources: {
    list: (enabledOnly = false) => apiClient.get('/data-sources', { params: { enabled_only: enabledOnly } }),
    get: (id) => apiClient.get(`/data-sources/${id}`),
    create: (data) => apiClient.post('/data-sources', data),
    update: (id, data) => apiClient.put(`/data-sources/${id}`, data),
    delete: (id) => apiClient.delete(`/data-sources/${id}`),
    test: (data) => apiClient.post('/data-sources/test', data),
  },

  // Assets
  assets: {
    list: (params = {}) => apiClient.get('/assets', { params }),
    get: (id) => apiClient.get(`/assets/${id}`),
    create: (data) => apiClient.post('/assets', data),
    bulkCreate: (assets) => apiClient.post('/assets/bulk', { assets }),
    update: (id, data) => apiClient.put(`/assets/${id}`, data),
    delete: (id) => apiClient.delete(`/assets/${id}`),
  },

  // Jobs
  jobs: {
    list: (params = {}) => apiClient.get('/jobs', { params }),
    get: (id) => apiClient.get(`/jobs/${id}`),
    create: (data) => apiClient.post('/jobs', data),
    cancel: (id) => apiClient.delete(`/jobs/${id}`),
  },

  // Configuration
  config: {
    get: () => apiClient.get('/config'),
    updateModel: (data) => apiClient.put('/config/model', data),
    updateData: (data) => apiClient.put('/config/data', data),
    updateTraining: (data) => apiClient.put('/config/training', data),
  },

  // System
  system: {
    status: () => apiClient.get('/system/status'),
    recommendations: () => apiClient.get('/system/resources/recommendations'),
  },
}

export default apiClient
