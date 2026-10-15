import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { Check, ChevronLeft, ChevronRight, Eye, Pencil, Plus, RefreshCw, Search, Trash2, X } from 'lucide-react'
import { api, errorMessage, uploadArtworkImage } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { EmptyState, ErrorState, LoadingState, Modal, StatusPill } from '../components/States'
import { ArtworkImage, ArtworkImagePicker } from '../components/ArtworkImage'
import type { Alert, Artwork, Device, Location, PageResult } from '../types'

type Row = Record<string, string | number | boolean | null> & { id: number }
type Field = { name: string; label: string; type?: 'text' | 'number' | 'textarea' | 'select'; required?: boolean; options?: { value: string; label: string }[]; relation?: string; placeholder?: string }
type Column = { name: string; label: string }
interface Config { title: string; eyebrow: string; description: string; path: string; columns: Column[]; fields: Field[]; filters?: { name: string; label: string; options: { value: string; label: string }[] }[]; searchPlaceholder: string; canDelete?: boolean; details?: boolean }
interface DeviceStatusEvent { id: number; status: string; recorded_at: string }

const statusOptions = (values: [string, string][]) => values.map(([value, label]) => ({ value, label }))
const configs: Record<string, Config> = {
  artworks: {
    title: 'Tác phẩm nghệ thuật', eyebrow: 'BỘ SƯU TẬP', description: 'Danh mục tác phẩm, thông tin trưng bày và vị trí liên quan.', path: '/artworks', searchPlaceholder: 'Tìm theo tên, tác giả hoặc mã tranh…', details: true, canDelete: true,
    columns: [{ name: 'inventory_code', label: 'Mã tác phẩm' }, { name: 'title', label: 'Tên tác phẩm' }, { name: 'artist', label: 'Tác giả' }, { name: 'location_name', label: 'Phòng trưng bày' }, { name: 'status', label: 'Trạng thái' }],
    fields: [{ name: 'inventory_code', label: 'Mã tác phẩm', required: true }, { name: 'title', label: 'Tên tác phẩm', required: true }, { name: 'artist', label: 'Tác giả', required: true }, { name: 'year_created', label: 'Năm sáng tác', type: 'number' }, { name: 'medium', label: 'Chất liệu' }, { name: 'location_id', label: 'Phòng trưng bày', type: 'select', relation: 'locations' }, { name: 'status', label: 'Trạng thái', type: 'select', required: true, options: statusOptions([['displayed', 'Đang trưng bày'], ['in_storage', 'Trong kho'], ['under_review', 'Đang kiểm tra']]) }, { name: 'description', label: 'Mô tả', type: 'textarea' }],
    filters: [{ name: 'status', label: 'Tất cả trạng thái', options: statusOptions([['displayed', 'Đang trưng bày'], ['in_storage', 'Trong kho'], ['under_review', 'Đang kiểm tra']]) }],
  },
  locations: {
    title: 'Phòng trưng bày', eyebrow: 'BỘ SƯU TẬP', description: 'Quản lý khu vực, sức chứa và trạng thái hoạt động.', path: '/locations', searchPlaceholder: 'Tìm tên hoặc mã phòng…', canDelete: true, details: true,
    columns: [{ name: 'code', label: 'Mã khu vực' }, { name: 'name', label: 'Tên phòng' }, { name: 'capacity', label: 'Sức chứa' }, { name: 'is_active', label: 'Trạng thái' }],
    fields: [{ name: 'code', label: 'Mã khu vực', required: true }, { name: 'name', label: 'Tên phòng trưng bày', required: true }, { name: 'capacity', label: 'Sức chứa', type: 'number' }, { name: 'is_active', label: 'Trạng thái hoạt động', type: 'select', required: true, options: statusOptions([['true', 'Đang hoạt động'], ['false', 'Tạm ngưng']]) }, { name: 'description', label: 'Vị trí / mô tả', type: 'textarea' }],
  },
  devices: {
    title: 'Thiết bị giám sát', eyebrow: 'HỆ THỐNG GIÁM SÁT', description: 'Theo dõi camera mô phỏng và các thiết bị gắn với tác phẩm.', path: '/devices', searchPlaceholder: 'Tìm tên hoặc mã thiết bị…', canDelete: true, details: true,
    columns: [{ name: 'device_code', label: 'Mã thiết bị' }, { name: 'name', label: 'Tên thiết bị' }, { name: 'location_name', label: 'Khu vực' }, { name: 'device_type', label: 'Loại' }, { name: 'status', label: 'Tình trạng' }, { name: 'last_seen_at', label: 'Lần cuối hoạt động' }],
    fields: [{ name: 'device_code', label: 'Mã thiết bị', required: true }, { name: 'name', label: 'Tên thiết bị', required: true }, { name: 'device_type', label: 'Loại thiết bị', required: true, placeholder: 'simulated_camera' }, { name: 'location_id', label: 'Khu vực', type: 'select', relation: 'locations' }, { name: 'artwork_id', label: 'Tác phẩm liên quan', type: 'select', relation: 'artworks' }, { name: 'status', label: 'Trạng thái', type: 'select', required: true, options: statusOptions([['online', 'Đang hoạt động'], ['offline', 'Ngoại tuyến'], ['maintenance', 'Bảo trì']]) }, { name: 'notes', label: 'Ghi chú', type: 'textarea' }],
    filters: [{ name: 'status', label: 'Tất cả thiết bị', options: statusOptions([['online', 'Đang hoạt động'], ['offline', 'Ngoại tuyến'], ['maintenance', 'Bảo trì']]) }],
  },
}

