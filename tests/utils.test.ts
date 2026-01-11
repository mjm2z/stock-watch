import {
  cn,
  formatCurrency,
  formatPercent,
  formatLargeNumber,
  formatVolume,
} from '@/lib/utils'

describe('cn (className merge)', () => {
  it('should merge class names', () => {
    expect(cn('foo', 'bar')).toBe('foo bar')
  })

  it('should handle conditional classes', () => {
    expect(cn('foo', false && 'bar', 'baz')).toBe('foo baz')
  })

  it('should merge Tailwind classes correctly', () => {
    expect(cn('px-2 py-1', 'px-4')).toBe('py-1 px-4')
  })
})

describe('formatCurrency', () => {
  it('should format numbers as USD currency', () => {
    expect(formatCurrency(1234.56)).toBe('$1,234.56')
  })

  it('should handle zero', () => {
    expect(formatCurrency(0)).toBe('$0.00')
  })

  it('should handle negative numbers', () => {
    expect(formatCurrency(-100)).toBe('-$100.00')
  })
})

describe('formatPercent', () => {
  it('should format positive percentages with + sign', () => {
    expect(formatPercent(5.25)).toBe('+5.25%')
  })

  it('should format negative percentages', () => {
    expect(formatPercent(-3.5)).toBe('-3.50%')
  })

  it('should handle zero', () => {
    expect(formatPercent(0)).toBe('+0.00%')
  })

  it('should respect decimal parameter', () => {
    expect(formatPercent(5.2567, 1)).toBe('+5.3%')
  })
})

describe('formatLargeNumber', () => {
  it('should format trillions', () => {
    expect(formatLargeNumber(2_500_000_000_000)).toBe('$2.50T')
  })

  it('should format billions', () => {
    expect(formatLargeNumber(150_000_000_000)).toBe('$150.00B')
  })

  it('should format millions', () => {
    expect(formatLargeNumber(50_000_000)).toBe('$50.00M')
  })

  it('should format smaller numbers as currency', () => {
    expect(formatLargeNumber(50_000)).toBe('$50,000.00')
  })
})

describe('formatVolume', () => {
  it('should format billions', () => {
    expect(formatVolume(1_500_000_000)).toBe('1.50B')
  })

  it('should format millions', () => {
    expect(formatVolume(15_000_000)).toBe('15.00M')
  })

  it('should format thousands', () => {
    expect(formatVolume(500_000)).toBe('500.00K')
  })

  it('should return raw number for small values', () => {
    expect(formatVolume(999)).toBe('999')
  })
})
