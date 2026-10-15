import { LoaderCircle, SearchX, TriangleAlert } from 'lucide-react'
import type { ReactNode } from 'react'

export function LoadingState({ label = 'Đang tải dữ liệu…' }: { label?: string }) {
  return <div className="state-panel"><LoaderCircle className="spin" size={22} /><span>{label}</span></div>
}

export function EmptyState({ title = 'Chưa có dữ liệu', detail = 'Thử thay đổi bộ lọc hoặc tạo bản ghi mới.' }: { title?: string; detail?: string }) {
  return <div className="state-panel empty-state"><SearchX size={25} /><strong>{title}</strong><span>{detail}</span></div>
}

export function ErrorState({ message, retry }: { message: string; retry?: () => void }) {
  return <div className="state-panel error-state"><TriangleAlert size={21} /><span>{message}</span>{retry && <button className="button button-secondary button-small" onClick={retry}>Thử lại</button>}</div>
}

export function StatusPill({ value }: { value: string }) {
  const normalized = value.toLowerCase()
  const label: Record<string, string> = {
    online: 'Đang hoạt động', offline: 'Ngoại tuyến', maintenance: 'Bảo trì',
    displayed: 'Đang trưng bày', in_storage: 'Trong kho', under_review: 'Đang kiểm tra',
    new: 'Mới', acknowledged: 'Đã tiếp nhận', investigating: 'Đang xử lý', resolved: 'Đã giải quyết',
    false_positive: 'Không phải sự cố', critical: 'Nghiêm trọng', high: 'Cao', medium: 'Trung bình', low: 'Thấp',
    active: 'Đang dùng', inactive: 'Tạm dừng', demo: 'Mô phỏng', success: 'Thành công',
  }
  return <span className={`status-pill status-${normalized.replaceAll('_', '-')}`}><i />{label[normalized] ?? value}</span>
}

export function Modal({ title, onClose, children, wide = false }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <section className={`modal ${wide ? 'modal-wide' : ''}`} role="dialog" aria-modal="true" aria-label={title}>
      <header className="modal-header"><div><span className="eyebrow">ARTGUARD · QUẢN LÝ</span><h2>{title}</h2></div><button className="icon-button" aria-label="Đóng" onClick={onClose}>×</button></header>
      {children}
    </section>
  </div>
}