function labelFor(name: string, value: string) {
  if (name === 'status') {
    return <StatusPill value={value} />
  }
  return value
}

function relationOptions(field: Field, references: Record<string, { value: string; label: string }[]>): { value: string; label: string }[] {
  if (field.relation) return [{ value: '', label: 'Chưa gán' }, ...(references[field.relation] ?? [])]
  return field.options ?? []
}

export function DataPage({ kind }: { kind: keyof typeof configs }) {
  const config = configs[kind]
  const { hasRole } = useAuth()
  const canEdit = hasRole('admin', 'manager')
  const canDelete = hasRole('admin') && !!config.canDelete
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [query, setQuery] = useState('')
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<Row | null>(null)
  const [form, setForm] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [formImage, setFormImage] = useState<File | null>(null)
  const [formImageProgress, setFormImageProgress] = useState(0)
  const [formError, setFormError] = useState('')
  const [notice, setNotice] = useState('')
  const [references, setReferences] = useState<Record<string, { value: string; label: string }[]>>({})
  const [detail, setDetail] = useState<Artwork | null>(null)
  const [detailAlerts, setDetailAlerts] = useState<Alert[]>([])
  const [detailImage, setDetailImage] = useState<File | null>(null)
  const [detailImageProgress, setDetailImageProgress] = useState(0)
  const [detailImageUploading, setDetailImageUploading] = useState(false)
  const [detailImageError, setDetailImageError] = useState('')
  const [selectedLocation, setSelectedLocation] = useState<Location | null>(null)
  const [locationArtworks, setLocationArtworks] = useState<Artwork[]>([])
  const [locationDevices, setLocationDevices] = useState<Device[]>([])
  const [selectedDevice, setSelectedDevice] = useState<Device | null>(null)
  const [deviceHistory, setDeviceHistory] = useState<DeviceStatusEvent[]>([])
  const pageSize = 12

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const params: Record<string, string | number> = { page, page_size: pageSize }
      if (search) params.q = search
      if (filter) params.status = filter
      const { data } = await api.get<PageResult<Row>>(config.path, { params })
      setRows(data.items); setTotal(data.total)
    } catch (reason) { setError(errorMessage(reason)) }
    finally { setLoading(false) }
  }, [config.path, filter, page, search])

  useEffect(() => { void load() }, [load])
  useEffect(() => {
    async function loadReferences() {
      const refs: Record<string, { value: string; label: string }[]> = {}
      if (config.fields.some((field) => field.relation === 'locations')) {
        const { data } = await api.get<PageResult<Location>>('/locations', { params: { page_size: 100 } })
        refs.locations = data.items.map((item) => ({ value: String(item.id), label: `${item.name} · ${item.code}` }))
      }
      if (config.fields.some((field) => field.relation === 'artworks')) {
        const { data } = await api.get<PageResult<Artwork>>('/artworks', { params: { page_size: 100 } })
        refs.artworks = data.items.map((item) => ({ value: String(item.id), label: `${item.title} · ${item.inventory_code}` }))
      }
      setReferences(refs)
    }
    loadReferences().catch(() => undefined)
  }, [config.fields])

  const maxPage = Math.max(1, Math.ceil(total / pageSize))
  const formTitle = editing ? `Chỉnh sửa ${kind === 'artworks' ? 'tác phẩm' : kind === 'devices' ? 'thiết bị' : 'phòng trưng bày'}` : `Thêm ${kind === 'artworks' ? 'tác phẩm' : kind === 'devices' ? 'thiết bị' : 'phòng trưng bày'}`

  function openForm(row?: Row) {
    const values: Record<string, string> = {}
    for (const field of config.fields) {
      const current = row?.[field.name]
      values[field.name] = current == null ? '' : String(current)
    }
    if (!row && kind === 'locations') values.is_active = 'true'
    if (!row && kind === 'devices') { values.status = 'online'; values.device_type = 'simulated_camera' }
    if (!row && kind === 'artworks') values.status = 'displayed'
    setEditing(row ?? null); setForm(values); setFormImage(null); setFormImageProgress(0); setFormError(''); setFormOpen(true)
  }

  function changeQuery(event: React.FormEvent) { event.preventDefault(); setPage(1); setSearch(query.trim()) }

  async function submitForm(event: FormEvent) {
    event.preventDefault(); setSaving(true); setFormError(''); setFormImageProgress(0)
    const payload: Record<string, unknown> = {}
    for (const field of config.fields) {
      const value = form[field.name] ?? ''
      if (field.type === 'number') payload[field.name] = value === '' ? null : Number(value)
      else if (field.name === 'is_active') payload[field.name] = value === 'true'
      else payload[field.name] = value === '' ? null : value
    }
    try {
      let saved: Row
      if (editing) {
        const { data } = await api.patch<Row>(`${config.path}/${editing.id}`, payload)
        saved = data
      } else {
        const { data } = await api.post<Row>(config.path, payload)
        saved = data
      }
      if (kind === 'artworks' && formImage) {
        setEditing(saved)
        try {
          await uploadArtworkImage(saved.id, formImage, setFormImageProgress)
        } catch (reason) {
          setFormError(`Thông tin tác phẩm đã lưu. Tải ảnh chưa thành công: ${errorMessage(reason)} Hãy thử lại.`)
          await load()
          return
        }
      }
      setFormOpen(false); setFormImage(null); setNotice(editing ? 'Đã cập nhật bản ghi.' : 'Đã thêm bản ghi mới.'); await load()
      window.setTimeout(() => setNotice(''), 3200)
    } catch (reason) { setFormError(errorMessage(reason)) }
    finally { setSaving(false) }
  }

  async function removeRow(row: Row) {
    const identity = String(row.title ?? row.name ?? row.code ?? row.device_code ?? row.inventory_code ?? '')
    if (!window.confirm(`Xóa “${identity}”? Các cảnh báo liên quan vẫn được giữ lại.`)) return
    try { await api.delete(`${config.path}/${row.id}`); setNotice('Đã xóa bản ghi.'); await load(); window.setTimeout(() => setNotice(''), 3200) }
    catch (reason) { setError(errorMessage(reason)) }
  }

  async function showDetail(row: Row) {
    try {
      if (kind === 'artworks') {
        const [{ data: artwork }, { data: alerts }] = await Promise.all([api.get<Artwork>(`/artworks/${row.id}`), api.get<Alert[]>(`/artworks/${row.id}/alerts`)] as const)
        setDetail(artwork); setDetailAlerts(alerts); setDetailImage(null); setDetailImageProgress(0); setDetailImageError('')
      } else if (kind === 'locations') {
        const [{ data: location }, { data: artworks }, { data: devices }] = await Promise.all([api.get<Location>(`/locations/${row.id}`), api.get<PageResult<Artwork>>('/artworks', { params: { location_id: row.id, page_size: 100 } }), api.get<PageResult<Device>>('/devices', { params: { location_id: row.id, page_size: 100 } })] as const)
        setSelectedLocation(location); setLocationArtworks(artworks.items); setLocationDevices(devices.items)
      } else {
        const device = row as unknown as Device
        const { data: history } = await api.get<DeviceStatusEvent[]>(`/devices/${row.id}/history`)
        setSelectedDevice(device); setDeviceHistory(history)
      }
    } catch (reason) { setError(errorMessage(reason)) }
  }

  async function uploadDetailImage() {
    if (!detail || !detailImage) return
    setDetailImageUploading(true); setDetailImageError(''); setDetailImageProgress(0)
    try {
      const result = await uploadArtworkImage(detail.id, detailImage, setDetailImageProgress)
      setDetail({ ...detail, image_url: result.image_url })
      setDetailImage(null); setNotice('Đã lưu ảnh tác phẩm.'); await load()
      window.setTimeout(() => setNotice(''), 3200)
    } catch (reason) {
      setDetailImageError(errorMessage(reason))
    } finally { setDetailImageUploading(false) }
  }

  const visibleRows = useMemo(() => rows, [rows])

  return <div className="page-stack"><div className="page-heading-row"><div><span className="eyebrow">{config.eyebrow}</span><h1>{config.title}</h1><p>{config.description}</p></div>{canEdit && <button className="button button-primary" onClick={() => openForm()}><Plus size={16} /> Thêm mới</button>}</div>
    {notice && <div className="toast-notice"><Check size={16} />{notice}</div>}
    <section className="panel list-panel"><div className="list-toolbar"><form className="search-form" onSubmit={changeQuery}><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={config.searchPlaceholder} aria-label="Tìm kiếm" /><button className="search-submit" type="submit">Tìm</button></form><div className="toolbar-actions">{config.filters?.map((item) => <select className="filter-select" aria-label={item.label} key={item.name} value={filter} onChange={(event) => { setFilter(event.target.value); setPage(1) }}><option value="">{item.label}</option>{item.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select>)}<button className="icon-button refresh-button" aria-label="Tải lại" onClick={() => void load()}><RefreshCw size={16} /></button></div></div>
      {loading ? <LoadingState /> : error ? <ErrorState message={error} retry={() => void load()} /> : visibleRows.length === 0 ? <EmptyState title={search || filter ? 'Không tìm thấy kết quả' : undefined} detail={search || filter ? 'Thử bỏ bớt bộ lọc tìm kiếm.' : undefined} /> : <><div className="table-scroll"><table className="data-table"><thead><tr>{config.columns.map((column) => <th key={column.name}>{column.label}</th>)}<th className="actions-header">Thao tác</th></tr></thead><tbody>{visibleRows.map((row) => <tr key={row.id}>{config.columns.map((column, index) => { const value = row[column.name]; return <td key={column.name}>{index === 0 ? kind === 'artworks' ? <span className="artwork-row-primary"><ArtworkImage src={typeof row.image_url === 'string' ? row.image_url : null} alt={String(row.title ?? '\u0054\u00e1c ph\u1ea9m')} className="artwork-row-thumbnail" /><b className="row-primary">{String(value ?? '\u2014')}</b></span> : <b className="row-primary">{String(value ?? '\u2014')}</b> : column.name === 'status' ? labelFor(column.name, String(value ?? '')) : column.name === 'is_active' ? <StatusPill value={value ? 'active' : 'inactive'} /> : column.name === 'last_seen_at' ? value ? new Date(`${String(value)}Z`).toLocaleString('vi-VN', { dateStyle: 'short', timeStyle: 'short' }) : <span className="muted">Chưa ghi nhận</span> : <span className="row-cell">{String(value ?? '—')}</span>}</td> })}<td><div className="row-actions">{config.details && <button className="icon-button" title="Chi tiết" onClick={() => void showDetail(row)}><Eye size={16} /></button>}{canEdit && <button className="icon-button" title="Chỉnh sửa" onClick={() => openForm(row)}><Pencil size={15} /></button>}{canDelete && <button className="icon-button danger-icon" title="Xóa" onClick={() => void removeRow(row)}><Trash2 size={15} /></button>}</div></td></tr>)}</tbody></table></div><div className="table-pagination"><span>Hiển thị <b>{(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)}</b> trong {total} bản ghi</span><div><button className="icon-button" aria-label="Trang trước" disabled={page <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))}><ChevronLeft size={17} /></button><span>Trang {page} / {maxPage}</span><button className="icon-button" aria-label="Trang sau" disabled={page >= maxPage} onClick={() => setPage((current) => Math.min(maxPage, current + 1))}><ChevronRight size={17} /></button></div></div></>}
    </section>
    <div className="data-footnote"><span><i className="dot" /> Dữ liệu lưu trong cơ sở dữ liệu SQL Server</span><span>Thiết bị hiển thị hiện là bản ghi mô phỏng</span></div>

    {formOpen && <Modal title={formTitle} onClose={() => { if (!saving) setFormOpen(false) }}><form className="entity-form" onSubmit={submitForm}><div className="form-grid">{config.fields.map((field) => <label className={field.type === 'textarea' ? 'field-wide' : ''} key={field.name}>{field.label}{field.type === 'textarea' ? <textarea rows={3} required={field.required} value={form[field.name] ?? ''} placeholder={field.placeholder} onChange={(event) => setForm({ ...form, [field.name]: event.target.value })} /> : field.type === 'select' ? <select required={field.required} value={form[field.name] ?? ''} onChange={(event) => setForm({ ...form, [field.name]: event.target.value })}><option value="">{field.required ? 'Chọn một mục' : 'Chưa gán'}</option>{relationOptions(field, references).filter((option) => option.value !== '').map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select> : <input required={field.required} type={field.type === 'number' ? 'number' : 'text'} min={field.type === 'number' ? '0' : undefined} value={form[field.name] ?? ''} placeholder={field.placeholder} onChange={(event) => setForm({ ...form, [field.name]: event.target.value })} />}</label>)}</div>{kind === 'artworks' && <ArtworkImagePicker imageUrl={typeof editing?.image_url === 'string' ? editing.image_url : null} inventoryCode={form.inventory_code || 'T\u00e1c ph\u1ea9m m\u1edbi'} selectedFile={formImage} onFileChange={(file) => { setFormImage(file); setFormError('') }} error={formError} uploading={saving && !!formImage} uploadProgress={formImageProgress} disabled={saving} />}<div className="modal-footer"><button className="button button-secondary" type="button" disabled={saving} onClick={() => setFormOpen(false)}><X size={15} /> Hủy</button><button className="button button-primary" disabled={saving}>{saving ? formImage ? '\u0110ang t\u1ea3i \u1ea3nh\u2026' : 'Đang lưu…' : <><Check size={15} /> Lưu thay đổi</>}</button></div></form></Modal>}

    {detail && <Modal title={detail.title} onClose={() => setDetail(null)} wide><div className="artwork-detail"><div className={`detail-cover ${detail.image_url ? 'detail-cover-has-image' : ''}`}>{detail.image_url ? <ArtworkImage src={detail.image_url} alt={`\u1ea2nh t\u00e1c ph\u1ea9m ${detail.title}`} className="detail-cover-image" /> : <div className="detail-art-mark"><BookImageIcon /></div>}<span>{detail.inventory_code}</span></div><div className="detail-content"><div className="detail-facts"><div><span>Tác giả</span><b>{detail.artist}</b></div><div><span>Năm sáng tác</span><b>{detail.year_created ?? 'Chưa rõ'}</b></div><div><span>Chất liệu</span><b>{detail.medium ?? 'Chưa cập nhật'}</b></div><div><span>Phòng trưng bày</span><b>{detail.location_name ?? 'Chưa gán khu vực'}</b></div></div>{canEdit && <ArtworkImagePicker imageUrl={detail.image_url} inventoryCode={detail.inventory_code} selectedFile={detailImage} onFileChange={(file) => { setDetailImage(file); setDetailImageError('') }} onUpload={() => void uploadDetailImage()} uploading={detailImageUploading} uploadProgress={detailImageProgress} error={detailImageError} disabled={detailImageUploading} />}<p className="detail-description">{detail.description ?? 'Chưa có mô tả cho tác phẩm này.'}</p><div className="detail-alert-heading"><b>Lịch sử cảnh báo</b><span>{detailAlerts.length} sự kiện</span></div>{detailAlerts.length === 0 ? <div className="inline-empty">Chưa có sự kiện liên quan đến tác phẩm.</div> : detailAlerts.slice(0, 6).map((item) => <div className="detail-alert-row" key={item.id}><span><i className={`severity-dot severity-${item.severity}`} />{item.title}</span><StatusPill value={item.status} /><time>{new Date(`${item.detected_at}Z`).toLocaleDateString('vi-VN')}</time></div>)}</div></div></Modal>}

    {selectedLocation && <Modal title={selectedLocation.name} onClose={() => setSelectedLocation(null)} wide><div className="location-detail"><div className="detail-facts"><div><span>Mã khu vực</span><b>{selectedLocation.code}</b></div><div><span>Sức chứa</span><b>{selectedLocation.capacity ?? 'Chưa đặt giới hạn'}</b></div><div><span>Trạng thái</span><StatusPill value={selectedLocation.is_active ? 'active' : 'inactive'} /></div><div><span>Mô tả</span><b>{selectedLocation.description ?? 'Chưa có mô tả'}</b></div></div><div className="location-assets-grid"><section><div className="detail-alert-heading"><b>Tác phẩm trong khu vực</b><span>{locationArtworks.length}</span></div>{locationArtworks.length === 0 ? <div className="inline-empty">Chưa gắn tác phẩm.</div> : locationArtworks.map((item) => <div className="detail-alert-row" key={item.id}><span><b>{item.inventory_code}</b> · {item.title}</span><StatusPill value={item.status} /></div>)}</section><section><div className="detail-alert-heading"><b>Thiết bị trong khu vực</b><span>{locationDevices.length}</span></div>{locationDevices.length === 0 ? <div className="inline-empty">Chưa gắn thiết bị.</div> : locationDevices.map((item) => <div className="detail-alert-row" key={item.id}><span><b>{item.device_code}</b> · {item.name}</span><StatusPill value={item.status} /></div>)}</section></div></div></Modal>}

    {selectedDevice && <Modal title={selectedDevice.name} onClose={() => setSelectedDevice(null)}><div className="entity-detail"><div className="device-detail-summary"><span className="model-icon"><Eye size={18} /></span><StatusPill value={selectedDevice.status} /></div><div className="detail-facts"><div><span>Mã thiết bị</span><b>{selectedDevice.device_code}</b></div><div><span>Loại</span><b>{selectedDevice.device_type}</b></div><div><span>Khu vực</span><b>{selectedDevice.location_name ?? 'Chưa gán'}</b></div><div><span>Tác phẩm</span><b>{selectedDevice.artwork_title ?? 'Chưa gắn'}</b></div><div><span>Lần cuối hoạt động</span><b>{selectedDevice.last_seen_at ? new Date(`${selectedDevice.last_seen_at}Z`).toLocaleString('vi-VN') : 'Chưa ghi nhận'}</b></div><div><span>Ghi chú</span><b>{selectedDevice.notes ?? '—'}</b></div></div><div className="detail-alert-heading"><b>Lịch sử trạng thái</b><span>{deviceHistory.length} sự kiện</span></div>{deviceHistory.length === 0 ? <div className="inline-empty">Chưa có lịch sử trạng thái.</div> : deviceHistory.map((event) => <div className="detail-alert-row" key={event.id}><StatusPill value={event.status} /><time>{new Date(`${event.recorded_at}Z`).toLocaleString('vi-VN')}</time></div>)}<div className="simulation-footnote">Đây là metadata mô phỏng; chưa kết nối camera thật hoặc luồng hình ảnh.</div></div></Modal>}
  </div>
}

function BookImageIcon() { return <span className="book-image-icon">AG</span> }
