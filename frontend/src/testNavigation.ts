import { fireEvent, screen, within } from '@testing-library/react'

export function openResearchSection(name = 'Research Tools') {
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Research Results' }))
  fireEvent.click(screen.getByText('Explore sources and research tools', { selector: 'summary' }))
  fireEvent.click(screen.getByRole('button', { name }))
}

export function openDemo() {
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Evidence Review' }))
  fireEvent.click(screen.getByRole('button', { name: 'Try a Demo' }))
}
