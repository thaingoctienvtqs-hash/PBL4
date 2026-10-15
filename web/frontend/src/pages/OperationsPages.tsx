import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Activity, Check, ChevronRight, Cpu, LockKeyhole, Plus, Save, Shield, UserRoundPlus, UsersRound } from 'lucide-react'
import { CartesianGrid, Cell, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, errorMessage } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { EmptyState, ErrorState, LoadingState, Modal, StatusPill } from '../components/States'
import type { AuditEntry, DashboardData, PageResult, Setting, User } from '../types'

const statusNames: Record<string, string> = { low: 'Thấp', medium: 'Trung bình', high: 'Cao', critical: 'Nghiêm trọng' }
const colors: Record<string, string> = { low: '#9bbaa8', medium: '#d7b66b', high: '#d8875e', critical: '#b84839' }

export function ReportsPage() {
  const [data, setData] = useState<(DashboardData & { period_days: number; location_count: number }) | null>(null)
  const [days, setDays] = useState(30)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const load = useCallback(() => { setLoading(true); setError(''); api.get('/reports/summary', { params: { days } }).then(({ data: result }) => setData(result)).catch((reason) => setError(errorMessage(reason))).finally(() => setLoading(false)) }, [days])
  useEffect(() => { load() }, [load])
  if (loading) return <LoadingState label="Đang tạo báo cáo từ SQL Server…" />
  if (error || !data) return <ErrorState message={error || 'Không tải được báo cáo'} retry={load} />
  return <div className="page-stack"><div className="page-heading-row"><div><span className="eyebrow">PHÂN TÍCH VÀ BÁO CÁO</span><h1>Báo cáo thống kê</h1><p>Tổng hợp hoạt động bộ sưu tập trong khoảng thời gian đã chọn.</p></div><select className="filter-select report-period" value={days} onChange={(e) => setDays(Number(e.target.value))}><option value={7}>7 ngày qua</option><option value={30}>30 ngày qua</option><option value={90}>90 ngày qua</option></select></div><div className="report-sample-callout"><Activity size={17} /><span><b>Báo cáo dữ liệu mô phỏng.</b> Thống kê được tổng hợp từ các bản ghi trong database; chưa đại diện cho hoạt động AI hoặc phần cứng thực.</span></div>
    <div className="report-stat-grid"><div><span>Sự kiện trong kỳ</span><b>{data.trend.reduce((sum, item) => sum + item.count, 0)}</b><small>{days} ngày gần nhất</small></div><div><span>Cảnh báo đang mở</span><b>{data.metrics.pending_alerts}</b><small>Chờ tiếp nhận hoặc xử lý</small></div><div><span>Thiết bị hoạt động</span><b>{data.metrics.active_devices}<i> / {data.metrics.devices}</i></b><small>{data.metrics.offline_devices} thiết bị ngoại tuyến</small></div><div><span>Khu vực hoạt động</span><b>{data.location_count}</b><small>Phòng trưng bày</small></div></div>
    <div className="dashboard-grid report-charts"><article className="panel trend-panel"><div className="panel-heading"><div><span className="eyebrow">XU HƯỚNG</span><h2>Sự kiện theo ngày</h2></div><span className="subtle-tag">{days} ngày</span></div><div className="chart-box report-line-chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={data.trend} margin={{ top: 15, right: 14, left: -18, bottom: 0 }}><CartesianGrid stroke="#eae8e2" vertical={false} /><XAxis dataKey="date" tickFormatter={(v: string) => `${v.slice(8, 10)}/${v.slice(5, 7)}`} tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: '#8b8b84' }} /><YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: '#8b8b84' }} /><Tooltip formatter={(value) => [`${value} sự kiện`, 'Cảnh báo']} /><Line type="monotone" dataKey="count" stroke="#70694e" strokeWidth={2.4} dot={false} /></LineChart></ResponsiveContainer></div></article><article className="panel side-chart-panel"><div className="panel-heading"><div><span className="eyebrow">MỨC ĐỘ</span><h2>Phân bố cảnh báo</h2></div></div><div className="severity-chart-wrap report-severity"><div className="chart-box donut-chart"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={data.severity} dataKey="value" nameKey="name" innerRadius="62%" outerRadius="86%" paddingAngle={3} stroke="none">{data.severity.map((item) => <Cell key={item.name} fill={colors[item.name]} />)}</Pie><Tooltip formatter={(value, name) => [value, statusNames[String(name)] ?? name]} /></PieChart></ResponsiveContainer></div><div className="chart-legend">{data.severity.map((item) => <div key={item.name}><span><i style={{ background: colors[item.name] }} />{statusNames[item.name] ?? item.name}</span><b>{item.value}</b></div>)}</div></div></article></div><div className="report-footer-note">Báo cáo được tạo lúc {new Date(data.generated_at).toLocaleString('vi-VN')} · Nguồn: cơ sở dữ liệu SQL Server</div>
  </div>
}

