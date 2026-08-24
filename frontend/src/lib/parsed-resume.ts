import type { AtsBreakdown, ParsedResumeData } from "@/api/types" // pipeline JSON written to resumes.parsed_data

// Narrows an unknown GET /resumes payload field into ParsedResumeData; missing keys become empty/null.
export function asParsedResumeData(raw: unknown): ParsedResumeData | null {
  if (typeof raw !== "object" || raw === null) {
    return null // backend stores null until status == parsed
  }
  const record = raw as Record<string, unknown> // FastAPI JSON object
  const sectionsRaw = record.sections // expected dict[str, str]
  const sections: Record<string, string> = {} // always a plain object the UI can iterate
  if (typeof sectionsRaw === "object" && sectionsRaw !== null && !Array.isArray(sectionsRaw)) {
    for (const [key, value] of Object.entries(sectionsRaw as Record<string, unknown>)) {
      if (typeof value === "string") {
        sections[key] = value // drop non-string values rather than crashing the page
      }
    }
  }
  const skillsRaw = record.skills // expected list[str]
  const skills = Array.isArray(skillsRaw)
    ? skillsRaw.filter((item): item is string => typeof item === "string") // ignore unexpected entries
    : [] // missing skills -> empty list so the empty-state copy can render
  const breakdownRaw = record.ats_breakdown // expected AtsBreakdown object
  const ats_breakdown = asAtsBreakdown(breakdownRaw) // zeros if the worker omitted a field
  const wordRaw = record.word_count // expected int
  return {
    sections, // section name -> body
    skills, // ESCO preferred labels
    email: typeof record.email === "string" ? record.email : null, // first regex hit or null
    phone: typeof record.phone === "string" ? record.phone : null, // first regex hit or null
    extractor_used: typeof record.extractor_used === "string" ? record.extractor_used : "unknown", // pymupdf | pypdfium2
    ats_breakdown, // per-signal points
    word_count: typeof wordRaw === "number" && Number.isFinite(wordRaw) ? wordRaw : 0, // token count
  }
}

// Narrows ats_breakdown into numbers so a partial payload cannot break the score card.
function asAtsBreakdown(raw: unknown): AtsBreakdown {
  const record = typeof raw === "object" && raw !== null ? (raw as Record<string, unknown>) : {} // empty -> zeros
  return {
    section_points: asFiniteNumber(record.section_points), // section-header signal
    contact_points: asFiniteNumber(record.contact_points), // email/phone signal
    skill_points: asFiniteNumber(record.skill_points), // ESCO hit signal
    length_points: asFiniteNumber(record.length_points), // word-count signal
    total: asFiniteNumber(record.total), // clamped 0–100 total
  }
}

// Coerces a JSON value to a finite number, otherwise 0.
function asFiniteNumber(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0 // NaN/Infinity would break the bar width
}
