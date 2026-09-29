import { groupChartEvents } from '@/lib/chart-events'
test('clusters at available chart bars while retaining exact timestamps and deduplicating IDs', () => {
  const event = { id: 'a', at: '2026-01-01T00:00:30Z', label: 'fill', evidence: { broker: 'one' } }
  const start = Date.parse('2026-01-01T00:00:00Z') / 1000
  const groups = groupChartEvents(
    [start, start + 60],
    [
      event,
      event,
      { ...event, id: 'b', at: '2026-01-01T00:00:40Z' },
      { ...event, id: 'old', at: '2025-12-01T00:00:00Z' },
    ]
  )
  expect(groups.size).toBe(1)
  expect(groups.get(start)).toHaveLength(2)
  expect(groups.get(start)?.[0].at).toBe(event.at)
})
