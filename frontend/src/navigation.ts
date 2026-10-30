import { useEffect, useState } from 'react'

const pages = ['Home', 'Evidence Review Demo', 'Research Results', 'Interactive Demo', 'Review Evidence', 'Research Lab', 'Trial Library']
export function readRoute() {
  const params = new URLSearchParams(window.location.hash.slice(1))
  const value = params.get('page') ?? 'Home'
  const requested = value === 'Real Review' ? 'Evidence Review Demo' : value
  return { page: pages.includes(requested) ? requested : 'Home', trial: params.get('trial') ?? '', snapshot: params.get('snapshot') ?? '', view: params.get('view') ?? '' }
}

export function writeRoute(route: { page: string; trial?: string; snapshot?: string; view?: string }) {
  const params = new URLSearchParams({ page: route.page })
  for (const field of ['trial', 'snapshot', 'view'] as const) if (route[field]) params.set(field, route[field])
  const hash = `#${params}`
  if (window.location.hash === hash) return
  window.history.pushState(null, '', hash)
  window.dispatchEvent(new Event('triallens:navigation'))
}

export function useRoute() {
  const [route, setRoute] = useState(readRoute)
  useEffect(() => {
    const sync = () => setRoute(readRoute())
    for (const event of ['popstate', 'hashchange', 'triallens:navigation']) window.addEventListener(event, sync)
    return () => { for (const event of ['popstate', 'hashchange', 'triallens:navigation']) window.removeEventListener(event, sync) }
  }, [])
  return route
}
