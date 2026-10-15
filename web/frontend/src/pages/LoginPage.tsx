import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { ArrowRight, Eye, EyeOff, ShieldCheck } from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import { errorMessage } from '../api/client'

export function LoginPage() {
  const { user, login, ready } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  if (user) return <Navigate to="/" replace />

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    setBusy(true)
    try { await login(username.trim(), password); navigate('/', { replace: true }) }
    catch (reason) { setError(errorMessage(reason)) }
    finally { setBusy(false) }
  }

  return <main className="login-screen"><div className="login-visual"><div className="login-art-orbit orbit-one" /><div className="login-art-orbit orbit-two" /><div className="login-art-card"><div className="art-card-top"><span>COLLECTION NO. 08</span><span>1987 — 1994</span></div><div className="painting-shape"><i /><b /><em /></div><div className="art-card-caption"><span>STUDY OF LIGHT</span><span>01 / 08</span></div></div><div className="visual-copy"><span className="eyebrow">PRESERVE WHAT MATTERS</span><h2>Mỗi tác phẩm<br />kể một câu chuyện.</h2><p>Quản lý bộ sưu tập và theo dõi an toàn trong cùng một không gian.</p></div><span className="visual-coordinate">16°03′ N&nbsp;&nbsp; 108°12′ E</span></div>
    <section className="login-panel"><div className="login-panel-inner"><div className="login-brand"><div className="brand-mark"><ShieldCheck size={20} /></div><div><b>ArtGuard</b><span>COLLECTION CARE</span></div></div><div className="login-heading"><span className="eyebrow">CHÀO MỪNG TRỞ LẠI</span><h1>Đăng nhập</h1><p>Nhập thông tin tài khoản để vào không gian quản lý.</p></div><form className="login-form" onSubmit={submit}><label>Tên đăng nhập<div className="input-wrap"><input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required placeholder="Tên đăng nhập" /></div></label><label>Mật khẩu<div className="input-wrap"><input autoComplete="current-password" type={showPassword ? 'text' : 'password'} value={password} onChange={(e) => setPassword(e.target.value)} required placeholder="Nhập mật khẩu" /><button type="button" className="password-toggle" aria-label="Hiện hoặc ẩn mật khẩu" onClick={() => setShowPassword(!showPassword)}>{showPassword ? <EyeOff size={17} /> : <Eye size={17} />}</button></div></label>{error && <div className="form-alert">{error}</div>}<button className="button button-primary login-submit" disabled={busy || !ready}>{busy ? 'Đang xác thực…' : <>Vào hệ thống <ArrowRight size={16} /></>}</button></form><div className="login-note"><ShieldCheck size={15} /><span>Phiên đăng nhập chỉ được lưu trong bộ nhớ trình duyệt.</span></div><div className="login-footer"><span>© 2026 ArtGuard</span><span><i className="dot" /> Môi trường phát triển</span></div></div></section>
  </main>
}
