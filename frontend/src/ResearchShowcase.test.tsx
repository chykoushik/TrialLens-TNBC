import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import ResearchShowcase from './ResearchShowcase'

test('showcase distinguishes source-aligned entries from unreviewed failed output', () => {
  render(<ResearchShowcase />)
  expect(screen.getByRole('region')).toHaveAccessibleName('An AI proposal must earn its evidence link.')
  expect(screen.getByText('5 / 24')).toBeVisible()
  expect(screen.getByText('19')).toBeVisible()
  expect(screen.getByText('39')).toBeVisible()
  expect(screen.getByText('Full extraction: validation_failed.')).toBeVisible()
  expect(screen.getByText(/not clinical accuracy or human-reviewed ground truth/)).toBeVisible()
  expect(screen.getByRole('link', { name: /ClinicalTrials.gov/ })).toHaveAttribute('href', 'https://clinicaltrials.gov/study/NCT01770353')
})
