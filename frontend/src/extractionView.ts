import type { Trial } from './types'

export type ExtractionSource = {
  nct_id: string; text: string; source_url: string; source_snapshot: string
  retrieval_timestamp: string | null; sha256: string; is_synthetic: boolean | null
}
export type SourceSelection = {
  source: ExtractionSource; snapshots: Trial[]; warnings: string[]; mock_version: string
  configuration?: { ready: boolean; model: string; errors: string[] }
}
export type ExtractionReport = {
  source: ExtractionSource | null
  manifest: {
    status: string; prompt_version: string; requested_model: string | null
    returned_model: string | null; mode: string
    usage?: { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number } | null
    estimated_cost_usd?: number | null
  }
  mock_version: string; validated: unknown; candidate: unknown
  validation_errors: { code: string; criterion_id?: string | null; field?: string | null }[]
  unsupported_criteria: { criterion_id: string | null; reason: string }[]
  assessment_allowed: boolean; assessment_block_reason: string; output_directory: string
}
export type SourceSpan = { start: number; end: number }
export type CandidateNode = {
  key: string; id: string | null; text: string | null
  raw: Record<string, unknown>; children: CandidateNode[]
}

export function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function candidateView(value: unknown) {
  const issues: string[] = []
  function read(nodes: unknown[], parent = '', depth = 0): CandidateNode[] {
    if (depth > 32) { issues.push('Nested output exceeds display depth; inspect raw output.'); return [] }
    return nodes.flatMap((node, index) => {
      if (!isObject(node)) { issues.push('A candidate is not a criterion object.'); return [] }
      const key = parent ? `${parent}.${index}` : String(index)
      return [{ key, id: typeof node.criterion_id === 'string' ? node.criterion_id : null,
        text: typeof node.original_text === 'string' ? node.original_text : null, raw: node,
        children: Array.isArray(node.dependencies) ? read(node.dependencies, key, depth + 1) : [] }]
    })
  }
  const criteria = isObject(value) && Array.isArray(value.criteria) ? read(value.criteria) : []
  const evidence = isObject(value) && Array.isArray(value.evidence) ? value.evidence.filter(isObject) : []
  return { criteria, evidence, issues }
}

export function allCandidates(nodes: CandidateNode[]): CandidateNode[] {
  return nodes.flatMap(node => [node, ...allCandidates(node.children)])
}

export function sameSource(first: ExtractionSource | null, second: ExtractionSource) {
  return first !== null && first.nct_id === second.nct_id && first.sha256 === second.sha256
    && first.source_snapshot === second.source_snapshot && first.text === second.text
}

export function verifySourceSpan(node: CandidateNode, report: ExtractionReport, source: ExtractionSource): { span: SourceSpan | null; message: string } {
  if (!sameSource(report.source, source)) return { span: null, message: 'Source identity mismatch. No passage highlighted.' }
  const view = candidateView(report.candidate ?? report.validated)
  if (!node.id?.trim() || allCandidates(view.criteria).filter(item => item.id === node.id).length !== 1) {
    return { span: null, message: 'Criterion ID is missing or duplicated. No passage highlighted.' }
  }
  const entries = view.evidence.filter(entry => entry.criterion_id === node.id)
  if (entries.length !== 1 || !isObject(entries[0].original_span)) {
    return { span: null, message: 'A unique source span is unavailable. No passage highlighted.' }
  }
  const { start, end } = entries[0].original_span
  const characters = Array.from(source.text)
  if (typeof start !== 'number' || typeof end !== 'number' || !Number.isSafeInteger(start)
      || !Number.isSafeInteger(end) || start < 0 || start >= end || end > characters.length) {
    return { span: null, message: 'Source span is invalid or outside this snapshot. No passage highlighted.' }
  }
  if (!node.text || characters.slice(start, end).join('') !== node.text) {
    return { span: null, message: 'Source span does not reproduce the criterion text exactly. No passage highlighted.' }
  }
  return { span: { start, end }, message: `Exact source quote verified at characters ${start}\u2013${end} (end exclusive). This does not validate its clinical meaning.` }
}

export function schemaStatus(report: ExtractionReport) {
  if (report.manifest.status === 'validated' && report.validated !== null && report.validation_errors.length === 0) return 'Passed'
  if (report.manifest.status !== 'validation_failed') return 'Not confirmed'
  if (report.validation_errors.some(error => ['schema_error', 'invalid_json_or_schema'].includes(error.code))) return 'Failed'
  return report.validation_errors.length ? 'Accepted structure' : 'Not confirmed'
}