interface ModelItem { id: number; name: string; version: string; status: string; is_demo: boolean; notes: string | null; created_at: string }
export function ModelsPage() {
  const { hasRole } = useAuth()
  const [items, setItems] = useState<ModelItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [modal, setModal] = useState(false)
  const [saving, setSaving] = useState(false)
  const [draft, setDraft] = useState({ name: '', version: '', notes: '' })
  const load = useCallback(() => { setLoading(true); setError(''); api.get<ModelItem[]>('/models').then(({ data }) => setItems(data)).catch((reason) => setError(errorMessage(reason))).finally(() => setLoading(false)) }, [])
  useEffect(() => { load() }, [load])
  async function changeStatus(item: ModelItem, value: string) {
    try { await api.patch(`/models/${item.id}/status`, null, { params: { status: value } }); await load() }
    catch (reason) { setError(errorMessage(reason)) }
  }
  async function createModel(event: FormEvent) {
    event.preventDefault(); setSaving(true)
    try { await api.post('/models', draft); setModal(false); setDraft({ name: '', version: '', notes: '' }); await load() }
    catch (reason) { setError(errorMessage(reason)) }
    finally { setSaving(false) }
  }
  return <div className="page-stack"><div className="page-heading-row"><div><span className="eyebrow">GIÁM SÁT · QUẢN LÝ PHIÊN BẢN</span><h1>Mô hình AI</h1><p>Danh mục metadata phiên bản mô hình. Trang này chưa tải hoặc chạy mô hình.</p></div>{hasRole('admin', 'manager') && <button className="button button-primary" onClick={() => setModal(true)}><Plus size={15} /> Thêm phiên bản demo</button>}</div><div className="model-safety-banner"><Cpu size={17} /><div><b>Chưa kết nối pipeline AI</b><span>Các mục hiển thị chỉ là metadata demo. Không có chỉ số huấn luyện hay suy luận thực tế.</span></div><StatusPill value="demo" /></div><section className="model-grid">{loading ? <LoadingState /> : error ? <ErrorState message={error} retry={load} /> : items.length === 0 ? <EmptyState /> : items.map((item) => <article className="panel model-card" key={item.id}><div className="model-card-top"><span className="model-icon"><Cpu size={18} /></span><StatusPill value={item.status} /></div><span className="eyebrow">{item.name}</span><h2>{item.version}</h2><p>{item.notes}</p><div className="model-card-meta"><span><i className="dot" /> Nhãn mô phỏng</span><time>{new Date(`${item.created_at}Z`).toLocaleDateString('vi-VN')}</time></div>{hasRole('admin', 'manager') && <div className="model-card-actions"><label htmlFor={`model-${item.id}`}>Trạng thái</label><select id={`model-${item.id}`} value={item.status} onChange={(e) => void changeStatus(item, e.target.value)}><option value="demo">Mô phỏng</option><option value="inactive">Tạm dừng</option><option value="active">Đang dùng</option></select></div>}</article>)}</section>{modal && <Modal title="Thêm metadata phiên bản" onClose={() => setModal(false)}><form className="entity-form" onSubmit={createModel}><div className="form-grid"><label className="field-wide">Tên mô hình<input required minLength={2} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="Ví dụ: ArtGuard Contact Demo" /></label><label className="field-wide">Nhãn phiên bản<input required value={draft.version} onChange={(e) => setDraft({ ...draft, version: e.target.value })} placeholder="demo-1.0" /></label><label className="field-wide">Ghi chú<textarea rows={3} value={draft.notes} onChange={(e) => setDraft({ ...draft, notes: e.target.value })} placeholder="Metadata tham khảo; không phải kết quả huấn luyện." /></label></div><div className="simulation-footnote">Bản ghi mới luôn được lưu dưới dạng metadata demo.</div><div className="modal-footer"><button className="button button-secondary" type="button" onClick={() => setModal(false)}>Hủy</button><button className="button button-primary" disabled={saving}>{saving ? 'Đang lưu…' : <><Plus size={15} /> Thêm bản ghi</>}</button></div></form></Modal>}</div>
}

