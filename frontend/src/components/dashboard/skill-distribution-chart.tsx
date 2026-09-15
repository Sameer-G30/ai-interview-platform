import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts" // plan Part 3

import { SkillChipList } from "@/components/dashboard/skill-chips" // posting required_skills chips
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card" // chrome
import { splitRequiredSkills } from "@/lib/dashboard" // comma/newline split; not MiniLM

// Recruiter skill chart from posting.required_skills. Candidate chips live on GET /matches, not ranking rows.
export function SkillDistributionChart({ requiredSkills }: { requiredSkills: string | null | undefined }) {
  const skills = splitRequiredSkills(requiredSkills) // de-duped tokens
  const data = skills.map((skill) => ({ skill, listed: 1 })) // each required skill counts once on this posting
  return (
    <Card data-testid="recruiter-skill-chart">
      <CardHeader>
        <CardTitle>Required skills</CardTitle>
        <CardDescription>
          Tokens from this posting’s required_skills field. Ranking rows do not include resume chips — no MiniLM in the
          browser.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {skills.length === 0 ? (
          <p className="text-sm text-muted-foreground">This posting listed no required skills.</p>
        ) : (
          <>
            <SkillChipList skills={skills} variant="required" />
            <div className="h-56 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data} layout="vertical" margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis type="number" domain={[0, 1]} hide />
                  <YAxis type="category" dataKey="skill" width={96} tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Bar dataKey="listed" name="Listed on posting" fill="var(--chart-2)" isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}
