// Skill chip row shared by candidate skill-gap and recruiter required-skills (no MiniLM in the browser).

// Positive chips are skills the resume already has; missing chips are the gap from GET /matches.
export function SkillChipList({ skills, variant }: { skills: string[]; variant: "matched" | "missing" | "required" }) {
  if (skills.length === 0) {
    return null // caller renders empty copy instead
  }
  const chipClass =
    variant === "matched"
      ? "border-primary/30 bg-primary/10 text-primary" // already on the resume
      : variant === "missing"
        ? "border-destructive/30 bg-destructive/10 text-destructive" // skill gap
        : "border-border bg-muted text-muted-foreground" // posting required_skills
  return (
    <ul className="flex flex-wrap gap-1.5">
      {skills.map((skill) => (
        <li key={skill} className={`rounded-full border px-2 py-0.5 text-xs font-medium ${chipClass}`}>
          {skill}
        </li>
      ))}
    </ul>
  )
}
