import { test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

const widths = [390, 1280]

async function login(page: import('@playwright/test').Page, email: string) {
  await page.goto('/signin')
  await page.fill('#em', email)
  await page.fill('#pw', 'ellis-demo')
  await page.click('button[type=submit]')
}

test('phase 1 screens', async ({ page }) => {
  for (const width of widths) {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/')
    await page.waitForSelector('text=Have these ready')
    await page.screenshot({ path: `e2e-shots/guest-${width}.png`, fullPage: true })
  }

  const axe = await new AxeBuilder({ page }).analyze()
  console.log('axe violations', axe.violations.length)

  for (const width of widths) {
    await page.setViewportSize({ width, height: 900 })
    await login(page, 'maria@valle.demo')
    await page.getByRole('button', { name: /I agree|Estoy de acuerdo/ }).waitFor()
    await page.screenshot({ path: `e2e-shots/consent-${width}.png`, fullPage: true })
    await page.goto('/signin')
    await page.request.post('/api/auth/logout')
  }

  for (const width of widths) {
    await page.setViewportSize({ width, height: 900 })
    await login(page, 'jorge@valle.demo')
    await page.getByRole('button', { name: /Start talking|Empezar a hablar/ }).waitFor()
    await page.screenshot({ path: `e2e-shots/chat-${width}.png`, fullPage: true })
    await page.request.post('/api/auth/logout')
  }

  for (const width of widths) {
    await page.setViewportSize({ width, height: 900 })
    await login(page, 'dana@valle.demo')
    await page.waitForSelector('text=Cases')
    await page.screenshot({ path: `e2e-shots/cases-${width}.png`, fullPage: true })
    await page.click('text=María T.')
    await page.waitForSelector('text=Ready gate')
    await page.getByRole('tab', { name: 'Activity' }).click()
    await page.getByText(/No activity|Clinic staff/).first().waitFor({ timeout: 5000 }).catch(() => {})
    await page.screenshot({ path: `e2e-shots/activity-${width}.png`, fullPage: true })
    await page.click('text=Memos')
    await page.waitForSelector('text=What Ellis will ask next')
    await page.screenshot({ path: `e2e-shots/memos-${width}.png`, fullPage: true })
    await page.request.post('/api/auth/logout')
  }
})

test('phase 2-3 screens', async ({ page }) => {
  // Applicant pages with demo-jorge (has consent and data)
  for (const width of widths) {
    await page.setViewportSize({ width, height: 900 })
    await login(page, 'jorge@valle.demo')
    await page.getByRole('button', { name: /Start talking|Empezar a hablar/ }).waitFor()

    // Form page
    await page.goto('/form')
    await page.waitForSelector('text=parts done')
    await page.screenshot({ path: `e2e-shots/form-${width}.png`, fullPage: true })
    // Form all-parts view
    await page.getByRole('button', { name: 'See all parts' }).click()
    await page.waitForSelector('text=Answer')
    await page.screenshot({ path: `e2e-shots/form-allparts-${width}.png`, fullPage: true })

    // Interview page
    await page.goto('/interview')
    await page.waitForSelector('text=Interview prep')
    await page.screenshot({ path: `e2e-shots/interview-${width}.png`, fullPage: true })

    // Reminders page
    await page.goto('/reminders')
    await page.waitForSelector('text=Reminders')
    await page.screenshot({ path: `e2e-shots/reminders-${width}.png`, fullPage: true })

    // Profile page
    await page.goto('/profile')
    await page.waitForSelector('text=Profile')
    await page.screenshot({ path: `e2e-shots/profile-${width}.png`, fullPage: true })

    await page.request.post('/api/auth/logout')
  }

  // Reviewer pages
  for (const width of widths) {
    await page.setViewportSize({ width, height: 900 })
    await login(page, 'dana@valle.demo')
    await page.waitForSelector('text=Cases')
    await page.screenshot({ path: `e2e-shots/cases-${width}.png`, fullPage: true })

    await page.click('text=María T.')
    await page.waitForSelector('text=Ready gate')

    // Facts tab
    await page.screenshot({ path: `e2e-shots/case-facts-${width}.png`, fullPage: true })

    // Documents tab
    await page.getByRole('tab', { name: 'Documents' }).click()
    await page.waitForSelector('text=Expected documents')
    await page.screenshot({ path: `e2e-shots/case-docs-${width}.png`, fullPage: true })

    // Review tab
    await page.getByRole('tab', { name: 'Review' }).click()
    await page.waitForSelector('text=Open review queue')
    await page.screenshot({ path: `e2e-shots/case-review-${width}.png`, fullPage: true })

    // Activity tab
    await page.getByRole('tab', { name: 'Activity' }).click()
    await page.waitForSelector('text=Filter:')
    await page.screenshot({ path: `e2e-shots/case-activity-${width}.png`, fullPage: true })

    // Memos tab
    await page.getByRole('tab', { name: 'Memos' }).click()
    await page.waitForSelector('text=AI staff task board')
    await page.screenshot({ path: `e2e-shots/case-memos-${width}.png`, fullPage: true })

    // Transcript tab
    await page.getByRole('tab', { name: 'Transcript' }).click()
    await page.waitForSelector('text=Ellis', { timeout: 3000 }).catch(() => {})
    await page.screenshot({ path: `e2e-shots/case-transcript-${width}.png`, fullPage: true })

    await page.request.post('/api/auth/logout')
  }

  // Run axe on the case detail page
  await login(page, 'dana@valle.demo')
  await page.waitForSelector('text=Cases')
  await page.click('text=María T.')
  await page.waitForSelector('text=Ready gate')
  const axeCase = await new AxeBuilder({ page }).analyze()
  console.log('axe violations (case detail):', axeCase.violations.length)
  if (axeCase.violations.length > 0) {
    console.log(axeCase.violations.map((v) => `${v.id}: ${v.description}`).join('\n'))
  }
})
