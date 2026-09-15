import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card" // chrome
import type { Recommendation } from "@/lib/dashboard" // derived facts, not an LLM essay

// Candidate recommendations: ATS / skill-gap / omitted communication / last composite only.
export function RecommendationsCard({ items }: { items: Recommendation[] }) {
  return (
    <Card data-testid="candidate-recommendations">
      <CardHeader>
        <CardTitle>Recommendations</CardTitle>
        <CardDescription>Derived from stored scores and match chips. No extra LLM call.</CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="flex list-disc flex-col gap-2 pl-5 text-sm">
          {items.map((item) => (
            <li key={item.id}>{item.text}</li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}
