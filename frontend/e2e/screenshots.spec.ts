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
    await page.getByText(/Raw event|No activity yet/).first().waitFor()
    await page.screenshot({ path: `e2e-shots/activity-${width}.png`, fullPage: true })
    await page.click('text=Memos')
    await page.waitForSelector('text=What Ellis will ask next')
    await page.screenshot({ path: `e2e-shots/memos-${width}.png`, fullPage: true })
    await page.request.post('/api/auth/logout')
  }
})