export function UsersPage() {
  const { user: actor } = useAuth()
  const [items, setItems] = useState<User[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [modal, setModal] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState({ username: '', email: '', full_name: '', password: '', role: 'operator' })
  const load = useCallback(() => { setLoading(true); setError(''); api.get<PageResult<User>>('/users', { params: { page_size: 100 } }).then(({ data }) => setItems(data.items)).catch((reason) => setError(errorMessage(reason))).finally(() => setLoading(false)) }, [])
  useEffect(() => { load() }, [load])
  async function create(event: FormEvent) {
    event.preventDefault(); setSaving(true)
    try { await api.post('/users', { ...form, roles: [form.role] }); setModal(false); setForm({ username: '', email: '', full_name: '', password: '', role: 'operator' }); await load() }
    catch (reason) { setError(errorMessage(reason)) }
    finally { setSaving(false) }
  }
  async function toggleUser(target: User) {
    try { await api.patch(`/users/${target.id}`, { is_active: !target.is_active }); await load() }
    catch (reason) { setError(errorMessage(reason)) }
  }
  async function changeRole(target: User, role: string) {
    try { await api.patch(`/users/${target.id}`, { roles: [role] }); await load() }
    catch (reason) { setError(errorMessage(reason)) }
  }
  return <div className="page-stack"><div className="page-heading-row"><div><span className="eyebrow">QUẢN TRỊ HỆ THỐNG</span><h1>Người dùng và phân quyền</h1><p>Quản lý tài khoản nội bộ và vai trò truy cập.</p></div><button className="button button-primary" onClick={() => setModal(true)}><UserRoundPlus size={16} /> Tạo tài khoản</button></div><div className="role-summary"><div><Shield size={17} /><b>Admin</b><span>Quản trị hệ thống, người dùng và cài đặt.</span></div><div><UsersRound size={17} /><b>Manager</b><span>Quản lý tác phẩm, thiết bị, cảnh báo và báo cáo.</span></div><div><Activity size={17} /><b>Operator</b><span>Theo dõi cảnh báo và cập nhật xử lý.</span></div></div><section className="panel list-panel"><div className="panel-heading inner-heading"><div><span className="eyebrow">TÀI KHOẢN</span><h2>Danh sách người dùng <span className="count-chip">{items.length}</span></h2></div><button className="button button-secondary button-small" onClick={load}>Làm mới</button></div>{loading ? <LoadingState /> : error ? <ErrorState message={error} retry={load} /> : items.length === 0 ? <EmptyState /> : <div className="table-scroll"><table className="data-table"><thead><tr><th>Người dùng</th><th>Email</th><th>Vai trò</th><th>Trạng thái</th><th>Ngày tạo</th><th>Thao tác</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td><div className="user-cell"><span className="avatar avatar-small">{item.full_name.slice(0, 1)}</span><span><b className="row-primary">{item.full_name}</b><small className="row-secondary">@{item.username}</small></span></div></td><td>{item.email}</td><td><select className="role-select" aria-label={`Vai trò ${item.username}`} value={item.roles[0] ?? 'operator'} disabled={item.id === actor?.id} onChange={(e) => void changeRole(item, e.target.value)}><option value="admin">Admin</option><option value="manager">Manager</option><option value="operator">Operator</option></select></td><td><StatusPill value={item.is_active ? 'active' : 'inactive'} /></td><td>{new Date(`${item.created_at}Z`).toLocaleDateString('vi-VN')}</td><td><button className={`button button-small ${item.is_active ? 'button-secondary' : 'button-primary'}`} disabled={item.id === actor?.id} onClick={() => void toggleUser(item)}>{item.is_active ? <><LockKeyhole size={14} /> Khóa</> : <><Check size={14} /> Mở khóa</>}</button></td></tr>)}</tbody></table></div>}</section><div className="security-footnote"><Shield size={15} /> Quyền truy cập được kiểm tra ở backend cho từng API; ẩn nút trên giao diện không thay thế phân quyền máy chủ.</div>
    {modal && <Modal title="Tạo tài khoản nội bộ" onClose={() => setModal(false)}><form className="entity-form" onSubmit={create}><div className="form-grid"><label>Tên đăng nhập<input required minLength={3} pattern="[A-Za-z0-9_.-]+" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} /></label><label>Họ và tên<input required minLength={2} value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></label><label className="field-wide">Email<input required type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label><label className="field-wide">Mật khẩu tạm thời<input required type="password" minLength={10} autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /><small>Tối thiểu 10 ký tự. Không thể xem lại sau khi tạo.</small></label><label className="field-wide">Vai trò<select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}><option value="operator">Operator</option><option value="manager">Manager</option><option value="admin">Admin</option></select></label></div><div className="modal-footer"><button className="button button-secondary" type="button" onClick={() => setModal(false)}>Hủy</button><button className="button button-primary" disabled={saving}>{saving ? 'Đang tạo…' : <><Plus size={15} /> Tạo tài khoản</>}</button></div></form></Modal>}
  </div>
}

