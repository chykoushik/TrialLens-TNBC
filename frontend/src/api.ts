export class ApiError extends Error { constructor(message: string, public status: number) { super(message) } }
const base = import.meta.env.VITE_API_BASE_URL ?? '/api'
export const apiUrl = (path: string) => `${base.replace(/\/$/, '')}${path}`
export async function api<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(apiUrl(path), {
    signal,
    ...(body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  })
  let data
  try { data = await response.json() } catch { throw new ApiError('Backend returned an unreadable response. Check API routing and retry.', response.status) }
  if (!response.ok) throw new ApiError(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status}). Check inputs.`, response.status)
  return data as T
}
