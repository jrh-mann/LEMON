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
      window.location.hash = '#/home'
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
            <h1>Build and run workflows.</h1>
            <p>Design, test, and iterate on automation workflows.</p>
          </div>
        </aside>

        <section className="auth-panel">
          <div className="auth-panel-header">
            <a className="auth-back" href="#/home">
              Back to home
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
