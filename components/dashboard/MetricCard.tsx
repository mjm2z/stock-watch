import type { LucideIcon } from 'lucide-react'

export function MetricCard({
  label,
  value,
  detail,
  icon: Icon,
}: {
  label: string
  value: string
  detail?: string
  icon: LucideIcon
}) {
  return (
    <div className="rounded-xl border bg-card p-3 sm:p-5 shadow-sm">
      <div className="mb-3 flex items-start justify-between gap-2">
        <span className="text-sm text-muted-foreground">{label}</span>
        <span className="hidden shrink-0 rounded-lg bg-muted p-2 sm:block">
          <Icon className="h-4 w-4" />
        </span>
      </div>
      <div className="text-xl font-semibold sm:text-2xl tracking-tight">{value}</div>
      {detail ? <p className="mt-1 text-xs text-muted-foreground">{detail}</p> : null}
    </div>
  )
}
