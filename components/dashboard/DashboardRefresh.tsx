'use client'
import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
export function DashboardRefresh() {
  const router = useRouter()
  const [pending, setPending] = useState(false)
  useEffect(() => {
    const timer = setInterval(() => {
      if (!document.hidden) router.refresh()
    }, 60000)
    return () => clearInterval(timer)
  }, [router])
  return (
    <button
      className="min-h-11 text-sm underline"
      disabled={pending}
      onClick={() => {
        setPending(true)
        router.refresh()
        setTimeout(() => setPending(false), 1500)
      }}
    >
      {pending ? 'Refreshing…' : 'Refresh saved results'}
    </button>
  )
}
