import { useEffect, useRef } from 'react'
import { Button } from './ui'
import type { SourceSpan } from './extractionView'

export default function ProtocolSource({ text, highlight }: { text: string; highlight: SourceSpan | null }) {
  const container = useRef<HTMLPreElement>(null)
  const passage = useRef<HTMLElement>(null)
  const characters = Array.from(text)
  const headings = Array.from(text.matchAll(/^[ \t]*(?:#+[ \t]*)?(Inclusion|Exclusion)(?:[ \t]+Criteria)?[ \t]*:?[ \t]*$/gim), match => {
    const start = Array.from(text.slice(0, match.index)).length
    return { start, end: start + Array.from(match[0]).length, type: match[1].toLowerCase() }
  })
  const bulletStarts = Array.from(text.matchAll(/^[ \t]*(?:[-*\u2022]|\d+[.)])[ \t]+/gm), match => Array.from(text.slice(0, match.index)).length)
  const blockBoundaries = Array.from(new Set([0, characters.length, ...headings.map(heading => heading.start), ...bulletStarts])).sort((a, b) => a - b)
  function renderRange(start: number, end: number) {
    const boundaries = Array.from(new Set([start, end,
      ...headings.flatMap(heading => [heading.start, heading.end]).filter(position => start < position && position < end),
    ])).sort((a, b) => a - b)
    return boundaries.slice(0, -1).map((position, index) => {
      const boundary = boundaries[index + 1]
      const value = characters.slice(position, boundary).join('')
      const heading = headings.find(item => position >= item.start && boundary <= item.end)
      return heading ? <strong key={position} className={`source-section-heading section-${heading.type}`} data-section={heading.type} tabIndex={-1}>{value}</strong> : <span key={position}>{value}</span>
    })
  }

  useEffect(() => {
    if (highlight) passage.current?.scrollIntoView?.({ behavior: 'auto', block: 'center', inline: 'nearest' })
  }, [highlight])

  function jump(type: string) {
    const target = container.current?.querySelector<HTMLElement>(`[data-section="${type}"]`)
    target?.scrollIntoView?.({ behavior: 'auto', block: 'start', inline: 'nearest' })
    target?.focus({ preventScroll: true })
  }

  return <>
    <div className="source-jumps" aria-label="Source section navigation">
      {['inclusion', 'exclusion'].filter(type => headings.some(heading => heading.type === type)).map(type =>
        <Button variant="quiet" key={type} onClick={() => jump(type)}>Jump to {type}</Button>)}
      {!headings.length && <span>No recognized section headings; original text is unchanged.</span>}
    </div>
    <pre className="protocol-source" ref={container} tabIndex={0} aria-label="Exact original eligibility text">{blockBoundaries.slice(0, -1).map((start, index) => {
      const end = blockBoundaries[index + 1]
      const overlap = highlight && highlight.start < end && highlight.end > start
      const first = highlight && highlight.start >= start && highlight.start < end
      return <span className="source-reading-block" key={start}>{overlap ? <>
        {renderRange(start, Math.max(start, highlight.start))}
        <mark ref={first ? passage : undefined} aria-label={first ? 'Verified source passage' : 'Verified source passage continuation'}>{renderRange(Math.max(start, highlight.start), Math.min(end, highlight.end))}</mark>
        {renderRange(Math.min(end, highlight.end), end)}
      </> : renderRange(start, end)}</span>
    })}</pre>
  </>
}
