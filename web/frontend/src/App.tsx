import { useEffect, useState, type ReactNode } from 'react'
import { BrowserRouter, Link, Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import { ArrowLeft, ShieldAlert } from 'lucide-react'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { Shell } from './components/Shell'
import { LoginPage } from './pages/LoginPage'
import { DashboardPage } from './pages/DashboardPage'
import { DataPage } from './pages/DataPage'
import { AlertsPage } from './pages/AlertsPage'
import { AuditPage, ModelsPage, ReportsPage, SettingsPage, UsersPage } from './pages/OperationsPages'

function RequireAuth() {
  const { user } = useAuth()
  const location = useLocation()
  return user ? <Outlet /> : <Navigate to="/login" replace state={{ from: location.pathname }} />
}

function RequireRole({ roles, children }: { roles: string[]; children: ReactNode }) {
  const { hasRole } = useAuth()
  return hasRole(...roles) ? children : <Navigate to="/" replace />
}

function NotFound() {
  return <main className="not-found"><div className="not-found-card"><span className="not-found-mark"><ShieldAlert size={20} /></span><span className="eyebrow">LỖI 404</span><h1>Không tìm thấy trang</h1><p>Đường dẫn có thể đã thay đổi hoặc không còn tồn tại.</p><Link className="button button-primary" to="/"><ArrowLeft size={15} /> Về tổng quan</Link></div></main>
}

function SessionNotice() {
  const { user } = useAuth()
  const [expired, setExpired] = useState(false)
  useEffect(() => {
    const onExpired = () => { setExpired(true); window.setTimeout(() => setExpired(false), 6500) }
    window.addEventListener('artguard:session-expired', onExpired)
    return () => window.removeEventListener('artguard:session-expired', onExpired)
  }, [])
  if (!expired || user) return null
  return <div className="session-toast"><ShieldAlert size={16} /> Phiên đăng nhập đã hết hạn. Hãy đăng nhập lại.</div>
}

function AppRoutes() {
  return <><SessionNotice /><Routes><Route path="/login" element={<LoginPage />} /><Route element={<RequireAuth />}><Route element={<Shell />}><Route index element={<DashboardPage />} /><Route path="alerts" element={<AlertsPage />} /><Route path="artworks" element={<DataPage kind="artworks" />} /><Route path="locations" element={<DataPage kind="locations" />} /><Route path="devices" element={<DataPage kind="devices" />} /><Route path="models" element={<ModelsPage />} /><Route path="reports" element={<ReportsPage />} /><Route path="users" element={<RequireRole roles={['admin']}><UsersPage /></RequireRole>} /><Route path="settings" element={<RequireRole roles={['admin']}><SettingsPage /></RequireRole>} /><Route path="audit" element={<RequireRole roles={['admin']}><AuditPage /></RequireRole>} /></Route></Route><Route path="*" element={<NotFound />} /></Routes></>
}

export function App() {
  return <BrowserRouter><AuthProvider><AppRoutes /></AuthProvider></BrowserRouter>
}
