

'use client'

import { useEffect, useState } from 'react'
import {
  usePathname,
  useRouter,
  useSearchParams,
} from 'next/navigation'
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Bell,
  CheckCircle2,
  ChevronDown,
  Database,
  FileCheck2,
  Gauge,
  LineChart,
  Menu,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Timer,
} from 'lucide-react'

type View =
  | 'landing'
  | 'login'
  | 'overview'
  | 'quality'
  | 'processing'
  | 'sla'
  | 'anomalies'
  | 'insights'
  | 'alerts'
  | 'batch'
  | 'data'
  | 'settings'

const nav = [
  ['overview', 'Overview', Activity],
  ['quality', 'Data Quality', Database],
  ['processing', 'Processing', Timer],
  ['sla', 'SLA & Behavior', Gauge],
  ['anomalies', 'Anomalies', AlertTriangle],
  ['insights', 'Insights', Sparkles],
  ['alerts', 'Alerts', Bell],
  ['settings', 'Settings', Settings2],
] as const

const dimensions = [
  'Completeness',
  'Validity',
  'Uniqueness',
  'Timeliness',
  'Consistency',
  'Accuracy',
  'Integrity',
  'Conformity',
]

const findings = [
  ['Member ID', 'Format validation', '1,204', '0.38%', 'Medium', 'Review'],
  ['Date of Service', 'Required field', '482', '0.15%', 'Low', 'Resolved'],
  ['Procedure Code', 'Code set match', '89', '0.03%', 'High', 'Open'],
  ['Payer ID', 'Reference integrity', '12', '0.01%', 'Low', 'Monitoring'],
]

type AuthUser = {
  email: string
  name: string
}

type RoutedPage =
  | 'dashboard'
  | 'data'
  | 'claims'
  | 'claim-detail'
  | 'drugs'
  | 'providers'
  | 'provider-detail'

type DashboardModule =
  | 'claims'
  | 'drugs'
  | 'authorization'

const dashboardModules: Array<{
  key: DashboardModule
  label: string
}> = [
  { key: 'claims', label: 'Claims' },
  { key: 'drugs', label: 'Drugs' },
  { key: 'authorization', label: 'Authorization' },
]

function toTitleCase(value: string) {
  return value
    .split(' ')
    .filter(Boolean)
    .map(part => part[0].toUpperCase() + part.slice(1).toLowerCase())
    .join(' ')
}

function deriveNameFromEmail(email: string) {
  const localPart = email.split('@')[0] || ''
  const normalized = localPart.replace(/[._-]+/g, ' ')
  const display = toTitleCase(normalized)

  return display || 'User'
}

function getInitials(name: string) {
  const parts = name
    .trim()
    .split(' ')
    .filter(Boolean)

  if (parts.length === 0) return 'U'

  if (parts.length === 1) {
    return parts[0].slice(0, 2).toUpperCase()
  }

  return `${parts[0][0] || ''}${parts[1][0] || ''}`.toUpperCase()
}

function Glass({
  children,
  className = '',
  style,
}: {
  children: React.ReactNode
  className?: string
  style?: React.CSSProperties
}) {
  return (
    <div className={`glass ${className}`} style={style}>
      {children}
    </div>
  )
}

function Status({
  children,
  tone = 'good',
}: {
  children: React.ReactNode
  tone?: 'good' | 'warn' | 'bad' | 'info'
}) {
  return <span className={`status ${tone}`}>{children}</span>
}

function Logo() {
  return (
    <div className="brand">
      <img
        src="/claimcare_logo.png"
        alt="ClaimCare - Data Quality Monitoring for Insurance"
        className="claimcare_logo"
      />
    </div>
  )
}

export default function ClaimCareApp() {
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const router = useRouter()
  const [view, setView] = useState<View>('landing')
  const [mobileNav, setMobileNav] = useState(false)
  const [alertFilter, setAlertFilter] = useState('All')
  const [search, setSearch] = useState('')
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null)

  const routedPage: RoutedPage =
    pathname.startsWith('/claims/')
      ? 'claim-detail'
      : pathname === '/claims'
        ? 'claims'
        : pathname === '/data'
          ? 'data'
        : pathname === '/drugs'
          ? 'drugs'
        : pathname.startsWith('/providers/')
          ? 'provider-detail'
          : pathname === '/providers'
            ? 'providers'
            : 'dashboard'

  useEffect(() => {
    const raw = localStorage.getItem('claimcare_user')

    if (!raw) return

    try {
      const parsed = JSON.parse(raw) as Partial<AuthUser>

      if (parsed.email) {
        const resolvedName =
          parsed.name?.trim() ||
          deriveNameFromEmail(parsed.email)

        setCurrentUser({
          email: parsed.email,
          name: resolvedName,
        })
      }
    } catch {
      // Ignore malformed auth data in localStorage.
    }
  }, [])

  const go = (next: View) => {
    setView(next)
    setMobileNav(false)

    if (pathname !== '/') {
      router.push('/')
      return
    }

    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const displayName =
    currentUser?.name?.trim() || 'Alex Rivera'

  const firstName =
    displayName.split(' ')[0] || 'Alex'

  if (
    routedPage === 'dashboard' &&
    view === 'landing'
  ) {
    return <Landing go={go} />
  }

  if (
    routedPage === 'dashboard' &&
    view === 'login'
  ) {
    return (
      <Login
        go={go}
        onAuth={user => setCurrentUser(user)}
      />
    )
  }

  const active =
    routedPage === 'data'
      ? 'View Data'
      : routedPage === 'claims'
      ? 'All Claims'
      : routedPage === 'claim-detail'
        ? 'Claim Detail'
        : routedPage === 'drugs'
          ? 'Drug Records'
        : routedPage === 'providers'
          ? 'All Providers'
          : routedPage === 'provider-detail'
            ? 'Provider Profile'
            : nav.find(([key]) => key === view)?.[1] ?? 'Overview'

  const routeClaimId =
    routedPage === 'claim-detail'
      ? decodeURIComponent(
          pathname.split('/').pop() || ''
        )
      : ''

  const routeNpi =
    routedPage === 'provider-detail'
      ? decodeURIComponent(
          pathname.split('/').pop() || ''
        )
      : ''

  const routePeriod =
    searchParams.get('period') || ''

  const routeRiskLevel =
    searchParams.get('risk_level') || ''

  const routeDrugDataset =
    searchParams.get('dataset') || 'drug-volume'

  const routeDrugYear =
    searchParams.get('calendar_year') || ''

  const routeAlertLevel =
    searchParams.get('alert_level') || ''

  const dashboardModule: DashboardModule =
    searchParams.get('module') ===
    'authorization'
      ? 'authorization'
      : searchParams.get('module') ===
          'drugs'
        ? 'drugs'
        : 'claims'

  return (
    <div className="app-shell">
      <Background />

      <header className="topbar">
        <button
          className="mobile-menu"
          onClick={() => setMobileNav(!mobileNav)}
          aria-label="Open navigation"
        >
          <Menu />
        </button>

        <button
          className="logo-button"
          onClick={() =>
            routedPage === 'dashboard'
              ? go('overview')
              : router.push('/')
          }
        >
          <Logo />
        </button>

        <div className="top-actions">
          <button className="icon-button">
            <Search size={16} />
          </button>

          <button className="icon-button notification">
            <Bell size={16} />
            <i />
          </button>

          <button className="profile">
            <span>{getInitials(displayName)}</span>
            <strong>
              {displayName}
              <small>
                {currentUser?.email ||
                  'Operations lead'}
              </small>
            </strong>
            <ChevronDown size={14} />
          </button>
        </div>
      </header>

      {routedPage === 'dashboard' && (
        <div className="subnav-shell">
          <div className="subnav">
            {dashboardModules.map(module => (
              <button
                key={module.key}
                className={
                  dashboardModule === module.key
                    ? 'active'
                    : ''
                }
                onClick={() => {
                  setView('overview')
                  setMobileNav(false)
                  router.push(
                    `/${buildQuery({
                      module: module.key,
                    })}`
                  )
                }}
              >
                {module.label}
              </button>
            ))}
          </div>
        </div>
      )}

      <main className="workspace">
        <div className="page-heading">
          <div>
            <p className="eyebrow">
              PAYER OPERATIONS / {active.toUpperCase()}
            </p>

            <h1>
              {routedPage === 'dashboard' &&
              active === 'Overview' ? (
                <>
                  Good morning, <em>{firstName}</em>
                </>
              ) : (
                active
              )}
            </h1>

            <p className="subhead">
              {routedPage === 'dashboard' &&
              active === 'Overview'
                ? 'Here is the current health of your payer data operations.'
                : routedPage === 'claims'
                  ? routePeriod
                    ? `Claims for ${routePeriod} with live pagination, filters, and export.`
                    : 'Browse the complete claims dataset with live filters and drill-down.'
                  : routedPage === 'data'
                    ? 'Browse the connected claim_sentinel data tables.'
                  : routedPage === 'claim-detail'
                    ? `Inspect claim ${routeClaimId} using only the fields available from the connected data sources.`
                    : routedPage === 'drugs'
                      ? routeDrugDataset === 'provider-impact'
                        ? 'Review the pharmacy provider impact records with live filters and export.'
                        : routeDrugDataset === 'overall-trend'
                          ? routeDrugYear
                            ? `Review the pharmacy overall trend record for ${routeDrugYear}.`
                            : 'Review the pharmacy overall risk trend table with live filters and export.'
                          : routeRiskLevel
                            ? `${toTitleCase(routeRiskLevel.replace(/_/g, ' '))} drug records with live filters and export.`
                            : 'Browse pharmacy drug risk records with live filters, chart drill-down, and export.'
                    : routedPage === 'providers'
                      ? routeRiskLevel
                        ? `${toTitleCase(routeRiskLevel.replace(/_/g, ' '))} provider landscape with live summary metrics.`
                        : 'Browse provider risk profiles with live filters and drill-down analytics.'
                      : routedPage === 'provider-detail'
                        ? `Review provider ${routeNpi} volume risk, history, and associated claims.`
                : `Monitor, understand, and improve your ${active.toLowerCase()} signals.`}
            </p>
          </div>

          <div className="heading-actions">
            {routedPage === 'dashboard' ? (
              <>
                <button
                  className="small-button"
                  onClick={() => router.back()}
                >
                  <ArrowLeft size={16} />
                  Back
                </button>
                <button
                  className="primary-button"
                  onClick={() => router.push('/data?dataset=carrier')}
                >
                  <Database size={16} />
                  View data
                </button>
              </>
            ) : (
              <button
                className="primary-button"
                onClick={() => router.back()}
              >
                <ArrowLeft size={16} />
                Back
              </button>
            )}
          </div>
        </div>

        {routedPage === 'dashboard' && view === 'overview' && (
          <Overview
            go={go}
            router={router}
            module={dashboardModule}
          />
        )}
        {routedPage === 'dashboard' && view === 'quality' && <Quality />}
        {routedPage === 'dashboard' && view === 'processing' && <Processing />}
        {routedPage === 'dashboard' && view === 'sla' && <SLA />}
        {routedPage === 'dashboard' && view === 'anomalies' && <Anomalies />}
        {routedPage === 'dashboard' && view === 'insights' && <Insights />}
        {routedPage === 'dashboard' && view === 'alerts' && (
          <Alerts
            filter={alertFilter}
            setFilter={setAlertFilter}
            search={search}
            setSearch={setSearch}
          />
        )}
        {routedPage === 'dashboard' && view === 'batch' && <Batch />}
        {routedPage === 'dashboard' && view === 'settings' && <Settings />}
        {routedPage === 'data' && <DataPage router={router} />}
        {routedPage === 'claims' && <ClaimsPage router={router} />}
        {routedPage === 'claim-detail' && (
          <ClaimDetailPage
            claimId={routeClaimId}
            router={router}
          />
        )}
        {routedPage === 'drugs' && (
          <DrugsPage router={router} />
        )}
        {routedPage === 'providers' && (
          <ProvidersPage router={router} />
        )}
        {routedPage === 'provider-detail' && (
          <ProviderDetailPage
            npi={routeNpi}
            router={router}
            initialAlertLevel={routeAlertLevel}
          />
        )}
      </main>
    </div>
  )
}

function Background() {
  return (
    <div className="ambient" aria-hidden="true">
      <span className="pulse p1" />
      <span className="pulse p2" />
      <span className="grid-lines" />

      <svg
        className="ecg"
        viewBox="0 0 900 180"
        preserveAspectRatio="none"
      >
        <path d="M0 100h160l24-1 20-66 24 112 28-45h160l18-1 20-43 23 75 30-31h190" />
      </svg>
    </div>
  )
}

function Landing({ go }: { go: (v: View) => void }) {
  return (
    <div className="landing">
      <Background />

      <header className="landing-nav">
        <Logo />

        <div className="landing-links">
          <a href="#platform">Overview</a>
          <a href="#signals">Capabilities</a>
          <a href="#security">Monitoring</a>
        </div>

        <button
          className="login-link"
          onClick={() => go('login')}
        >
          Sign up/Sign in
        </button>
      </header>

      <main className="hero">
        <div className="hero-copy">
          <div className="kicker">
            <span className="live-dot" />
            Intelligence for payer operations
          </div>

          <h1>
            See the story
            <br />
            behind every <em>claim.</em>
          </h1>

          <p>
            ClaimCare turns payer data pipelines into a living picture of
            operational health — revealing quality gaps, processing friction,
            and the next best action before they become costly.
          </p>

          <div className="hero-actions">
            <button
              className="primary-button"
              onClick={() => go('login')}
            >
              Explore the platform <ArrowRight size={16} />
            </button>

          </div>

          <div className="trust-row">
            <ShieldCheck size={16} />
            Built for sensitive healthcare operations
            <span />
          </div>
        </div>

        <div className="hero-visual">
          <Glass className="signal-card">
            <div className="signal-head">
              <div>
                <span className="mini-label">LIVE PIPELINE PULSE</span>
                <h3>Claims ingestion</h3>
              </div>

              <Status>Healthy</Status>
            </div>

            <div className="pulse-chart">
              <span className="chart-glow" />

              <div className="bars">
                {[42, 58, 48, 74, 60, 84, 72, 92, 76, 88, 100, 86].map(
                  (h, i) => (
                    <i
                      key={i}
                      style={{ height: `${h}%` }}
                    />
                  )
                )}
              </div>
            </div>

            <div className="signal-foot">
              <div>
                <small>Records processed</small>
                <strong>3.18M</strong>
              </div>

              <div>
                <small>Current batch</small>
                <strong>CC-2847</strong>
              </div>

              <div>
                <small>Last sync</small>
                <strong>2m ago</strong>
              </div>
            </div>
          </Glass>

          <div className="floating-tag tag-one">
            <CheckCircle2 size={15} />
            Quality score <strong>98.7</strong>
          </div>

          <div className="floating-tag tag-two">
            <Activity size={15} />
            Signal detected <strong>2m</strong>
          </div>
        </div>
      </main>

      <section id="platform" className="platform-section">
        <div className="section-intro">
          <p className="eyebrow">ONE CONNECTED VIEW</p>

          <h2>
            From raw signal to
            <br />
            <em>clear action.</em>
          </h2>
        </div>

        <div className="feature-grid">
          {[
            ['Data Quality', 'Eight dimensions. One trusted score.', Database],
            ['Processing', 'Know when the pipeline drifts.', Timer],
            ['SLA & Behavior', 'See the patterns that change outcomes.', Gauge],
            ['Anomaly Detection', 'Surface what deserves attention.', AlertTriangle],
            ['Root Cause', 'Move from symptom to source.', LineChart],
            ['Recommendations', 'Give teams their next best move.', Sparkles],
          ].map(([title, copy, Icon]) => (
            <Glass
              className="feature-card"
              key={title as string}
            >
              <span className="feature-icon">
                <Icon size={19} />
              </span>

              <h3>{title as string}</h3>
              <p>{copy as string}</p>
              <ArrowRight size={16} />
            </Glass>
          ))}
        </div>
      </section>

      <section id="security" className="cta-band">
        <div>
          <p className="eyebrow">THE OPERATIONS ADVANTAGE</p>

          <h2>
            Healthcare data deserves
            <br />
            <em>better visibility.</em>
          </h2>
        </div>

        <button
          className="primary-button"
          onClick={() => go('login')}
        >
          Enter ClaimCare <ArrowRight size={16} />
        </button>
      </section>

      <footer>
        <Logo />
        <span>Intelligent payer monitoring for a healthier operation.</span>
        <span>© 2026 ClaimCare</span>
      </footer>
    </div>
  )
}

/* ============================================================
   UPDATED LOGIN
   ============================================================ */
