import 'server-only'
export async function macroContext(health = false) {
  try {
    const response = await fetch('http://127.0.0.1:9034' + (health ? '/health' : '/v1/context'), {
      cache: 'no-store',
      signal: AbortSignal.timeout(3000),
    })
    const reader = response.body?.getReader()
    if (!reader) throw Error('Missing body')
    let length = 0
    const chunks: Uint8Array[] = []
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      length += value.length
      if (length > 2 * 1024 * 1024) {
        await reader.cancel()
        throw Error('Oversized body')
      }
      chunks.push(value)
    }
    const result = JSON.parse(Buffer.concat(chunks).toString('utf8'))
    if (
      typeof result.configured !== 'boolean' ||
      typeof result.healthy !== 'boolean' ||
      (!health && !Array.isArray(result.series))
    )
      throw Error('Invalid context')
    return result
  } catch {
    return {
      configured: false,
      healthy: false,
      status: 'service_unavailable',
      stale: false,
      updated_at: null,
      series: [],
    }
  }
}
