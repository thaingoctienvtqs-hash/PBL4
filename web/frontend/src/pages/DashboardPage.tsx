import { useCallback, useState } from 'react'
import { Activity, AlertTriangle, ArrowUpRight, BookOpen, Camera, ChevronRight, CircleCheck, RadioTower, ShieldAlert } from 'lucide-react'
import { CartesianGrid, Cell, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, alertOriginLabel, getIntegrationStatus, withAlertOrigins } from '../api/client'
import type { DashboardData } from '../types'
import { ErrorState, LoadingState, StatusPill } from '../components/States'
import { Link } from 'react-router-dom'
import { useAlertVisibility, usePolling } from '../hooks/usePolling'
import { formatEventTime } from '../utils/datetime'

const severityLabels: Record<string, string> = { low: 'Thấp', medium: 'Trung bình', high: 'Cao', critical: 'Nghiêm trọng' }
const severityColors: Record<string, string> = { low: '#9bbaa8', medium: '#d7b66b', high: '#d8875e', critical: '#b84839' }
const statusLabels: Record<string, string> = { online: 'Hoạt động', offline: 'Ngoại tuyến', maintenance: 'Bảo trì' }

export function DashboardPage() {
  const [days, setDays] = useState(7)
  const fetchDashboard = useCallback(async (signal: AbortSignal) => {
    const [result, profile] = await Promise.all([
      api.get<DashboardData>('/dashboard', { params: { days }, signal }), getIntegrationStatus(signal),
    ])
    const recent_alerts = await withAlertOrigins(result.data.recent_alerts, profile, signal)
    return { ...result.data, recent_alerts, profile }
  }, [days])
  const { data, error, loading, refresh: load, updatedAt } = usePolling(fetchDashboard, 2000)
  useAlertVisibility(data?.recent_alerts)

  if (loading) return <LoadingState label="Đang tổng hợp số liệu từ cơ sở dữ liệu…" />
  if (!data) return <ErrorState message={error || 'Không tải được dashboard'} retry={load} />

  const metrics = [
    { label: 'Tác phẩm quản lý', value: data.metrics.artworks, icon: BookOpen, note: 'Trong bộ sưu tập', color: 'sand' },
    { label: 'Thiết bị giám sát', value: data.metrics.devices, icon: Camera, note: `${data.metrics.active_devices} đang hoạt động`, color: 'sage' },
    { label: 'Cảnh báo chờ xử lý', value: data.metrics.pending_alerts, icon: ShieldAlert, note: 'Cần được rà soát', color: 'amber' },
    { label: 'Mức nghiêm trọng', value: data.metrics.critical_alerts, icon: AlertTriangle, note: 'Đang chờ xử lý', color: 'rose' },
  ]

  return <div className="page-stack"><div className="page-heading-row"><div><span className="eyebrow">THỨ TƯ · PHÒNG TRƯNG BÀY</span><h1>Tổng quan</h1><p>Theo dõi bộ sưu tập và tình trạng giám sát hôm nay.</p></div><div className="heading-actions"><span className="data-mode-badge"><i /> {data.profile ? 'SQL Server TEST' : 'Nguồn theo từng sự kiện'}</span><button className="button button-secondary" onClick={load}><Activity size={15} /> Làm mới</button></div></div>
    <div className="notice-banner"><div className="notice-icon"><RadioTower size={17} /></div><div><b>{data.profile ? data.profile.database_name : 'Theo dõi dữ liệu backend'}</b><span>DEMO / SYNTHETIC_TEST là mô phỏng. REAL_AI yêu cầu metadata ingest xác minh. Không có camera vẫn có thể kiểm thử phần mềm. Tự cập nhật sau mỗi 2 giây.</span></div><Link to="/settings">Cấu hình <ChevronRight size={14} /></Link></div>
    {error && <ErrorState message={error + ' Dữ liệu đang hiển thị là lần tải thành công trước.'} retry={load} />}
    <section className="metric-grid">{metrics.map(({ label, value, icon: Icon, note, color }) => <article className="metric-card" key={label}><div className={`metric-icon metric-${color}`}><Icon size={18} /></div><span className="metric-label">{label}</span><div className="metric-value-row"><strong>{value.toLocaleString('vi-VN')}</strong><span className="metric-note">{note}</span></div></article>)}</section>
    <section className="dashboard-grid"><article className="panel trend-panel"><div className="panel-heading"><div><span className="eyebrow">HOẠT ĐỘNG</span><h2>Diễn biến cảnh báo</h2></div><select aria-label="Khoảng thời gian" className="compact-select" value={days} onChange={(e) => setDays(Number(e.target.value))}><option value={7}>7 ngày</option><option value={14}>14 ngày</option><option value={30}>30 ngày</option></select></div><div className="chart-summary"><b>{data.trend.reduce((sum, item) => sum + item.count, 0)}</b><span>sự kiện trong {days} ngày</span><span className="chart-summary-mark"><ArrowUpRight size={14} /> {data.profile ? 'dữ liệu TEST' : 'dữ liệu backend'}</span></div><div className="chart-box trend-chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={data.trend} margin={{ top: 14, right: 14, left: -18, bottom: 0 }}><CartesianGrid stroke="#eae8e2" vertical={false} /><XAxis dataKey="date" tickFormatter={(v: string) => `${v.slice(8, 10)}/${v.slice(5, 7)}`} tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: '#8b8b84' }} dy={9} /><YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: '#8b8b84' }} /><Tooltip labelFormatter={(v) => new Date(`${v}T00:00:00`).toLocaleDateString('vi-VN')} formatter={(v) => [`${v} sự kiện`, 'Cảnh báo']} contentStyle={{ borderRadius: 10, border: '1px solid #e8e5dd', fontSize: 12 }} /><Line type="monotone" dataKey="count" stroke="#70694e" strokeWidth={2.4} dot={{ r: 3, fill: '#70694e', stroke: '#fff', strokeWidth: 2 }} activeDot={{ r: 5 }} /></LineChart></ResponsiveContainer></div></article>
    <article className="panel side-chart-panel"><div className="panel-heading"><div><span className="eyebrow">PHÂN LOẠI</span><h2>Mức độ cảnh báo</h2></div><span className="subtle-tag">{data.severity.reduce((sum, item) => sum + item.value, 0)} tổng</span></div><div className="severity-chart-wrap"><div className="chart-box donut-chart"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={data.severity} dataKey="value" nameKey="name" innerRadius="65%" outerRadius="88%" paddingAngle={3} stroke="none">{data.severity.map((item) => <Cell key={item.name} fill={severityColors[item.name] ?? '#9da19a'} />)}</Pie><Tooltip formatter={(v, name) => [v, severityLabels[String(name)] ?? name]} contentStyle={{ borderRadius: 10, border: '1px solid #e8e5dd', fontSize: 12 }} /></PieChart></ResponsiveContainer><div className="donut-center"><b>{data.severity.reduce((sum, item) => sum + item.value, 0)}</b><span>sự kiện</span></div></div><div className="chart-legend">{data.severity.map((item) => <div key={item.name}><span><i style={{ background: severityColors[item.name] }} />{severityLabels[item.name] ?? item.name}</span><b>{item.value}</b></div>)}</div></div><div className="device-status-strip">{data.device_status.map((item) => <div key={item.name}><span><i className={`status-dot dot-${item.name}`} />{statusLabels[item.name] ?? item.name}</span><b>{item.value}</b></div>)}</div></article></section>
    <section className="panel recent-panel"><div className="panel-heading"><div><span className="eyebrow">CẬP NHẬT GẦN ĐÂY</span><h2>Cảnh báo mới nhất</h2></div><Link className="text-link" to="/alerts">Xem tất cả <ChevronRight size={15} /></Link></div>{data.recent_alerts.length === 0 ? <div className="inline-empty"><CircleCheck size={18} /> Chưa ghi nhận cảnh báo nào.</div> : <div className="table-scroll"><table className="data-table"><thead><tr><th>Sự kiện</th><th>Tác phẩm / thiết bị</th><th>Mức độ</th><th>Trạng thái</th><th>Thời điểm</th><th /></tr></thead><tbody>{data.recent_alerts.slice(0, 6).map((alert) => <tr key={alert.id} data-alert-id={alert.id} data-event-id={alert.ingest?.event_id} data-origin={alertOriginLabel(alert)}><td><b className="row-primary">{alert.title}</b><span className="row-secondary">{alert.event_code} · {alertOriginLabel(alert)}</span></td><td><span className="row-primary">{alert.artwork_title ?? '—'}</span><span className="row-secondary">{alert.device_name ?? 'Chưa gán thiết bị'}</span></td><td><StatusPill value={alert.severity} /></td><td><StatusPill value={alert.status} /></td><td>{formatEventTime(alert.detected_at, { dateStyle: 'medium', timeStyle: 'short' })}</td><td><Link className="table-arrow" to="/alerts" aria-label="Xem cảnh báo"><ChevronRight size={17} /></Link></td></tr>)}</tbody></table></div>}<div className="panel-footnote"><span>Chỉ số được truy vấn từ SQL Server.</span><span>Cập nhật {updatedAt ? new Date(updatedAt).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' }) : formatEventTime(data.generated_at)}</span></div></section>
  </div>
}
