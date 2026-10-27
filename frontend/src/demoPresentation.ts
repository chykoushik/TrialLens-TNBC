import type { Assessed, Evaluation, Review } from './types'

export const stateText = { satisfied: 'Clause met', violated: 'Clause not met', unknown: 'Missing information', temporal: 'Timing unclear', conflict: 'Conflicting records' }
export function allNodes(data: Evaluation): Assessed[] {
  const visit = (nodes: Assessed[]): Assessed[] => nodes.flatMap(node => [node, ...visit(node.dependencies)])
  return data.assessment.decisions.flatMap(decision => visit(decision.assessment.assessments))
}
export const unclearChecks = (data: Evaluation) => data.assessment.decisions.flatMap(item => item.assessment.assessments).filter(node => ['unknown', 'temporal', 'conflict'].includes(node.state))
export function outcomeText(outcome: Review['outcomes'][number], data: Evaluation) {
  if (outcome.additions?.length) return outcome.additions.map(item => `${data.display_labels?.[item.clinical_attribute] ?? item.clinical_attribute}: ${item.value?.replaceAll('_', ' ') ?? 'not recorded'}${item.units ? ` ${item.units}` : ''}`).join(' · ')
  return outcome.description.replace(/^FICTIONAL existing record review:\s*/i, '').replaceAll('-', ' ').replaceAll('_', ' ')
}
