// Screenshots of every screen at 390x844 into docs/screenshots/.
//
//   cd backend && rm -f data/dev.db && DEV_AUTH=1 DEV_FAKE_PROVIDERS=1 OWNER_ID=1 .venv/bin/python scripts/demo_seed.py
//   DEV_AUTH=1 DEV_FAKE_PROVIDERS=1 OWNER_ID=1 .venv/bin/uvicorn app.main:app --port 8000   # serves frontend/dist
//   node scripts/screenshots.cjs            # BASE=http://localhost:8000 by default
const path = require('path')
const { chromium } = require('playwright')

const BASE = process.env.BASE || 'http://localhost:8000'
const OUT = path.join(__dirname, '..', 'docs', 'screenshots')

;(async () => {
  const browser = await chromium.launch()
  const shots = []
  const page = async (dev) => {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, locale: 'ru-RU' })
    const p = await ctx.newPage()
    p.on('pageerror', (e) => console.error('page error:', e.message))
    p.on('dialog', (d) => d.accept())
    await p.goto(`${BASE}/?dev=${dev}`)
    await p.waitForSelector('nav, form, h1')
    await p.waitForTimeout(700)
    return p
  }
  const snap = async (p, name, scroll = 0) => {
    await p.evaluate((y) => document.querySelector('main')?.scrollTo(0, y), scroll)
    await p.waitForTimeout(scroll ? 400 : 900)
    await p.screenshot({ path: path.join(OUT, `${name}.png`) })
    shots.push(name)
  }
  const tab = async (p, name) => {
    await p.getByRole('button', { name: new RegExp(name) }).last().click()
    await p.waitForTimeout(600)
  }
  const back = async (p) => {
    await p.getByRole('button', { name: 'Назад' }).first().click()
    await p.waitForTimeout(500)
  }
  const openCard = async (p, text) => {
    await p.locator('main button').filter({ hasText: text }).first().click()
    await p.waitForTimeout(900)
  }

  // a stranger without an invite
  let p = await page(5)
  await snap(p, '01-invite')
  await p.context().close()

  // the owner
  p = await page(1)
  await snap(p, '02-characters')
  await openCard(p, 'Don Whiskers')
  await snap(p, '08-character')
  await snap(p, '09-character-settings', 700)
  await back(p)
  await p.getByRole('button', { name: 'Новый персонаж' }).click()
  await p.waitForTimeout(500)
  await p.getByPlaceholder('кот-мафиози из Нью-Йорка 50-х').fill('кот-мафиози из Нью-Йорка 50-х')
  await p.getByRole('button', { name: 'Заполнить с Claude' }).click()
  await p.waitForTimeout(1200)
  await snap(p, '03-wizard-card', 230)
  await back(p)
  await tab(p, 'Черновики')
  await snap(p, '10-drafts')
  await openCard(p, 'Don Whiskers')
  await snap(p, '11-draft-preview')
  await snap(p, '12-draft-edit', 760)
  await back(p)
  await openCard(p, 'Нужна проверка')
  await snap(p, '13-draft-qa', 560)
  await back(p)
  await tab(p, 'Календарь')
  await snap(p, '14-calendar')
  await tab(p, 'Дашборд')
  await snap(p, '15-dashboard')
  await snap(p, '16-dashboard-charts', 620)
  await tab(p, 'Профиль')
  await snap(p, '17-profile')
  await p.getByRole('button', { name: /Свои ключи API/ }).click()
  await p.waitForTimeout(500)
  await snap(p, '18-keys')
  await back(p)
  await p.getByRole('button', { name: /Админка/ }).click()
  await p.waitForTimeout(900)
  await snap(p, '19-admin')
  await snap(p, '20-admin-characters', 900)
  await p.context().close()

  // a friend on an invite, with cats at every wizard step
  p = await page(2)
  await snap(p, '21-friend-characters')
  for (const [name, file] of [['Biscuit', '04-wizard-candidates'], ['Mochi', '05-wizard-refs'], ['Pixel', '06-wizard-training'], ['Nori', '07-wizard-testing']]) {
    await openCard(p, name)
    await p.waitForTimeout(600)
    await snap(p, file)
    await back(p)
  }
  await p.context().close()
  await browser.close()
  console.log(`${shots.length} screenshots in ${OUT}`)
})()
