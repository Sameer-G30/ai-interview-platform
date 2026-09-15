import type {
  InterviewSessionListItemOut,
  InterviewSessionStatus,
  MatchOut,
  RankingRowOut,
  ScoreOut,
} from "@/api/types" // dashboard facts come from stored JSON, never from MiniLM/Ollama in the browser

// One coaching line derived from resume/matches/score facts (no LLM essay).
export type Recommendation = {
  id: string // stable React key
  text: string // sentence shown on the candidate dashboard
}

// Display labels for the four scoring_v1 signals (coding dropped).
export const SIGNAL_LABELS = {
  resume: "Resume (ATS)", // resumes.ats_score 0–100
  technical: "Technical", // mean technical evaluation.score × 20
  communication: "Communication", // dual-fluency mapping; omitted on text-only
  behavioral: "Behavioral", // mean behavioral evaluation.score × 20
} as const

// Keys of SIGNAL_LABELS, used when iterating score cards.
export type SignalName = keyof typeof SIGNAL_LABELS

// Ordered so score-summary cards match the brief’s 20/30/25/15 story.
export const SIGNAL_ORDER: SignalName[] = ["resume", "technical", "communication", "behavioral"]

// Render a stored 0–100 signal. Null/undefined is omitted, never a fake 0.
export function formatSignalScore(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "Not recorded" // text-only communication, missing kind, in_progress
  }
  return `${Math.round(value)} / 100` // composite is 0–100 after renormalize, not “out of 90”
}

// Human label for session.status on the history table.
export function formatSessionStatus(status: InterviewSessionStatus): string {
  if (status === "in_progress") {
    return "In progress" // still answering; GET /scores/{id} is 404
  }
  if (status === "completed") {
    return "Completed" // Score row should exist
  }
  if (status === "abandoned") {
    return "Abandoned" // generate failed or left; no composite
  }
  return "Scheduled" // waiting on interview_generate
}

// Practice vs posting chip copy. Practice sessions stay off recruiter ranking.
export function formatSessionKind(row: InterviewSessionListItemOut): string {
  if (row.job_id === null) {
    return "Practice" // job_id null
  }
  return row.posting_title ?? "Posting" // title from GET /interviews join; fallback if posting was deleted
}

// Newest completed row from a newest-first history list (undefined if none scored yet).
export function latestCompletedSession(
  rows: InterviewSessionListItemOut[] | undefined,
): InterviewSessionListItemOut | undefined {
  if (rows === undefined) {
    return undefined // query still loading
  }
  return rows.find((row) => row.status === "completed") // list is already newest first
}

// True when the candidate has an open session that cannot show a composite yet.
export function hasInProgressWithoutScore(rows: InterviewSessionListItemOut[] | undefined): boolean {
  if (rows === undefined) {
    return false // do not flash the empty state while loading
  }
  return rows.some((row) => row.status === "in_progress" && row.composite_score === null)
}

// Split recruiter required_skills the same way the Jobs form stores them (comma / semicolon / newline).
export function splitRequiredSkills(raw: string | null | undefined): string[] {
  if (raw === null || raw === undefined || raw.trim() === "") {
    return [] // posting listed no skills
  }
  const seen = new Set<string>() // de-dupe case-insensitively
  const skills: string[] = [] // preserve first-seen spelling
  for (const part of raw.split(/[,;\n]+/)) {
    const skill = part.trim() // drop whitespace
    if (skill === "") {
      continue // empty token from trailing comma
    }
    const key = skill.toLowerCase() // Python vs python
    if (seen.has(key)) {
      continue // already listed
    }
    seen.add(key) // remember
    skills.push(skill) // original casing
  }
  return skills // used by the skill-distribution chart (not MiniLM)
}

// Client-side ranking sort keys; values stay the API numbers (do not re-aggregate).
export type RankingSortKey =
  | "rank"
  | "email"
  | "composite"
  | "resume"
  | "technical"
  | "communication"
  | "behavioral"

// Compare two ranking rows for a chosen column. Null signals sort last (omitted ≠ 0).
export function compareRankingRows(a: RankingRowOut, b: RankingRowOut, key: RankingSortKey): number {
  if (key === "email") {
    return a.candidate_email.localeCompare(b.candidate_email) // A–Z
  }
  if (key === "rank") {
    return a.rank - b.rank // API 1 is the highest composite; keep that order
  }
  const left = rankingNumeric(a, key) // number or null
  const right = rankingNumeric(b, key) // number or null
  if (left === null && right === null) {
    return 0 // both omitted
  }
  if (left === null) {
    return 1 // omitted after a real number
  }
  if (right === null) {
    return -1 // real number before omitted
  }
  return right - left // high scores first, matching API composite desc
}

