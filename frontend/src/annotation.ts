import { apiUrl } from './api'
import type { ExtractionSource, SourceSpan } from './extractionView'

export type Review = { status: 'unreviewed' | 'uncertain' | 'reviewed'; reviewer: string | null; reviewed_at: string | null; note: string | null }
export type Quote = { span: SourceSpan; text: string }
export type Label = { value: unknown; evidence: Quote[]; review: Review }
export type Criterion = { reference_id: string; original: Quote; boundary_review: Review; dependencies: Criterion[]; [key: string]: unknown }
export type Reference = { annotation_version: string; annotation_revision: number; nct_id: string; snapshot_sha256: string; annotation_origin: string; inventory_review: Review; criteria: Criterion[] }
export type Audit = { version: string; parent: string | null; stage: string; reviewer: string; saved_at: string; note: string; operation: string; reference_sha256: string }
export type Bundle = { bundle_version: string; snapshot: string; source: ExtractionSource; reference: Reference; audit: Audit }
export type Candidate = { id: string; original: Quote; suggested_polarity: 'inclusion' | 'exclusion' | null; heading: Quote | null; context: Quote | null; warnings: string[] }
export type ExtractionProposal = { candidate_id?: string; criterion_id: string; status: string; proposal: { original_text: string; criterion_type: string; logical_operator: string | null; dependencies: unknown; [key: string]: unknown }; issues: { code: string; field: string | null }[] }
export type Workspace = { extraction_proposals?: ExtractionProposal[]; candidates?: Candidate[]; source: ExtractionSource; reference: Reference; slots: string[]; versions: Audit[]; snapshots: { snapshot: string; retrieved_at: string | null }[] }
export const unreviewed = (): Review => ({ status: 'unreviewed', reviewer: null, reviewed_at: null, note: null })
export const slots = ['polarity', 'threshold_operator', 'threshold_value', 'unit', 'temporal_constraint', 'cohort', 'biomarker', 'assay', 'logic', 'exceptions', 'unsupported_semantics']
export function criterion(id: string, original: Quote): Criterion {
  return { reference_id: id, original, boundary_review: unreviewed(), dependencies: [], ...Object.fromEntries(slots.map(slot => [slot, { value: null, evidence: [], review: unreviewed() }])) }
}
export function flatten(criteria: Criterion[]): Criterion[] { return criteria.flatMap(node => [node, ...flatten(node.dependencies)]) }
export function editCriterion(criteria: Criterion[], id: string, change: (node: Criterion) => Criterion): Criterion[] {
  return criteria.map(node => node.reference_id === id ? change(node) : { ...node, dependencies: editCriterion(node.dependencies, id, change) })
}
export function clearReviews(node: Criterion): Criterion {
  return { ...node, boundary_review: unreviewed(), dependencies: node.dependencies.map(clearReviews),
    ...Object.fromEntries(slots.map(slot => [slot, { ...node[slot] as Label, review: unreviewed() }])) }
}
export async function annotationApi<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(apiUrl(path), { signal, ...(body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) })
  let result
  try { result = await response.json() } catch { throw new Error('Backend returned an unreadable response. Check API routing and reload source.') }
  if (!response.ok) {
    const detail = result.detail
    throw new Error(typeof detail === 'string' ? (response.status === 404 && detail === 'Not Found' ? 'Annotation endpoint not found. Check the API base URL and restart the local backend, then reload source.' : detail) : Array.isArray(detail) ? detail.map(item => `${item.loc?.join('.') ?? 'Annotation'}: ${item.msg}`).join('; ') : `Annotation request failed (${response.status})`)
  }
  return result as T
}
export function captureSpan(pre: HTMLElement, selection: Selection | null, text: string): Quote | null {
  if (!selection?.rangeCount || selection.isCollapsed) return null
  const range = selection.getRangeAt(0)
  if (!pre.contains(range.startContainer) || !pre.contains(range.endContainer)) return null
  const prefix = range.cloneRange(); prefix.selectNodeContents(pre); prefix.setEnd(range.startContainer, range.startOffset)
  const start = Array.from(prefix.toString()).length
  const value = range.toString(), end = start + Array.from(value).length
  return Array.from(text).slice(start, end).join('') === value && value.length ? { span: { start, end }, text: value } : null
}
