import { useId } from 'react'
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from 'react'
import type { State } from './types'

export type IconName = 'overview' | 'trials' | 'evidence' | 'assessment' | 'priority' | 'arrow' | 'refresh' | 'menu' | 'close' | 'check'

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  const paths: Record<IconName, ReactNode> = {
    overview: <><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></>,
    trials: <><path d="M5 4h14v16H5zM9 4v16M12 8h4M12 12h4M12 16h3" /></>,
    evidence: <><path d="M5 3h10l4 4v14H5zM14 3v5h5M8 12h8M8 16h5" /></>,
    assessment: <><circle cx="12" cy="12" r="9" /><path d="m8 12 3 3 5-6" /></>,
    priority: <><path d="M4 6h16M4 12h11M4 18h6M17 15v6m-3-3 3 3 3-3" /></>,
    arrow: <path d="M5 12h14m-5-5 5 5-5 5" />,
    refresh: <><path d="M20 10a8 8 0 0 0-14-4L3 9m0-6v6h6M4 14a8 8 0 0 0 14 4l3-3m0 6v-6h-6" /></>,
    menu: <path d="M4 6h16M4 12h16M4 18h16" />,
    close: <path d="m6 6 12 12M6 18 18 6" />,
    check: <path d="m5 12 4 4L19 6" />,
  }
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>
}

export function Button({ variant = 'secondary', className = '', children, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'quiet'; children: ReactNode }) {
  return <button type="button" className={`button button-${variant} ${className}`} {...props}>{children}</button>
}

export function StatusIndicator({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'success' | 'warning' | 'error' }) {
  return <span className={`status-indicator status-${tone}`}><span className="status-dot" aria-hidden="true" />{children}</span>
}

export function StateBadge({ state }: { state: State }) {
  return <span className={`badge ${state}`}><span className="badge-dot" aria-hidden="true" />{state}</span>
}

export function Panel({ title, eyebrow, accessory, children, className = '' }: { title: string; eyebrow?: string; accessory?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={`panel ${className}`}>
    <div className="section-heading"><div>{eyebrow && <p className="eyebrow">{eyebrow}</p>}<h2>{title}</h2></div>{accessory}</div>
    {children}
  </section>
}

export function DataTable({ label, children }: { label: string; children: ReactNode }) {
  return <div className="table-wrap" role="region" aria-label={label} tabIndex={0}><table><caption className="sr-only">{label}</caption>{children}</table></div>
}

export function TextField({ label, hideLabel = false, className = '', id, ...props }: InputHTMLAttributes<HTMLInputElement> & { label: string; hideLabel?: boolean }) {
  const generatedId = useId()
  const inputId = id ?? generatedId
  return <label className={`text-field ${className}`} htmlFor={inputId}><span className={hideLabel ? 'sr-only' : undefined}>{label}</span><input id={inputId} {...props} /></label>
}

export function EmptyState({ title, description, action, error = false }: { title: string; description: string; action?: ReactNode; error?: boolean }) {
  return <div className={`empty-state ${error ? 'empty-error' : ''}`} role={error ? 'alert' : 'status'}><strong>{title}</strong><p>{description}</p>{action}</div>
}