export function SettingsPage() {
  const { hasRole } = useAuth()
  const [items, setItems] = useState<Setting[]>([])
  const [values, setValues] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const load = useCallback(() => { setLoading(true); setError(''); api.get<Setting[]>('/settings').then(({ data }) => { setItems(data); setValues(Object.fromEntries(data.map((item) => [item.key, item.value]))) }).catch((reason) => setError(errorMessage(reason))).finally(() => setLoading(false)) }, [])
  useEffect(() => { load() }, [load])
  async function save(key: string) {
    setSaving(key)
    try { const { data } = await api.put<Setting>(`/settings/${key}`, { value: values[key] }); setItems((current) => current.map((item) => item.key === key ? data : item)); setNotice('Đã lưu cài đặt.'); window.setTimeout(() => setNotice(''), 2600) }
    catch (reason) { setError(errorMessage(reason)) }
    finally { setSaving(null) }
  }
  const labels: Record<string, string> = { demo_alerts_enabled: 'Cho phép tạo cảnh báo demo', demo_alert_interval_seconds: 'Khoảng thời gian mô phỏng (giây)', system_display_name: 'Tên hiển thị hệ thống', data_mode: 'Chế độ dữ liệu' }
  return <div className="page-stack"><div className="page-heading-row"><div><span className="eyebrow">QUẢN TRỊ HỆ THỐNG</span><h1>Cài đặt</h1><p>Metadata và tùy chọn mô phỏng được lưu trong database.</p></div></div><div className="settings-caution"><Shield size={17} /><span>Thay đổi tại đây không cập nhật cấu hình SQL Server, mạng, camera hoặc AI thực.</span></div>{notice && <div className="toast-notice"><Check size={16} />{notice}</div>}<section className="panel settings-panel"><div className="panel-heading inner-heading"><div><span className="eyebrow">CẤU HÌNH DEMO</span><h2>Tùy chọn ứng dụng</h2></div></div>{loading ? <LoadingState /> : error ? <ErrorState message={error} retry={load} /> : items.length === 0 ? <EmptyState title="Chưa có cài đặt" detail="Hãy chạy seed_demo.py trước." /> : items.map((item) => <div className="setting-row" key={item.key}><div><b>{labels[item.key] ?? item.key}</b><span>{item.key}</span></div><div className="setting-input"><input value={values[item.key] ?? item.value} disabled={!hasRole('admin')} onChange={(e) => setValues({ ...values, [item.key]: e.target.value })} /><button className="button button-secondary button-small" disabled={!hasRole('admin') || saving === item.key || values[item.key] === item.value} onClick={() => void save(item.key)}>{saving === item.key ? 'Đang lưu…' : <><Save size={14} /> Lưu</>}</button></div></div>)}</section></div>
}

export function AuditPage() {
  const [items, setItems] = useState<AuditEntry[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const load = useCallback(() => { setLoading(true); setError(''); api.get('/audit-logs', { params: { page, page_size: 25 } }).then(({ data }) => { setItems(data.items); setTotal(data.total) }).catch((reason) => setError(errorMessage(reason))).finally(() => setLoading(false)) }, [page])
  useEffect(() => { load() }, [load])
  const maxPage = Math.max(1, Math.ceil(total / 25))
  return <div className="page-stack"><div className="page-heading-row"><div><span className="eyebrow">QUẢN TRỊ HỆ THỐNG</span><h1>Nhật ký hoạt động</h1><p>Lịch sử thao tác quan trọng được ghi lại từ backend.</p></div></div><div className="audit-info"><Shield size={16} /><span>Mật khẩu, token và dữ liệu xác thực không được lưu trong nhật ký.</span></div><section className="panel list-panel">{loading ? <LoadingState /> : error ? <ErrorState message={error} retry={load} /> : items.length === 0 ? <EmptyState title="Chưa có hoạt động" /> : <><div className="table-scroll"><table className="data-table"><thead><tr><th>Người thực hiện</th><th>Thao tác</th><th>Đối tượng</th><th>Kết quả</th><th>Chi tiết</th><th>Thời điểm</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td><b className="row-primary">{item.actor}</b></td><td><span className="audit-action">{item.action.replaceAll('_', ' ')}</span></td><td>{item.entity_type}{item.entity_id ? ` #${item.entity_id}` : ''}</td><td><StatusPill value={item.result} /></td><td className="audit-detail-cell">{item.detail ?? '—'}</td><td>{new Date(`${item.created_at}Z`).toLocaleString('vi-VN', { dateStyle: 'short', timeStyle: 'short' })}</td></tr>)}</tbody></table></div><div className="table-pagination"><span>{total} hoạt động · Trang {page}/{maxPage}</span><div><button className="icon-button" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}><ChevronRight className="rotate-180" size={17} /></button><button className="icon-button" disabled={page >= maxPage} onClick={() => setPage((value) => value + 1)}><ChevronRight size={17} /></button></div></div></>}</section></div>
}
