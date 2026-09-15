import { Link } from "react-router-dom" // upload CTA when GET /matches is 404

import type { MatchOut } from "@/api/types" // GET /matches chips
import { SkillChipList } from "@/components/dashboard/skill-chips" // matched vs missing
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card" // chrome

// Candidate skill-gap from GET /matches — do not invent a second matcher in the browser.
export function SkillGapCard({
  noParsedResume,
  matches,
}: {
  noParsedResume: boolean // 404 from GET /matches
  matches: MatchOut[] | undefined // ranked postings
}) {
  const missing = [...new Set((matches ?? []).flatMap((match) => match.missing_skills))] // unique gaps
  const matched = [...new Set((matches ?? []).flatMap((match) => match.matched_skills))] // unique hits
  return (
    <Card data-testid="candidate-skill-gap">
      <CardHeader>
        <CardTitle>Skill gap</CardTitle>
        <CardDescription>From GET /matches against your latest parsed resume. Same chips as Matches.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {noParsedResume ? (
          <p className="text-sm text-muted-foreground">
            No parsed resume yet.{" "}
            <Link className="font-medium underline underline-offset-4" to="/candidate/resume">
              Upload a PDF
            </Link>{" "}
            so skill-gap chips can load.
          </p>
        ) : null}
        {!noParsedResume && matches !== undefined && matches.length === 0 ? (
          <p className="text-sm text-muted-foreground">No active embedded postings to compare against yet.</p>
        ) : null}
        {!noParsedResume && matched.length > 0 ? (
          <div className="flex flex-col gap-1">
            <p className="text-xs text-muted-foreground">You have</p>
            <SkillChipList skills={matched} variant="matched" />
          </div>
        ) : null}
        {!noParsedResume && missing.length > 0 ? (
          <div className="flex flex-col gap-1">
            <p className="text-xs text-muted-foreground">Skill gap</p>
            <SkillChipList skills={missing} variant="missing" />
          </div>
        ) : null}
        {!noParsedResume && matches !== undefined && matches.length > 0 && matched.length === 0 && missing.length === 0 ? (
          <p className="text-sm text-muted-foreground">Active postings listed no required skills.</p>
        ) : null}
      </CardContent>
    </Card>
  )
}
