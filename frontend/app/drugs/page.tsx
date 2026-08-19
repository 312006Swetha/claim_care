import ClaimCareApp from '@/components/claimcare-app'
import { Suspense } from 'react'

export default function DrugsPage() {
  return (
    <Suspense fallback={null}>
      <ClaimCareApp />
    </Suspense>
  )
}
