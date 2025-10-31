import { test, expect } from '@playwright/test'

test('globe responds to user rotation', async ({ page }) => {
  await page.goto('/', { waitUntil: 'networkidle' })
  const canvas = page.locator('canvas')
  await canvas.waitFor()
  await page.waitForTimeout(1500)

  const initial = (await page.waitForFunction(() => {
    const ref = (window as any).__BEACON_GLOBE__
    return ref?.getState?.() ?? null
  }).then((handle) => handle.jsonValue())) as {
    target: number[]
    position: number[]
    azimuthalAngle: number | null
    polarAngle: number | null
    quaternion: number[]
  }

  const box = await canvas.boundingBox()
  if (!box) throw new Error('Globe canvas has no bounding box')

  const deltaX = Math.min(box.width * 0.4, 220)
  const deltaY = Math.min(box.height * 0.3, 100)

  await canvas.dragTo(canvas, {
    sourcePosition: { x: box.width / 2, y: box.height / 2 },
    targetPosition: { x: box.width / 2 + deltaX, y: box.height / 2 - deltaY },
    force: true
  })
  await page.waitForTimeout(1400)

  const final = (await page.evaluate(() => {
    const ref = (window as any).__BEACON_GLOBE__
    return ref?.getState?.() ?? null
  })) as typeof initial | null

  expect(final).not.toBeNull()
  expect(final!.target).toEqual(initial.target)

  const positionDelta = final!.position.map((value, index) => Math.abs(value - initial.position[index]))
  expect(positionDelta.some((delta) => delta > 0.015)).toBeTruthy()

  const [iq0, iq1, iq2, iq3] = initial.quaternion
  const [fq0, fq1, fq2, fq3] = final!.quaternion
  const dot = Math.min(1, Math.max(-1, iq0 * fq0 + iq1 * fq1 + iq2 * fq2 + iq3 * fq3))
  const angle = 2 * Math.acos(Math.abs(dot))
  expect(angle).toBeGreaterThan(0.08)
})
