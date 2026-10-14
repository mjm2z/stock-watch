jest.mock('next/server', () => ({
  NextResponse: {
    json: (body: unknown, init?: { status: number }) => ({ body, status: init?.status || 200 }),
  },
}))
jest.mock('@/lib/systems-auth', () => ({
  authenticated: jest.fn(),
  sameOrigin: jest.fn(),
  boundedBody: jest.fn(),
}))
jest.mock('@/lib/experiment-store', () => ({
  experimentCommand: jest.fn(),
  ExperimentInputError: class extends Error {},
}))
import type { NextRequest } from 'next/server'
import { authenticated, sameOrigin, boundedBody } from '@/lib/systems-auth'
import { experimentCommand } from '@/lib/experiment-store'
import { POST } from '@/app/api/systems/experiments/route'
test('execution mutations require both operator session and same origin', async () => {
  const request = {} as NextRequest
  ;(sameOrigin as jest.Mock).mockReturnValue(true)
  ;(authenticated as jest.Mock).mockReturnValue(false)
  expect((await POST(request)).status).toBe(403)
  expect(experimentCommand).not.toHaveBeenCalled()
  ;(sameOrigin as jest.Mock).mockReturnValue(false)
  ;(authenticated as jest.Mock).mockReturnValue(true)
  expect((await POST(request)).status).toBe(403)
  ;(sameOrigin as jest.Mock).mockReturnValue(true)
  ;(boundedBody as jest.Mock).mockResolvedValue({ action: 'preview' })
  ;(experimentCommand as jest.Mock).mockReturnValue({ status: 'queued' })
  expect((await POST(request)).status).toBe(202)
})
