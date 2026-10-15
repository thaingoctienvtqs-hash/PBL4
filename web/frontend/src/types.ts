export type Role = 'admin' | 'manager' | 'operator'

export interface User {
  id: number
  username: string
  email: string
  full_name: string
  is_active: boolean
  roles: Role[]
  created_at: string
}

export interface PageResult<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface Location {
  id: number; code: string; name: string; description: string | null; capacity: number | null
  is_active: boolean; created_at: string; updated_at: string
}

export interface Artwork {
  id: number; inventory_code: string; title: string; artist: string; year_created: number | null
  medium: string | null; description: string | null; image_url: string | null; status: string
  location_id: number | null; location_name: string | null; created_at: string; updated_at: string
}

export interface Device {
  id: number; device_code: string; name: string; device_type: string; status: string
  location_id: number | null; location_name: string | null; artwork_id: number | null
  artwork_title: string | null; last_seen_at: string | null; notes: string | null
  stream_url: string | null; stream_type: string | null
  created_at: string; updated_at: string
}

export interface Alert {
  id: number; event_code: string; title: string; description: string; severity: string; status: string
  source: string; detected_at: string; resolved_at: string | null; artwork_id: number | null
  artwork_title: string | null; device_id: number | null; device_name: string | null; assigned_user_id: number | null
}

export interface DashboardData {
  metrics: { artworks: number; devices: number; active_devices: number; offline_devices: number; pending_alerts: number; critical_alerts: number }
  trend: { date: string; count: number }[]
  severity: { name: string; value: number }[]
  device_status: { name: string; value: number }[]
  recent_alerts: Alert[]
  generated_at: string
  data_mode: 'demo'
}

export interface Setting { key: string; value: string; updated_at: string }
export interface AuditEntry { id: number; actor: string; action: string; entity_type: string; entity_id: number | null; result: string; detail: string | null; created_at: string }

// ── Evidence types ──────────────────────────────────────────────────────────

export interface EvidenceMedia {
  id: number
  media_type: 'image' | 'video'
  file_path: string
  file_size: number | null
  mime_type: string | null
  thumbnail_path: string | null
  media_timestamp: string | null
  duration_seconds: number | null
  created_at: string
}

export interface Evidence {
  id: number
  evidence_code: string
  alert_id: number | null
  device_id: number | null
  device_name: string | null
  artwork_id: number | null
  artwork_title: string | null
  location_id: number | null
  location_name: string | null
  event_type: string
  severity: string
  processing_status: string
  source: string
  confidence: number | null
  description: string | null
  detected_at: string
  clip_start_at: string | null
  clip_end_at: string | null
  created_at: string
  updated_at: string
  assigned_user_id: number | null
  has_image: boolean
  has_video: boolean
}

export interface EvidenceDetail extends Evidence {
  media: EvidenceMedia[]
  history: EvidenceHistoryEntry[]
}

export interface EvidenceHistoryEntry {
  id: number
  from_status: string | null
  to_status: string
  note: string | null
  changed_at: string
  user_name: string | null
}
