import ClaimCareApp from '@/components/claimcare-app'
import { Suspense } from 'react'

export default function ProviderDetailPage() {
  return (
    <Suspense fallback={null}>
      <ClaimCareApp />
    </Suspense>
  )
}
