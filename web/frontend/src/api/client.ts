import axios from 'axios'

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
