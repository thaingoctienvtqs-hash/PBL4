import axios from 'axios'
import type { Alert, AlertOrigin, IntegrationStatus } from '../types'

export const api = axios.create({ baseURL: '/api/v1', timeout: 12000, headers: { 'Content-Type': 'application/json' } })
let accessToken: string | null = null

export function setAccessToken(token: string | null) {
  accessToken = token
}

api.interceptors.request.use((config) => {
  if (accessToken) config.headers.Authorization = `Bearer ${accessToken}`
  return config
})

api.interceptors.response.use((response) => response, (error: unknown) => {
  if (axios.isAxiosError(error) && error.response?.status === 401 && accessToken) {
    accessToken = null
    window.dispatchEvent(new Event('artguard:session-expired'))
  }
  return Promise.reject(error)
})

export function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail: unknown = error.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) return detail.map((entry) => entry.msg).join(' · ')
    if (!error.response) return 'Không kết nối được API. Hãy kiểm tra backend và SQL Server đang chạy.'
  }
  return 'Đã xảy ra lỗi. Vui lòng thử lại.'
}

export async function uploadArtworkImage(artworkId: number, file: File, onProgress?: (percent: number) => void): Promise<{ image_url: string }> {
  const body = new FormData()
  body.append('file', file, file.name)
  const { data } = await api.post<{ image_url: string }>(`/artworks/${artworkId}/image`, body, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (event) => {
      if (event.total) onProgress?.(Math.min(100, Math.round((event.loaded / event.total) * 100)))
    },
  })
  return data
}

export async function uploadEvidenceMedia(evidenceId: number, file: File, onProgress?: (percent: number) => void): Promise<{ id: number; media_type: string; file_path: string }> {
  const body = new FormData()
  body.append('file', file, file.name)
  const { data } = await api.post(`/evidences/${evidenceId}/media`, body, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (event) => {
      if (event.total) onProgress?.(Math.min(100, Math.round((event.loaded / event.total) * 100)))
    },
  })
  return data
}

/** A legacy backend has no AI status route; its rows must not be labelled REAL_AI. */
export async function getIntegrationStatus(signal?: AbortSignal): Promise<IntegrationStatus | null> {
  try {
    const { data } = await api.get<IntegrationStatus>('/ai/status', { signal })
    return data
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 404) return null
    throw error
  }
}

/** One bounded metadata request per list, never an N+1 request for each row. */
export async function withAlertOrigins(items: Alert[], status: IntegrationStatus | null, signal?: AbortSignal): Promise<Alert[]> {
  if (!items.length || !status?.enabled) return items
  const ids = [...new Set(items.map((item) => item.id))]
  if (ids.length > 100) throw new Error('Too many alert IDs for provenance lookup')
  const { data } = await api.get<{ items: AlertOrigin[] }>('/ai/alert-origins', { params: { alert_ids: ids.join(',') }, signal })
  const origins = new Map(data.items.map((item) => [item.alert_id, item]))
  return items.map((item) => ({ ...item, ingest: origins.get(item.id) }))
}

export function alertOriginLabel(alert: Alert): string {
  if (alert.ingest) return alert.ingest.data_origin
  if (alert.source === 'demo') return 'DEMO'
  return 'UNVERIFIED'
}
