/**
 * CameraLiveView — Modal xem camera với zoom/fullscreen.
 *
 * Hỗ trợ nguồn:
 *  - MJPEG: hiển thị trực tiếp qua <img>
 *  - HLS / MP4 / WebM: qua <video>
 *  - RTSP: không thể phát thẳng trong trình duyệt — hiển thị cảnh báo cần gateway
 *  - Không cấu hình: hiển thị chế độ DEMO
 *
 * Zoom ảnh hưởng đến vùng hình ảnh/video, không zoom trang.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AlertTriangle, Camera, Maximize2, Minimize2, RotateCcw, Signal, SignalZero,
  X, ZoomIn, ZoomOut,
} from 'lucide-react'
import type { Device } from '../types'

interface CameraLiveViewProps {
  device: Device
  onClose: () => void
}

type StreamMode = 'mjpeg' | 'video' | 'rtsp_unsupported' | 'demo'

const MIN_ZOOM = 0.5
const MAX_ZOOM = 4
const ZOOM_STEP = 0.25

function detectMode(device: Device): StreamMode {
  if (!device.stream_url) return 'demo'
  const t = (device.stream_type ?? '').toLowerCase()
  if (t === 'rtsp') return 'rtsp_unsupported'
  if (t === 'mjpeg') return 'mjpeg'
  if (t === 'hls' || t === 'mp4') return 'video'
  // heuristic từ URL
  const url = device.stream_url.toLowerCase()
  if (url.startsWith('rtsp://')) return 'rtsp_unsupported'
  if (url.endsWith('.m3u8') || url.endsWith('.ts')) return 'video'
  if (url.endsWith('.mp4') || url.endsWith('.webm')) return 'video'
  return 'mjpeg'
}

export function CameraLiveView({ device, onClose }: CameraLiveViewProps) {
  const mode = detectMode(device)
  const [zoom, setZoom] = useState(1)
  const [fullscreen, setFullscreen] = useState(false)
  const [imgError, setImgError] = useState(false)
  const [videoError, setVideoError] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  const zoomIn = useCallback(() => setZoom((z) => Math.min(MAX_ZOOM, +(z + ZOOM_STEP).toFixed(2))), [])
  const zoomOut = useCallback(() => setZoom((z) => Math.max(MIN_ZOOM, +(z - ZOOM_STEP).toFixed(2))), [])
  const resetZoom = useCallback(() => setZoom(1), [])

  // Fullscreen API
  const enterFullscreen = useCallback(async () => {
    try {
      await containerRef.current?.requestFullscreen()
      setFullscreen(true)
    } catch {
      // fallback: ignore
    }
  }, [])
  const exitFullscreen = useCallback(async () => {
    try {
      await document.exitFullscreen()
      setFullscreen(false)
    } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    const handler = () => setFullscreen(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', handler)
    return () => document.removeEventListener('fullscreenchange', handler)
  }, [])

  // Đóng bằng Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape' && !document.fullscreenElement) onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  const statusColor = device.status === 'online' ? '#78947c' : device.status === 'offline' ? '#b45e51' : '#c1a05e'
  const statusLabel = device.status === 'online' ? 'Đang hoạt động' : device.status === 'offline' ? 'Ngoại tuyến' : 'Bảo trì'

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <section className="modal modal-wide camera-modal" role="dialog" aria-modal aria-label={`Xem camera: ${device.name}`}>
        {/* Header */}
        <header className="modal-header camera-modal-header">
          <div className="camera-modal-title">
            <span className="camera-modal-icon"><Camera size={18} /></span>
            <div>
              <span className="eyebrow">{device.device_code} · {device.device_type}</span>
              <h2>{device.name}</h2>
            </div>
          </div>
          <div className="camera-modal-meta">
            <span className="camera-status-badge" style={{ color: statusColor }}>
              {device.status === 'online' ? <Signal size={13} /> : <SignalZero size={13} />}
              {statusLabel}
            </span>
            {device.location_name && <span className="camera-location-chip">{device.location_name}</span>}
            <button className="icon-button" aria-label="Đóng" onClick={onClose}><X size={20} /></button>
          </div>
        </header>

        {/* Viewport + controls */}
        <div className="camera-body" ref={containerRef}>
          {/* Zoom controls */}
          <div className="camera-zoom-bar">
            <button className="camera-ctrl-btn" title="Thu nhỏ" onClick={zoomOut} disabled={zoom <= MIN_ZOOM}>
              <ZoomOut size={15} />
            </button>
            <span className="camera-zoom-label">{Math.round(zoom * 100)}%</span>
            <button className="camera-ctrl-btn" title="Phóng to" onClick={zoomIn} disabled={zoom >= MAX_ZOOM}>
              <ZoomIn size={15} />
            </button>
            <button className="camera-ctrl-btn" title="Đặt lại" onClick={resetZoom} disabled={zoom === 1}>
              <RotateCcw size={14} />
            </button>
            <div className="camera-zoom-spacer" />
            {fullscreen
              ? <button className="camera-ctrl-btn" title="Thoát toàn màn hình" onClick={exitFullscreen}><Minimize2 size={15} /></button>
              : <button className="camera-ctrl-btn" title="Toàn màn hình" onClick={enterFullscreen}><Maximize2 size={15} /></button>
            }
          </div>

          {/* Khung hình */}
          <div className="camera-viewport-wrapper">
            <div
              className="camera-viewport-inner"
              style={{ transform: `scale(${zoom})`, transformOrigin: 'center center' }}
            >
              {mode === 'demo' && <DemoFrame device={device} />}
              {mode === 'rtsp_unsupported' && <RtspNotice device={device} />}
              {mode === 'mjpeg' && !imgError && (
                <img
                  className="camera-stream-img"
                  src={device.stream_url!}
                  alt={`Luồng camera ${device.name}`}
                  onError={() => setImgError(true)}
                />
              )}
              {mode === 'mjpeg' && imgError && <StreamError device={device} />}
              {mode === 'video' && !videoError && (
                <video
                  className="camera-stream-video"
                  src={device.stream_url!}
                  autoPlay
                  muted
                  playsInline
                  controls
                  onError={() => setVideoError(true)}
                />
              )}
              {mode === 'video' && videoError && <StreamError device={device} />}
            </div>
          </div>

          {/* Footer info */}
          <div className="camera-footer-info">
            <span>Thiết bị: <b>{device.device_code}</b></span>
            {device.artwork_title && <span>Tác phẩm: <b>{device.artwork_title}</b></span>}
            {mode !== 'demo' && mode !== 'rtsp_unsupported' && (
              <span className="camera-source-chip">
                {mode === 'mjpeg' ? 'MJPEG Stream' : 'Video'}
              </span>
            )}
          </div>
        </div>
      </section>
    </div>
  )
}

