import type { AtsBreakdown, ResumeOut } from "@/api/types" // GET /resumes/{id} + pipeline JSON
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card" // results chrome
import { asParsedResumeData } from "@/lib/parsed-resume" // defensive parse of parsed_data

// One ATS signal row: label, points, and a bar scaled to `max`.
function BreakdownRow({ label, points, max }: { label: string; points: number; max: number }) {
  const width = max > 0 ? Math.min(100, Math.round((points / max) * 100)) : 0 // 0–100% of the row
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-medium tabular-nums">{points.toFixed(1)}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-primary" style={{ width: `${width}%` }} />
      </div>
    </div>
  )
}

// ATS score card: total 0–100 plus the four explainable signals.
function AtsScoreCard({ score, breakdown }: { score: number | null; breakdown: AtsBreakdown }) {
  const display = score ?? breakdown.total // prefer the column; fall back to the breakdown total
  return (
    <Card>
      <CardHeader>
        <CardTitle>ATS score</CardTitle>
        <CardDescription>Deterministic checklist, not a learned model. Higher is better (0–100).</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <p className="text-4xl font-semibold tabular-nums">{display.toFixed(1)}</p>
        <div className="flex flex-col gap-3">
          <BreakdownRow label="Sections" points={breakdown.section_points} max={60} />
          <BreakdownRow label="Contact" points={breakdown.contact_points} max={10} />
          <BreakdownRow label="Skills" points={breakdown.skill_points} max={20} />
          <BreakdownRow label="Length" points={breakdown.length_points} max={10} />
        </div>
      </CardContent>
    </Card>
  )
}

// Skill chips; empty list gets an explicit empty state instead of a blank card.
function SkillChips({ skills }: { skills: string[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Extracted skills</CardTitle>
        <CardDescription>ESCO PhraseMatcher hits against the in-repo sample taxonomy.</CardDescription>
      </CardHeader>
      <CardContent>
        {skills.length === 0 ? (
          <p className="text-sm text-muted-foreground">No skills matched the sample ESCO list.</p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            {skills.map((skill) => (
              <li
                key={skill}
                className="rounded-full border border-border bg-muted px-2.5 py-0.5 text-xs font-medium"
              >
                {skill}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

// Parsed section bodies; empty dict gets an explicit empty state.
function SectionList({ sections }: { sections: Record<string, string> }) {
  const entries = Object.entries(sections) // stable enough for a small dict
  return (
    <Card>
      <CardHeader>
        <CardTitle>Sections</CardTitle>
        <CardDescription>Header-line splits from the extracted PDF text.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {entries.length === 0 ? (
          <p className="text-sm text-muted-foreground">No sections were detected in this PDF.</p>
        ) : (
          entries.map(([name, body]) => (
            <section key={name} className="flex flex-col gap-1">
              <h3 className="text-sm font-medium capitalize">{name.replaceAll("_", " ")}</h3>
              <p className="whitespace-pre-wrap text-sm text-muted-foreground">{body.trim() || "—"}</p>
            </section>
          ))
        )}
      </CardContent>
    </Card>
  )
}

// Parsed-results stack: ATS card, skill chips, sections, plus failed/empty handling.
export function ResumeResults({ resume }: { resume: ResumeOut }) {
  if (resume.status === "failed") {
    return (
      <p className="text-sm text-destructive" role="alert">
        Parsing failed for {resume.original_filename}. Try a text-based PDF (not a scanned image).
      </p>
    )
  }
  if (resume.status !== "parsed") {
    return (
      <p className="text-sm text-muted-foreground">
        Resume status is {resume.status}. Results appear once parsing succeeds.
      </p>
    )
  }
  const parsed = asParsedResumeData(resume.parsed_data) // null if the worker wrote a surprising shape
  if (parsed === null) {
    return (
      <p className="text-sm text-muted-foreground" role="status">
        Parsed, but no structured data was stored for {resume.original_filename}.
      </p>
    )
  }
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h2 className="text-lg font-semibold">{resume.original_filename}</h2>
        <p className="text-xs text-muted-foreground">
          {parsed.extractor_used}
          {parsed.email ? ` · ${parsed.email}` : ""}
          {parsed.phone ? ` · ${parsed.phone}` : ""}
          {` · ${parsed.word_count} words`}
        </p>
      </div>
      <AtsScoreCard score={resume.ats_score} breakdown={parsed.ats_breakdown} />
      <SkillChips skills={parsed.skills} />
      <SectionList sections={parsed.sections} />
    </div>
  )
}
