export async function navigate(page, name) {
  const secondary = ['Research Tools', 'Explore Trials'].includes(name)
  const nav = page.getByRole('navigation', { name: 'Main navigation' })
  if (!await nav.isVisible()) await page.getByRole('button', { name: 'Open navigation' }).click()
  await nav.getByRole('button', { name: secondary ? 'Research Results' : name === 'Try a Demo' ? 'Evidence Review' : name, exact: true }).click()
  if (name === 'Try a Demo') await page.getByRole('button', { name: 'Try a Demo', exact: true }).click()
  if (secondary) {
    await page.getByText('Explore sources and research tools', { exact: true }).click()
    await page.getByRole('button', { name: name === 'Explore Trials' ? 'Browse saved trials' : name, exact: true }).click()
  }
}
