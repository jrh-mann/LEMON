import { useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import { loginUser } from '../api/auth'

const authCopy = {
  title: 'Welcome back',
  subtitle: 'Sign in to review runs, validate changes, and ship updates.',
  action: 'Sign in',
}

export default function AuthPage() {
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (isSubmitting) return
    setError(null)

    const formData = new FormData(event.currentTarget)
    const email = String(formData.get('email') || '').trim()
    const password = String(formData.get('password') || '')
    const remember = Boolean(formData.get('remember'))

    setIsSubmitting(true)
    try {
      await loginUser({ email, password, remember })
      window.location.hash = '#/'
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message)
      } else {
        setError('Unable to sign in right now. Please try again.')
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-shell">
        <aside className="auth-hero">
          <div className="auth-hero-top">
            <div className="logo auth-logo">
              <span className="logo-mark">L</span>
              <span className="logo-text">Lemon</span>
            </div>
            <span className="auth-hero-badge">Private beta</span>
          </div>

          <div className="auth-hero-copy">
            <h1>Run workflows with full traceability.</h1>
            <p>Design, validate, and share automation with a clear audit trail for every change.</p>
          </div>

          <div className="auth-stats">
            <div className="auth-stat">
              <span className="auth-stat-value">4x</span>
              <span className="auth-stat-label">faster iteration cycles</span>
            </div>
            <div className="auth-stat">
              <span className="auth-stat-value">92%</span>
              <span className="auth-stat-label">validation confidence</span>
            </div>
            <div className="auth-stat">
              <span className="auth-stat-value">1 hub</span>
              <span className="auth-stat-label">for workflows and evidence</span>
            </div>
          </div>

          <div className="auth-highlights">
            <div className="auth-highlight-card">
              <h3>Live collaboration</h3>
              <p>Share runs, capture feedback, and keep approvals in one place.</p>
            </div>
            <div className="auth-highlight-card">
              <h3>Risk-aware testing</h3>
              <p>Run validation cases and watch scores update in real time.</p>
            </div>
            <div className="auth-highlight-card">
              <h3>Clean exports</h3>
              <p>Ship JSON runbooks with versioned history baked in.</p>
            </div>
          </div>
        </aside>

        <section className="auth-panel">
          <div className="auth-panel-header">
            <a className="auth-back" href="#/">
              Back to workspace
            </a>
          </div>

          <div className="auth-panel-title">
            <h2>{authCopy.title}</h2>
            <p>{authCopy.subtitle}</p>
          </div>

          <form className="auth-form" onSubmit={handleSubmit}>
            <div className="auth-field">
              <label htmlFor="auth-email">Work email</label>
              <input
                id="auth-email"
                type="email"
                name="email"
                placeholder="you@company.com"
                autoComplete="email"
                required
                disabled={isSubmitting}
              />
            </div>
            <div className="auth-field">
              <label htmlFor="auth-password">Password</label>
              <input
                id="auth-password"
                type="password"
                name="password"
                placeholder="Your password"
                autoComplete="current-password"
                required
                disabled={isSubmitting}
              />
            </div>

            <div className="auth-row">
              <label className="auth-checkbox">
                <input type="checkbox" name="remember" disabled={isSubmitting} />
                <span>Remember this device.</span>
              </label>
            </div>

            {error && (
              <div className="auth-error" role="alert">
                {error}
              </div>
            )}

            <button className="primary auth-submit" type="submit" disabled={isSubmitting}>
              {isSubmitting ? 'Please wait...' : authCopy.action}
            </button>
          </form>
        </section>
      </div>
    </div>
  )
}
