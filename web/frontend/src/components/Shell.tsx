import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Activity, BellRing, BookImage, Boxes, ChevronLeft, ChevronRight, CircleHelp, LayoutDashboard, LogOut, MapPinned, Menu, ScrollText, Settings2, ShieldCheck, UsersRound, Video } from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import { api } from '../api/client'

const links = [
  { to: '/', label: 'Tổng quan', icon: LayoutDashboard, group: 'Không gian làm việc' },
  { to: '/alerts', label: 'Cảnh báo', icon: BellRing, group: 'Không gian làm việc', badge: true },
  { to: '/artworks', label: 'Tác phẩm', icon: BookImage, group: 'Bộ sưu tập' },
  { to: '/locations', label: 'Phòng trưng bày', icon: MapPinned, group: 'Bộ sưu tập' },
  { to: '/devices', label: 'Thiết bị', icon: Video, group: 'Giám sát' },
  { to: '/models', label: 'Mô hình AI', icon: Boxes, group: 'Giám sát' },
  { to: '/reports', label: 'Báo cáo', icon: ScrollText, group: 'Phân tích' },
  { to: '/users', label: 'Người dùng', icon: UsersRound, group: 'Hệ thống', admin: true },
  { to: '/settings', label: 'Cài đặt', icon: Settings2, group: 'Hệ thống', admin: true },
  { to: '/audit', label: 'Nhật ký hoạt động', icon: Activity, group: 'Hệ thống', admin: true },
]

export function Shell() {
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [pendingCount, setPendingCount] = useState<number | null>(null)
  const { user, logout, hasRole } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  useEffect(() => {
    api.get('/dashboard').then(({ data }) => setPendingCount(data.metrics.pending_alerts)).catch(() => setPendingCount(null))
  }, [location.pathname])
  useEffect(() => setMobileOpen(false), [location.pathname])
  const visibleLinks = links.filter((item) => !item.admin || hasRole('admin'))
  const page = visibleLinks.find((item) => item.to === location.pathname)?.label ?? 'Không tìm thấy trang'
  const groups = [...new Set(visibleLinks.map((item) => item.group))]

  async function handleLogout() {
    await logout()
    navigate('/login', { replace: true })
  }

  return <div className={`app-shell ${collapsed ? 'sidebar-collapsed' : ''} ${mobileOpen ? 'mobile-sidebar-open' : ''}`}>
    <div className="mobile-scrim" onClick={() => setMobileOpen(false)} />
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><ShieldCheck size={20} /></div><div className="brand-word"><b>ArtGuard</b><span>COLLECTION CARE</span></div><button className="collapse-button" aria-label="Thu gọn menu" onClick={() => setCollapsed(!collapsed)}>{collapsed ? <ChevronRight size={15} /> : <ChevronLeft size={15} />}</button></div>
      <div className="sidebar-scroll">
        {groups.map((group) => <div className="nav-group" key={group}><span className="nav-group-title">{group}</span>{visibleLinks.filter((item) => item.group === group).map(({ to, label, icon: Icon, badge }) => <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => `nav-link ${isActive ? 'nav-active' : ''}`} title={collapsed ? label : undefined}><Icon size={18} strokeWidth={1.8} /><span>{label}</span>{badge && pendingCount !== null && pendingCount > 0 && <i className="nav-badge">{pendingCount > 9 ? '9+' : pendingCount}</i>}</NavLink>)}</div>)}
      </div>
      <div className="sidebar-foot"><div className="sidebar-help"><CircleHelp size={17} /><span>Trung tâm hỗ trợ</span></div><div className="sidebar-user"><div className="avatar">{user?.full_name.slice(0, 1) ?? 'A'}</div><div className="user-meta"><b>{user?.full_name}</b><span>{user?.roles.join(' · ')}</span></div><button className="icon-button logout-button" title="Đăng xuất" onClick={handleLogout}><LogOut size={16} /></button></div></div>
    </aside>
    <main className="main-area">
      <header className="topbar"><div className="topbar-left"><button className="mobile-menu-button icon-button" aria-label="Mở menu" onClick={() => setMobileOpen(true)}><Menu size={20} /></button><span className="topbar-context">Bảo tàng nghệ thuật</span><span className="topbar-slash">/</span><b>{page}</b></div><div className="topbar-right"><span className="live-indicator"><i /> Dữ liệu mô phỏng</span><button className="topbar-alert icon-button" aria-label="Mở cảnh báo" onClick={() => navigate('/alerts')}><BellRing size={18} />{pendingCount !== null && pendingCount > 0 && <i />}</button><div className="topbar-avatar">{user?.full_name.slice(0, 1) ?? 'A'}</div></div></header>
      <div className="page-frame"><Outlet /></div>
      <footer className="app-footer"><span>ArtGuard <b>·</b> Quản lý bộ sưu tập nghệ thuật</span><span>Hệ thống đang dùng dữ liệu mẫu <i className="dot" /></span></footer>
    </main>
  </div>
}