function Login({
  go,
  onAuth,
}: {
  go: (v: View) => void
  onAuth: (user: AuthUser) => void
}) {
  const [mode, setMode] = useState<'signin' | 'signup'>('signin')

  const [fullName, setFullName] = useState('')
  const [workEmail, setWorkEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')

  const [showPassword, setShowPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)

  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')


  async function handleSubmit(
    event: React.FormEvent<HTMLFormElement>
  ) {
    event.preventDefault()

    setError('')
    setMessage('')


    // ========================================================
    // VALIDATION
    // ========================================================

    if (!workEmail.trim() || !password) {
      setError('Please enter your email and password.')
      return
    }


    // ========================================================
    // SIGN UP VALIDATION
    // ========================================================

    if (mode === 'signup') {

      if (!fullName.trim()) {
        setError('Please enter your name.')
        return
      }

      if (password.length < 6) {
        setError('Password must contain at least 6 characters.')
        return
      }

      if (password !== confirmPassword) {
        setError('Passwords do not match.')
        return
      }
    }


    try {

      setLoading(true)

      const email = workEmail.trim().toLowerCase()
      let name = fullName.trim()

      if (mode === 'signup') {
        const existingRaw =
          localStorage.getItem('claimcare_users')

        const users: Record<string, string> =
          existingRaw
            ? JSON.parse(existingRaw)
            : {}

        users[email] = name

        localStorage.setItem(
          'claimcare_users',
          JSON.stringify(users)
        )
      } else {
        const existingRaw =
          localStorage.getItem('claimcare_users')

        const users: Record<string, string> =
          existingRaw
            ? JSON.parse(existingRaw)
            : {}

        name =
          users[email]?.trim() ||
          deriveNameFromEmail(email)
      }

      // Store user email locally (demo mode — no backend auth)
      localStorage.setItem(
        'claimcare_user',
        JSON.stringify({
          email,
          name,
        })
      )

      onAuth({ email, name })

      go('overview')

    } catch (err) {

      console.error(err)

      setError(
        err instanceof Error
          ? err.message
          : 'Unable to connect to the server.'
      )

    } finally {

      setLoading(false)
    }
  }


  return (
    <div className="login-page">

      <Background />


      <header className="landing-nav">

        <button
          className="login-link"
          onClick={() => go('landing')}
        >
          <ArrowLeft size={15} />
          Back to site
        </button>

      </header>


      <Glass className="login-card">

        {/* ==================================================
            TITLE
        ================================================== */}

        <p className="eyebrow">
          {mode === 'signin'
            ? 'WELCOME BACK'
            : 'CREATE ACCOUNT'}
        </p>


        <h1>
          {mode === 'signin'
            ? 'Welcome to ClaimCare'
            : 'Create your ClaimCare account'}
        </h1>


        <p>
          {mode === 'signin'
            ? 'Sign in to your payer operations workspace.'
            : 'Create an account to access your payer operations workspace.'}
        </p>


        {/* ==================================================
            SIGN IN / SIGN UP SWITCH
        ================================================== */}

        <div
          style={{
            display: 'flex',
            gap: '8px',
            margin: '20px 0',
          }}
        >

          <button
            type="button"
            onClick={() => {
              setMode('signin')
              setError('')
              setMessage('')
            }}
            style={{
              flex: 1,
              padding: '10px',
              borderRadius: '10px',
              border: '1px solid rgba(255,255,255,0.2)',
              background:
                mode === 'signin'
                  ? 'rgba(255,255,255,0.2)'
                  : 'transparent',
              cursor: 'pointer',
            }}
          >
            Sign In
          </button>


          <button
            type="button"
            onClick={() => {
              setMode('signup')
              setError('')
              setMessage('')
            }}
            style={{
              flex: 1,
              padding: '10px',
              borderRadius: '10px',
              border: '1px solid rgba(255,255,255,0.2)',
              background:
                mode === 'signup'
                  ? 'rgba(255,255,255,0.2)'
                  : 'transparent',
              cursor: 'pointer',
            }}
          >
            Sign Up
          </button>

        </div>


        {/* ==================================================
            FORM
        ================================================== */}

        <form onSubmit={handleSubmit}>

          {/* NAME - SIGN UP ONLY */}

          {mode === 'signup' && (

            <label>

              Full name

              <input
                value={fullName}

                onChange={e =>
                  setFullName(e.target.value)
                }

                type="text"

                autoComplete="name"

                placeholder="Enter your full name"

                required
              />

            </label>

          )}

          {/* EMAIL */}

          <label>

            Work email

            <input
              value={workEmail}

              onChange={e =>
                setWorkEmail(e.target.value)
              }

              type="email"

              autoComplete="email"

              placeholder="you@healthsystem.org"

              required
            />

          </label>


          {/* PASSWORD */}

          <label>

            Password

            <div className="password">

              <input
                value={password}

                onChange={e =>
                  setPassword(e.target.value)
                }

                type={
                  showPassword
                    ? 'text'
                    : 'password'
                }

                autoComplete={
                  mode === 'signin'
                    ? 'current-password'
                    : 'new-password'
                }

                placeholder="Enter your password"

                required
              />


              <button
                type="button"

                onClick={() =>
                  setShowPassword(
                    !showPassword
                  )
                }
              >
                {showPassword
                  ? 'Hide'
                  : 'Show'}
              </button>

            </div>

          </label>


          {/* CONFIRM PASSWORD - SIGN UP ONLY */}

          {mode === 'signup' && (

            <label>

              Confirm password

              <div className="password">

                <input
                  value={confirmPassword}

                  onChange={e =>
                    setConfirmPassword(
                      e.target.value
                    )
                  }

                  type={
                    showConfirmPassword
                      ? 'text'
                      : 'password'
                  }

                  autoComplete="new-password"

                  placeholder="Confirm your password"

                  required
                />


                <button
                  type="button"

                  onClick={() =>
                    setShowConfirmPassword(
                      !showConfirmPassword
                    )
                  }
                >
                  {showConfirmPassword
                    ? 'Hide'
                    : 'Show'}
                </button>

              </div>

            </label>

          )}


          {/* SUCCESS MESSAGE */}

          {message && (

            <p
              style={{
                color: '#16803c',
                margin: '8px 0 12px',
                fontSize: '13px',
              }}
            >
              {message}
            </p>

          )}


          {/* ERROR MESSAGE */}

          {error && (

            <p
              style={{
                color: '#b42318',
                margin: '8px 0 12px',
                fontSize: '13px',
              }}
            >
              {error}
            </p>

          )}


          {/* SUBMIT BUTTON */}

          <button
            className="primary-button full"

            type="submit"

            disabled={loading}
          >

            {loading
              ? mode === 'signin'
                ? 'Signing in…'
                : 'Creating account…'
              : mode === 'signin'
                ? 'Sign in to workspace'
                : 'Create account'}

            {!loading && (
              <ArrowRight size={16} />
            )}

          </button>

        </form>


        {/* ==================================================
            FOOTER NOTE
        ================================================== */}

        <div className="login-note">

          <ShieldCheck size={15} />

          Secure enterprise access

          <span>•</span>

          Passwords stored securely

        </div>


      </Glass>

    </div>
  )
}

function Metric({
  label,
  value,
  detail,
  icon: Icon,
  tone = 'blue',
  onClick,
}: any) {
  return (
    <Glass
      className={`metric ${onClick ? 'metric-clickable' : ''}`}
    >
      <div className={`metric-icon ${tone}`}>
        <Icon size={17} />
      </div>

      <button
        type="button"
        className="metric-button"
        onClick={onClick}
        disabled={!onClick}
      >
        <div className="metric-label">
          {label}
          <span>↗</span>
        </div>

        <strong>{value}</strong>
        {detail ? <small>{detail}</small> : null}
      </button>
    </Glass>
  )
}

type DashboardSummary = {
  module?: string
  total_records: number
  processed_claims: number
  total_providers: number
  sla_breaches: number
  sla_compliance: number | null
  active_alerts: number
  dq_alerts: number
  volume_alerts: number
  sla_alerts: number
  drug_anomalies: number
  claim_anomalies: number
  total_anomalies: number
  high_risk: number
  affected_providers: number
  psi_anomalies?: number
  robust_z_anomalies?: number
}

type DrugSummary = {
  total_drugs: number
  unique_drugs: number
  affected_providers: number
  high_severity: number
  risk_anomalies: number
  active_alerts: number
}

type OperationalSignal = {
  type: string
  period?: string | number
  compliance?: number | null
  status?: string
  records?: number | null
  processing_time?: number | null
  providers?: number | null
}

type DashboardAlert = {
  type: string
  provider_id?: string | number
  category?: string
  period?: string | number
  step?: string
  processing_time?: number
  sla_limit?: number
  severity?: string
  reason?: string
}

type SeverityData = {
  labels: string[]
  values: number[]
}

type RiskSlice = {
  label: string
  value: number
}

type DrugTopRiskItem = {
  Brnd_Name?: string | null
  Gnrc_Name?: string | null
  volume_risk_score?: number | null
  volume_risk_level?: string | null
}

type DrugClaimsVsCostPoint = {
  Brnd_Name?: string | null
  Gnrc_Name?: string | null
  total_claims?: number | null
  total_drug_cost?: number | null
  volume_risk_score?: number | null
  volume_risk_level?: string | null
}

type DrugUtilizationItem = {
  Brnd_Name?: string | null
  total_claims?: number | null
  total_fills?: number | null
  total_day_supply?: number | null
}

type DrugRiskVsBeneficiariesPoint = {
  Brnd_Name?: string | null
  Gnrc_Name?: string | null
  total_beneficiaries?: number | null
  volume_risk_score?: number | null
  total_claims?: number | null
  volume_risk_level?: string | null
}

type DrugOverallTrendPoint = {
  calendar_year?: number | null
  total_claims?: number | null
  total_standardized_30_day_fills?: number | null
  total_beneficiaries?: number | null
  final_volume_risk_score?: number | null
  volume_risk_level?: string | null
}

type SlaPerformancePoint = {
  run: number
  period: string
  processing_time: number
  sla_limit: number
}

type SlaPerformanceResponse = {
  points: SlaPerformancePoint[]
  avg_processing_time: number
  max_processing_time: number
  sla_limit: number
}

type AuthorizationSlaFunnel = {
  total_authorizations: number
  pending_na: number
  sla_met: number
  sla_breached: number
}

type AuthorizationProviderSlaBreach = {
  npi: string
  total_authorizations: number
  pending_na: number
  sla_met: number
  sla_breached: number
  sla_breach_pct: number
  current_month_volume?: number | null
  baseline_volume?: number | null
  volume_risk?: number | null
}

type ClaimVolumePoint = {
  period: string
  total_claims: number
  baseline_claims?: number | null
}

type AlertDistributionItem = {
  label: string
  value: number
}

type ProviderOption = {
  npi: string
}

type ProviderRiskProfile = {
  npi: string
  risk_level?: string
  overall_risk_score?: number
  axes: Array<{
    metric: string
    value: number
  }>
  risk_trend?: Array<{
    period: string
    value: number
  }>
}

type ClaimRecord = Record<string, unknown> & {
  CLM_ID?: string
  NPI?: string
  source?: string
  DT?: string
  period?: string
  root_cause?: string
  recommendation?: string
}

type ProviderRecord = Record<string, unknown> & {
  NPI?: string
  period?: string
  current_period?: string
  current_month_volume?: number
  monthly_volume?: number
  baseline_volume?: number
  deviation_pct?: number
  volume_risk?: number
  risk_level?: string
  history_months?: number
  total_claim_volume?: number
  source_count?: number
  sources?: string
  months_available?: number
  root_cause?: string
  recommendation?: string
}

type Pagination = {
  page: number
  page_size: number
  total: number
  total_pages: number
}

type ClaimsResponse = {
  columns: string[]
  items: ClaimRecord[]
  pagination: Pagination
  filters: Record<string, string>
  filter_options: {
    sources: string[]
    periods: string[]
  }
}

type ClaimSentinelDataResponse = {
  dataset: string
  columns: string[]
  items: Record<string, unknown>[]
  pagination: Pagination
}

type ClaimDetailResponse = {
  claim: ClaimRecord
  provider_risk?: ProviderRecord | null
  quality_context?: Record<string, unknown> | null
}

type ProvidersResponse = {
  columns: string[]
  items: ProviderRecord[]
  pagination: Pagination
  filters: Record<string, string>
  summary: {
    provider_count: number
    total_claims: number
    avg_monthly_volume: number
    avg_deviation: number
  }
  filter_options: {
    risk_levels: string[]
    sources: string[]
  }
}

type ProviderDetailResponse = {
  provider: ProviderRecord
  history: ProviderRecord[]
  claims: ClaimRecord[]
  quality_context?: Record<string, unknown> | null
}

type DrugListingRecord = Record<string, unknown>

type DrugRecordsResponse = {
  dataset:
    | 'drug-volume'
    | 'provider-impact'
    | 'overall-trend'
  columns: string[]
  items: DrugListingRecord[]
  pagination: Pagination
  filters: Record<string, string>
  summary: {
    total_records: number
    unique_drugs?: number
    total_claims?: number
    total_drug_cost?: number
    avg_risk_score?: number
    provider_count?: number
    latest_year?: number
  }
  filter_options: {
    risk_levels: string[]
    years: Array<string | number>
  }
}

type AlertDrilldownResponse = {
  level: string
  data_quality: Record<string, unknown>[]
  provider_risk: ProviderRecord[]
  sla_behavior: Record<string, unknown>[]
}

type RouterLike = {
  push: (href: string) => void
  back: () => void
}

const API_BASE =
  'http://localhost:5000/api/dashboard'
const DRUG_API_BASE = 'http://localhost:5000/api/drugs'

async function fetchApi<T>(
  base: string,
  endpoint: string
): Promise<T> {
  const response = await fetch(`${base}${endpoint}`)

  if (!response.ok) {
    throw new Error(
      `Dashboard API error: ${response.status}`
    )
  }

  return response.json()
}

async function fetchDashboard<T>(
  endpoint: string
): Promise<T> {
  return fetchApi<T>(API_BASE, endpoint)
}

async function fetchDrugApi<T>(
  endpoint: string
): Promise<T> {
  return fetchApi<T>(DRUG_API_BASE, endpoint)
}

function buildQuery(
  values: Record<string, string | number | undefined | null>
) {
  const params = new URLSearchParams()

  Object.entries(values).forEach(([key, value]) => {
    if (
      value !== undefined &&
      value !== null &&
      String(value).trim() !== ''
    ) {
      params.set(key, String(value))
    }
  })

  const query = params.toString()
  return query ? `?${query}` : ''
}

function downloadCsv(
  filename: string,
  rows: Record<string, unknown>[]
) {
  if (rows.length === 0) return

  const headers = Array.from(
    rows.reduce((set, row) => {
      Object.keys(row).forEach(key => set.add(key))
      return set
    }, new Set<string>())
  )

  const csv = [
    headers.join(','),
    ...rows.map(row =>
      headers
        .map(header => {
          const raw = row[header]
          const value =
            raw === null || raw === undefined
              ? ''
              : String(raw)
          return `"${value.replace(/"/g, '""')}"`
        })
        .join(',')
    ),
  ].join('\n')

  const blob = new Blob([csv], {
    type: 'text/csv;charset=utf-8;',
  })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

function escapeXml(value: string) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;')
}

function downloadExcel(
  filename: string,
  rows: Record<string, unknown>[],
  worksheetName = 'Sheet1'
) {
  if (rows.length === 0) return

  const headers = Array.from(
    rows.reduce((set, row) => {
      Object.keys(row).forEach(key => set.add(key))
      return set
    }, new Set<string>())
  )

  const toCell = (value: unknown) => {
    const text =
      value === null || value === undefined ? '' : String(value)
    return `<Cell><Data ss:Type="String">${escapeXml(text)}</Data></Cell>`
  }

  const worksheetRows = [
    `<Row>${headers.map(header => toCell(header)).join('')}</Row>`,
    ...rows.map(
      row =>
        `<Row>${headers
          .map(header => toCell(row[header]))
          .join('')}</Row>`
    ),
  ].join('')

  const workbook = `<?xml version="1.0"?>
<?mso-application progid="Excel.Sheet"?>
<Workbook
  xmlns="urn:schemas-microsoft-com:office:spreadsheet"
  xmlns:o="urn:schemas-microsoft-com:office:office"
  xmlns:x="urn:schemas-microsoft-com:office:excel"
  xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"
  xmlns:html="http://www.w3.org/TR/REC-html40">
  <Worksheet ss:Name="${escapeXml(worksheetName)}">
    <Table>${worksheetRows}</Table>
  </Worksheet>
</Workbook>`

  const blob = new Blob([workbook], {
    type: 'application/vnd.ms-excel;charset=utf-8;',
  })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

function formatValue(value: unknown) {
  if (
    value === null ||
    value === undefined ||
    value === ''
  ) {
    return '—'
  }

  if (typeof value === 'number') {
    return Number.isInteger(value)
      ? formatNumber(value)
      : value.toFixed(2)
  }

  return String(value)
}

function toLabel(value: string) {
  return value
    .replace(/_/g, ' ')
    .replace(/\b\w/g, part => part.toUpperCase())
}

function formatNumber(
  value: number | null | undefined
) {
  if (
    value === null ||
    value === undefined ||
    Number.isNaN(value)
  ) {
    return '—'
  }

  return new Intl.NumberFormat(
    'en-US'
  ).format(value)
}

function formatCompact(
  value: number | null | undefined
) {
  if (
    value === null ||
    value === undefined ||
    Number.isNaN(value)
  ) {
    return '—'
  }

  if (value >= 1_000_000) {
    return `${(
      value / 1_000_000
    ).toFixed(2)}M`
  }

  if (value >= 1_000) {
    return `${(
      value / 1_000
    ).toFixed(1)}K`
  }

  return formatNumber(value)
}

function formatCurrency(
  value: number | null | undefined
) {
  if (
    value === null ||
    value === undefined ||
    Number.isNaN(value)
  ) {
    return '—'
  }

  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(value)
}

function formatRiskScore(
  value: number | null | undefined
) {
  if (
    value === null ||
    value === undefined ||
    Number.isNaN(value)
  ) {
    return '—'
  }

  return value.toFixed(1)
}

function formatMinutes(
  value: number | null | undefined
) {
  if (
    value === null ||
    value === undefined ||
    Number.isNaN(value)
  ) {
    return '—'
  }

  const totalSeconds =
    Math.round(value * 60)

  const minutes =
    Math.floor(totalSeconds / 60)

  const seconds =
    totalSeconds % 60

  return `${minutes}m ${String(
    seconds
  ).padStart(2, '0')}s`
}

function formatProcessingStat(
  value: number | null | undefined
) {
  if (
    value === null ||
    value === undefined ||
    Number.isNaN(value)
  ) {
    return '—'
  }

  if (value < 1) {
    return `${Math.round(value * 60)} sec`
  }

  return `${value.toFixed(1)} min`
}

function formatMonthLabel(period?: string) {
  if (!period) {
    return '--'
  }

  const [year, month] = period.split('-')

  if (!year || !month) {
    return period
  }

  const monthIndex = Number(month) - 1
  const date = new Date(
    Number(year),
    monthIndex,
    1
  )

  if (Number.isNaN(date.getTime())) {
    return period
  }

  return date.toLocaleString('en-US', {
    month: 'short',
  })
}

function getStatusTone(
  status?: string
): 'good' | 'warn' | 'bad' | 'info' {
  const value =
    (status || '').toUpperCase()

  if (
    value.includes('BREACH') ||
    value.includes('HIGH') ||
    value.includes('CRITICAL') ||
    value.includes('ERROR')
  ) {
    return 'bad'
  }

  if (
    value.includes('WARN') ||
    value.includes('OVERRUN') ||
    value.includes('MINOR')
  ) {
    return 'warn'
  }

  if (
    value.includes('NORMAL') ||
    value.includes('HEALTH') ||
    value.includes('MET') ||
    value.includes('GOOD')
  ) {
    return 'good'
  }

  return 'info'
}

function Overview({
  go,
  router,
  module,
}: {
  go: (v: View) => void
  router: RouterLike
  module: DashboardModule
}) {
  const [summary, setSummary] =
    useState<DashboardSummary | null>(null)
  const [drugSummary, setDrugSummary] =
    useState<DrugSummary | null>(null)

  const [riskDistribution, setRiskDistribution] =
    useState<RiskSlice[]>([])

  const [slaTrend, setSlaTrend] =
    useState<SlaPerformancePoint[]>([])

  const [claimVolumeTrend, setClaimVolumeTrend] =
    useState<ClaimVolumePoint[]>([])

  const [alertDistribution, setAlertDistribution] =
    useState<AlertDistributionItem[]>([])

  const [providerNpi, setProviderNpi] =
    useState('')

  const [providerOptions, setProviderOptions] =
    useState<ProviderOption[]>([])

  const [providerProfile, setProviderProfile] =
    useState<ProviderRiskProfile | null>(null)
  const [authorizationSlaFunnel, setAuthorizationSlaFunnel] =
    useState<AuthorizationSlaFunnel>({
      total_authorizations: 0,
      pending_na: 0,
      sla_met: 0,
      sla_breached: 0,
    })
  const [authorizationProviderSlaBreaches, setAuthorizationProviderSlaBreaches] =
    useState<AuthorizationProviderSlaBreach[]>([])

  const [drugTopRisk, setDrugTopRisk] = useState<
    DrugTopRiskItem[]
  >([])
  const [drugUtilization, setDrugUtilization] =
    useState<DrugUtilizationItem[]>([])
  const [drugClaimsVsCost, setDrugClaimsVsCost] =
    useState<DrugClaimsVsCostPoint[]>([])
  const [
    drugRiskVsBeneficiaries,
    setDrugRiskVsBeneficiaries,
  ] = useState<DrugRiskVsBeneficiariesPoint[]>([])
  const [drugOverallTrend, setDrugOverallTrend] =
    useState<DrugOverallTrendPoint[]>([])

  const [loading, setLoading] =
    useState(true)

  const [error, setError] =
    useState('')

  useEffect(() => {
    let cancelled = false

    async function loadOverview() {
      try {
        setLoading(true)
        setError('')

        if (module === 'drugs') {
          const [
            drugSummaryData,
            riskDistributionData,
            drugTrendData,
            topRiskData,
            utilizationData,
            claimsVsCostData,
            riskVsBeneficiariesData,
          ] = await Promise.all([
            fetchDrugApi<DrugSummary>('/summary'),
            fetchDrugApi<RiskSlice[]>(
              '/risk-distribution'
            ),
            fetchDrugApi<DrugOverallTrendPoint[]>(
              '/overall-trend'
            ),
            fetchDrugApi<DrugTopRiskItem[]>(
              '/top-risk'
            ),
            fetchDrugApi<DrugUtilizationItem[]>(
              '/utilization'
            ),
            fetchDrugApi<DrugClaimsVsCostPoint[]>(
              '/claims-by-drug'
            ),
            fetchDrugApi<
              DrugRiskVsBeneficiariesPoint[]
            >('/risk-vs-beneficiaries'),
          ])

          if (cancelled) return

          setDrugSummary(drugSummaryData)
          setRiskDistribution(riskDistributionData)
          setDrugOverallTrend(drugTrendData)
          setDrugTopRisk(topRiskData)
          setDrugUtilization(utilizationData)
          setDrugClaimsVsCost(claimsVsCostData)
          setDrugRiskVsBeneficiaries(
            riskVsBeneficiariesData
          )
          setSummary(null)
          setSlaTrend([])
          setClaimVolumeTrend([])
          setAlertDistribution([])
          setProviderProfile(null)
          setProviderOptions([])
          setProviderNpi('')
          return
        }

        const [
          summaryData,
          riskDistributionData,
          slaTrendData,
          claimVolumeTrendData,
          alertDistributionData,
          providerProfileData,
          providerOptionsData,
          authorizationSlaFunnelData,
          authorizationProviderSlaBreachesData,
        ] = await Promise.all([
          fetchDashboard<DashboardSummary>(
            `/summary${buildQuery({
              module,
            })}`
          ),
          fetchDashboard<RiskSlice[]>(
            `/provider-risk-distribution${buildQuery({
              module,
            })}`
          ),
          fetchDashboard<SlaPerformanceResponse>(
            `/sla-performance-trend${buildQuery({
              module,
            })}`
          ),
          fetchDashboard<ClaimVolumePoint[]>(
            `/claim-volume-trend${buildQuery({
              module,
            })}`
          ),
          fetchDashboard<AlertDistributionItem[]>(
            `/alert-issue-distribution${buildQuery({
              module,
            })}`
          ),
          fetchDashboard<ProviderRiskProfile>(
            `/provider-risk-profile${buildQuery({
              module,
            })}`
          ),
          fetchDashboard<ProviderOption[]>(
            `/provider-options${buildQuery({
              module,
            })}`
          ),
          fetchDashboard<AuthorizationSlaFunnel>(
            '/authorization-sla-funnel'
          ),
          fetchDashboard<AuthorizationProviderSlaBreach[]>(
            '/authorization-provider-sla-breaches'
          ),
        ])

        if (cancelled) return

        setSummary(summaryData)
        setRiskDistribution(riskDistributionData)
        setSlaTrend(slaTrendData.points || [])
        setClaimVolumeTrend(
          claimVolumeTrendData
        )
        setAlertDistribution(alertDistributionData)
        setProviderProfile(providerProfileData)
        setProviderOptions(providerOptionsData)
        setProviderNpi(providerProfileData?.npi || '')
        setAuthorizationSlaFunnel(authorizationSlaFunnelData)
        setAuthorizationProviderSlaBreaches(
          authorizationProviderSlaBreachesData
        )
        setDrugSummary(null)
        setDrugOverallTrend([])
        setDrugTopRisk([])
        setDrugUtilization([])
        setDrugClaimsVsCost([])
        setDrugRiskVsBeneficiaries([])
      } catch (err) {
        if (!cancelled) {
          console.error(err)

          setError(
            'Unable to load live dashboard data. Make sure the Flask API is running on port 5000.'
          )
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    loadOverview()

    return () => {
      cancelled = true
    }
  }, [module])

  useEffect(() => {
    if (module === 'drugs') {
      setProviderProfile(null)
      setProviderOptions([])
      setProviderNpi('')
      return
    }

    let cancelled = false

    async function loadProviderProfile() {
      try {
        const endpoint = providerNpi.trim()
          ? `/provider-risk-profile${buildQuery({
              module,
              npi: providerNpi.trim(),
            })}`
          : `/provider-risk-profile${buildQuery({
              module,
            })}`

        const profile =
          await fetchDashboard<ProviderRiskProfile>(
            endpoint
          )

        if (!cancelled) {
          setProviderProfile(profile)
          if (!providerNpi.trim() && profile.npi) {
            setProviderNpi(profile.npi)
          }
        }
      } catch (err) {
        if (!cancelled) {
          console.error(err)
        }
      }
    }

    loadProviderProfile()

    return () => {
      cancelled = true
    }
  }, [providerNpi, module])

  const moduleConfig =
    module === 'drugs'
      ? {
          metrics: [
            {
              label: 'Total Drug Records',
              value: drugSummary?.total_drugs,
              icon: Database,
              tone: 'blue',
              onClick: () =>
                router.push('/drugs'),
            },
            {
              label: 'Unique Drugs',
              value: drugSummary?.unique_drugs,
              icon: FileCheck2,
              tone: 'green',
              onClick: () =>
                router.push(
                  `/drugs${buildQuery({
                    sort_by: 'Brnd_Name',
                    sort_dir: 'asc',
                  })}`
                ),
            },
            {
              label: 'Affected Providers',
              value: drugSummary?.affected_providers,
              icon: Activity,
              tone: 'violet',
              onClick: () =>
                router.push(
                  `/drugs${buildQuery({
                    dataset: 'provider-impact',
                  })}`
                ),
            },
            {
              label: 'High Severity',
              value: drugSummary?.high_severity,
              icon: AlertTriangle,
              tone: 'amber',
              onClick: () =>
                router.push(
                  `/drugs${buildQuery({
                    risk_bucket: 'high_severity',
                  })}`
                ),
            },
            {
              label: 'Drug Risk Anomalies',
              value: drugSummary?.risk_anomalies,
              icon: Gauge,
              tone: 'green',
              onClick: () =>
                router.push(
                  `/drugs${buildQuery({
                    risk_bucket: 'high_severity',
                  })}`
                ),
            },
            {
              label: 'Active Alerts',
              value: drugSummary?.active_alerts,
              icon: Bell,
              tone: 'amber',
              onClick: () =>
                router.push(
                  `/drugs${buildQuery({
                    risk_bucket: 'active_alerts',
                  })}`
                ),
            },
          ],
          riskEyebrow: 'DRUG SEVERITY LANDSCAPE',
          riskTitle:
            'Distribution of drug records by risk level',
          riskUnit: 'drug records',
          riskInsightLabel: 'Severity Insight',
          slaEyebrow: 'OVERALL RISK TREND',
          slaTitle: 'Year-wise final volume risk score',
          slaComplianceLabel: 'Latest Risk Score',
          trendEyebrow: 'DRUG UTILIZATION',
          trendTitle: 'Top 10 drugs by utilization',
          trendPrimaryLabel: 'Leading Metric',
          trendAverageLabel: 'Average of Top 10',
          trendSecondaryLabel: 'Selected Metric',
          trendComparisonLegend: 'Utilization metric',
          radarEyebrow: 'DRUG SCATTER ANALYSIS',
          radarTitle:
            'Claims, cost, beneficiaries, and risk relationships',
        }
      : module === 'authorization'
        ? {
            metrics: [
              {
                label: 'Total Authorizations',
                value: summary?.total_records,
                icon: Database,
                tone: 'blue',
              },
              {
                label: 'Processed Records',
                value: summary?.processed_claims,
                icon: FileCheck2,
                tone: 'green',
              },
              {
                label: 'Total Providers',
                value: summary?.total_providers,
                icon: Activity,
                tone: 'violet',
              },
              {
                label: 'SLA Breaches',
                value: summary?.sla_breaches,
                icon: AlertTriangle,
                tone: 'amber',
              },
              {
                label: 'SLA Compliance',
                value: summary?.sla_compliance,
                icon: Gauge,
                tone: 'green',
                isPercent: true,
              },
              {
                label: 'Active Alerts',
                value: summary?.active_alerts,
                icon: Bell,
                tone: 'amber',
              },
            ],
            riskEyebrow:
              'AUTHORIZATION RISK LANDSCAPE',
            riskTitle:
              'Distribution of providers by authorization risk',
            riskUnit: 'providers',
            riskInsightLabel: 'Risk Insight',
            slaEyebrow: 'AUTHORIZATION SLA TREND',
            slaTitle:
              'Turnaround time vs SLA limit',
            slaComplianceLabel: 'SLA Compliance',
            trendEyebrow:
              'AUTHORIZATION VOLUME TREND',
            trendTitle:
              'Authorization volume by month',
            trendPrimaryLabel: 'Latest Volume',
            trendAverageLabel: 'Avg Monthly Volume',
            trendSecondaryLabel: 'Avg Baseline',
            trendComparisonLegend:
              'Average baseline',
            radarEyebrow:
              'AUTHORIZATION PROVIDER RADAR',
            radarTitle:
              'Selected provider authorization profile',
          }
        : {
            metrics: [
              {
                label: 'Total Records',
                value: summary?.total_records,
                icon: Database,
                tone: 'blue',
                onClick: () =>
                  router.push('/claims'),
              },
              {
                label: 'Processed Claims',
                value: summary?.processed_claims,
                icon: FileCheck2,
                tone: 'green',
              },
              {
                label: 'Total Providers',
                value: summary?.total_providers,
                icon: Activity,
                tone: 'violet',
                onClick: () =>
                  router.push('/providers'),
              },
              {
                label: 'SLA Breaches',
                value: summary?.sla_breaches,
                icon: AlertTriangle,
                tone: 'amber',
              },
              {
                label: 'SLA Compliance',
                value: summary?.sla_compliance,
                icon: Gauge,
                tone: 'green',
                isPercent: true,
              },
              {
                label: 'Active Alerts',
                value: summary?.active_alerts,
                icon: Bell,
                tone: 'amber',
              },
            ],
            riskEyebrow: 'PROVIDER RISK LANDSCAPE',
            riskTitle:
              'Distribution of providers by risk level',
            riskUnit: 'providers',
            riskInsightLabel: 'Risk Insight',
            slaEyebrow: 'SLA PERFORMANCE TREND',
            slaTitle: 'Processing time vs SLA limit',
            slaComplianceLabel: 'SLA Compliance',
            trendEyebrow: 'CLAIM VOLUME TREND',
            trendTitle: 'Claim volume by month',
            trendPrimaryLabel: 'Latest Claims',
            trendAverageLabel: 'Avg Monthly Claims',
            trendSecondaryLabel: 'Latest Baseline',
            trendComparisonLegend:
              'Historical Baseline',
            radarEyebrow: 'PROVIDER RISK RADAR',
            radarTitle:
              'Selected provider investigation',
          }

  return (
    <>
      {error && (
        <Glass
          className="wide-card"
          style={{ marginBottom: 16 }}
        >
          <div className="card-title">
            <div>
              <p className="eyebrow">
                BACKEND CONNECTION
              </p>
              <h2>Live data unavailable</h2>
            </div>

            <Status tone="bad">
              Offline
            </Status>
          </div>

          <p>{error}</p>
        </Glass>
      )}

      <div className="metric-grid">
        {moduleConfig.metrics.map(metric => (
          <Metric
            key={metric.label}
            label={metric.label}
            value={
              loading
                ? '…'
                : metric.isPercent
                  ? metric.value != null
                    ? `${Number(
                        metric.value
                      ).toFixed(1)}%`
                    : '—'
                  : formatCompact(
                      Number(metric.value ?? 0)
                    )
            }
            icon={metric.icon}
            tone={metric.tone}
            onClick={metric.onClick}
          />
        ))}
      </div>

      {module === 'drugs' ? (
        <>
          <div
            className="overview-support-grid"
            style={{ marginTop: 14 }}
          >
            <Glass className="overview-chart-card provider-landscape-container">
              <ProviderRiskDistributionCard
                slices={riskDistribution}
                eyebrow={moduleConfig.riskEyebrow}
                title={moduleConfig.riskTitle}
                unitLabel={moduleConfig.riskUnit}
                insightLabel={
                  moduleConfig.riskInsightLabel
                }
                onSliceClick={label =>
                  router.push(
                    `/drugs${buildQuery({
                      risk_level: label,
                    })}`
                  )
                }
              />
            </Glass>

            <Glass className="overview-chart-card">
              <DrugOverallTrendCard
                data={drugOverallTrend}
                eyebrow={moduleConfig.slaEyebrow}
                title={moduleConfig.slaTitle}
                onPointClick={year =>
                  router.push(
                    `/drugs${buildQuery({
                      dataset: 'overall-trend',
                      calendar_year: year,
                    })}`
                  )
                }
              />
            </Glass>
          </div>

          <div
            className="overview-support-grid"
            style={{ marginTop: 14 }}
          >
            <Glass className="overview-chart-card">
              <DrugUtilizationCard
                data={drugUtilization}
                eyebrow={moduleConfig.trendEyebrow}
                title="Top 5 drugs by utilization"
                onBarClick={item =>
                  router.push(
                    `/drugs${buildQuery({
                      brand_name:
                        item.Brnd_Name || undefined,
                    })}`
                  )
                }
              />
            </Glass>

            <Glass className="overview-chart-card">
              <DrugTopRiskCard
                data={drugTopRisk}
                onBarClick={item =>
                  router.push(
                    `/drugs${buildQuery({
                      brand_name:
                        item.Brnd_Name || undefined,
                      generic_name:
                        item.Gnrc_Name || undefined,
                    })}`
                  )
                }
              />
            </Glass>

          </div>

          <Glass
            className="overview-chart-card overview-chart-wide"
            style={{ marginTop: 14 }}
          >
            <DrugClaimsLollipopCard
              data={drugClaimsVsCost}
              onPointClick={item =>
                router.push(
                  `/drugs${buildQuery({
                    brand_name:
                      item.Brnd_Name || undefined,
                    generic_name:
                      item.Gnrc_Name || undefined,
                  })}`
                )
              }
            />
          </Glass>
        </>
      ) : (
        <>
          <div
            className="overview-support-grid"
            style={{ marginTop: 14 }}
          >
            <Glass className="overview-chart-card provider-landscape-container">
              <ProviderRiskDistributionCard
                slices={riskDistribution}
                eyebrow={moduleConfig.riskEyebrow}
                title={moduleConfig.riskTitle}
                unitLabel={moduleConfig.riskUnit}
                insightLabel={moduleConfig.riskInsightLabel}
                onSliceClick={
                  module === 'claims'
                    ? label =>
                        router.push(
                          `/providers${buildQuery({
                            risk_level: label,
                          })}`
                        )
                    : undefined
                }
              />
            </Glass>

            <Glass className="overview-chart-card">
              {module === 'authorization' ? (
                <AuthorizationPendingFunnelCard
                  data={authorizationSlaFunnel}
                />
              ) : (
                <SlaPerformanceCard
                  data={slaTrend}
                  compliance={
                    summary?.sla_compliance || 0
                  }
                  eyebrow={moduleConfig.slaEyebrow}
                  title={moduleConfig.slaTitle}
                  complianceLabel={
                    moduleConfig.slaComplianceLabel
                  }
                />
              )}
            </Glass>
          </div>

          <Glass
            className="overview-chart-card overview-chart-wide"
            style={{ marginTop: 14 }}
          >
            <ClaimVolumeTrendCard
              data={claimVolumeTrend}
              eyebrow={moduleConfig.trendEyebrow}
              title={moduleConfig.trendTitle}
              primaryLabel={
                moduleConfig.trendPrimaryLabel
              }
              averageLabel={
                moduleConfig.trendAverageLabel
              }
              secondaryLabel={
                moduleConfig.trendSecondaryLabel
              }
              comparisonLegend={
                moduleConfig.trendComparisonLegend
              }
              onPointClick={
                module === 'claims'
                  ? period =>
                      router.push(
                        `/claims${buildQuery({
                          period,
                        })}`
                      )
                  : undefined
              }
            />
          </Glass>

          <div
            className="overview-support-grid"
            style={{ marginTop: 14 }}
          >
            {module === 'claims' ? (
              <Glass className="overview-chart-card claims-provider-overview">
                <ClaimsProviderRiskOverviewCard
                  providerNpi={providerNpi}
                  providerOptions={providerOptions}
                  providerProfile={providerProfile}
                  onProviderChange={setProviderNpi}
                />
              </Glass>
            ) : module === 'authorization' ? null : (
              <>
                <Glass className="overview-chart-card">
                  <AlertFlowCard
                    bars={alertDistribution}
                    onBarClick={label =>
                      router.push(
                        `/providers${buildQuery({
                          alert_level: label.toUpperCase(),
                        })}`
                      )
                    }
                  />
                </Glass>

                <Glass className="overview-chart-card">
                  <ProviderRadarCard
                    providerNpi={providerNpi}
                    providerOptions={providerOptions}
                    providerProfile={providerProfile}
                    onProviderChange={setProviderNpi}
                    eyebrow={moduleConfig.radarEyebrow}
                    title={moduleConfig.radarTitle}
                  />
                </Glass>
              </>
            )}
          </div>
        </>
      )}
    </>
  )
}

function SimpleLineChart({
  points,
  yFormatter,
  secondaryLabel,
  onPointClick,
}: {
  points: Array<{
    label: string
    value: number
    period?: string
    secondary?: number | null
  }>
  yFormatter: (value: number) => string
  secondaryLabel?: string
  onPointClick?: (period: string) => void
}) {
  const hasSecondaryLine = points.some(
    point => point.secondary != null
  )

  const maxPrimary = Math.max(
    ...points.map(point => point.value),
    1
  )

  const maxSecondary = Math.max(
    ...points.map(
      point => point.secondary ?? 0
    ),
    1
  )

  const maxValue = Math.max(
    maxPrimary,
    maxSecondary
  )

  const xStep =
    points.length > 1
      ? 520 / (points.length - 1)
      : 520

  const primaryPath = points
    .map((point, index) => {
      const x = 20 + index * xStep
      const y =
        190 - (point.value / maxValue) * 150
      return `${index === 0 ? 'M' : 'L'}${x} ${y}`
    })
    .join(' ')

  const secondaryPath = hasSecondaryLine
    ? points
        .map((point, index) => {
          const secondaryValue =
            point.secondary ?? 0

          const x = 20 + index * xStep
          const y =
            190 -
            (secondaryValue / maxValue) * 150
          return `${index === 0 ? 'M' : 'L'}${x} ${y}`
        })
        .join(' ')
    : ''

  const yTicks = [
    maxValue,
    maxValue * 0.66,
    maxValue * 0.33,
    0,
  ]

  return (
    <div className="overview-line-chart">
      <div className="y-labels">
        {yTicks.map(value => (
          <span key={value}>
            {yFormatter(value)}
          </span>
        ))}
      </div>

      <div className="chart-area">
        <div className="chart-grid" />

        <svg
          viewBox="0 0 560 220"
          preserveAspectRatio="none"
        >
          {secondaryLabel &&
          hasSecondaryLine && (
            <path
              className="baseline"
              d={secondaryPath}
            />
          )}

          <path
            className="trend-line"
            d={primaryPath}
          />

          {points.map((point, index) => {
            const x = 20 + index * xStep
            const y =
              190 - (point.value / maxValue) * 150

            return (
              <circle
                key={`${point.label}-${index}`}
                cx={x}
                cy={y}
                r="3.5"
                className={
                  onPointClick
                    ? 'chart-point interactive'
                    : 'chart-point'
                }
                onClick={() =>
                  point.period &&
                  onPointClick?.(point.period)
                }
              />
            )
          })}
        </svg>

        <div className="x-labels">
          {points.map((point, index) => (
            <span
              key={`${point.label}-${index}`}
            >
              {point.label}
            </span>
          ))}
        </div>
      </div>

      {secondaryLabel &&
      hasSecondaryLine && (
        <div className="chart-legend">
          <span>
            <i className="legend-primary" />
            Actual
          </span>
          <span>
            <i className="legend-secondary" />
            {secondaryLabel}
          </span>
        </div>
      )}
    </div>
  )
}

function ClaimVolumeTrendCard({
  data,
  eyebrow,
  title,
  primaryLabel,
  averageLabel,
  secondaryLabel,
  comparisonLegend,
  onPointClick,
}: {
  data: ClaimVolumePoint[]
  eyebrow: string
  title: string
  primaryLabel: string
  averageLabel: string
  secondaryLabel: string
  comparisonLegend: string
  onPointClick?: (period: string) => void
}) {
  const points = data.map(item => ({
    label: formatMonthLabel(item.period),
    period: item.period,
    value: item.total_claims,
    secondary: item.baseline_claims,
  }))

  const latestPoint =
    points.length > 0
      ? points[points.length - 1]
      : null

  const avgClaims =
    points.length > 0
      ? points.reduce(
          (sum, point) => sum + point.value,
          0
        ) / points.length
      : 0

  return (
    <>
      <div className="card-title">
        <div>
          <p className="eyebrow">
            {eyebrow}
          </p>
          <h2>{title}</h2>
        </div>

        <div className="corner-stat">
          <small>Latest Month</small>
          <strong>
            {latestPoint?.label || '--'}
          </strong>
        </div>
      </div>

      <SimpleLineChart
        points={points}
        yFormatter={value =>
          `${Math.round(value)}`
        }
        secondaryLabel={comparisonLegend}
        onPointClick={onPointClick}
      />

      <div className="chart-stat-row">
        <div className="stat-chip">
          <small>{primaryLabel}</small>
          <strong>
            {formatNumber(
              latestPoint?.value
            )}
          </strong>
        </div>

        <div className="stat-chip">
          <small>{averageLabel}</small>
          <strong>
            {avgClaims.toFixed(1)}
          </strong>
        </div>

        <div className="stat-chip">
          <small>{secondaryLabel}</small>
          <strong>
            {latestPoint?.secondary != null
              ? latestPoint.secondary.toFixed(
                  1
                )
              : '--'}
          </strong>
        </div>
      </div>
    </>
  )
}

function DonutChart({
  slices,
  unitLabel = 'providers',
  onSliceClick,
}: {
  slices: RiskSlice[]
  unitLabel?: string
  onSliceClick?: (label: string) => void
}) {
  const total = slices.reduce(
    (sum, slice) => sum + slice.value,
    0
  )

  const semanticColors: Record<string, string> = {
    LOW: '#7ac943',
    LOW_VOLUME: '#56d6ff',
    INSUFFICIENT_HISTORY: '#f2cf7b',
    MEDIUM: '#ff9f43',
    MODERATE: '#ffb15a',
    HIGH: '#ff5d73',
    CRITICAL: '#b4233c',
    WARNING: '#f2cf7b',
    INFO: '#8eeeff',
    UNKNOWN: '#c5dcf3',
  }

  const palette = [
    '#ff9baf',
    '#f2cf7b',
    '#8eeeff',
    '#6fd8ff',
    '#b8c3ff',
    '#c5dcf3',
  ]

  const segments = slices.map(
    (slice, index) => {
      const fraction =
        total > 0
          ? slice.value / total
          : 0
      return {
        ...slice,
        fraction,
        color:
          semanticColors[slice.label] ||
          palette[index % palette.length],
      }
    }
  )

  let cursor = 0

  const dashData = segments.map(item => {
    const length = 314 * item.fraction
    const entry = {
      ...item,
      dash: `${length} ${314 - length}`,
      offset: -cursor,
    }
    cursor += length
    return entry
  })

  return (
    <div className="donut-wrap">
      <svg
        viewBox="0 0 140 140"
        className="donut"
      >
        <circle
          cx="70"
          cy="70"
          r="50"
          className="donut-track"
        />
        {dashData.map(item => (
          <circle
            key={item.label}
            cx="70"
            cy="70"
            r="50"
            stroke={item.color}
            strokeDasharray={item.dash}
            strokeDashoffset={item.offset}
            className={
              onSliceClick
                ? 'donut-segment interactive'
                : 'donut-segment'
            }
            onClick={() =>
              onSliceClick?.(item.label)
            }
          />
        ))}
        <text
          x="70"
          y="66"
          textAnchor="middle"
          className="donut-total"
        >
          {formatNumber(total)}
        </text>
        <text
          x="70"
          y="82"
          textAnchor="middle"
          className="donut-caption"
        >
          {unitLabel}
        </text>
      </svg>

      <div className="donut-legend">
        {dashData.map(item => (
          <button
            key={item.label}
            className="donut-row"
            type="button"
            onClick={() =>
              onSliceClick?.(item.label)
            }
          >
            <span>
              <i
                style={{
                  background: item.color,
                }}
              />
              {item.label}
            </span>
            <strong>
              {formatNumber(item.value)}
            </strong>
          </button>
        ))}
      </div>
    </div>
  )
}

function SimpleBarChart({
  bars,
}: {
  bars: AlertDistributionItem[]
}) {
  const maxValue = Math.max(
    ...bars.map(item => item.value),
    1
  )

  return (
    <div className="alert-bar-list">
      {bars.map(item => (
        <div
          className="alert-bar-row"
          key={item.label}
        >
          <div className="alert-bar-head">
            <span>{item.label}</span>
            <strong>
              {formatNumber(item.value)}
            </strong>
          </div>

          <div className="alert-bar-track">
            <i
              style={{
                width: `${(item.value / maxValue) * 100}%`,
              }}
            />
          </div>
        </div>
      ))}
    </div>
  )
}

function RadarChartView({
  axes,
  npi,
  riskLevel,
}: {
  axes: Array<{
    metric: string
    value: number
  }>
  npi: string
  riskLevel?: string
}) {
  const centerX = 160
  const centerY = 145
  const radius = 92

  const points = axes.map(
    (axis, index) => {
      const angle =
        (-Math.PI / 2) +
        (index * 2 * Math.PI) /
          Math.max(axes.length, 1)

      const outerX =
        centerX +
        Math.cos(angle) * radius

      const outerY =
        centerY +
        Math.sin(angle) * radius

      const valueRadius =
        (Math.max(
          0,
          Math.min(100, axis.value)
        ) /
          100) *
        radius

      const valueX =
        centerX +
        Math.cos(angle) * valueRadius

      const valueY =
        centerY +
        Math.sin(angle) * valueRadius

      return {
        ...axis,
        angle,
        outerX,
        outerY,
        valueX,
        valueY,
      }
    }
  )

  const polygon = points
    .map((point, index) =>
      `${index === 0 ? 'M' : 'L'}${point.valueX} ${point.valueY}`
    )
    .join(' ') + ' Z'

  return (
    <div className="radar-wrap">
      <div className="radar-meta">
        <span>
          NPI: <strong>{npi || '—'}</strong>
        </span>
        <Status
          tone={getStatusTone(riskLevel)}
        >
          {riskLevel || 'UNKNOWN'}
        </Status>
      </div>

      <svg
        viewBox="0 0 320 290"
        className="radar"
      >
        {[1, 2, 3, 4].map(step => {
          const stepRadius =
            (radius * step) / 4

          const ring = points
            .map((point, index) => {
              const x =
                centerX +
                Math.cos(point.angle) *
                  stepRadius
              const y =
                centerY +
                Math.sin(point.angle) *
                  stepRadius
              return `${index === 0 ? 'M' : 'L'}${x} ${y}`
            })
            .join(' ') + ' Z'

          return (
            <path
              key={step}
              d={ring}
              className="radar-ring"
            />
          )
        })}

        {points.map(point => (
          <g key={point.metric}>
            <line
              x1={centerX}
              y1={centerY}
              x2={point.outerX}
              y2={point.outerY}
              className="radar-axis"
            />

            <text
              x={
                centerX +
                Math.cos(point.angle) * 112
              }
              y={
                centerY +
                Math.sin(point.angle) * 112
              }
              textAnchor="middle"
              className="radar-label"
            >
              {point.metric}
            </text>
          </g>
        ))}

        <path
          d={polygon}
          className="radar-shape"
        />

        {points.map(point => (
          <circle
            key={`dot-${point.metric}`}
            cx={point.valueX}
            cy={point.valueY}
            r="3.5"
            className="radar-dot"
          />
        ))}
      </svg>
    </div>
  )
}

function ProviderRadarCard({
  providerNpi,
  providerOptions,
  providerProfile,
  onProviderChange,
  eyebrow,
  title,
}: {
  providerNpi: string
  providerOptions: ProviderOption[]
  providerProfile: ProviderRiskProfile | null
  onProviderChange: (npi: string) => void
  eyebrow: string
  title: string
}) {
  return (
    <>
      <div className="card-title">
        <div>
          <p className="eyebrow">
            {eyebrow}
          </p>
          <h2>{title}</h2>
        </div>

        <select
          className="themed-select"
          value={providerNpi}
          onChange={event =>
            onProviderChange(
              event.target.value
            )
          }
          style={{
            width: 180,
            height: 36,
          }}
        >
          {providerOptions.map(option => (
            <option
              key={option.npi}
              value={option.npi}
            >
              {option.npi}
            </option>
          ))}
        </select>
      </div>

      <RadarChartView
        axes={
          providerProfile?.axes || []
        }
        npi={providerProfile?.npi || ''}
        riskLevel={
          providerProfile?.risk_level
        }
      />
    </>
  )
}

function ClaimsProviderRiskOverviewCard({
  providerNpi,
  providerOptions,
  providerProfile,
  onProviderChange,
}: {
  providerNpi: string
  providerOptions: ProviderOption[]
  providerProfile: ProviderRiskProfile | null
  onProviderChange: (npi: string) => void
}) {
  const axes = providerProfile?.axes || []
  const score = Math.round(
    Number(providerProfile?.overall_risk_score ?? 0)
  )
  const trend = providerProfile?.risk_trend || []
  const maxTrend = Math.max(
    ...trend.map(point => point.value),
    1
  )
  const colors = ['#ff5575', '#ff922b', '#8b5cf6', '#2d8cff', '#28bed1']
  let runningTotal = 0
  const contributionTotal = axes.reduce(
    (sum, axis) => sum + Math.max(0, axis.value),
    0
  )
  const gradient = axes.length
    ? `conic-gradient(${axes
        .map((axis, index) => {
          const start = runningTotal
          runningTotal +=
            (Math.max(0, axis.value) / contributionTotal) * 100
          return `${colors[index % colors.length]} ${start}% ${runningTotal}%`
        })
        .join(', ')})`
    : 'conic-gradient(rgba(255,255,255,.12) 0 100%)'

  const trendPath = trend
    .map((point, index) => {
      const x =
        trend.length > 1
          ? 22 + (index / (trend.length - 1)) * 516
          : 280
      const y = 180 - (point.value / maxTrend) * 145
      return `${index === 0 ? 'M' : 'L'}${x} ${y}`
    })
    .join(' ')

  return (
    <>
      <div className="card-title claims-provider-title">
        <div>
          <p className="eyebrow">PROVIDER RISK OVERVIEW</p>
          <h2>Selected Provider Investigation</h2>
          <div className="claims-provider-npi">
            NPI: {providerProfile?.npi || '--'}
            <Status tone={getStatusTone(providerProfile?.risk_level)}>
              {providerProfile?.risk_level || 'UNKNOWN'} RISK
            </Status>
          </div>
        </div>

        <select
          className="themed-select"
          value={providerNpi}
          onChange={event => onProviderChange(event.target.value)}
          style={{ width: 180, height: 36 }}
          aria-label="Select provider NPI"
        >
          {providerOptions.map(option => (
            <option key={option.npi} value={option.npi}>
              {option.npi}
            </option>
          ))}
        </select>
      </div>

      <div className="claims-provider-summary-grid">
        <section className="claims-provider-panel">
          <p className="eyebrow">RISK SUMMARY</p>
          <div className="claims-risk-summary-content">
            <div
              className="claims-risk-ring"
              style={{ '--risk-score': `${score * 3.6}deg` } as React.CSSProperties}
            >
              <strong>{score}%</strong>
              <small>Overall Risk Score</small>
            </div>
            <div className="claims-contribution-list">
              {axes.map((axis, index) => (
                <div key={axis.metric}>
                  <span>
                    <i style={{ background: colors[index % colors.length] }} />
                    {axis.metric}
                  </span>
                  <b>{Math.round(axis.value)}%</b>
                  <em>
                    <i
                      style={{
                        width: `${Math.max(0, Math.min(100, axis.value))}%`,
                        background: colors[index % colors.length],
                      }}
                    />
                  </em>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="claims-provider-panel">
          <p className="eyebrow">RISK CONTRIBUTION</p>
          <div className="claims-donut-layout">
            <div className="claims-contribution-donut" style={{ background: gradient }}>
              <div>Risk Impact<br />Breakdown</div>
            </div>
            <div className="claims-donut-legend">
              {axes.map((axis, index) => (
                <span key={axis.metric}>
                  <i style={{ background: colors[index % colors.length] }} />
                  {axis.metric}
                </span>
              ))}
            </div>
          </div>
        </section>
      </div>

      <section className="claims-provider-panel claims-risk-trend-panel">
        <p className="eyebrow">RISK TREND (LAST 12 PERIODS)</p>
        {trend.length ? (
          <div className="claims-risk-trend-chart">
            <svg viewBox="0 0 560 205" preserveAspectRatio="none">
              <path d={trendPath} className="claims-risk-trend-line" />
              {trend.map((point, index) => {
                const x = trend.length > 1 ? 22 + (index / (trend.length - 1)) * 516 : 280
                const y = 180 - (point.value / maxTrend) * 145
                return <circle key={point.period} cx={x} cy={y} r="4"><title>{`${point.period}: ${Math.round(point.value)}%`}</title></circle>
              })}
            </svg>
            <div className="claims-risk-trend-labels">
              {trend.map(point => <span key={point.period}>{point.period}</span>)}
            </div>
          </div>
        ) : (
          <DrugEmptyState message="No provider risk trend available" />
        )}
      </section>
    </>
  )
}

function ProviderRiskDistributionCard({
  slices,
  eyebrow,
  title,
  unitLabel,
  insightLabel,
  onSliceClick,
}: {
  slices: RiskSlice[]
  eyebrow: string
  title: string
  unitLabel: string
  insightLabel: string
  onSliceClick?: (label: string) => void
}) {
  const total = slices.reduce(
    (sum, slice) => sum + slice.value,
    0
  )

  const displayOrder = [
    'CRITICAL',
    'HIGH',
    'MEDIUM',
    'MODERATE',
    'LOW',
    'WARNING',
    'INFO',
    'INSUFFICIENT_HISTORY',
    'LOW_VOLUME',
    'UNKNOWN',
  ]

  const ordered = displayOrder
    .map(label =>
      slices.find(
        slice => slice.label === label
      )
    )
    .filter(Boolean) as RiskSlice[]

  const criticalCount =
    ordered.find(
      item => item.label === 'CRITICAL'
    )?.value || 0

  return (
    <>
      <div className="card-title">
        <div>
          <p className="eyebrow">
            {eyebrow}
          </p>
          <h2>{title}</h2>
        </div>

        <div className="corner-stat">
          <small>
            Total {toTitleCase(unitLabel)}
          </small>
          <strong>{formatNumber(total)}</strong>
        </div>
      </div>

      <DonutChart
        slices={ordered}
        unitLabel={unitLabel}
        onSliceClick={onSliceClick}
      />

      <div className="risk-insight">
        <strong>{insightLabel}</strong>
        <p>
          {criticalCount} {unitLabel} are in the leading critical bucket and require immediate attention.
        </p>
      </div>
    </>
  )
}

function SlaPerformanceCard({
  data,
  compliance,
  eyebrow,
  title,
  complianceLabel,
  unitLabel = 'min',
}: {
  data: SlaPerformancePoint[]
  compliance: number
  eyebrow: string
  title: string
  complianceLabel: string
  unitLabel?: 'min' | 'hr'
}) {
  const points = data
    .slice(-10)
    .map(item => ({
      label: item.period || `Run ${item.run}`,
      value: item.processing_time,
      secondary: item.sla_limit,
    }))

  const slaLimit =
    points.length > 0
      ? points[points.length - 1].secondary
      : 60

  const avg =
    points.length > 0
      ? points.reduce(
          (sum, point) => sum + point.value,
          0
        ) / points.length
      : 0

  const max =
    points.length > 0
      ? Math.max(
          ...points.map(
            point => point.value
          )
        )
      : 0

  return (
    <>
      <div className="card-title">
        <div>
          <p className="eyebrow">
            {eyebrow}
          </p>
          <h2>{title}</h2>
        </div>

        <div className="corner-stat">
          <small>{complianceLabel}</small>
          <strong>
            {Number(compliance).toFixed(0)}%
          </strong>
        </div>
      </div>

      <SimpleLineChart
        points={points}
        yFormatter={value =>
          `${Math.round(value)} ${unitLabel}`
        }
        secondaryLabel={`SLA Limit (${Math.round(
          slaLimit
        )} ${unitLabel})`}
      />

      <div className="chart-stat-row">
        <div className="stat-chip">
          <small>Avg Processing Time</small>
          <strong>
            {unitLabel === 'hr'
              ? `${avg.toFixed(1)} hr`
              : formatProcessingStat(avg)}
          </strong>
        </div>

        <div className="stat-chip">
          <small>Max Processing Time</small>
          <strong>
            {unitLabel === 'hr'
              ? `${max.toFixed(1)} hr`
              : formatProcessingStat(max)}
          </strong>
        </div>

        <div className="stat-chip">
          <small>SLA Limit</small>
          <strong>
            {slaLimit.toFixed(1)} {unitLabel}
          </strong>
        </div>
      </div>
    </>
  )
}

function AuthorizationPendingFunnelCard({
  data,
}: {
  data: AuthorizationSlaFunnel
}) {
  const statuses = [
    {
      label: 'SLA Breached',
      value: data.sla_breached,
      tone: 'breached',
    },
    {
      label: 'SLA Met',
      value: data.sla_met,
      tone: 'met',
    },
    {
      label: 'SLA N/A',
      value: data.pending_na,
      tone: 'pending',
    },
  ]
  const maximum = Math.max(
    ...statuses.map(status => status.value),
    1
  )

  return (
    <>
      <div className="card-title">
        <div>
          <p className="eyebrow">AUTHORIZATION SLA STATUS</p>
          <h2>Authorization SLA Status</h2>
          <p className="authorization-funnel-subtitle">
            Distribution of authorization records across SLA breached, met, and unavailable statuses.
          </p>
        </div>
      </div>

      <div className="authorization-sla-bar-chart" aria-label="Authorization SLA status bar chart">
        <div className="authorization-sla-y-axis">
          {[maximum, maximum * 0.75, maximum * 0.5, maximum * 0.25, 0].map(value => (
            <span key={value}>{formatNumber(Math.round(value))}</span>
          ))}
        </div>
        <div className="authorization-sla-bars">
          <div className="authorization-sla-grid" />
          {statuses.map(status => (
            <div className="authorization-sla-bar-column" key={status.label}>
              <div
                className={`authorization-sla-bar ${status.tone}`}
                style={{ height: `${Math.max(3, (status.value / maximum) * 100)}%` }}
              >
                <title>{`${status.label}: ${formatNumber(status.value)} authorizations`}</title>
              </div>
              <span>{status.label}</span>
            </div>
          ))}
        </div>
      </div>
    </>
  )
}

function AuthorizationProviderSlaBreachCard({
  providers,
}: {
  providers: AuthorizationProviderSlaBreach[]
}) {
  if (providers.length === 0) {
    return <DrugEmptyState message="No provider SLA data available" />
  }

  return (
    <>
      <div className="card-title">
        <div>
          <p className="eyebrow">PROVIDER-WISE SLA</p>
          <h2>Providers with Highest SLA Breach Rate</h2>
          <p className="authorization-funnel-subtitle">
            Top 10 providers ranked by authorization SLA breach rate.
          </p>
        </div>
      </div>

      <div className="authorization-provider-breach-chart">
        <div className="authorization-provider-breach-axis">
          <span>0%</span><span>25%</span><span>50%</span><span>75%</span><span>100%</span>
        </div>
        {providers.map(provider => {
          const title = [
            `Provider: ${provider.npi}`,
            `Total Authorizations: ${formatNumber(provider.total_authorizations)}`,
            `Pending / N/A: ${formatNumber(provider.pending_na)}`,
            `SLA Met: ${formatNumber(provider.sla_met)}`,
            `SLA Breached: ${formatNumber(provider.sla_breached)}`,
            `SLA Breach Rate: ${provider.sla_breach_pct.toFixed(1)}%`,
            `Current Volume: ${formatNumber(Number(provider.current_month_volume ?? 0))}`,
            `Baseline Volume: ${formatNumber(Number(provider.baseline_volume ?? 0))}`,
            `Volume Risk: ${(Number(provider.volume_risk ?? 0) * 100).toFixed(1)}%`,
          ].join('\n')

          return (
            <div className="authorization-provider-breach-row" key={provider.npi}>
              <span>{provider.npi}</span>
              <div>
                <i style={{ width: `${Math.min(100, Math.max(0, provider.sla_breach_pct))}%` }}>
                  <title>{title}</title>
                </i>
                <b>{provider.sla_breach_pct.toFixed(1)}%</b>
              </div>
            </div>
          )
        })}
      </div>
    </>
  )
}

function DrugEmptyState({
  message,
}: {
  message: string
}) {
  return (
    <div className="alert-flow-layout">
      <div className="alert-core">
        <strong>0</strong>
        <small>{message}</small>
      </div>
    </div>
  )
}

function DrugHorizontalBarChart({
  bars,
  valueFormatter,
  onBarClick,
}: {
  bars: Array<{
    label: string
    value: number
    detail?: string
    meta?: string
    title?: string
  }>
  valueFormatter: (value: number) => string
  onBarClick?: (label: string) => void
}) {
  if (bars.length === 0) {
    return (
      <DrugEmptyState message="No drug data available" />
    )
  }

  const maxValue = Math.max(
    ...bars.map(item => item.value),
    1
  )

  return (
    <div className="alert-bar-list">
      {bars.map(item => (
        <button
          className="alert-bar-row"
          key={`${item.label}-${item.meta || ''}`}
          title={item.title}
          type="button"
          onClick={() => onBarClick?.(item.label)}
        >
          <div className="alert-bar-head">
            <span>{item.label}</span>
            <strong>
              {valueFormatter(item.value)}
            </strong>
          </div>

          {(item.detail || item.meta) && (
            <small
              style={{
                color: 'rgba(255,255,255,0.72)',
                display: 'block',
                marginBottom: 8,
              }}
            >
              {[item.detail, item.meta]
                .filter(Boolean)
                .join(' • ')}
            </small>
          )}

          <div className="alert-bar-track">
            <i
              style={{
                width: `${(item.value / maxValue) * 100}%`,
              }}
            />
          </div>
        </button>
      ))}
    </div>
  )
}

function DrugOverallTrendCard({
  data,
  eyebrow,
  title,
  onPointClick,
}: {
  data: DrugOverallTrendPoint[]
  eyebrow: string
  title: string
  onPointClick?: (year: string) => void
}) {
  const points = data
    .filter(
      item =>
        item.calendar_year != null &&
        item.final_volume_risk_score != null
    )
    .map(item => ({
      label: String(item.calendar_year),
      period: String(item.calendar_year),
      value: Number(item.final_volume_risk_score),
    }))

  if (points.length === 0) {
    return (
      <>
        <div className="card-title">
          <div>
            <p className="eyebrow">{eyebrow}</p>
            <h2>{title}</h2>
          </div>
        </div>
        <DrugEmptyState message="No year-wise risk trend available" />
      </>
    )
  }

  const latestPoint = points[points.length - 1]
  const peakPoint = points.reduce((best, point) =>
    point.value > best.value ? point : best
  )
  const averageScore =
    points.reduce((sum, point) => sum + point.value, 0) /
    points.length

  return (
    <>
      <div className="card-title">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h2>{title}</h2>
        </div>

        <div className="corner-stat">
          <small>Latest Year</small>
          <strong>{latestPoint.label}</strong>
        </div>
      </div>

      <SimpleLineChart
        points={points}
        yFormatter={value => formatRiskScore(value)}
        onPointClick={onPointClick}
      />

      <div className="chart-stat-row">
        <div className="stat-chip">
          <small>Latest Risk Score</small>
          <strong>
            {formatRiskScore(latestPoint.value)}
          </strong>
        </div>

        <div className="stat-chip">
          <small>Average Risk Score</small>
          <strong>
            {formatRiskScore(averageScore)}
          </strong>
        </div>

        <div className="stat-chip">
          <small>Peak Year</small>
          <strong>
            {peakPoint.label} (
            {formatRiskScore(peakPoint.value)})
          </strong>
        </div>
      </div>
    </>
  )
}

function DrugTopRiskCard({
  data,
  onBarClick,
}: {
  data: DrugTopRiskItem[]
  onBarClick?: (item: DrugTopRiskItem) => void
}) {
  const bars = data
    .filter(
      item =>
        item.volume_risk_score != null &&
        (item.Brnd_Name || item.Gnrc_Name)
    )
    .map(item => ({
      label:
        item.Brnd_Name ||
        item.Gnrc_Name ||
        'Unknown Drug',
      value: Number(item.volume_risk_score),
      sourceItem: item,
      detail:
        item.Gnrc_Name &&
        item.Gnrc_Name !== item.Brnd_Name
          ? item.Gnrc_Name
          : undefined,
      meta: item.volume_risk_level || undefined,
      title: [
        `Brand: ${item.Brnd_Name || 'Unknown'}`,
        `Generic: ${item.Gnrc_Name || 'Unknown'}`,
        `Risk Score: ${formatRiskScore(
          item.volume_risk_score
        )}`,
        `Risk Level: ${item.volume_risk_level || 'Unknown'}`,
      ].join('\n'),
    }))

  const averageScore =
    bars.length > 0
      ? bars.reduce((sum, item) => sum + item.value, 0) /
        bars.length
      : 0

  return (
    <>
      <div className="card-title">
        <div>
          <p className="eyebrow">
            TOP 5 DRUGS BY RISK SCORE
          </p>
          <h2>
            Highest-risk drugs from the pharmacy volume table
          </h2>
        </div>

        <div className="corner-stat">
          <small>Average Score</small>
          <strong>
            {formatRiskScore(averageScore)}
          </strong>
        </div>
      </div>

      <DrugHorizontalBarChart
        bars={bars}
        valueFormatter={value =>
          formatRiskScore(value)
        }
        onBarClick={label => {
          const match = bars.find(
            item => item.label === label
          )

          if (match) {
            onBarClick?.(match.sourceItem)
          }
        }}
      />
    </>
  )
}

function DrugUtilizationCard({
  data,
  eyebrow,
  title,
  onBarClick,
}: {
  data: DrugUtilizationItem[]
  eyebrow: string
  title: string
  onBarClick?: (item: DrugUtilizationItem) => void
}) {
  const [metric, setMetric] = useState<
    'total_claims' | 'total_fills' | 'total_day_supply'
  >('total_claims')

  const metricLabel =
    metric === 'total_claims'
      ? 'Total Claims'
      : metric === 'total_fills'
        ? 'Total Fills'
        : 'Total Day Supply'

  const bars = data
    .filter(item => item[metric] != null)
    .slice(0, 5)
    .map(item => ({
      label: item.Brnd_Name || 'Unknown Drug',
      value: Number(item[metric] ?? 0),
      sourceItem: item,
      detail: metricLabel,
      title: [
        `Brand: ${item.Brnd_Name || 'Unknown'}`,
        `Total Claims: ${formatNumber(
          Number(item.total_claims ?? 0)
        )}`,
        `Total Fills: ${formatNumber(
          Number(item.total_fills ?? 0)
        )}`,
        `Total Day Supply: ${formatNumber(
          Number(item.total_day_supply ?? 0)
        )}`,
      ].join('\n'),
    }))

  const averageValue =
    bars.length > 0
      ? bars.reduce((sum, item) => sum + item.value, 0) /
        bars.length
      : 0

  return (
    <>
      <div className="card-title">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h2>{title}</h2>
        </div>

        <select
          className="themed-select"
          value={metric}
          onChange={event =>
            setMetric(
              event.target.value as
                | 'total_claims'
                | 'total_fills'
                | 'total_day_supply'
            )
          }
          style={{
            width: 170,
            height: 36,
          }}
        >
          <option value="total_claims">
            Total Claims
          </option>
          <option value="total_fills">
            Total Fills
          </option>
          <option value="total_day_supply">
            Total Day Supply
          </option>
        </select>
      </div>

      <DrugHorizontalBarChart
        bars={bars}
        valueFormatter={value =>
          formatNumber(Math.round(value))
        }
        onBarClick={label => {
          const match = bars.find(
            item => item.label === label
          )

          if (match) {
            onBarClick?.(match.sourceItem)
          }
        }}
      />

      <div className="chart-stat-row">
        <div className="stat-chip">
          <small>Selected Metric</small>
          <strong>{metricLabel}</strong>
        </div>

        <div className="stat-chip">
          <small>Top Drug</small>
          <strong>{bars[0]?.label || '--'}</strong>
        </div>

        <div className="stat-chip">
          <small>Average of Top 10</small>
          <strong>
            {formatNumber(Math.round(averageValue))}
          </strong>
        </div>
      </div>
    </>
  )
}

function DrugScatterPlot({
  points,
  xLabel,
  yLabel,
  xFormatter,
  yFormatter,
}: {
  points: Array<{
    label: string
    x: number
    y: number
    title: string
    riskLevel?: string | null
  }>
  xLabel: string
  yLabel: string
  xFormatter: (value: number) => string
  yFormatter: (value: number) => string
}) {
  if (points.length === 0) {
    return (
      <DrugEmptyState message="No scatter data available" />
    )
  }

  const maxX = Math.max(
    ...points.map(point => point.x),
    1
  )
  const maxY = Math.max(
    ...points.map(point => point.y),
    1
  )

  const toneColor = (riskLevel?: string | null) => {
    const value = (riskLevel || '').toUpperCase()
    if (value === 'CRITICAL') return '#ff8da1'
    if (value === 'HIGH') return '#ffd166'
    if (value === 'MEDIUM') return '#7ee0ff'
    return '#aebdff'
  }

  return (
    <div className="overview-line-chart">
      <div className="y-labels">
        {[maxY, maxY * 0.66, maxY * 0.33, 0].map(
          value => (
            <span key={value}>
              {yFormatter(value)}
            </span>
          )
        )}
      </div>

      <div className="chart-area">
        <div className="chart-grid" />

        <svg
          viewBox="0 0 560 220"
          preserveAspectRatio="none"
        >
          {points.map(point => {
            const x =
              20 + (point.x / maxX) * 500
            const y =
              190 - (point.y / maxY) * 150

            return (
              <circle
                key={point.title}
                cx={x}
                cy={y}
                r="4"
                fill={toneColor(point.riskLevel)}
                className="chart-point"
              >
                <title>{point.title}</title>
              </circle>
            )
          })}
        </svg>

        <div className="x-labels">
          <span>0</span>
          <span>{xLabel}</span>
          <span>{xFormatter(maxX)}</span>
        </div>
      </div>

      <div className="chart-legend">
        <span>
          <i className="legend-primary" />
          {xLabel}
        </span>
        <span>
          <i className="legend-secondary" />
          {yLabel}
        </span>
      </div>
    </div>
  )
}

function DrugRiskScoreTrendChart({
  points,
  onPointClick,
}: {
  points: Array<{
    label: string
    shortLabel: string
    value: number
    title: string
    sourceItem: DrugClaimsVsCostPoint
  }>
  onPointClick?: (item: DrugClaimsVsCostPoint) => void
}) {
  if (points.length === 0) {
    return (
      <DrugEmptyState message="No drug risk score trend data available" />
    )
  }

  const maxValue = Math.max(
    ...points.map(point => point.value),
    1
  )
  const xStep =
    points.length > 1
      ? 520 / (points.length - 1)
      : 520

  const linePath = points
    .map((point, index) => {
      const x = 20 + index * xStep
      const y =
        190 - (point.value / maxValue) * 150
      return `${index === 0 ? 'M' : 'L'}${x} ${y}`
    })
    .join(' ')

  const areaPath = `${linePath} L${20 + (points.length - 1) * xStep} 190 L20 190 Z`

  const avgRisk =
    points.reduce(
      (sum, point) => sum + point.value,
      0
    ) / points.length

  const peakPoint = points.reduce((best, point) =>
    point.value > best.value ? point : best
  )

  return (
    <div className="overview-line-chart drug-risk-trend-chart">
      <div className="y-labels">
        {[maxValue, maxValue * 0.66, maxValue * 0.33, 0].map(
          value => (
            <span key={value}>
              {formatRiskScore(value)}
            </span>
          )
        )}
      </div>

      <div className="chart-area">
        <div className="chart-grid" />

        <svg
          viewBox="0 0 560 220"
          preserveAspectRatio="none"
        >
          <defs>
            <linearGradient
              id="drug-risk-area-gradient"
              x1="0"
              x2="0"
              y1="0"
              y2="1"
            >
              <stop
                offset="0%"
                stopColor="rgba(255, 103, 196, 0.55)"
              />
              <stop
                offset="100%"
                stopColor="rgba(255, 103, 196, 0.08)"
              />
            </linearGradient>
          </defs>

          <path
            d={areaPath}
            fill="url(#drug-risk-area-gradient)"
          />

          <path
            d={linePath}
            className="drug-risk-line"
          />

          {points.map(point => {
            const index = points.indexOf(point)
            const x = 20 + index * xStep
            const y =
              190 - (point.value / maxValue) * 150

            return (
              <g key={point.title}>
                <text
                  x={x}
                  y={y - 10}
                  textAnchor="middle"
                  className="drug-risk-point-label"
                >
                  {formatRiskScore(point.value)}
                </text>
                <circle
                  cx={x}
                  cy={y}
                  r="4"
                  className={
                    onPointClick
                      ? 'drug-risk-point interactive'
                      : 'drug-risk-point'
                  }
                  onClick={() =>
                    onPointClick?.(point.sourceItem)
                  }
                >
                  <title>{point.title}</title>
                </circle>
              </g>
            )
          })}
        </svg>

        <div className="x-labels">
          {points.map(point => (
            <span key={point.label}>
              {point.shortLabel}
            </span>
          ))}
        </div>
      </div>

      <div className="chart-stat-row">
        <div className="stat-chip">
          <small>Y-Axis</small>
          <strong>Avg Risk Score</strong>
        </div>

        <div className="stat-chip">
          <small>Average Score</small>
          <strong>
            {formatRiskScore(avgRisk)}
          </strong>
        </div>

        <div className="stat-chip">
          <small>Peak Drug</small>
          <strong>{peakPoint.label}</strong>
        </div>
      </div>
    </div>
  )
}

function DrugClaimsLollipopCard({
  data,
  onPointClick,
}: {
  data: DrugClaimsVsCostPoint[]
  onPointClick?: (item: DrugClaimsVsCostPoint) => void
}) {
  const points = data
    .filter(
      item =>
        item.Brnd_Name != null &&
        item.total_claims != null
    )
    .sort(
      (a, b) =>
        Number(b.total_claims) - Number(a.total_claims)
    )
    .slice(0, 10)

  if (points.length === 0) {
    return <DrugEmptyState message="No drug claims data available" />
  }

  const maxClaims = Math.max(
    ...points.map(point => Number(point.total_claims)),
    1
  )
  const chartHeight = Math.max(220, points.length * 27)

  return (
    <>
      <div className="card-title">
        <div>
          <p className="eyebrow">DRUG vs CLAIMS</p>
          <h2>Total claims by drug</h2>
        </div>
      </div>

      <div className="drug-claims-lollipop">
        <div className="drug-claims-labels">
          {points.map(point => (
            <span key={point.Brnd_Name} title={point.Brnd_Name || ''}>
              {point.Brnd_Name}
            </span>
          ))}
        </div>

        <div className="drug-claims-chart-area">
          <div className="drug-claims-grid" />
          <svg
            viewBox={`0 0 560 ${chartHeight}`}
            preserveAspectRatio="none"
            aria-label="Top 10 drugs by total claims"
          >
            {points.map((point, index) => {
              const claims = Number(point.total_claims)
              const y = 14 + index * (chartHeight - 28) / Math.max(points.length - 1, 1)
              const x = 8 + (claims / maxClaims) * 532
              const title = [
                `Brand: ${point.Brnd_Name}`,
                `Generic: ${point.Gnrc_Name || 'Unknown'}`,
                `Total Claims: ${formatNumber(claims)}`,
              ].join('\n')

              return (
                <g key={`${point.Brnd_Name}-${index}`}>
                  <line
                    x1="8"
                    x2={x}
                    y1={y}
                    y2={y}
                    className="drug-claims-stem"
                  />
                  <circle
                    cx={x}
                    cy={y}
                    r="5"
                    className={
                      onPointClick
                        ? 'drug-claims-dot interactive'
                        : 'drug-claims-dot'
                    }
                    onClick={() => onPointClick?.(point)}
                  >
                    <title>{title}</title>
                  </circle>
                </g>
              )
            })}
          </svg>

          <div className="drug-claims-axis">
            <span>0</span>
            <span>{formatCompact(maxClaims / 2)}</span>
            <span>{formatCompact(maxClaims)}</span>
          </div>
        </div>
      </div>
    </>
  )
}

function DrugVolumeRiskLevelCard({
  slices,
  eyebrow,
  title,
  onBucketClick,
  onLevelClick,
}: {
  slices: RiskSlice[]
  eyebrow: string
  title: string
  onBucketClick?: (
    bucket: 'STABLE' | 'ELEVATED'
  ) => void
  onLevelClick?: (label: string) => void
}) {
  const total = slices.reduce(
    (sum, slice) => sum + slice.value,
    0
  )

  const elevatedLabels = new Set([
    'HIGH',
    'CRITICAL',
  ])

  const elevated = slices
    .filter(slice =>
      elevatedLabels.has(slice.label)
    )
    .reduce((sum, slice) => sum + slice.value, 0)

  const stable = Math.max(0, total - elevated)
  const stablePct =
    total > 0 ? (stable / total) * 100 : 0
  const elevatedPct =
    total > 0 ? (elevated / total) * 100 : 0

  const radius = 52
  const circumference = Math.PI * radius
  const stableLength =
    (stablePct / 100) * circumference
  const elevatedLength =
    (elevatedPct / 100) * circumference

  const breakdown = slices
    .slice()
    .sort((a, b) => b.value - a.value)

  return (
    <>
      <div className="card-title">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h2>{title}</h2>
        </div>
      </div>

      <div className="drug-volume-level-card">
        <button
          type="button"
          className="drug-volume-donut-button"
          onClick={() =>
            onBucketClick?.('STABLE')
          }
        >
          <svg
            viewBox="0 0 180 130"
            className="drug-volume-donut"
          >
            <path
              d="M 26 102 A 64 64 0 0 1 154 102"
              className="drug-volume-track"
            />
            <path
              d="M 26 102 A 64 64 0 0 1 154 102"
              className="drug-volume-stable"
              strokeDasharray={`${stableLength} ${circumference}`}
            />
            <path
              d="M 26 102 A 64 64 0 0 1 154 102"
              className="drug-volume-elevated"
              strokeDasharray={`${elevatedLength} ${circumference}`}
              strokeDashoffset={`-${stableLength}`}
            />
            <text
              x="90"
              y="68"
              textAnchor="middle"
              className="drug-volume-total"
            >
              {stablePct.toFixed(1)}%
            </text>
            <text
              x="90"
              y="87"
              textAnchor="middle"
              className="drug-volume-caption"
            >
              Volume Stability
            </text>
          </svg>
        </button>

        <div className="drug-volume-summary-grid">
          <button
            type="button"
            className="drug-volume-summary stable"
            onClick={() =>
              onBucketClick?.('STABLE')
            }
          >
            <small>Stable</small>
            <strong>
              {formatNumber(stable)} ({stablePct.toFixed(1)}%)
            </strong>
          </button>

          <button
            type="button"
            className="drug-volume-summary elevated"
            onClick={() =>
              onBucketClick?.('ELEVATED')
            }
          >
            <small>Elevated</small>
            <strong>
              {formatNumber(elevated)} ({elevatedPct.toFixed(1)}%)
            </strong>
          </button>

          <div className="drug-volume-breakdown">
            {breakdown.map(slice => (
              <button
                key={slice.label}
                type="button"
                className="drug-volume-level-row"
                onClick={() =>
                  onLevelClick?.(slice.label)
                }
              >
                <span>{slice.label}</span>
                <strong>
                  {formatNumber(slice.value)}
                </strong>
              </button>
            ))}
          </div>
        </div>
      </div>
    </>
  )
}

function DrugScatterExplorerCard({
  claimsVsCost,
  riskVsBeneficiaries,
  eyebrow,
  title,
  onPointClick,
}: {
  claimsVsCost: DrugClaimsVsCostPoint[]
  riskVsBeneficiaries: DrugRiskVsBeneficiariesPoint[]
  eyebrow: string
  title: string
  onPointClick?: (item: DrugClaimsVsCostPoint) => void
}) {
  const trendPoints = claimsVsCost
    .filter(
      item =>
        item.volume_risk_score != null &&
        (item.Brnd_Name || item.Gnrc_Name)
    )
    .sort(
      (a, b) =>
        Number(a.total_claims ?? 0) -
        Number(b.total_claims ?? 0)
    )
    .slice(-6)
    .map(item => ({
      label:
        item.Brnd_Name ||
        item.Gnrc_Name ||
        'Unknown Drug',
      shortLabel: (
        item.Brnd_Name ||
        item.Gnrc_Name ||
        'Unknown'
      )
        .split(' ')
        .slice(0, 1)
        .join(' ')
        .slice(0, 8),
      value: Number(item.volume_risk_score ?? 0),
      sourceItem: item,
      title: [
        `Brand: ${item.Brnd_Name || 'Unknown'}`,
        `Generic: ${item.Gnrc_Name || 'Unknown'}`,
        `Total Claims: ${formatNumber(
          Number(item.total_claims ?? 0)
        )}`,
        `Total Drug Cost: ${formatCurrency(
          Number(item.total_drug_cost ?? 0)
        )}`,
        `Risk Score: ${formatRiskScore(
          item.volume_risk_score
        )}`,
        `Risk Level: ${item.volume_risk_level || 'Unknown'}`,
      ].join('\n'),
    }))

  const highestRiskDrug = riskVsBeneficiaries
    .filter(
      item =>
        item.volume_risk_score != null &&
        (item.Brnd_Name || item.Gnrc_Name)
    )
    .sort(
      (a, b) =>
        Number(b.volume_risk_score ?? 0) -
        Number(a.volume_risk_score ?? 0)
    )[0]

  return (
    <>
      <div className="card-title">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h2>{title}</h2>
        </div>

        <div className="corner-stat">
          <small>Graph Style</small>
          <strong>Risk Score Trend</strong>
        </div>
      </div>

      <DrugRiskScoreTrendChart
        points={trendPoints}
        onPointClick={onPointClick}
      />

      <div className="chart-stat-row">
        <div className="stat-chip">
          <small>X-Axis</small>
          <strong>Total Claims Order</strong>
        </div>

        <div className="stat-chip">
          <small>Y-Axis</small>
          <strong>
            Avg Risk Score
          </strong>
        </div>

        <div className="stat-chip">
          <small>Top Risk Drug</small>
          <strong>
            {highestRiskDrug?.Brnd_Name ||
              highestRiskDrug?.Gnrc_Name ||
              '--'}
          </strong>
        </div>
      </div>
    </>
  )
}

function AlertFlowCard({
  bars,
  onBarClick,
}: {
  bars: AlertDistributionItem[]
  onBarClick?: (label: string) => void
}) {
  const total = bars.reduce(
    (sum, bar) => sum + bar.value,
    0
  )

  const colors: Record<string, string> = {
    'DQ Critical': '#ff4d6d',
    'Provider Risk': '#ffaf33',
    'Behavior Anomaly': '#b04dff',
    'SLA Breach': '#10c7ff',
  }

  return (
    <>
      <div className="card-title">
        <div>
          <p className="eyebrow">
            ALERT DISTRIBUTION FLOW
          </p>
          <h2>
            Breakdown of active alerts by category
          </h2>
        </div>
      </div>

      <div className="alert-flow-layout">
        <div className="alert-core">
          <strong>
            {formatNumber(total)}
          </strong>
          <small>Active Alerts</small>
        </div>

        <div className="alert-flow-rows">
          {bars.map(item => {
            const pct =
              total > 0
                ? (item.value / total) * 100
                : 0

            return (
              <button
                key={item.label}
                className="alert-flow-row"
                type="button"
                onClick={() =>
                  onBarClick?.(item.label)
                }
              >
                <span
                  className="flow-dot"
                  style={{
                    background:
                      colors[item.label] ||
                      '#8eeeff',
                  }}
                />

                <div>
                  <small>{item.label}</small>
                  <strong>
                    {formatNumber(item.value)}
                  </strong>
                </div>

                <em>
                  ({pct.toFixed(2)}%)
                </em>
              </button>
            )
          })}
        </div>
      </div>
    </>
  )
}

function PaginationControls({
  pagination,
  onPageChange,
}: {
  pagination?: Pagination
  onPageChange: (page: number) => void
}) {
  if (!pagination) return null

  return (
    <div className="pager">
      <small>
        Page {pagination.page} of {pagination.total_pages} •{' '}
        {formatNumber(pagination.total)} records
      </small>

      <div className="pager-actions">
        <button
          className="small-button"
          onClick={() =>
            onPageChange(
              Math.max(1, pagination.page - 1)
            )
          }
          disabled={pagination.page <= 1}
        >
          Previous
        </button>

        <button
          className="small-button"
          onClick={() =>
            onPageChange(
              Math.min(
                pagination.total_pages,
                pagination.page + 1
              )
            )
          }
          disabled={
            pagination.page >=
            pagination.total_pages
          }
        >
          Next
        </button>
      </div>
    </div>
  )
}

function SummaryStrip({
  items,
}: {
  items: Array<{
    label: string
    value: string
  }>
}) {
  return (
    <div className="drill-summary-grid">
      {items.map(item => (
        <Glass
          key={item.label}
          className="drill-summary-card"
        >
          <small>{item.label}</small>
          <strong>{item.value}</strong>
        </Glass>
      ))}
    </div>
  )
}

function DetailFieldGrid({
  title,
  data,
  priorityKeys = [],
}: {
  title: string
  data: Record<string, unknown>
  priorityKeys?: string[]
}) {
  const handled = new Set(priorityKeys)
  const orderedKeys = [
    ...priorityKeys.filter(key => key in data),
    ...Object.keys(data).filter(key => !handled.has(key)),
  ]

  return (
    <Glass className="table-card">
      <div className="card-title">
        <div>
          <p className="eyebrow">{title}</p>
          <h2>{toLabel(title)}</h2>
        </div>
      </div>

      <div className="detail-record-grid">
        {orderedKeys.map(key => (
          <div key={key} className="detail-record">
            <small>{toLabel(key)}</small>
            <strong>{formatValue(data[key])}</strong>
          </div>
        ))}
      </div>
    </Glass>
  )
}

function DataPage({
  router,
}: {
  router: RouterLike
}) {
  const searchParams = useSearchParams()
  const dataset = searchParams.get('dataset') || 'carrier'
  const page = Number(searchParams.get('page') || '1')
  const [data, setData] =
    useState<ClaimSentinelDataResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const datasets = [
    'authorization_dataset',
    'beneficiary',
    'carrier',
    'dme',
    'hha',
    'hospice',
    'inpatient',
    'outpatient',
    'snf',
  ]

  useEffect(() => {
    let cancelled = false

    async function loadData() {
      try {
        setLoading(true)
        setError('')
        const response = await fetchDashboard<ClaimSentinelDataResponse>(
          `/data${buildQuery({ dataset, page, page_size: 50 })}`
        )

        if (!cancelled) setData(response)
      } catch (err) {
        console.error(err)
        if (!cancelled) {
          setError('Unable to load claim_sentinel data.')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    loadData()
    return () => {
      cancelled = true
    }
  }, [dataset, page])

  const goToDataset = (nextDataset: string) =>
    router.push(`/data${buildQuery({ dataset: nextDataset })}`)

  return (
    <>
      <Glass className="filter-card">
        <div className="card-title">
          <div>
            <p className="eyebrow">CLAIM SENTINEL</p>
            <h2>View data</h2>
          </div>
          <button
            className="small-button"
            onClick={() =>
              downloadCsv(
                `claim-sentinel-${dataset}.csv`,
                data?.items || []
              )
            }
          >
            Export page
          </button>
        </div>

        <select
          className="themed-select"
          value={dataset}
          onChange={event => goToDataset(event.target.value)}
          aria-label="Choose claim_sentinel dataset"
        >
          {datasets.map(option => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </Glass>

      {error && (
        <Glass className="wide-card" style={{ marginTop: 14 }}>
          <p>{error}</p>
        </Glass>
      )}

      <Glass className="table-card" style={{ marginTop: 14 }}>
        <div className="table-wrap">
          <table className="interactive-table">
            <thead>
              <tr>
                {(data?.columns || []).map(column => (
                  <th key={column}>{column}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={Math.max(1, data?.columns.length || 1)}>
                    Loading...
                  </td>
                </tr>
              ) : data?.items.length ? (
                data.items.map((item, index) => (
                  <tr key={`${dataset}-${index}`}>
                    {data.columns.map(column => (
                      <td key={column}>{formatValue(item[column])}</td>
                    ))}
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={Math.max(1, data?.columns.length || 1)}>
                    No records found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <PaginationControls
          pagination={data?.pagination}
          onPageChange={nextPage =>
            router.push(
              `/data${buildQuery({ dataset, page: nextPage })}`
            )
          }
        />
      </Glass>
    </>
  )
}

function ClaimsPage({
  router,
}: {
  router: RouterLike
}) {
  const searchParams = useSearchParams()
  const [data, setData] =
    useState<ClaimsResponse | null>(null)
  const [loading, setLoading] =
    useState(true)
  const [error, setError] = useState('')

  const [claimId, setClaimId] =
    useState(searchParams.get('claim_id') || '')
  const [npi, setNpi] = useState(
    searchParams.get('npi') || ''
  )
  const [source, setSource] =
    useState(searchParams.get('source') || '')
  const [period, setPeriod] =
    useState(searchParams.get('period') || '')
  const [dateFrom, setDateFrom] =
    useState(searchParams.get('date_from') || '')
  const [dateTo, setDateTo] = useState(
    searchParams.get('date_to') || ''
  )

  const page = Number(
    searchParams.get('page') || '1'
  )
  const sortBy =
    searchParams.get('sort_by') || 'DT'
  const sortDir =
    searchParams.get('sort_dir') || 'desc'

  useEffect(() => {
    setClaimId(searchParams.get('claim_id') || '')
    setNpi(searchParams.get('npi') || '')
    setSource(searchParams.get('source') || '')
    setPeriod(searchParams.get('period') || '')
    setDateFrom(searchParams.get('date_from') || '')
    setDateTo(searchParams.get('date_to') || '')
  }, [searchParams])

  useEffect(() => {
    let cancelled = false

    async function loadClaims() {
      try {
        setLoading(true)
        setError('')

        const response =
          await fetchDashboard<ClaimsResponse>(
            `/claims${buildQuery({
              page,
              page_size: 25,
              claim_id: searchParams.get('claim_id'),
              npi: searchParams.get('npi'),
              source: searchParams.get('source'),
              period: searchParams.get('period'),
              date_from: searchParams.get('date_from'),
              date_to: searchParams.get('date_to'),
              sort_by: searchParams.get('sort_by'),
              sort_dir: searchParams.get('sort_dir'),
            })}`
          )

        if (!cancelled) {
          setData(response)
        }
      } catch (err) {
        if (!cancelled) {
          console.error(err)
          setError('Unable to load claims data.')
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    loadClaims()

    return () => {
      cancelled = true
    }
  }, [page, searchParams])

  const pushFilters = (
    overrides: Record<string, string | number | undefined | null>
  ) => {
    router.push(
      `/claims${buildQuery({
        page: 1,
        claim_id: claimId,
        npi,
        source,
        period,
        date_from: dateFrom,
        date_to: dateTo,
        sort_by: sortBy,
        sort_dir: sortDir,
        ...overrides,
      })}`
    )
  }

  return (
    <>
      <Glass className="table-card">
        <div className="card-title">
          <div>
            <p className="eyebrow">ALL CLAIMS</p>
            <h2>All Claims</h2>
          </div>

          <div className="toolbar-actions">
            <button
              className="small-button"
              onClick={() =>
                downloadCsv(
                  'claimcare-claims.csv',
                  data?.items || []
                )
              }
            >
              Export
            </button>
          </div>
        </div>

        {data?.filters.period && (
          <div className="filter-chip-row">
            <span className="filter-chip">
              Claims for {data.filters.period}
            </span>
            <span className="filter-chip muted">
              {formatNumber(
                data.pagination.total
              )}{' '}
              records
            </span>
          </div>
        )}

        <div className="drill-filter-grid">
          <input
            className="setting-input"
            value={claimId}
            onChange={event =>
              setClaimId(event.target.value)
            }
            placeholder="Search Claim ID"
          />
          <input
            className="setting-input"
            value={npi}
            onChange={event =>
              setNpi(event.target.value)
            }
            placeholder="Search Provider NPI"
          />
          <select
            className="themed-select"
            value={source}
            onChange={event =>
              setSource(event.target.value)
            }
          >
            <option value="">All Sources</option>
            {data?.filter_options.sources.map(
              option => (
                <option
                  key={option}
                  value={option}
                >
                  {option}
                </option>
              )
            )}
          </select>
          <select
            className="themed-select"
            value={period}
            onChange={event =>
              setPeriod(event.target.value)
            }
          >
            <option value="">All Periods</option>
            {data?.filter_options.periods.map(
              option => (
                <option
                  key={option}
                  value={option}
                >
                  {option}
                </option>
              )
            )}
          </select>
          <input
            className="setting-input"
            type="date"
            value={dateFrom}
            onChange={event =>
              setDateFrom(event.target.value)
            }
          />
          <input
            className="setting-input"
            type="date"
            value={dateTo}
            onChange={event =>
              setDateTo(event.target.value)
            }
          />
        </div>

        <div className="toolbar-actions toolbar-actions-spread">
          <button
            className="primary-button"
            onClick={() => pushFilters({})}
          >
            Filter
          </button>

          <button
            className="small-button"
            onClick={() =>
              router.push('/claims')
            }
          >
            Reset
          </button>
        </div>
      </Glass>

      {error && (
        <Glass
          className="wide-card"
          style={{ marginTop: 14 }}
        >
          <p>{error}</p>
        </Glass>
      )}

      <Glass
        className="table-card"
        style={{ marginTop: 14 }}
      >
        <div className="table-wrap">
          <table className="interactive-table">
            <thead>
              <tr>
                {[
                  ['Claim ID', 'CLM_ID'],
                  ['Provider NPI', 'NPI'],
                  ['Source', 'source'],
                  ['Claim Date', 'DT'],
                  ['Period', 'period'],
                  ['Root Cause', 'root_cause'],
                  ['Recommendation', 'recommendation'],
                ].map(([label, key]) => (
                  <th key={key}>
                    <button
                      className="table-sort"
                      onClick={() =>
                        router.push(
                          `/claims${buildQuery({
                            page: 1,
                            claim_id: data?.filters.claim_id,
                            npi: data?.filters.npi,
                            source: data?.filters.source,
                            period: data?.filters.period,
                            date_from:
                              data?.filters.date_from,
                            date_to:
                              data?.filters.date_to,
                            sort_by: key,
                            sort_dir:
                              sortBy === key &&
                              sortDir === 'asc'
                                ? 'desc'
                                : 'asc',
                          })}`
                        )
                      }
                    >
                      {label}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>

            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={7}>Loading…</td>
                </tr>
              ) : (
                data?.items.map(item => (
                  <tr key={String(item.CLM_ID)}>
                    <td>
                      <button
                        className="table-link"
                        onClick={() =>
                          router.push(
                            `/claims/${encodeURIComponent(
                              String(
                                item.CLM_ID || ''
                              )
                            )}`
                          )
                        }
                      >
                        {formatValue(item.CLM_ID)}
                      </button>
                    </td>
                    <td>
                      <button
                        className="table-link"
                        onClick={() =>
                          router.push(
                            `/providers/${encodeURIComponent(
                              String(item.NPI || '')
                            )}`
                          )
                        }
                      >
                        {formatValue(item.NPI)}
                      </button>
                    </td>
                    <td>{formatValue(item.source)}</td>
                    <td>{formatValue(item.DT)}</td>
                    <td>{formatValue(item.period)}</td>
                    <td>{formatValue(item.root_cause)}</td>
                    <td>
                      {formatValue(
                        item.recommendation
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <PaginationControls
          pagination={data?.pagination}
          onPageChange={nextPage =>
            router.push(
              `/claims${buildQuery({
                ...data?.filters,
                page: nextPage,
              })}`
            )
          }
        />
      </Glass>
    </>
  )
}

function ClaimDetailPage({
  claimId,
  router,
}: {
  claimId: string
  router: RouterLike
}) {
  const [data, setData] =
    useState<ClaimDetailResponse | null>(null)
  const [loading, setLoading] =
    useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false

    async function loadDetail() {
      try {
        setLoading(true)
        setError('')
        const response =
          await fetchDashboard<ClaimDetailResponse>(
            `/claims/${encodeURIComponent(
              claimId
            )}`
          )

        if (!cancelled) {
          setData(response)
        }
      } catch (err) {
        if (!cancelled) {
          console.error(err)
          setError('Unable to load claim detail.')
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    loadDetail()

    return () => {
      cancelled = true
    }
  }, [claimId])

  if (loading) {
    return (
      <Glass className="table-card">
        <p>Loading claim detail…</p>
      </Glass>
    )
  }

  if (error || !data) {
    return (
      <Glass className="table-card">
        <p>{error || 'Claim not found.'}</p>
      </Glass>
    )
  }

  const { claim } = data

  return (
    <>
      <SummaryStrip
        items={[
          {
            label: 'Claim ID',
            value: String(claim.CLM_ID || '—'),
          },
          {
            label: 'Provider NPI',
            value: String(claim.NPI || '—'),
          },
          {
            label: 'Source',
            value: String(claim.source || '—'),
          },
          {
            label: 'Period',
            value: String(claim.period || '—'),
          },
        ]}
      />

      <Glass
        className="table-card"
        style={{ marginTop: 14 }}
      >
        <div className="card-title">
          <div>
            <p className="eyebrow">
              ROOT CAUSE / RECOMMENDATION
            </p>
            <h2>Claim Guidance</h2>
          </div>
        </div>

        <div className="detail-record-grid">
          <div className="detail-record">
            <small>Root Cause</small>
            <strong>
              {formatValue(claim.root_cause)}
            </strong>
          </div>

          <div className="detail-record">
            <small>Recommendation</small>
            <strong>
              {formatValue(claim.recommendation)}
            </strong>
          </div>
        </div>
      </Glass>

      <div className="toolbar-actions">
        <button
          className="small-button"
          onClick={() => router.back()}
        >
          Back to Claims
        </button>
      </div>
    </>
  )
}

function DrugsPage({
  router,
}: {
  router: RouterLike
}) {
  const searchParams = useSearchParams()
  const [data, setData] =
    useState<DrugRecordsResponse | null>(null)
  const [loading, setLoading] =
    useState(true)
  const [error, setError] = useState('')

  const [dataset, setDataset] = useState(
    searchParams.get('dataset') || 'drug-volume'
  )
  const [brandName, setBrandName] =
    useState(searchParams.get('brand_name') || '')
  const [genericName, setGenericName] =
    useState(searchParams.get('generic_name') || '')
  const [riskLevel, setRiskLevel] =
    useState(searchParams.get('risk_level') || '')
  const [riskBucket, setRiskBucket] =
    useState(searchParams.get('risk_bucket') || '')
  const [providerSearch, setProviderSearch] =
    useState(
      searchParams.get('provider_search') || ''
    )
  const [calendarYear, setCalendarYear] =
    useState(
      searchParams.get('calendar_year') || ''
    )

  const page = Number(
    searchParams.get('page') || '1'
  )
  const sortBy =
    searchParams.get('sort_by') ||
    (dataset === 'overall-trend'
      ? 'calendar_year'
      : 'volume_risk_score')
  const sortDir =
    searchParams.get('sort_dir') || 'desc'

  useEffect(() => {
    setDataset(
      searchParams.get('dataset') || 'drug-volume'
    )
    setBrandName(
      searchParams.get('brand_name') || ''
    )
    setGenericName(
      searchParams.get('generic_name') || ''
    )
    setRiskLevel(
      searchParams.get('risk_level') || ''
    )
    setRiskBucket(
      searchParams.get('risk_bucket') || ''
    )
    setProviderSearch(
      searchParams.get('provider_search') || ''
    )
    setCalendarYear(
      searchParams.get('calendar_year') || ''
    )
  }, [searchParams])

  useEffect(() => {
    let cancelled = false

    async function loadDrugRecords() {
      try {
        setLoading(true)
        setError('')

        const response =
          await fetchDrugApi<DrugRecordsResponse>(
            `/records${buildQuery({
              page,
              page_size: 25,
              dataset: searchParams.get('dataset'),
              brand_name:
                searchParams.get('brand_name'),
              generic_name:
                searchParams.get('generic_name'),
              risk_level:
                searchParams.get('risk_level'),
              risk_bucket:
                searchParams.get('risk_bucket'),
              provider_search:
                searchParams.get('provider_search'),
              calendar_year:
                searchParams.get('calendar_year'),
              sort_by: searchParams.get('sort_by'),
              sort_dir: searchParams.get('sort_dir'),
            })}`
          )

        if (!cancelled) {
          setData(response)
        }
      } catch (err) {
        if (!cancelled) {
          console.error(err)
          setError('Unable to load drug records.')
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    loadDrugRecords()

    return () => {
      cancelled = true
    }
  }, [page, searchParams])

  const pushFilters = (
    overrides: Record<string, string | number | undefined | null>
  ) => {
    router.push(
      `/drugs${buildQuery({
        page: 1,
        dataset,
        brand_name: brandName,
        generic_name: genericName,
        risk_level: riskLevel,
        risk_bucket: riskBucket,
        provider_search: providerSearch,
        calendar_year: calendarYear,
        sort_by: sortBy,
        sort_dir: sortDir,
        ...overrides,
      })}`
    )
  }

  const activeDataset =
    data?.dataset || dataset

  const heading =
    activeDataset === 'provider-impact'
      ? 'Affected Providers'
      : activeDataset === 'overall-trend'
        ? calendarYear
          ? `Overall Risk Trend for ${calendarYear}`
          : 'Overall Risk Trend'
        : riskBucket === 'high_severity'
          ? 'High Severity Drugs'
          : riskBucket === 'active_alerts'
            ? 'Active Drug Alerts'
            : riskLevel
              ? `${toLabel(riskLevel)} Drug Records`
              : 'All Drug Records'

  const summaryItems =
    activeDataset === 'provider-impact'
      ? [
          {
            label: 'Providers',
            value: formatNumber(
              data?.summary.provider_count || 0
            ),
          },
          {
            label: 'Total Claims',
            value: formatNumber(
              data?.summary.total_claims || 0
            ),
          },
          {
            label: 'Total Drug Cost',
            value: formatCurrency(
              data?.summary.total_drug_cost || 0
            ),
          },
          {
            label: 'Average Risk Score',
            value: formatRiskScore(
              data?.summary.avg_risk_score || 0
            ),
          },
        ]
      : activeDataset === 'overall-trend'
        ? [
            {
              label: 'Rows',
              value: formatNumber(
                data?.summary.total_records || 0
              ),
            },
            {
              label: 'Total Claims',
              value: formatNumber(
                data?.summary.total_claims || 0
              ),
            },
            {
              label: 'Average Risk Score',
              value: formatRiskScore(
                data?.summary.avg_risk_score || 0
              ),
            },
            {
              label: 'Latest Year',
              value: String(
                data?.summary.latest_year || '—'
              ),
            },
          ]
        : [
            {
              label: 'Records',
              value: formatNumber(
                data?.summary.total_records || 0
              ),
            },
            {
              label: 'Unique Drugs',
              value: formatNumber(
                data?.summary.unique_drugs || 0
              ),
            },
            {
              label: 'Total Claims',
              value: formatNumber(
                data?.summary.total_claims || 0
              ),
            },
            {
              label: 'Total Drug Cost',
              value: formatCurrency(
                data?.summary.total_drug_cost || 0
              ),
            },
            {
              label: 'Average Risk Score',
              value: formatRiskScore(
                data?.summary.avg_risk_score || 0
              ),
            },
          ]

  return (
    <>
      {data && <SummaryStrip items={summaryItems} />}

      <Glass
        className="table-card"
        style={{ marginTop: 14 }}
      >
        <div className="card-title">
          <div>
            <p className="eyebrow">
              DRUG DRILL-DOWN
            </p>
            <h2>{heading}</h2>
          </div>

          <button
            className="small-button"
            onClick={() =>
              downloadExcel(
                'claimcare-drugs.xls',
                data?.items || [],
                'DrugRecords'
              )
            }
          >
            Export
          </button>
        </div>

        <div className="filter-chip-row">
          <span className="filter-chip">
            Dataset: {toLabel(activeDataset)}
          </span>
          {riskLevel && (
            <span className="filter-chip">
              Risk Level: {riskLevel}
            </span>
          )}
          {riskBucket && (
            <span className="filter-chip">
              Bucket: {toLabel(riskBucket)}
            </span>
          )}
          {calendarYear && (
            <span className="filter-chip">
              Year: {calendarYear}
            </span>
          )}
          {data && (
            <span className="filter-chip muted">
              {formatNumber(
                data.pagination.total
              )}{' '}
              records
            </span>
          )}
        </div>

        <div className="drill-filter-grid">
          <select
            className="themed-select"
            value={dataset}
            onChange={event =>
              setDataset(event.target.value)
            }
          >
            <option value="drug-volume">
              Drug Volume Risk
            </option>
            <option value="provider-impact">
              Affected Providers
            </option>
            <option value="overall-trend">
              Overall Risk Trend
            </option>
          </select>

          {dataset === 'provider-impact' ? (
            <input
              className="setting-input"
              value={providerSearch}
              onChange={event =>
                setProviderSearch(
                  event.target.value
                )
              }
              placeholder="Search provider or NPI"
            />
          ) : dataset === 'overall-trend' ? (
            <select
              className="themed-select"
              value={calendarYear}
              onChange={event =>
                setCalendarYear(
                  event.target.value
                )
              }
            >
              <option value="">All Years</option>
              {data?.filter_options.years.map(
                option => (
                  <option
                    key={String(option)}
                    value={String(option)}
                  >
                    {option}
                  </option>
                )
              )}
            </select>
          ) : (
            <>
              <input
                className="setting-input"
                value={brandName}
                onChange={event =>
                  setBrandName(
                    event.target.value
                  )
                }
                placeholder="Search brand name"
              />
              <input
                className="setting-input"
                value={genericName}
                onChange={event =>
                  setGenericName(
                    event.target.value
                  )
                }
                placeholder="Search generic name"
              />
            </>
          )}

          {dataset !== 'overall-trend' && (
            <select
              className="themed-select"
              value={riskLevel}
              onChange={event =>
                setRiskLevel(event.target.value)
              }
            >
              <option value="">All Risk Levels</option>
              {data?.filter_options.risk_levels.map(
                option => (
                  <option
                    key={option}
                    value={option}
                  >
                    {option}
                  </option>
                )
              )}
            </select>
          )}

          {dataset === 'drug-volume' && (
            <select
              className="themed-select"
              value={riskBucket}
              onChange={event =>
                setRiskBucket(event.target.value)
              }
            >
              <option value="">All Buckets</option>
              <option value="high_severity">
                High Severity
              </option>
              <option value="active_alerts">
                Active Alerts
              </option>
            </select>
          )}
        </div>

        <div className="toolbar-actions toolbar-actions-spread">
          <button
            className="primary-button"
            onClick={() =>
              pushFilters({
                dataset,
                brand_name:
                  dataset === 'drug-volume'
                    ? brandName
                    : undefined,
                generic_name:
                  dataset === 'drug-volume'
                    ? genericName
                    : undefined,
                provider_search:
                  dataset === 'provider-impact'
                    ? providerSearch
                    : undefined,
                calendar_year:
                  dataset === 'overall-trend'
                    ? calendarYear
                    : undefined,
                risk_level:
                  dataset === 'overall-trend'
                    ? undefined
                    : riskLevel,
                risk_bucket:
                  dataset === 'drug-volume'
                    ? riskBucket
                    : undefined,
              })
            }
          >
            Filter
          </button>

          <button
            className="small-button"
            onClick={() => router.push('/drugs')}
          >
            Reset
          </button>
        </div>
      </Glass>

      {error && (
        <Glass
          className="wide-card"
          style={{ marginTop: 14 }}
        >
          <p>{error}</p>
        </Glass>
      )}

      <Glass
        className="table-card"
        style={{ marginTop: 14 }}
      >
        <div className="table-wrap">
          <table className="interactive-table">
            <thead>
              <tr>
                {data?.columns.map(column => (
                  <th key={column}>
                    <button
                      className="table-sort"
                      onClick={() =>
                        router.push(
                          `/drugs${buildQuery({
                            ...data.filters,
                            page: 1,
                            sort_by: column,
                            sort_dir:
                              sortBy === column &&
                              sortDir === 'asc'
                                ? 'desc'
                                : 'asc',
                          })}`
                        )
                      }
                    >
                      {toLabel(column)}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>

            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={data?.columns.length || 1}>
                    Loading…
                  </td>
                </tr>
              ) : (
                (data?.items || []).map((item, index) => (
                  <tr
                    key={`${activeDataset}-${index}`}
                  >
                    {(data?.columns || []).map(column => (
                      <td key={column}>
                        {formatValue(item[column])}
                      </td>
                    ))}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <PaginationControls
          pagination={data?.pagination}
          onPageChange={nextPage =>
            router.push(
              `/drugs${buildQuery({
                ...data?.filters,
                page: nextPage,
              })}`
            )
          }
        />
      </Glass>
    </>
  )
}

function ProvidersPage({
  router,
}: {
  router: RouterLike
}) {
  const searchParams = useSearchParams()
  const [data, setData] =
    useState<ProvidersResponse | null>(null)
  const [alerts, setAlerts] =
    useState<AlertDrilldownResponse | null>(null)
  const [loading, setLoading] =
    useState(true)
  const [error, setError] = useState('')

  const [npi, setNpi] = useState(
    searchParams.get('npi') || ''
  )
  const [riskLevel, setRiskLevel] =
    useState(searchParams.get('risk_level') || '')
  const [source, setSource] =
    useState(searchParams.get('source') || '')

  const page = Number(
    searchParams.get('page') || '1'
  )
  const sortBy =
    searchParams.get('sort_by') ||
    'volume_risk'
  const sortDir =
    searchParams.get('sort_dir') || 'desc'
  const alertLevel =
    searchParams.get('alert_level') || ''

  useEffect(() => {
    setNpi(searchParams.get('npi') || '')
    setRiskLevel(
      searchParams.get('risk_level') || ''
    )
    setSource(searchParams.get('source') || '')
  }, [searchParams])

  useEffect(() => {
    let cancelled = false

    async function loadProviders() {
      try {
        setLoading(true)
        setError('')

        const response =
          await fetchDashboard<ProvidersResponse>(
            `/providers${buildQuery({
              page,
              page_size: 25,
              npi: searchParams.get('npi'),
              risk_level:
                searchParams.get('risk_level'),
              source: searchParams.get('source'),
              sort_by: searchParams.get('sort_by'),
              sort_dir:
                searchParams.get('sort_dir'),
            })}`
          )

        if (!cancelled) {
          setData(response)
        }

        if (alertLevel) {
          const alertResponse =
            await fetchDashboard<AlertDrilldownResponse>(
              `/alerts/drilldown${buildQuery({
                level: alertLevel,
              })}`
            )

          if (!cancelled) {
            setAlerts(alertResponse)
          }
        } else if (!cancelled) {
          setAlerts(null)
        }
      } catch (err) {
        if (!cancelled) {
          console.error(err)
          setError('Unable to load provider data.')
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    loadProviders()

    return () => {
      cancelled = true
    }
  }, [page, searchParams, alertLevel])

  const pushFilters = (
    overrides: Record<string, string | number | undefined | null>
  ) => {
    router.push(
      `/providers${buildQuery({
        page: 1,
        npi,
        risk_level: riskLevel,
        source,
        sort_by: sortBy,
        sort_dir: sortDir,
        alert_level: alertLevel,
        ...overrides,
      })}`
    )
  }

  return (
    <>
      {data && (
        <SummaryStrip
          items={[
            {
              label: 'Providers',
              value: formatNumber(
                data.summary.provider_count
              ),
            },
            {
              label: 'Total Claims',
              value: formatNumber(
                data.summary.total_claims
              ),
            },
            {
              label: 'Average Monthly Volume',
              value: data.summary.avg_monthly_volume.toFixed(
                1
              ),
            },
            {
              label: 'Average Deviation',
              value: `${data.summary.avg_deviation.toFixed(
                2
              )}%`,
            },
          ]}
        />
      )}

      <Glass
        className="table-card"
        style={{ marginTop: 14 }}
      >
        <div className="card-title">
          <div>
            <p className="eyebrow">
              PROVIDER DIRECTORY
            </p>
            <h2>
              {riskLevel
                ? `${toLabel(
                    riskLevel
                  )} Risk Providers`
                : 'All Providers'}
            </h2>
          </div>

          <button
            className="small-button"
            onClick={() =>
              downloadExcel(
                'claimcare-providers.xls',
                data?.items || [],
                'Providers'
              )
            }
          >
            Export
          </button>
        </div>

        <div className="filter-chip-row">
          {riskLevel && (
            <span className="filter-chip">
              Risk Level: {riskLevel}
            </span>
          )}
          {alertLevel && (
            <span className="filter-chip">
              Alert Level: {alertLevel}
            </span>
          )}
          {data && (
            <span className="filter-chip muted">
              {formatNumber(
                data.pagination.total
              )}{' '}
              Providers
            </span>
          )}
        </div>

        <div className="drill-filter-grid">
          <input
            className="setting-input"
            value={npi}
            onChange={event =>
              setNpi(event.target.value)
            }
            placeholder="Search NPI"
          />
          <select
            className="themed-select"
            value={riskLevel}
            onChange={event =>
              setRiskLevel(event.target.value)
            }
          >
            <option value="">All Risk Levels</option>
            {data?.filter_options.risk_levels.map(
              option => (
                <option
                  key={option}
                  value={option}
                >
                  {option}
                </option>
              )
            )}
          </select>
          <select
            className="themed-select"
            value={source}
            onChange={event =>
              setSource(event.target.value)
            }
          >
            <option value="">All Sources</option>
            {data?.filter_options.sources.map(
              option => (
                <option
                  key={option}
                  value={option}
                >
                  {option}
                </option>
              )
            )}
          </select>
        </div>

        <div className="toolbar-actions toolbar-actions-spread">
          <button
            className="primary-button"
            onClick={() => pushFilters({})}
          >
            Filter
          </button>

          <button
            className="small-button"
            onClick={() =>
              router.push('/providers')
            }
          >
            Reset
          </button>
        </div>
      </Glass>

      {alerts && (
        <Glass
          className="table-card"
          style={{ marginTop: 14 }}
        >
          <div className="card-title">
            <div>
              <p className="eyebrow">
                ALERT DRILL-DOWN
              </p>
              <h2>
                {toLabel(alerts.level)} Records
              </h2>
            </div>
          </div>

          <div className="alert-drill-grid">
            <div className="alert-drill-section">
              <small>Data Quality</small>
              <strong>
                {formatNumber(
                  alerts.data_quality.length
                )}
              </strong>
            </div>
            <div className="alert-drill-section">
              <small>Provider Risk</small>
              <strong>
                {formatNumber(
                  alerts.provider_risk.length
                )}
              </strong>
            </div>
            <div className="alert-drill-section">
              <small>SLA / Behavior</small>
              <strong>
                {formatNumber(
                  alerts.sla_behavior.length
                )}
              </strong>
            </div>
          </div>
        </Glass>
      )}

      {error && (
        <Glass
          className="wide-card"
          style={{ marginTop: 14 }}
        >
          <p>{error}</p>
        </Glass>
      )}

      <Glass
        className="table-card"
        style={{ marginTop: 14 }}
      >
        <div className="table-wrap">
          <table className="interactive-table">
            <thead>
              <tr>
                {[
                  ['Provider NPI', 'NPI'],
                  ['Current Period', 'current_period'],
                  ['Current Month Volume', 'current_month_volume'],
                  ['Baseline Volume', 'baseline_volume'],
                  ['Deviation %', 'deviation_pct'],
                  ['Volume Risk', 'volume_risk'],
                  ['Risk Level', 'risk_level'],
                  ['History Months', 'history_months'],
                  ['Total Claim Volume', 'total_claim_volume'],
                  ['Source Count', 'source_count'],
                  ['Sources', 'sources'],
                  ['Months Available', 'months_available'],
                  ['Root Cause', 'root_cause'],
                  ['Recommendation', 'recommendation'],
                ].map(([label, key]) => (
                  <th key={key}>
                    <button
                      className="table-sort"
                      onClick={() =>
                        router.push(
                          `/providers${buildQuery({
                            page: 1,
                            npi: data?.filters.npi,
                            risk_level:
                              data?.filters.risk_level,
                            source:
                              data?.filters.source,
                            alert_level: alertLevel,
                            sort_by: key,
                            sort_dir:
                              sortBy === key &&
                              sortDir === 'asc'
                                ? 'desc'
                                : 'asc',
                          })}`
                        )
                      }
                    >
                      {label}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>

            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={14}>Loading…</td>
                </tr>
              ) : (
                data?.items.map(item => (
                  <tr key={String(item.NPI)}>
                    <td>
                      <button
                        className="table-link"
                        onClick={() =>
                          router.push(
                            `/providers/${encodeURIComponent(
                              String(item.NPI || '')
                            )}`
                          )
                        }
                      >
                        {formatValue(item.NPI)}
                      </button>
                    </td>
                    <td>
                      {formatValue(
                        item.current_period
                      )}
                    </td>
                    <td>
                      {formatValue(
                        item.current_month_volume
                      )}
                    </td>
                    <td>
                      {formatValue(
                        item.baseline_volume
                      )}
                    </td>
                    <td>
                      {formatValue(
                        item.deviation_pct
                      )}
                    </td>
                    <td>
                      {formatValue(item.volume_risk)}
                    </td>
                    <td>
                      {formatValue(item.risk_level)}
                    </td>
                    <td>
                      {formatValue(
                        item.history_months
                      )}
                    </td>
                    <td>
                      {formatValue(
                        item.total_claim_volume
                      )}
                    </td>
                    <td>
                      {formatValue(item.source_count)}
                    </td>
                    <td>{formatValue(item.sources)}</td>
                    <td>
                      {formatValue(
                        item.months_available
                      )}
                    </td>
                    <td>
                      {formatValue(item.root_cause)}
                    </td>
                    <td>
                      {formatValue(
                        item.recommendation
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <PaginationControls
          pagination={data?.pagination}
          onPageChange={nextPage =>
            router.push(
              `/providers${buildQuery({
                ...data?.filters,
                alert_level: alertLevel,
                page: nextPage,
              })}`
            )
          }
        />
      </Glass>
    </>
  )
}

function ProviderDetailPage({
  npi,
  router,
}: {
  npi: string
  router: RouterLike
  initialAlertLevel?: string
}) {
  const [data, setData] =
    useState<ProviderDetailResponse | null>(null)
  const [loading, setLoading] =
    useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false

    async function loadDetail() {
      try {
        setLoading(true)
        setError('')

        const response =
          await fetchDashboard<ProviderDetailResponse>(
            `/providers/${encodeURIComponent(
              npi
            )}`
          )

        if (!cancelled) {
          setData(response)
        }
      } catch (err) {
        if (!cancelled) {
          console.error(err)
          setError(
            'Unable to load provider detail.'
          )
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    loadDetail()

    return () => {
      cancelled = true
    }
  }, [npi])

  if (loading) {
    return (
      <Glass className="table-card">
        <p>Loading provider profile…</p>
      </Glass>
    )
  }

  if (error || !data) {
    return (
      <Glass className="table-card">
        <p>{error || 'Provider not found.'}</p>
      </Glass>
    )
  }

  const { provider, history, claims, quality_context } =
    data

  return (
    <>
      <SummaryStrip
        items={[
          {
            label: 'Provider NPI',
            value: String(provider.NPI || '—'),
          },
          {
            label: 'Risk Level',
            value: String(
              provider.risk_level || '—'
            ),
          },
          {
            label: 'Volume Risk',
            value: formatValue(
              provider.volume_risk
            ),
          },
          {
            label: 'Total Claim Volume',
            value: formatValue(
              provider.total_claim_volume
            ),
          },
          {
            label: 'Current Month Volume',
            value: formatValue(
              provider.current_month_volume
            ),
          },
          {
            label: 'Baseline Volume',
            value: formatValue(
              provider.baseline_volume
            ),
          },
        ]}
      />

      <div
        className="overview-support-grid"
        style={{ marginTop: 14 }}
      >
        <DetailFieldGrid
          title="PROVIDER RISK SUMMARY"
          data={provider}
          priorityKeys={[
            'NPI',
            'risk_level',
            'volume_risk',
            'current_period',
            'current_month_volume',
            'baseline_volume',
            'deviation_pct',
            'history_months',
            'sources',
          ]}
        />

        <DetailFieldGrid
          title="DATA QUALITY CONTEXT"
          data={quality_context || {}}
          priorityKeys={[
            'status',
            'severity',
            'quality_score',
            'overall_status',
            'root_cause',
            'recommendation',
          ]}
        />
      </div>

      <Glass
        className="overview-chart-card"
        style={{ marginTop: 14 }}
      >
        <div className="card-title">
          <div>
            <p className="eyebrow">
              PROVIDER VOLUME TREND
            </p>
            <h2>Provider volume trend</h2>
          </div>
        </div>

        <SimpleLineChart
          points={history.map(item => ({
            label: formatMonthLabel(
              String(item.period || '')
            ),
            period: String(item.period || ''),
            value: Number(
              item.monthly_volume || 0
            ),
            secondary: Number(
              item.baseline_volume || 0
            ),
          }))}
          yFormatter={value =>
            `${Math.round(value)}`
          }
          secondaryLabel="Baseline Volume"
          onPointClick={period =>
            router.push(
              `/claims${buildQuery({
                period,
                npi,
              })}`
            )
          }
        />
      </Glass>

      <Glass
        className="table-card"
        style={{ marginTop: 14 }}
      >
        <div className="card-title">
          <div>
            <p className="eyebrow">
              PROVIDER RISK HISTORY
            </p>
            <h2>Provider risk history</h2>
          </div>
        </div>

        <div className="table-wrap">
          <table className="interactive-table">
            <thead>
              <tr>
                {[
                  'Period',
                  'Monthly Volume',
                  'Baseline',
                  'Deviation %',
                  'Risk Level',
                  'Volume Risk',
                ].map(header => (
                  <th key={header}>{header}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {history.map(item => (
                <tr key={String(item.period)}>
                  <td>{formatValue(item.period)}</td>
                  <td>
                    {formatValue(item.monthly_volume)}
                  </td>
                  <td>
                    {formatValue(
                      item.baseline_volume
                    )}
                  </td>
                  <td>
                    {formatValue(
                      item.deviation_pct
                    )}
                  </td>
                  <td>
                    {formatValue(item.risk_level)}
                  </td>
                  <td>
                    {formatValue(item.volume_risk)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Glass>

      <Glass
        className="table-card"
        style={{ marginTop: 14 }}
      >
        <div className="card-title">
          <div>
            <p className="eyebrow">
              PROVIDER CLAIMS
            </p>
            <h2>Provider claims</h2>
          </div>
        </div>

        <div className="table-wrap">
          <table className="interactive-table">
            <thead>
              <tr>
                {[
                  'Claim ID',
                  'Source',
                  'Claim Date',
                  'Period',
                  'Root Cause',
                  'Recommendation',
                ].map(header => (
                  <th key={header}>{header}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {claims.map(item => (
                <tr key={String(item.CLM_ID)}>
                  <td>
                    <button
                      className="table-link"
                      onClick={() =>
                        router.push(
                          `/claims/${encodeURIComponent(
                            String(
                              item.CLM_ID || ''
                            )
                          )}`
                        )
                      }
                    >
                      {formatValue(item.CLM_ID)}
                    </button>
                  </td>
                  <td>{formatValue(item.source)}</td>
                  <td>{formatValue(item.DT)}</td>
                  <td>{formatValue(item.period)}</td>
                  <td>
                    {formatValue(item.root_cause)}
                  </td>
                  <td>
                    {formatValue(
                      item.recommendation
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Glass>

      <div className="toolbar-actions">
        <button
          className="small-button"
          onClick={() => router.back()}
        >
          Back to Providers
        </button>
      </div>
    </>
  )
}

function Quality() {
  return (
    <>
      <div className="quality-hero">
        <Glass className="score-card">
          <div className="ring">
            <span>98.7</span>
            <small>/ 100</small>
          </div>

          <div>
            <p className="eyebrow">
              COMPOSITE QUALITY SCORE
            </p>

            <h2>
              Healthy data foundation
            </h2>

            <p>
              Across 12 active payer feeds{' '}
              <Status>+2.4%</Status>
            </p>
          </div>
        </Glass>

        <div className="dimension-grid">
          {dimensions.map(
            (d, i) => {
              const values = [
                99.8,
                98.9,
                100,
                97.6,
                99.1,
                98.3,
                100,
                99.4,
              ]

              return (
                <Glass
                  className="dimension"
                  key={d}
                >
                  <div className="dimension-top">
                    <span>{d}</span>

                    <strong>
                      {values[i]}%
                    </strong>
                  </div>

                  <div className="mini-bar">
                    <i
                      style={{
                        width: `${values[i]}%`,
                      }}
                    />
                  </div>

                  <small>
                    {i === 3
                      ? '2 rules need review'
                      : 'Within threshold'}
                  </small>
                </Glass>
              )
            }
          )}
        </div>
      </div>

      <Glass className="table-card">
        <div className="card-title">
          <div>
            <p className="eyebrow">
              QUALITY FINDINGS
            </p>
            <h2>
              Rules requiring attention
            </h2>
          </div>

          <button className="small-button">
            Export report
          </button>
        </div>

        <Table
          headers={[
            'Dimension',
            'Field',
            'Rule',
            'Affected rows',
            'Affected %',
            'Severity',
            'Status',
          ]}
          rows={findings}
        />
      </Glass>
    </>
  )
}

function Table({
  headers,
  rows,
}: {
  headers: string[]
  rows: string[][]
}) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {headers.map(
              header => (
                <th key={header}>
                  {header}
                </th>
              )
            )}
          </tr>
        </thead>

        <tbody>
          {rows.map(
            (row, i) => (
              <tr key={i}>
                {row.map(
                  (cell, j) => (
                    <td key={j}>
                      {j === 4 ? (
                        <Status
                          tone={
                            cell === 'High'
                              ? 'bad'
                              : cell ===
                                'Medium'
                              ? 'warn'
                              : 'info'
                          }
                        >
                          {cell}
                        </Status>
                      ) : j === 5 ? (
                        <Status
                          tone={
                            cell === 'Open'
                              ? 'bad'
                              : 'good'
                          }
                        >
                          {cell}
                        </Status>
                      ) : (
                        cell
                      )}
                    </td>
                  )
                )}
              </tr>
            )
          )}
        </tbody>
      </table>
    </div>
  )
}

function Processing() {
  return (
    <>
      <Glass className="process-card">
        <div className="card-title">
          <div>
            <p className="eyebrow">
              CURRENT EXECUTION · CC-2847
            </p>

            <h2>
              Claims daily adjudication
            </h2>
          </div>

          <Status>
            Running normally
          </Status>
        </div>

        <div className="timeline">
          {[
            ['Ingest', '09:20:04', 'done'],
            ['Validate', '09:24:18', 'done'],
            ['Transform', '09:31:42', 'done'],
            ['Adjudicate', '09:38:16', 'current'],
            ['Publish', '—', 'next'],
          ].map(
            ([name, time, state], i) => (
              <div
                className={`timeline-step ${state}`}
                key={name}
              >
                <span className="timeline-dot">
                  {state === 'done' ? (
                    <CheckCircle2 size={14} />
                  ) : (
                    i + 1
                  )}
                </span>

                <strong>{name}</strong>
                <small>{time}</small>

                {i < 4 && <i />}
              </div>
            )
          )}
        </div>

        <div className="process-foot">
          <span>
            <small>Elapsed</small>
            <strong>18m 42s</strong>
          </span>

          <span>
            <small>Expected</small>
            <strong>22m 00s</strong>
          </span>

          <span>
            <small>Records</small>
            <strong>1,842,091</strong>
          </span>

          <span>
            <small>Throughput</small>
            <strong>98.4K/min</strong>
          </span>
        </div>
      </Glass>

      <Glass className="chart-card">
        <div className="card-title">
          <div>
            <p className="eyebrow">
              EXECUTION TREND
            </p>

            <h2>
              Processing time over 7 days
            </h2>
          </div>

          <Status>Improving</Status>
        </div>

        <TrendChart />
      </Glass>
    </>
  )
}

function TrendChart() {
  return (
    <div className="trend-chart">
      <div className="y-labels">
        <span>30m</span>
        <span>20m</span>
        <span>10m</span>
        <span>0m</span>
      </div>

      <div className="chart-area">
        <div className="chart-grid" />

        <svg
          viewBox="0 0 700 220"
          preserveAspectRatio="none"
        >
          <path
            className="baseline"
            d="M0 58 C80 80 130 62 180 84 S280 70 340 108 S460 92 520 122 S630 94 700 104"
          />

          <path
            className="trend-line"
            d="M0 108 C80 102 130 118 180 96 S280 112 340 88 S460 102 520 76 S630 90 700 48"
          />

          <circle
            cx="700"
            cy="48"
            r="5"
          />
        </svg>

        <div className="x-labels">
          <span>Mon</span>
          <span>Tue</span>
          <span>Wed</span>
          <span>Thu</span>
          <span>Fri</span>
          <span>Sat</span>
          <span>Sun</span>
        </div>
      </div>
    </div>
  )
}

function SLA() {
  return (
    <>
      <div className="sla-grid">
        {[
          [
            'Claims',
            '22m',
            '18m 42s',
            'MET',
            'good',
          ],
          [
            'Pharmacy',
            '14m',
            '16m 08s',
            'MINOR OVERRUN',
            'warn',
          ],
          [
            'Authorization',
            '10m',
            '27m 34s',
            'BREACHED',
            'bad',
          ],
        ].map(
          ([
            name,
            target,
            current,
            state,
            tone,
          ]) => (
            <Glass
              className="sla-card"
              key={name}
            >
              <div className="sla-top">
                <div className="node-icon">
                  <Activity size={16} />
                </div>

                <span>{name}</span>

                <Status
                  tone={tone as
                    | 'good'
                    | 'warn'
                    | 'bad'
                    | 'info'}
                >
                  {state}
                </Status>
              </div>

              <div className="sla-time">
                <strong>
                  {current}
                </strong>

                <small>
                  of {target} target
                </small>
              </div>

              <div className="sla-bar">
                <i
                  className={
                    tone as string
                  }
                  style={{
                    width:
                      tone === 'bad'
                        ? '100%'
                        : tone === 'warn'
                        ? '84%'
                        : '72%',
                  }}
                />
              </div>

              <small>
                Current execution duration
              </small>
            </Glass>
          )
        )}
      </div>

      <div className="content-grid">
        <Glass className="wide-card">
          <div className="card-title">
            <div>
              <p className="eyebrow">
                BEHAVIORAL SIGNALS
              </p>

              <h2>
                Volume vs historical baseline
              </h2>
            </div>

            <Status>Stable</Status>
          </div>

          <TrendChart />
        </Glass>

        <Glass className="side-card breach">
          <p className="eyebrow">
            ROOT CAUSE ANALYSIS
          </p>

          <h2>
            Authorization SLA breach
          </h2>

          <p>
            Processing duration exceeded the
            configured SLA by 17m 34s. The
            signal is isolated to downstream
            clinical review.
          </p>

          <div className="cause">
            <AlertTriangle size={16} />

            <div>
              <strong>Likely cause</strong>

              <small>
                Retry loop in clinical review
                enrichment
              </small>
            </div>
          </div>

          <button className="primary-button full">
            View recommendation
            <ArrowRight size={16} />
          </button>
        </Glass>
      </div>
    </>
  )
}

function Anomalies() {
  return (
    <div className="anomaly-grid">
      {[
        [
          'Claims Anomalies',
          '2 signals',
          '18% volume shift',
          'Claims volume is above the historical baseline for this hour.',
          'warn',
        ],
        [
          'Pharmacy Anomalies',
          '1 signal',
          'New provider mix',
          'A new provider mix is contributing to an unusual NDC distribution.',
          'info',
        ],
        [
          'Authorization Anomalies',
          '3 signals',
          'Latency cluster',
          'Latency is clustering around clinical review enrichment.',
          'bad',
        ],
      ].map(
        ([
          name,
          count,
          title,
          description,
          tone,
        ]) => (
          <Glass
            className="anomaly-card"
            key={name}
          >
            <div className="anomaly-head">
              <span
                className={`anomaly-orb ${tone}`}
              >
                <Activity size={20} />
              </span>

              <Status
                tone={tone as
                  | 'good'
                  | 'warn'
                  | 'bad'
                  | 'info'}
              >
                {count}
              </Status>
            </div>

            <p className="eyebrow">
              {name}
            </p>

            <h2>{title}</h2>

            <p>{description}</p>

            <div className="anomaly-footer">
              <span>
                Detected 12m ago
              </span>

              <ArrowRight size={15} />
            </div>
          </Glass>
        )
      )}
    </div>
  )
}

function Insights() {
  return (
    <div className="insight-grid">
      {[
        [
          'SLA Breach',
          'Processing duration exceeded the configured SLA.',
          'Investigate pipeline delays, retries, processing bottlenecks, and upstream/downstream dependencies.',
          'Critical',
        ],
        [
          'Quality drift',
          'Procedure code validity is trending down on one payer feed.',
          'Review the latest code set mapping and confirm the source version with the payer.',
          'High',
        ],
        [
          'Volume shift',
          'Pharmacy volume is 18% above its historical baseline.',
          'Validate enrollment changes and prepare downstream capacity for the next batch.',
          'Monitor',
        ],
      ].map(
        ([
          title,
          what,
          action,
          tag,
        ]) => (
          <Glass
            className="insight-card"
            key={title}
          >
            <div className="insight-top">
              <span className="feature-icon">
                <Sparkles size={16} />
              </span>

              <Status
                tone={
                  tag === 'Critical'
                    ? 'bad'
                    : tag === 'High'
                    ? 'warn'
                    : 'info'
                }
              >
                {tag}
              </Status>
            </div>

            <h2>{title}</h2>

            <div className="insight-section">
              <small>
                WHAT HAPPENED?
              </small>

              <p>{what}</p>
            </div>

            <div className="insight-section">
              <small>
                WHAT SHOULD THE TEAM DO?
              </small>

              <p>{action}</p>
            </div>

            <button className="text-button">
              Open investigation
              <ArrowRight size={14} />
            </button>
          </Glass>
        )
      )}
    </div>
  )
}

function Alerts({
  filter,
  setFilter,
  search,
  setSearch,
}: {
  filter: string
  setFilter: (value: string) => void
  search: string
  setSearch: (value: string) => void
}) {
  const alerts = [
    [
      'Claims SLA breached',
      'Processing duration exceeded target by 17m 34s.',
      'Critical',
      '12m ago',
    ],
    [
      'Procedure code validity drop',
      '89 rows failed code set match in Claims.',
      'High',
      '24m ago',
    ],
    [
      'Pharmacy volume shift',
      '18% above historical baseline.',
      'Warning',
      '28m ago',
    ],
    [
      'Daily batch completed',
      'Claims batch CC-2847 completed successfully.',
      'Info',
      '1h ago',
    ],
  ]

  const filtered = alerts.filter(
    item =>
      (filter === 'All' ||
        item[2] === filter) &&
      item[0]
        .toLowerCase()
        .includes(
          search.toLowerCase()
        )
  )

  return (
    <Glass className="alerts-card">
      <div className="alerts-toolbar">
        <div className="search-box">
          <Search size={15} />

          <input
            placeholder="Search alerts"
            value={search}
            onChange={e =>
              setSearch(
                e.target.value
              )
            }
          />
        </div>

        <div className="filter-row">
          {[
            'All',
            'Critical',
            'High',
            'Warning',
            'Info',
          ].map(filterValue => (
            <button
              className={
                filter === filterValue
                  ? 'selected'
                  : ''
              }
              key={filterValue}
              onClick={() =>
                setFilter(
                  filterValue
                )
              }
            >
              {filterValue}
            </button>
          ))}
        </div>
      </div>

      {filtered.map(
        alert => (
          <div
            className="alert-row"
            key={alert[0]}
          >
            <span
              className={`alert-icon ${alert[2].toLowerCase()}`}
            >
              <AlertTriangle size={16} />
            </span>

            <div>
              <strong>
                {alert[0]}
              </strong>

              <p>{alert[1]}</p>
            </div>

            <Status
              tone={
                alert[2] === 'Critical'
                  ? 'bad'
                  : alert[2] === 'High'
                  ? 'warn'
                  : alert[2] === 'Info'
                  ? 'info'
                  : 'warn'
              }
            >
              {alert[2]}
            </Status>

            <time>{alert[3]}</time>

            <ArrowRight size={15} />
          </div>
        )
      )}
    </Glass>
  )
}

function Batch() {
  return (
    <>
      <Glass className="batch-header">
        <div>
          <p className="eyebrow">
            BATCH DETAIL / COMPLETED
          </p>

          <h2>
            CC-2847 · Claims daily adjudication
          </h2>

          <p>
            Completed today at 09:42 AM ·
            1,842,091 records
          </p>
        </div>

        <Status>Completed</Status>
      </Glass>

      <div className="flow">
        {[
          [
            'DQ Findings',
            '98.7%',
            'Data quality',
          ],
          [
            'SLA',
            '18m 42s',
            'Within target',
          ],
          [
            'Behavior',
            'Normal',
            'No drift',
          ],
          [
            'Root Cause',
            'None',
            'No issue found',
          ],
          [
            'Recommendation',
            'Ready',
            'Next action',
          ],
        ].map(
          ([title, value, sub], i) => (
            <Glass
              className="flow-card"
              key={title}
            >
              <span className="flow-number">
                0{i + 1}
              </span>

              <p className="eyebrow">
                {title}
              </p>

              <h2>{value}</h2>
              <small>{sub}</small>

              {i < 4 && (
                <ArrowRight
                  className="flow-arrow"
                  size={16}
                />
              )}
            </Glass>
          )
        )}
      </div>

      <Glass className="batch-detail">
        <div className="card-title">
          <div>
            <p className="eyebrow">
              BATCH INFORMATION
            </p>

            <h2>
              Execution summary
            </h2>
          </div>

          <button className="small-button">
            Download report
          </button>
        </div>

        <div className="detail-grid">
          {[
            ['Source', 'PayerCore / Claims'],
            ['Records received', '1,842,091'],
            ['Records published', '1,839,804'],
            ['Started', '09:20:04 AM'],
            ['Completed', '09:42:16 AM'],
            ['Run ID', 'run_2847_0920'],
          ].map(
            ([label, value]) => (
              <div key={label}>
                <small>{label}</small>
                <strong>{value}</strong>
              </div>
            )
          )}
        </div>
      </Glass>
    </>
  )
}

function Settings() {
  return (
    <Glass className="settings-card">
      <div className="settings-tabs">
        <button className="selected">
          Workspace
        </button>

        <button>
          Notifications
        </button>

        <button>
          Integrations
        </button>

        <button>
          Team access
        </button>
      </div>

      <div className="settings-content">
        <p className="eyebrow">
          WORKSPACE PREFERENCES
        </p>

        <h2>
          ClaimCare Operations
        </h2>

        <p>
          Configure the signals,
          thresholds, and team experience
          for this workspace.
        </p>

        {[
          [
            'Workspace name',
            'ClaimCare Operations',
          ],
          [
            'Default timezone',
            'Eastern Time (ET)',
          ],
          [
            'Alert digest',
            'Daily at 08:00 AM',
          ],
        ].map(
          ([label, value]) => (
            <label key={label}>
              {label}

              <div className="setting-input">
                {value}
                <ChevronDown size={15} />
              </div>
            </label>
          )
        )}

        <button className="primary-button">
          Save changes
          <CheckCircle2 size={16} />
        </button>
      </div>
    </Glass>
  )
}
