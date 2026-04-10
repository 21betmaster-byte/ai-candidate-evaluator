// Mirrors backend/app/schemas.py. Keep these in sync.

export type CandidateStatus =
  | "pending"
  | "incomplete"
  | "manual_review"
  | "auto_pass"
  | "auto_fail"
  | "passed_manual"
  | "failed_manual"
  | "processing_error";

export interface CandidateRow {
  id: number;
  email: string;
  name: string | null;
  status: CandidateStatus;
  overall_score: number | null;
  created_at: string;
}

export interface ScoreEntry {
  score: number;
  reasoning: string;
}

export interface EvaluationDetail {
  id: number;
  superseded: boolean;
  github_url: string | null;
  portfolio_url: string | null;
  resume_filename: string | null;
  structured_profile: Record<string, unknown> | null;
  scores: Record<string, ScoreEntry> | null;
  overall_score: number | null;
  tier: string | null;
  decision_reason: string | null;
  created_at: string;
}

export interface ProcessingLogEntry {
  id: number;
  step: string;
  level: "info" | "warn" | "error";
  message: string;
  meta: Record<string, unknown> | null;
  created_at: string;
}

export interface LogEntryWithCandidate extends ProcessingLogEntry {
  candidate_id: number | null;
  candidate_name: string | null;
  candidate_email: string | null;
}

export interface EmailHistoryEntry {
  id: number;
  direction: "in" | "out";
  sender: string | null;
  subject: string | null;
  classification: string | null;
  template_used: string | null;
  created_at: string;
  body: string | null;
  body_error: string | null;
}

export interface CandidateDetail {
  id: number;
  email: string;
  name: string | null;
  status: CandidateStatus;
  missing_items: string[] | null;
  review_source: "intake_review" | "score" | null;
  review_reason: string | null;
  created_at: string;
  updated_at: string;
  current_evaluation: EvaluationDetail | null;
  logs: ProcessingLogEntry[];
  email_history: EmailHistoryEntry[];
}

export interface RubricDimension {
  key: string;
  description: string;
  weight: number;
}

export interface SettingsModel {
  polling_minutes: number;
  rubric: RubricDimension[];
  tier_thresholds: {
    auto_fail_ceiling: number;
    manual_review_ceiling: number;
    auto_pass_floor: number;
  };
  pass_next_steps_text?: string;
  reminder_hours: number;
  incomplete_expiry_days: number;
  company_name: string;
}