// Pick the numeric field for compareRankingRows.
function rankingNumeric(row: RankingRowOut, key: RankingSortKey): number | null {
  if (key === "rank") {
    return row.rank // 1 is best
  }
  if (key === "composite") {
    return row.composite_score
  }
  if (key === "resume") {
    return row.resume_score
  }
  if (key === "technical") {
    return row.technical_score
  }
  if (key === "communication") {
    return row.communication_score
  }
  if (key === "behavioral") {
    return row.behavioral_score
  }
  return null // email is handled above
}

// Filter ranking rows by email substring and optional minimum composite (client-side only).
export function filterRankingRows(
  rows: RankingRowOut[],
  emailQuery: string,
  minComposite: number | null,
): RankingRowOut[] {
  const needle = emailQuery.trim().toLowerCase() // empty string matches all
  return rows.filter((row) => {
    if (needle !== "" && !row.candidate_email.toLowerCase().includes(needle)) {
      return false // email filter
    }
    if (minComposite !== null && (row.composite_score === null || row.composite_score < minComposite)) {
      return false // do not treat omitted composite as 0
    }
    return true // keep
  })
}

// Coaching bullets from stored ATS / skill-gap chips / omitted signals / last composite. No Ollama.
export function buildRecommendations(args: {
  noParsedResume: boolean // GET /matches 404
  hasSessions: boolean // GET /interviews length > 0
  inProgressWithoutScore: boolean // open session, no Score yet
  matches: MatchOut[] | undefined // GET /matches chips
  latestScore: ScoreOut | null // GET /scores/{id} for latest completed
}): Recommendation[] {
  const items: Recommendation[] = [] // accumulate in priority order
  if (args.noParsedResume) {
    items.push({
      id: "upload-resume",
      text: "Upload a PDF resume so matches, interviews, and ATS scoring can run.",
    })
    return items // later facts are unavailable without a parsed resume
  }
  if (!args.hasSessions) {
    items.push({
      id: "start-interview",
      text: "No interviews yet — start a practice session or open Matches to interview against a posting.",
    })
  }
  if (args.inProgressWithoutScore) {
    items.push({
      id: "finish-open",
      text: "You have an interview in progress with no composite yet. Open it from history and finish answering.",
    })
  }
  if (args.latestScore !== null) {
    const omitted = args.latestScore.attribution?.omitted ?? [] // scoring_v1 omitted list
    const communicationOmitted =
      omitted.includes("communication") || args.latestScore.communication_score === null
    if (communicationOmitted) {
      items.push({
        id: "record-audio",
        text: "Communication was not recorded on your last scored session. Upload a WebM answer next time so both fluency arms can be scored.",
      })
    }
    if (args.latestScore.resume_score !== null && args.latestScore.resume_score < 70) {
      items.push({
        id: "improve-ats",
        text: `Your last ATS score was ${Math.round(args.latestScore.resume_score)} / 100. Strengthen resume sections, contact details, and listed skills.`,
      })
    }
    if (args.latestScore.composite_score !== null && args.latestScore.composite_score < 70) {
      items.push({
        id: "retry-interview",
        text: `Last composite was ${Math.round(args.latestScore.composite_score)} / 100. Open the session report and retry the interview.`,
      })
    }
  }
  const missing = [...new Set((args.matches ?? []).flatMap((match) => match.missing_skills))] // unique chips
  for (const skill of missing.slice(0, 5)) {
    items.push({
      id: `gap-${skill}`,
      text: `${skill} is listed as a skill gap on at least one active posting.`,
    })
  }
  if (items.length === 0) {
    items.push({
      id: "keep-practicing",
      text: "Stored scores and skill-gap chips look solid — keep practicing, no extra coaching from those facts.",
    })
  }
  return items // never an LLM paragraph
}

// Read one named signal off ScoreOut / RankingRowOut without inventing 0.
export function signalValue(
  row: Pick<ScoreOut, "resume_score" | "technical_score" | "communication_score" | "behavioral_score">,
  name: SignalName,
): number | null {
  if (name === "resume") {
    return row.resume_score
  }
  if (name === "technical") {
    return row.technical_score
  }
  if (name === "communication") {
    return row.communication_score
  }
  return row.behavioral_score
}
