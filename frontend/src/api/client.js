import axios from 'axios'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:3456'

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

  // Results & Reports
  results: {
    list: (params = {}) => apiClient.get('/results', { params }),
    get: (jobId) => apiClient.get(`/results/${jobId}`),
    executiveSummary: (jobId) => apiClient.get(`/results/${jobId}/executive-summary`),
    visualizations: (jobId) => apiClient.get(`/results/${jobId}/visualizations`),
    dataQuality: (jobId) => apiClient.get(`/results/${jobId}/data-quality`),
    riskScores: (jobId) => apiClient.get(`/results/${jobId}/risk-scores`),
    delete: (jobId) => apiClient.delete(`/results/${jobId}`),
  },

  // Explainability (EU AI Act Compliant)
  explainability: {
    explanation: (jobId) => apiClient.get(`/explainability/${jobId}/explanation`),
    bankRisks: (jobId, params = {}) => apiClient.get(`/explainability/${jobId}/bank-risks`, { params }),
    contagionAnalysis: (jobId) => apiClient.get(`/explainability/${jobId}/contagion-analysis`),
    executiveSummary: (jobId, format = 'json') => apiClient.get(`/explainability/${jobId}/executive-summary`, { params: { format } }),
    visualization: (jobId, vizName) => `${API_BASE_URL}/api/v1/explainability/${jobId}/visualizations/${vizName}`,
    downloadPredictions: (jobId, format = 'csv') => `${API_BASE_URL}/api/v1/explainability/${jobId}/download/predictions?format=${format}`,
  },

  // Data Catalogue
  catalogue: {
    list: (params = {}) => apiClient.get('/catalogue', { params }),
    get: (id) => apiClient.get(`/catalogue/${id}`),
    categories: () => apiClient.get('/catalogue/categories'),
    regions: () => apiClient.get('/catalogue/regions'),
  },

  // Error Logging & Analytics
  errors: {
    list: (params = {}) => apiClient.get('/errors', { params }),
    get: (id) => apiClient.get(`/errors/${id}`),
    statistics: () => apiClient.get('/errors/statistics'),
    resolve: (id, notes) => apiClient.post(`/errors/${id}/resolve`, null, { params: { resolution_notes: notes } }),
    delete: (id) => apiClient.delete(`/errors/${id}`),
  },
}

export default apiClient
