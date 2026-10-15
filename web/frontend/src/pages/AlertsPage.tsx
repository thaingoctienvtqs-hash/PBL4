import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { BellRing, Check, ChevronLeft, ChevronRight, Clock3, Plus, Search, ShieldAlert, X } from 'lucide-react'
import { api, errorMessage } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { EmptyState, ErrorState, LoadingState, Modal, StatusPill } from '../components/States'
import type { Alert, Artwork, Device, PageResult } from '../types'

interface AlertHistory { id: number; from_status: string | null; to_status: string; note: string | null; changed_at: string; user_name: string | null }
interface AlertNote { id: number; content: string; created_at: string; user_name: string }
const statusFilters = [['', 'Tất cả trạng thái'], ['new', 'Mới'], ['acknowledged', 'Đã tiếp nhận'], ['investigating', 'Đang xử lý'], ['resolved', 'Đã giải quyết'], ['false_positive', 'Không phải sự cố']]

export function AlertsPage() {
  const { hasRole } = useAuth()
  const [items, setItems] = useState<Alert[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState('')
  const [severity, setSeverity] = useState('')
  const [query, setQuery] = useState('')
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<Alert | null>(null)
  const [history, setHistory] = useState<AlertHistory[]>([])
  const [notes, setNotes] = useState<AlertNote[]>([])
  const [noteText, setNoteText] = useState('')
  const [detailLoading, setDetailLoading] = useState(false)
  const [notice, setNotice] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [artworks, setArtworks] = useState<Artwork[]>([])
  const [devices, setDevices] = useState<Device[]>([])
  const [newEvent, setNewEvent] = useState({ title: '', description: '', severity: 'medium', artwork_id: '', device_id: '' })
  const [saving, setSaving] = useState(false)
  const pageSize = 15
  const canCreate = hasRole('admin', 'manager')
  const canUpdate = hasRole('admin', 'manager', 'operator')

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const params: Record<string, string | number> = { page, page_size: pageSize }
      if (status) params.status = status
      if (severity) params.severity = severity
      if (search) params.q = search
      const { data } = await api.get<PageResult<Alert>>('/alerts', { params })
      setItems(data.items); setTotal(data.total)
    } catch (reason) { setError(errorMessage(reason)) }
    finally { setLoading(false) }
  }, [page, search, severity, status])
  useEffect(() => { void load() }, [load])

  async function openAlert(item: Alert) {
    setSelected(item); setDetailLoading(true); setNoteText('')
    try {
      const [historyResult, notesResult] = await Promise.all([api.get<AlertHistory[]>(`/alerts/${item.id}/history`), api.get<AlertNote[]>(`/alerts/${item.id}/notes`)] as const)
      setHistory(historyResult.data); setNotes(notesResult.data)
    } catch (reason) { setError(errorMessage(reason)) }
    finally { setDetailLoading(false) }
  }

  async function openCreate() {
    setNewEvent({ title: '', description: '', severity: 'medium', artwork_id: '', device_id: '' })
    setCreateOpen(true)
    try {
      const [artworkResult, deviceResult] = await Promise.all([api.get<PageResult<Artwork>>('/artworks', { params: { page_size: 100 } }), api.get<PageResult<Device>>('/devices', { params: { page_size: 100 } })] as const)
      setArtworks(artworkResult.data.items); setDevices(deviceResult.data.items)
    } catch { setArtworks([]); setDevices([]) }
  }

  async function setAlertStatus(value: string) {
    if (!selected) return
    try {
      const { data } = await api.patch<Alert>(`/alerts/${selected.id}/status`, { status: value })
      setSelected(data); await load(); await openAlert(data)
      setNotice('Đã cập nhật trạng thái cảnh báo.'); window.setTimeout(() => setNotice(''), 3000)
    } catch (reason) { setError(errorMessage(reason)) }
  }

  async function addNote(event: FormEvent) {
    event.preventDefault()
    if (!selected || !noteText.trim()) return
    try {
      await api.post(`/alerts/${selected.id}/notes`, { content: noteText.trim() })
      setNoteText(''); await openAlert(selected); setNotice('Đã thêm ghi chú xử lý.'); window.setTimeout(() => setNotice(''), 3000)
    } catch (reason) { setError(errorMessage(reason)) }
  }

  async function submitDemo(event: FormEvent) {
    event.preventDefault(); setSaving(true)
    try {
      await api.post('/alerts', { ...newEvent, artwork_id: newEvent.artwork_id ? Number(newEvent.artwork_id) : null, device_id: newEvent.device_id ? Number(newEvent.device_id) : null })
      setCreateOpen(false); setPage(1); await load(); setNotice('Đã tạo sự kiện mô phỏng.'); window.setTimeout(() => setNotice(''), 3000)
    } catch (reason) { setError(errorMessage(reason)) }
    finally { setSaving(false) }
  }

  const maxPage = Math.max(1, Math.ceil(total / pageSize))
  return <div className="page-stack"><div className="page-heading-row"><div><span className="eyebrow">THEO DÕI VÀ XỬ LÝ</span><h1>Cảnh báo</h1><p>Rà soát sự kiện, cập nhật tiến độ và lưu ghi chú xử lý.</p></div>{canCreate && <button className="button button-primary" onClick={() => void openCreate()}><Plus size={16} /> Tạo sự kiện demo</button>}</div>
    <div className="alert-scope-banner"><ShieldAlert size={17} /><span><b>Chế độ mô phỏng.</b> Sự kiện trên trang không đến từ camera hoặc mô hình AI thật.</span></div>{notice && <div className="toast-notice"><Check size={16} />{notice}</div>}
    <section className="panel list-panel"><div className="list-toolbar"><form className="search-form" onSubmit={(event) => { event.preventDefault(); setPage(1); setSearch(query.trim()) }}><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Tìm mã sự kiện, tác phẩm hoặc thiết bị…" /><button className="search-submit">Tìm</button></form><div className="toolbar-actions"><select className="filter-select" value={status} aria-label="Lọc trạng thái" onChange={(event) => { setStatus(event.target.value); setPage(1) }}>{statusFilters.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><select className="filter-select" value={severity} aria-label="Lọc mức độ" onChange={(event) => { setSeverity(event.target.value); setPage(1) }}><option value="">Tất cả mức độ</option><option value="critical">Nghiêm trọng</option><option value="high">Cao</option><option value="medium">Trung bình</option><option value="low">Thấp</option></select></div></div>
      {loading ? <LoadingState label="Đang tải lịch sử cảnh báo…" /> : error ? <ErrorState message={error} retry={() => void load()} /> : items.length === 0 ? <EmptyState title="Không có cảnh báo phù hợp" detail="Thử bộ lọc khác hoặc tạo một sự kiện mô phỏng." /> : <><div className="table-scroll"><table className="data-table alert-table"><thead><tr><th>Sự kiện</th><th>Tác phẩm và thiết bị</th><th>Mức độ</th><th>Trạng thái</th><th>Thời điểm</th><th /></tr></thead><tbody>{items.map((item) => <tr key={item.id} className={item.severity === 'critical' && item.status === 'new' ? 'row-critical' : ''}><td><b className="row-primary">{item.title}</b><span className="row-secondary">{item.event_code} · {item.source === 'demo' ? 'DEMO' : item.source}</span></td><td><span className="row-primary">{item.artwork_title ?? 'Chưa gán tác phẩm'}</span><span className="row-secondary">{item.device_name ?? 'Không gắn thiết bị'}</span></td><td><StatusPill value={item.severity} /></td><td><StatusPill value={item.status} /></td><td>{new Date(`${item.detected_at}Z`).toLocaleString('vi-VN', { dateStyle: 'medium', timeStyle: 'short' })}</td><td><button className="button button-small button-secondary" onClick={() => void openAlert(item)}>Xử lý</button></td></tr>)}</tbody></table></div><div className="table-pagination"><span>{total} cảnh báo · Trang {page}/{maxPage}</span><div><button className="icon-button" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}><ChevronLeft size={17} /></button><button className="icon-button" disabled={page >= maxPage} onClick={() => setPage((value) => value + 1)}><ChevronRight size={17} /></button></div></div></>}
    </section>

    {selected && <Modal title="Chi tiết cảnh báo" onClose={() => setSelected(null)} wide><div className="alert-detail"><div className="alert-detail-main"><div className="alert-detail-code"><span className="severity-icon"><BellRing size={17} /></span><div><span className="eyebrow">{selected.event_code} · DỮ LIỆU {selected.source.toUpperCase()}</span><h3>{selected.title}</h3></div></div><p>{selected.description}</p><div className="alert-meta-grid"><div><span>Tác phẩm</span><b>{selected.artwork_title ?? 'Chưa gắn'}</b></div><div><span>Thiết bị</span><b>{selected.device_name ?? 'Không gắn'}</b></div><div><span>Thời điểm</span><b>{new Date(`${selected.detected_at}Z`).toLocaleString('vi-VN')}</b></div><div><span>Mức độ</span><StatusPill value={selected.severity} /></div></div>{canUpdate && !['resolved', 'false_positive'].includes(selected.status) && <div className="status-action"><label htmlFor="alert-status">Cập nhật trạng thái</label><select id="alert-status" value={selected.status} onChange={(event) => void setAlertStatus(event.target.value)}><option value="new">Mới</option><option value="acknowledged">Đã tiếp nhận</option><option value="investigating">Đang xử lý</option><option value="resolved">Đã giải quyết</option><option value="false_positive">Không phải sự cố</option></select></div>}<form className="note-form" onSubmit={addNote}><label htmlFor="alert-note">Ghi chú xử lý</label><textarea id="alert-note" rows={3} value={noteText} onChange={(event) => setNoteText(event.target.value)} placeholder="Ghi lại kết quả kiểm tra hoặc hướng xử lý…" /><button className="button button-primary button-small" disabled={!noteText.trim()}><Check size={14} /> Thêm ghi chú</button></form></div><div className="alert-history-panel"><h4><Clock3 size={15} /> Dòng thời gian</h4>{detailLoading ? <LoadingState label="Đang tải lịch sử…" /> : history.length === 0 ? <EmptyState title="Chưa có lịch sử" /> : history.map((entry) => <div className="timeline-entry" key={entry.id}><i /><b>{entry.user_name ?? 'Hệ thống'} <span>{entry.to_status.replaceAll('_', ' ')}</span></b><time>{new Date(`${entry.changed_at}Z`).toLocaleString('vi-VN')}</time>{entry.note && <p>{entry.note}</p>}</div>)}<h4 className="notes-heading">Ghi chú <span>{notes.length}</span></h4>{notes.map((note) => <div className="note-item" key={note.id}><b>{note.user_name}</b><time>{new Date(`${note.created_at}Z`).toLocaleDateString('vi-VN')}</time><p>{note.content}</p></div>)}</div></div></Modal>}

    {createOpen && <Modal title="Tạo sự kiện mô phỏng" onClose={() => setCreateOpen(false)}><form className="entity-form" onSubmit={submitDemo}><div className="form-grid"><label className="field-wide">Tiêu đề<input required minLength={3} value={newEvent.title} onChange={(e) => setNewEvent({ ...newEvent, title: e.target.value })} placeholder="Ví dụ: Cần kiểm tra khoảng cách an toàn" /></label><label className="field-wide">Mô tả<textarea required rows={3} minLength={3} value={newEvent.description} onChange={(e) => setNewEvent({ ...newEvent, description: e.target.value })} placeholder="Thông tin sự kiện demo" /></label><label>Mức độ<select value={newEvent.severity} onChange={(e) => setNewEvent({ ...newEvent, severity: e.target.value })}><option value="low">Thấp</option><option value="medium">Trung bình</option><option value="high">Cao</option><option value="critical">Nghiêm trọng</option></select></label><label>Tác phẩm<select value={newEvent.artwork_id} onChange={(e) => setNewEvent({ ...newEvent, artwork_id: e.target.value })}><option value="">Chưa gán</option>{artworks.map((item) => <option key={item.id} value={item.id}>{item.title} · {item.inventory_code}</option>)}</select></label><label className="field-wide">Thiết bị<select value={newEvent.device_id} onChange={(e) => setNewEvent({ ...newEvent, device_id: e.target.value })}><option value="">Không gắn thiết bị</option>{devices.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.device_code}</option>)}</select></label></div><div className="simulation-footnote">Sự kiện sẽ được lưu với nhãn “demo”. Đây không phải phát hiện từ AI.</div><div className="modal-footer"><button className="button button-secondary" type="button" onClick={() => setCreateOpen(false)}><X size={15} /> Hủy</button><button className="button button-primary" disabled={saving}>{saving ? 'Đang lưu…' : <><Plus size={15} /> Tạo sự kiện</>}</button></div></form></Modal>}
  </div>
}
