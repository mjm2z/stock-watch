import { cn } from '@/lib/utils'

const statusStyles: Record<string, string> = {
  succeeded: 'bg-emerald-500/10 text-emerald-700 border-emerald-500/20',
  qualified: 'bg-emerald-500/10 text-emerald-700 border-emerald-500/20',
  filled: 'bg-emerald-500/10 text-emerald-700 border-emerald-500/20',
  matched: 'bg-emerald-500/10 text-emerald-700 border-emerald-500/20',
  open: 'bg-blue-500/10 text-blue-700 border-blue-500/20',
  running: 'bg-blue-500/10 text-blue-700 border-blue-500/20',
  accepted: 'bg-blue-500/10 text-blue-700 border-blue-500/20',
  queued: 'bg-amber-500/10 text-amber-700 border-amber-500/20',
  pending: 'bg-amber-500/10 text-amber-700 border-amber-500/20',
  partial: 'bg-amber-500/10 text-amber-700 border-amber-500/20',
  drift: 'bg-red-500/10 text-red-700 border-red-500/20',
  blocked: 'bg-red-500/10 text-red-700 border-red-500/20',
  failed: 'bg-red-500/10 text-red-700 border-red-500/20',
  rejected: 'bg-red-500/10 text-red-700 border-red-500/20',
  error: 'bg-red-500/10 text-red-700 border-red-500/20',
  development: 'bg-violet-500/10 text-violet-700 border-violet-500/20',
  paper: 'bg-sky-500/10 text-sky-700 border-sky-500/20',
  reportable: 'bg-emerald-500/10 text-emerald-700 border-emerald-500/20',
  underpowered: 'bg-amber-500/10 text-amber-700 border-amber-500/20',
  no_observations: 'bg-muted text-muted-foreground',
}

export function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={cn(
        'inline-flex rounded-full border px-2 py-0.5 text-xs font-medium capitalize',
        statusStyles[status] ?? 'bg-muted text-muted-foreground'
      )}
    >
      {status.replaceAll('_', ' ')}
    </span>
  )
}
