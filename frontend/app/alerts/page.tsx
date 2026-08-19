import ClaimCareApp from '@/components/claimcare-app'
import { Suspense } from 'react'

export default function AlertsPage() {
  return (
    <Suspense fallback={null}>
      <ClaimCareApp />
    </Suspense>
  )
}