function DemoFrame({ device }: { device: Device }) {
  return (
    <div className="camera-demo-frame">
      <div className="camera-demo-inner">
        <Camera size={40} strokeWidth={1.2} />
        <span className="camera-demo-badge">CHẾ ĐỘ DEMO</span>
        <p className="camera-demo-msg">
          Thiết bị <b>{device.name}</b> chưa được cấu hình nguồn stream.
        </p>
        <p className="camera-demo-hint">
          Để kết nối camera thật, cần cấu hình <code>stream_url</code> và <code>stream_type</code> cho thiết bị này.
          Hệ thống chưa kết nối với ESP32-CAM hoặc phần cứng thật.
        </p>
      </div>
    </div>
  )
}

function RtspNotice({ device }: { device: Device }) {
  return (
    <div className="camera-demo-frame camera-rtsp-notice">
      <div className="camera-demo-inner">
        <AlertTriangle size={36} strokeWidth={1.3} color="#c1a05e" />
        <span className="camera-demo-badge camera-badge-warn">RTSP — CẦN GATEWAY</span>
        <p className="camera-demo-msg">
          Nguồn stream của <b>{device.name}</b> dùng giao thức RTSP.
        </p>
        <p className="camera-demo-hint">
          Trình duyệt không thể phát RTSP trực tiếp. Cần một gateway chuyển đổi
          (ví dụ: FFmpeg → HLS/MJPEG) trước khi tích hợp vào giai đoạn tiếp theo.
        </p>
      </div>
    </div>
  )
}

function StreamError({ device }: { device: Device }) {
  return (
    <div className="camera-demo-frame camera-error-frame">
      <div className="camera-demo-inner">
        <SignalZero size={36} strokeWidth={1.3} color="#b45e51" />
        <span className="camera-demo-badge camera-badge-err">KHÔNG KẾT NỐI ĐƯỢC</span>
        <p className="camera-demo-msg">
          Không thể tải stream từ <b>{device.name}</b>.
        </p>
        <p className="camera-demo-hint">
          Kiểm tra thiết bị đang online và URL stream có thể truy cập từ trình duyệt.
        </p>
      </div>
    </div>
  )
}
