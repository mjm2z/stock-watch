import 'server-only'
import { createHmac, timingSafeEqual } from 'node:crypto'
import { NextRequest } from 'next/server'
const cookieName = 'stockwatch_operator'
export { cookieName }
function equal(a: string, b: string) {
  const x = Buffer.from(a)
  const y = Buffer.from(b)
  return x.length === y.length && timingSafeEqual(x, y)
}
export function sameOrigin(request: NextRequest) {
  try {
    return new URL(request.headers.get('origin') || '').host === request.headers.get('host')
  } catch {
    return false
  }
}
export function login(token: unknown) {
  const secret = process.env.SYSTEMS_OPERATOR_TOKEN
  if (!secret || secret.length < 32 || typeof token !== 'string' || !equal(token, secret))
    return null
  const expires = String(Date.now() + 60 * 60 * 1000)
  return expires + '.' + createHmac('sha256', secret).update(expires).digest('hex')
}
export function authenticated(request: NextRequest) {
  const secret = process.env.SYSTEMS_OPERATOR_TOKEN
  const cookie = request.cookies.get(cookieName)?.value || ''
  const [expires, signature] = cookie.split('.')
  return Boolean(
    secret &&
    secret.length >= 32 &&
    Number(expires) > Date.now() &&
    signature &&
    equal(signature, createHmac('sha256', secret).update(expires).digest('hex'))
  )
}
export async function boundedBody(request: NextRequest): Promise<Record<string, unknown>> {
  if (!request.headers.get('content-type')?.startsWith('application/json'))
    throw new Error('JSON required.')
  const reader = request.body?.getReader()
  if (!reader) throw new Error('Body required.')
  const chunks: Uint8Array[] = []
  let size = 0
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    size += value.length
    if (size > 12000) {
      await reader.cancel()
      throw new Error('Request exceeds 12 KB.')
    }
    chunks.push(value)
  }
  const result = JSON.parse(Buffer.concat(chunks).toString('utf8'))
  if (!result || typeof result !== 'object' || Array.isArray(result))
    throw new Error('Object required.')
  return result
}
