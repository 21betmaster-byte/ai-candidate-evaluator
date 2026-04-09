# PRD: AI Candidate Evaluator Agent (V1)

## 1. Objective

Build an AI-powered email agent that receives job applications via a dedicated Gmail inbox, automatically evaluates candidates against a configurable scoring rubric, and responds with screening decisions — all without human intervention for clear pass/fail cases. The agent serves hiring managers (by reducing screening workload and surfacing top candidates), candidates (by providing fast, respectful responses), and the organization (by cutting time-to-screen from days to minutes). A lightweight web dashboard gives hiring managers visibility into all applications, scores, and pending reviews.

## 2. Problem Statement

Today, hiring teams manually read every application email, open every resume, check every GitHub profile, and make gut-call screening decisions. This takes hours per batch of applications, creates long response times for candidates (often days or weeks of silence), and leads to inconsistent evaluation — different reviewers weight different things. Candidates, meanwhile, have no idea if their application was even received, and strong builders get lost in the pile alongside spam and incomplete applications. The cost is real: good candidates accept other offers while waiting, hiring managers burn interview bandwidth on weak fits, and the organization's employer brand suffers every time a candidate gets ghosted.

## 3. User Stories

### Hiring Manager

- As a **hiring manager**, I should be able to **configure the scoring rubric weights and pass/fail thresholds per role**, so that I can **tailor screening criteria to different positions**.
- As a **hiring manager**, I should be able to **view all applications in a sortable, filterable table on the dashboard**, so that I can **quickly see the pipeline without digging through email**.
- As a **hiring manager**, I should be able to **click into any candidate to see their full evaluation breakdown (scores per dimension + AI reasoning)**, so that I can **understand why the agent scored them that way**.
- As a **hiring manager**, I should be able to **manually trigger a pass or fail decision for candidates in the "manual review" tier (50–69)**, so that I can **make the final call on borderline candidates**.
- As a **hiring manager**, I should be able to **trigger a manual inbox poll from the dashboard**, so that I can **check for new applications on demand during testing or demos**.
- As a **hiring manager**, I should be able to **configure the Gmail address and polling frequency**, so that I can **set up the agent for different inboxes and adjust responsiveness**.

### Candidate

- As a **candidate**, I should be able to **email my resume, GitHub link, and portfolio link to the agent's email address**, so that I can **apply for the role**.
- As a **candidate**, I should **receive an immediate acknowledgment email upon applying**, so that I **know my application was received and is being processed**.
- As a **candidate**, I should **receive a clear pass/fail decision email with a brief reason**, so that I **know the outcome without being left in the dark**.
- As a **candidate**, I should **receive a friendly email telling me what's missing if my application is incomplete**, so that I can **fix it and resubmit**.
- As a **candidate**, I should **always receive a response — even if I sent something weird or irrelevant**, so that I **never feel ignored**.

### Organization

- As the **organization**, I should be able to **see step-by-step processing logs for every application**, so that I can **debug issues, audit decisions, and understand agent behavior**.
- As the **organization**, I should have **a system that retries on infrastructure failures (e.g., GitHub API down) with queuing**, so that **transient failures don't cause lost or failed evaluations**.
- As the **organization**, I should have **graceful degradation — the agent never crashes on unexpected input**, so that **every application gets handled, even if it requires manual review flagging**.

## 4. Overarching Solution

The system is an always-on backend service connected to a dedicated Gmail inbox. It periodically polls the inbox for new emails, classifies each one (valid application, incomplete application, duplicate, spam/irrelevant, question about the role, auto-reply), and routes it through the appropriate workflow.

For valid applications, the system extracts data from three sources: the resume PDF (parsed for experience, skills, projects), the GitHub profile (fetched via API for repos, activity, languages), and the portfolio URL (fetched and analyzed for project quality). This raw data is structured using a fast, cost-effective AI model (Sonnet), then passed to a more capable reasoning model (Opus) for rubric-based evaluation and scoring.

Based on the score, the system takes one of three actions: auto-pass (70+), flag for manual review (50–69), or auto-fail (0–49). For auto-pass and auto-fail, the agent sends an email automatically. For manual review, the candidate waits until the hiring manager acts via the dashboard.

A web-based dashboard (protected by Google SSO) shows all applications in a table with filtering and sorting. Hiring managers can drill into individual evaluations and trigger emails for manual-review candidates. A "poll now" button lets users check the inbox on demand.

Every processing step is logged: email receipt, classification, PDF parsing, GitHub fetch, portfolio fetch, data structuring, AI evaluation, scoring, email sending. Infrastructure failures trigger retries via a queue — the candidate is never penalized for our system issues.

## 5. Step-by-Step Journey

### Flow: Happy Path — Complete Application

1. Candidate sends an email with resume (PDF attached), GitHub link, and portfolio link to the agent's Gmail address.
2. Agent picks up the email during the next polling cycle.
   → _Loader: polling cycle runs every X minutes (configurable)_
3. Agent classifies the email as a valid, complete application.
4. Agent sends an acknowledgment email to the candidate — fun, on-brand, confirming receipt.
5. Agent extracts text and data from the resume PDF.
   → _Loader: PDF parsing_
6. Agent fetches GitHub profile data via GitHub API.
   → _Loader: GitHub API call with retry/queue on failure_
7. Agent fetches portfolio URL and extracts project signals.
   → _Loader: HTTP fetch with retry/queue on failure_
8. Agent sends extracted raw data to Sonnet to produce structured candidate profile.
   → _Loader: Sonnet API call_
9. Agent sends structured profile + rubric to Opus for evaluation and scoring.
   → _Loader: Opus API call_
10. Opus returns scores per dimension + reasoning. Agent computes weighted total.
11. Agent determines tier: auto-pass (70+), manual review (50–69), or auto-fail (0–49).
12. For auto-pass: Agent sends congratulatory email with next steps.
13. For auto-fail: Agent sends a lite, warm close — not too direct, brief reason, encouraging. The most polite rejection the candidate has ever received.
14. For manual review: No email sent. Candidate flagged on dashboard.
15. All steps logged to database and application logs.
16. Done — evaluation visible on dashboard.

### Flow: Incomplete Application

1. Candidate sends an email missing one or more required items (resume, GitHub, portfolio).
2. Agent classifies email and identifies what's missing.
3. Agent sends a fun, specific email telling the candidate what's needed.
4. Candidate re-sends with missing items.
5. Agent picks up the new email, links it to the original application (by email address), and proceeds to evaluation.
6. Done — flows into Happy Path from step 5.

### Flow: Hiring Manager Reviews Manual-Review Candidate

1. Hiring manager logs into dashboard via Google SSO.
2. Hiring manager sees table of all applications — filters by "Manual Review" status.
3. Hiring manager clicks into a candidate to see full evaluation detail.
4. Hiring manager clicks "Pass" or "Fail" button.
5. Agent sends the appropriate email to the candidate.
6. Done — status updated on dashboard.

### Flow: Edge Case — Irrelevant/Gibberish Email

1. Agent picks up an email that isn't a job application.
2. Agent classifies it (spam, question, auto-reply, gibberish).
3. Agent sends a fun, appropriate response (e.g., for a question about the role, a helpful answer; for gibberish, a lighthearted nudge).
4. Email logged with classification. No evaluation created.
5. Done.

## 6. User Journeys

### Journey: Candidate Submits a Complete Application

**Actor:** Candidate
**Goal:** Apply for a role and receive a screening decision
**Preconditions:** Candidate has the agent's email address, a resume PDF, a GitHub profile, and a portfolio link

**Steps:**

1. **Compose Email**
   - User sees: Their email client (Gmail, Outlook, etc.)
   - User does: Composes email to agent's address. Attaches resume PDF. Includes GitHub and portfolio links in email body.
   - System responds: Email delivered to agent's Gmail inbox.

2. **Acknowledgment**
   - User sees: (within minutes, based on polling frequency) An acknowledgment email in their inbox.
   - System responds: Fun, branded email confirming receipt.

   → _Processing happens asynchronously — candidate waits_

3. **Decision Email**
   - User sees: A decision email.
   - For auto-pass: Warm, exciting email with next steps (configurable text).
   - If fail: a lite, warm close — not too direct, with a brief gentle reason. Never feels like a formal rejection letter. Leaves the door open.
   - For manual review: No email. Candidate waits until hiring manager acts.
   - System responds: Email sent. Status updated in DB.

**Postconditions:** Candidate has received acknowledgment + decision (or is awaiting manual review). Evaluation stored in DB. All steps logged.

**Error States:**
- Email parsing fails → Logged, candidate flagged for manual review, no email sent until resolved.
- GitHub API is down → Retry via queue. Candidate is NOT penalized. Evaluation delayed but eventually completes.
- Portfolio URL is unreachable → Retry. If still down after retries, score what's available, flag for manual review.

---

### Journey: Candidate Submits an Incomplete Application

**Actor:** Candidate
**Goal:** Apply for a role (but forgets something)
**Preconditions:** Candidate sends email missing one or more of: resume, GitHub link, portfolio link

**Steps:**

1. **Compose Email (Incomplete)**
   - User does: Sends email missing, e.g., the GitHub link.
   - System responds: Agent classifies as incomplete. Identifies missing item(s).

2. **"Missing Items" Email**
   - User sees: A friendly, specific email listing what's missing.
   - System responds: Candidate status set to "Incomplete — Awaiting Response." Logged.

3. **Candidate Resends**
   - User does: Replies or sends a new email with the missing item(s).
   - System responds: Agent detects same email address, links to existing application, proceeds to full evaluation.

4. **Auto-Reminder (if no response)**
   - System responds: After a configurable period, agent sends one follow-up reminder.
   - If still no response after reminder: Status remains "Incomplete." No further auto-emails.

**Postconditions:** Either candidate completes application (flows into evaluation) or remains in "Incomplete" status on dashboard.

**Error States:**
- Candidate sends the missing item but in the wrong format (e.g., GitHub link is actually a LinkedIn link) → Agent flags as still missing, sends another friendly email.

---

### Journey: Hiring Manager Reviews Applications on Dashboard

**Actor:** Hiring Manager
**Goal:** Review candidate pipeline and act on manual-review candidates
**Preconditions:** Hiring manager has Google SSO access to the dashboard

**Steps:**

1. **Login**
   - User sees: Google SSO login screen.
   - User does: Logs in with Google account.
   - System responds: Redirects to dashboard.

   → _Loader: Fetching application data_

2. **Application Table**
   - User sees: Table with columns: Candidate Name, Email, Overall Score, Status (Auto-Pass / Auto-Fail / Manual Review / Incomplete / Pending), Date Received. Filters for status. Sort by score or date.
   - User does: Filters by "Manual Review."
   - System responds: Table updates to show only manual-review candidates.

3. **Candidate Detail View**
   - User does: Clicks on a candidate row.
   - User sees: Full evaluation detail — scores per rubric dimension, AI reasoning for each score, links to resume/GitHub/portfolio, raw extracted data, processing logs for this candidate.

4. **Manual Decision**
   - User does: Clicks "Pass" or "Fail" button on the detail view.
   - System responds: Confirmation dialog: "Send pass/fail email to [candidate name]?"
   - User does: Confirms.
   - System responds: Email sent to candidate. Status updated. Logged.

5. **Manual Poll**
   - User does: Clicks "Poll Now" button on the dashboard header.
   - System responds: Triggers immediate inbox check. New applications appear in the table.

   → _Loader: "Checking inbox..." spinner_

**Postconditions:** Hiring manager has reviewed and acted on candidates. Decisions emailed. Dashboard reflects current state.

**Error States:**
- Google SSO fails → Standard OAuth error handling, retry prompt.
- Email sending fails on manual decision → Error toast on dashboard: "Failed to send email. Retrying..." Auto-retry. If persistent, flag for admin.

---

### Journey: Hiring Manager Configures Role Settings

**Actor:** Hiring Manager
**Goal:** Set up or modify rubric weights, pass/fail thresholds, polling frequency, and Gmail address
**Preconditions:** Hiring manager is logged into the dashboard

**Steps:**

1. **Settings Page**
   - User does: Navigates to Settings from dashboard nav.
   - User sees: Configuration form with:
     - Gmail address (text field)
     - Polling frequency in minutes (number field)
     - Rubric dimensions with weight sliders/inputs (must total 100%)
     - Tier thresholds: auto-fail ceiling (default 49), manual review ceiling (default 69), auto-pass floor (default 70)
     - Next steps text for pass email (text area)

2. **Edit and Save**
   - User does: Adjusts values, clicks Save.
   - System responds: Validates (weights sum to 100%, thresholds are in order, Gmail address is valid format). Saves to database. Confirmation toast: "Settings saved."

**Postconditions:** New settings apply to all future evaluations. Existing evaluations are NOT retroactively re-scored.

**Error States:**
- Weights don't sum to 100% → Inline validation error, Save button disabled.
- Invalid Gmail address format → Inline validation error.

---

### Journey: Edge Case — Gibberish / Irrelevant Email

**Actor:** Unknown sender
**Goal:** N/A (not a real application)
**Preconditions:** An email arrives that is not a job application

**Steps:**

1. **Classification**
   - System receives email.
   - System classifies using LLM: one of [spam/sales, question about role, auto-reply/OOO, gibberish, other irrelevant].

2. **Response by Type**
   - **Spam/Sales:** Fun deflection.
   - **Question about the role:** Helpful, on-brand answer about the role + how to apply.
   - **Auto-reply/OOO:** No response sent. Logged and ignored.
   - **Gibberish:** Lighthearted nudge with instructions on how to apply.
   - **Other irrelevant:** Gentle redirect to application format.

3. **Logging**
   - System logs: sender, classification, response sent (or not sent for auto-replies). No evaluation record created.

**Postconditions:** Sender received an appropriate response (or none for auto-replies). No evaluation in the database. Edge case logged.

---

### Journey: Duplicate Application

**Actor:** Candidate who has already applied
**Goal:** Update their application (or accidentally re-sends)
**Preconditions:** An evaluation (or incomplete application record) already exists for this email address

**Steps:**

1. **Detection**
   - System receives email from a known email address.
   - System detects existing record.

2. **Update**
   - System replaces the old evaluation data with the new submission.
   - If the new submission is also incomplete, the "missing items" flow triggers for whatever is still missing.
   - If complete, full evaluation runs on the new data.

3. **Response**
   - Fun acknowledgment about receiving the update.

4. **Logging**
   - Old evaluation marked as "superseded." New evaluation linked. Full audit trail preserved.

**Postconditions:** Only the latest evaluation is active. Old data preserved for audit but not shown as current on dashboard.

---

### Journey: GitHub/Portfolio/Resume Found Inside Portfolio or Resume (Not in Email Body)

**Actor:** Candidate
**Goal:** Apply for a role (but didn't include all materials in email body)
**Preconditions:** Candidate attached resume and/or shared portfolio, but GitHub/portfolio links are only inside the resume PDF or on the portfolio page — not in the email body. OR: candidate didn't attach a resume but their portfolio has a downloadable resume.

**Steps:**

1. **Email Body Parsing**
   - System parses email body. Finds no GitHub and/or no portfolio link. Or finds no resume attachment.

2. **Secondary Source Check — Resume**
   - Before flagging as incomplete, system checks the attached resume PDF for URLs.
   - If GitHub or portfolio links are found in the resume → extract and use them.

3. **Secondary Source Check — Portfolio Page**
   - If portfolio link was found (in email or resume), system fetches the portfolio page.
   - System scans the portfolio page for a GitHub link.
   - If found → extract and use it.
   - System scans the portfolio page for a downloadable resume (PDF link).
   - If found and no resume was attached → download and use it.

4. **Evaluation or Incomplete Flow**
   - If all three sources (resume, GitHub, portfolio) are now available → proceed to evaluation.
   - If still missing after secondary checks → trigger the "missing items" email flow.

**Postconditions:** Agent made a best effort to find all materials before asking the candidate for more info. Logged which source each link was found in.

---

### Journey: Infrastructure Failure During Processing

**Actor:** System (no direct user interaction)
**Goal:** Handle transient failures without losing applications or penalizing candidates
**Preconditions:** An application is being processed and an external service fails

**Steps:**

1. **Failure Detection**
   - A step fails: GitHub API returns 5xx, portfolio URL times out, Sonnet/Opus API errors, Gmail send fails.

2. **Retry with Backoff**
   - System places the failed step into a retry queue with exponential backoff.
   - Retry schedule: 1 min → 5 min → 15 min → 1 hour → flag for manual review.

3. **Partial Processing Continues**
   - If GitHub API is down but resume and portfolio are parsed, those results are saved.
   - When GitHub eventually succeeds, evaluation resumes from where it left off.

4. **Escalation**
   - If all retries exhausted → Candidate flagged as "Processing Error" on dashboard.
   - Hiring manager sees a clear indicator: "GitHub data could not be fetched after retries. Evaluation incomplete."
   - Hiring manager can manually retry from dashboard or proceed with partial data.

5. **Candidate Experience**
   - Candidate received the acknowledgment email (sent before processing starts).
   - Candidate sees NO error. They wait normally. Decision email arrives once processing completes (even if delayed by retries).
   - The candidate is NEVER penalized in their score for infrastructure issues.

**Postconditions:** Application eventually processed or flagged for manual intervention. Full retry history logged. No data lost.

## 7. Acceptance Criteria

### Email Receiving & Classification

- [ ] Agent polls the configured Gmail inbox at the configured frequency.
- [ ] Agent correctly classifies inbound emails into: complete application, incomplete application, duplicate, spam/sales, question about role, auto-reply/OOO, gibberish, other irrelevant.
- [ ] Agent sends an acknowledgment email for every valid application (complete or incomplete) within one polling cycle.
- [ ] Agent does NOT send a response to auto-reply/OOO emails.
- [ ] Agent sends an appropriate, on-brand response for every other classification type.
- [ ] All emails are logged with: sender, timestamp, classification, and response sent.

### Resume Parsing

- [ ] Agent extracts text from a PDF attachment.
- [ ] Agent identifies and extracts: work experience, technical skills, project descriptions, and education from the resume text.
- [ ] Agent extracts URLs (GitHub, portfolio) from the resume PDF if not found in the email body.
- [ ] Agent correctly identifies when the attachment is not a PDF and sends a "wrong format" email.
- [ ] Agent correctly handles multiple attachments — identifies which one is the resume (PDF), ignores others.

### GitHub Evaluation

- [ ] Agent fetches public profile data via GitHub API: number of repos, primary languages, recent commit activity (last 6 months), stars/forks.
- [ ] Agent detects a 404 or private profile and flags it as a candidate-side issue — emails the candidate.
- [ ] Agent retries on GitHub API 5xx errors with exponential backoff — does NOT email the candidate about infrastructure failures.
- [ ] Agent discovers GitHub link from the portfolio page if not provided directly.
- [ ] Agent handles GitHub profiles with zero public repos — logs it, factors into score, does not crash.

### Portfolio Evaluation

- [ ] Agent fetches the portfolio URL and confirms it loads (HTTP 200).
- [ ] Agent extracts project signals: project count, project descriptions, technologies mentioned.
- [ ] Agent detects a 404 or unreachable portfolio and retries before flagging.
- [ ] Agent detects if the "portfolio" link is actually just a LinkedIn profile and flags accordingly.
- [ ] Agent discovers a downloadable resume linked on the portfolio page if no resume was attached to the email — downloads and uses it for evaluation.

### AI Evaluation Pipeline

- [ ] Raw extracted data (resume, GitHub, portfolio) is sent to Sonnet for structuring into a candidate profile.
- [ ] Structured candidate profile + rubric configuration is sent to Opus for scoring and reasoning.
- [ ] Opus returns: score per rubric dimension (0–100), brief reasoning per dimension, overall weighted score.
- [ ] Scores are computed using the configured rubric weights (must sum to 100%).
- [ ] Evaluation result is stored in the database with all scores, reasoning, and raw data.

### Scoring & Decision Tiers

- [ ] Score 0–49 (inclusive) → auto-fail. Rejection email sent automatically.
- [ ] Score 50–69 (inclusive) → manual review. No email sent. Candidate appears on dashboard as "Manual Review."
- [ ] Score 70–100 (inclusive) → auto-pass. Pass email with next steps sent automatically.
- [ ] Boundary behavior is explicit: a score of exactly 50 falls in "manual review," a score of exactly 70 falls in "auto-pass." These boundaries shift when thresholds are reconfigured.
- [ ] Tier thresholds are configurable per role via the dashboard settings page.
- [ ] Changing thresholds does NOT retroactively re-score existing evaluations.

### Email Communication Quality

- [ ] All outbound emails match the brand voice: friendly, witty, bold, playful.
- [ ] Rejection emails are lite, warm, and not too direct — they should feel like a gentle, brief close, not a formal rejection letter. The tone is encouraging and leaves the door open. Include a brief, non-specific reason but keep it short (2–3 sentences max for the rejection-specific content). This should be the most polite but firm rejection a candidate has ever received.
- [ ] Pass emails include clear next steps (configurable text).
- [ ] "Missing items" emails specifically name what's missing and how to send it.
- [ ] Edge case emails (spam, gibberish, questions) are fun and appropriate to the scenario.
- [ ] Every candidate-facing email has a consistent template structure with scenario-specific text inserted.
- [ ] Candidate-facing emails MUST NOT contain numeric scores, rubric dimension names, or any internal evaluation data. Only the pass/fail decision and a brief human-readable reason are shared.

### Duplicate Handling

- [ ] Agent detects duplicate applications by matching sender email address to existing records.
- [ ] Duplicate submissions replace the previous evaluation with the new one.
- [ ] Old evaluation is preserved in the database as "superseded" for audit purposes.
- [ ] Agent sends a fun "we got your update" acknowledgment.

### Missing Info Handling

- [ ] Agent identifies exactly which items are missing (resume, GitHub, portfolio — any combination).
- [ ] Agent sends one automatic follow-up email listing the missing items.
- [ ] Agent sends one automatic reminder after a configurable period if still no response.
- [ ] Third reminder is NOT automated in V1 (future: recruiter-triggered from dashboard).
- [ ] When the candidate re-sends, agent links the response to the original application by email address.

### Dashboard

- [ ] Dashboard is accessible as a web application via a URL.
- [ ] Dashboard is protected by Google SSO — only authorized Google accounts can access.
- [ ] Main view is a table with columns: Candidate Name, Email, Overall Score, Status, Date Received.
- [ ] Table supports filtering by status: Auto-Pass, Auto-Fail, Manual Review, Incomplete, Pending, Processing Error.
- [ ] Table supports sorting by: Overall Score (asc/desc), Date Received (asc/desc).
- [ ] Clicking a row opens a detail view with: all rubric scores, AI reasoning per dimension, links to resume/GitHub/portfolio, processing logs.
- [ ] Manual Review candidates have "Pass" and "Fail" action buttons in the detail view.
- [ ] Clicking Pass/Fail shows a confirmation dialog before sending the email.
- [ ] "Poll Now" button in the dashboard header triggers an immediate inbox poll.
- [ ] Settings page allows configuration of: Gmail address, polling frequency, rubric weights (must sum to 100%), tier thresholds, pass email next-steps text.
- [ ] Settings page validates inputs before saving (weights sum, threshold order, email format).

### Logging

- [ ] Every processing step is logged with timestamp: email received, classification, PDF parsing started/completed, GitHub API called/response received, portfolio fetched, Sonnet called/response received, Opus called/response received, score computed, decision made, email sent.
- [ ] Edge case triggers are logged (which edge case, what was detected, what action was taken).
- [ ] Infrastructure failures are logged with: which service, error type, retry count, resolution.
- [ ] All logs are queryable — application logs for debugging, database records for evaluation data.
- [ ] Each candidate's processing timeline is viewable on their dashboard detail page.

### Graceful Degradation

- [ ] If any external service fails (GitHub API, portfolio URL, Sonnet, Opus, Gmail sending), the agent retries with exponential backoff.
- [ ] If retries are exhausted, the candidate is flagged as "Processing Error" on the dashboard — the agent does NOT crash.
- [ ] Candidates are NEVER penalized in scoring for infrastructure failures.
- [ ] Unrecognized email formats or unexpected content types are classified as "other irrelevant" and receive a generic fun response — agent does not crash.
- [ ] The agent handles any email content without crashing, including: empty bodies, extremely long emails, emails with 10+ attachments, emails with no subject line.
- [ ] When multiple applications arrive in the same polling cycle, each is processed independently with no data cross-contamination between candidates.

### Configuration

- [ ] Gmail address is configurable (not hardcoded).
- [ ] Polling frequency is configurable in minutes.
- [ ] Rubric dimension weights are configurable (must sum to 100%).
- [ ] Default rubric weights: Technical Depth 35%, Shipped Products 30%, Business Thinking 20%, Speed of Execution 15%.
- [ ] Tier thresholds (auto-fail ceiling, manual review ceiling, auto-pass floor) are configurable.
- [ ] Default tier thresholds: auto-fail ≤49, manual review 50–69, auto-pass ≥70.
- [ ] Pass email "next steps" text is configurable.
- [ ] Reminder timing (how long to wait before sending the missing-info reminder) is configurable.

## 8. Acceptance Tests

### Test: Happy Path — Complete Application

**Precondition:** Agent is running, polling is active, rubric is configured with defaults.
**Steps:**
1. Send an email to the agent's Gmail with: a PDF resume attached, a GitHub profile link in the body, a portfolio link in the body.
2. Wait for one polling cycle.
3. Check inbox for acknowledgment email.
4. Wait for processing to complete (check dashboard or logs).
5. Check inbox for decision email.
**Expected Result:** Acknowledgment email received within one polling cycle. Decision email received. If score 70+, it's a pass with next steps. If 0–49, it's a polite rejection. If 50–69, no decision email — candidate appears as "Manual Review" on dashboard.

---

### Test: Missing Resume

**Precondition:** Agent is running.
**Steps:**
1. Send an email with GitHub and portfolio links but NO attachment.
2. Wait for one polling cycle.
**Expected Result:** Agent sends a fun email saying the resume is missing and asking the candidate to re-send with a PDF attached.

---

### Test: Missing GitHub Link

**Precondition:** Agent is running.
**Steps:**
1. Send an email with a PDF resume and portfolio link but no GitHub link in the email body, resume, or portfolio page.
2. Wait for one polling cycle.
**Expected Result:** Agent sends a fun email identifying that the GitHub link is missing.

---

### Test: Missing Portfolio Link

**Precondition:** Agent is running.
**Steps:**
1. Send an email with a PDF resume and GitHub link but no portfolio link anywhere.
2. Wait for one polling cycle.
**Expected Result:** Agent sends a fun email identifying that the portfolio link is missing.

---

### Test: Non-PDF Attachment

**Precondition:** Agent is running.
**Steps:**
1. Send an email with a .docx file attached (not PDF), plus GitHub and portfolio links.
2. Wait for one polling cycle.
**Expected Result:** Agent sends a fun email asking the candidate to re-send their resume as a PDF.

---

### Test: Multiple Attachments

**Precondition:** Agent is running.
**Steps:**
1. Send an email with a PDF resume + a .png image + a .docx file, plus GitHub and portfolio links.
2. Wait for one polling cycle.
**Expected Result:** Agent identifies the PDF as the resume, ignores other attachments, and proceeds with evaluation normally.

---

### Test: Completely Empty Email

**Precondition:** Agent is running.
**Steps:**
1. Send an email with no body text and no attachments.
2. Wait for one polling cycle.
**Expected Result:** Agent sends a fun response nudging the sender to include their resume, GitHub, and portfolio.

---

### Test: Gibberish Email

**Precondition:** Agent is running.
**Steps:**
1. Send an email with random characters as the body.
2. Wait for one polling cycle.
**Expected Result:** Agent classifies as gibberish and sends a lighthearted response redirecting to proper application format.

---

### Test: Sales/Spam Email

**Precondition:** Agent is running.
**Steps:**
1. Send an email pitching a product or service.
2. Wait for one polling cycle.
**Expected Result:** Agent classifies as spam/sales, sends a fun deflection, does NOT create an application record.

---

### Test: Question About the Role

**Precondition:** Agent is running.
**Steps:**
1. Send an email asking about the role (e.g., salary, remote policy).
2. Wait for one polling cycle.
**Expected Result:** Agent classifies as a question, sends a helpful on-brand response explaining the role + how to apply.

---

### Test: Auto-Reply / Out-of-Office

**Precondition:** Agent is running.
**Steps:**
1. Trigger an auto-reply email to the agent's inbox.
2. Wait for one polling cycle.
**Expected Result:** Agent classifies as auto-reply. No response sent. Logged.

---

### Test: Duplicate Application — Same Email, Same Content

**Precondition:** Agent has already processed an application from candidate@test.com.
**Steps:**
1. Send an identical email from candidate@test.com.
2. Wait for one polling cycle.
**Expected Result:** Agent detects duplicate, sends a fun "we got your update" email, re-evaluates with the new data, marks old evaluation as superseded.

---

### Test: Duplicate Application — Same Email, Updated Resume

**Precondition:** Agent has already processed an application from candidate@test.com.
**Steps:**
1. Send a new email from candidate@test.com with a different resume PDF attached.
2. Wait for one polling cycle.
**Expected Result:** Agent detects duplicate, acknowledges update with fun email, evaluates using the new resume. Old evaluation superseded.

---

### Test: GitHub Link Found in Portfolio (Not in Email)

**Precondition:** Agent is running. Portfolio page contains a link to a GitHub profile.
**Steps:**
1. Send an email with a resume and portfolio link, but no GitHub link in email body or resume.
2. Wait for processing.
**Expected Result:** Agent fetches portfolio page, discovers GitHub link, uses it for evaluation. Candidate is NOT asked for the GitHub link.

---

### Test: GitHub Link Found in Resume (Not in Email)

**Precondition:** Agent is running. Resume PDF contains a GitHub URL.
**Steps:**
1. Send an email with a resume (containing GitHub link inside) and a portfolio link, but no GitHub link in the email body.
2. Wait for processing.
**Expected Result:** Agent extracts GitHub link from resume, uses it for evaluation. Candidate is NOT asked for the GitHub link.

---

### Test: Resume Found in Portfolio (Not Attached to Email)

**Precondition:** Agent is running. Portfolio page has a downloadable PDF resume link.
**Steps:**
1. Send an email with GitHub and portfolio links but no attachment.
2. Wait for processing.
**Expected Result:** Agent fetches portfolio page, discovers the resume PDF link, downloads it, and uses it for evaluation. Candidate is NOT asked to re-send with a resume attached.

---

### Test: GitHub Profile is 404 or Private

**Precondition:** Agent is running.
**Steps:**
1. Send an email with a resume, portfolio, and a GitHub link that leads to a 404 or a private profile.
2. Wait for processing.
**Expected Result:** Agent sends a friendly email saying the GitHub link doesn't seem to work and asks to check/re-send.

---

### Test: Portfolio URL is Down

**Precondition:** Agent is running.
**Steps:**
1. Send an email with a resume, GitHub, and a portfolio link that returns a 5xx or times out.
2. Wait for retries to be exhausted.
**Expected Result:** Agent retries. If still down, agent evaluates with available data and flags for manual review.

---

### Test: Portfolio Link is Just LinkedIn

**Precondition:** Agent is running.
**Steps:**
1. Send an email with a resume, GitHub, and a LinkedIn URL as the "portfolio."
2. Wait for processing.
**Expected Result:** Agent detects that the portfolio is a LinkedIn profile, sends a fun email asking for an actual project portfolio link.

---

### Test: GitHub Profile Has Zero Public Repos

**Precondition:** Agent is running. GitHub profile exists but has no public repositories.
**Steps:**
1. Send a complete application with this GitHub profile.
2. Wait for processing.
**Expected Result:** Agent processes normally. GitHub dimension scores low. Agent does NOT crash.

---

### Test: Candidate Sends Multiple Emails in Quick Succession

**Precondition:** Agent is running.
**Steps:**
1. Send email 1: "Oops, forgot to attach my resume."
2. Send email 2 (30 seconds later): Complete application.
**Expected Result:** Agent detects same sender. Uses the complete email for evaluation. Does not create duplicate records.

---

### Test: Manual Review — Hiring Manager Passes Candidate

**Precondition:** A candidate with score 55 is in "Manual Review" status on dashboard.
**Steps:**
1. Log into dashboard via Google SSO.
2. Filter by "Manual Review."
3. Click into the candidate.
4. Click "Pass." Confirm.
**Expected Result:** Pass email sent. Status updates to "Passed (Manual)."

---

### Test: Manual Review — Hiring Manager Fails Candidate

**Precondition:** A candidate with score 55 is in "Manual Review" status.
**Steps:**
1. Log into dashboard. Click into candidate. Click "Fail." Confirm.
**Expected Result:** Rejection email sent (warm, respectful). Status updates to "Failed (Manual)."

---

### Test: Poll Now Button

**Precondition:** Dashboard is open. A new email has arrived but polling hasn't triggered yet.
**Steps:**
1. Click "Poll Now" button.
**Expected Result:** Spinner shows briefly. New application appears in the table.

---

### Test: Settings — Change Rubric Weights

**Precondition:** Logged into dashboard, on Settings page.
**Steps:**
1. Change weights. Click Save.
**Expected Result:** Settings saved. Future evaluations use new weights. Existing evaluations unchanged.

---

### Test: Settings — Invalid Weights

**Precondition:** On Settings page.
**Steps:**
1. Set weights that total more or less than 100%.
2. Try to Save.
**Expected Result:** Validation error shown. Save blocked.

---

### Test: Graceful Degradation — Unexpected Content

**Precondition:** Agent is running.
**Steps:**
1. Send an email with a large zip file, long random body text, and no links.
2. Wait for polling cycle.
**Expected Result:** Agent does NOT crash. Classifies and responds appropriately.

---

### Test: Reminder for Missing Info

**Precondition:** Agent sent a "missing items" email. Reminder period has elapsed. No response.
**Steps:**
1. Wait for the configured reminder period.
**Expected Result:** One follow-up reminder sent. No further auto-reminders.

## 9. End-to-End Automation Tests

**E2E Test: Complete Application Flow (P0)**
Flow: Send email → Agent polls → Acknowledgment email → Processing → Decision email → Dashboard shows evaluation
Setup: Test Gmail account, test candidate email, sample resume PDF, live GitHub profile, live portfolio URL. Rubric configured with defaults.
Assertions:
- Acknowledgment email received within 2x polling interval
- Decision email received within 5 minutes of acknowledgment
- Dashboard shows candidate with correct name, email, score, status
- Candidate detail view shows all four rubric dimension scores
- All processing steps present in logs
Teardown: Delete test candidate record from DB.

---

**E2E Test: Incomplete → Complete Flow (P0)**
Flow: Send incomplete email → "Missing items" email → Re-send complete email → Acknowledgment → Decision
Setup: Test candidate email. First email has resume only (no GitHub, no portfolio).
Assertions:
- "Missing items" email correctly identifies GitHub and portfolio as missing
- After re-sending with all items, evaluation proceeds normally
- Only one active evaluation exists (not two separate records)
- Dashboard shows candidate with correct final status
Teardown: Delete test candidate record.

---

**E2E Test: Duplicate Application (P0)**
Flow: Send complete application → Receive decision → Send updated application → Receive new acknowledgment → New evaluation replaces old
Setup: Two different resume PDFs for the same test email address.
Assertions:
- Second submission triggers "got your update" email
- Dashboard shows only one active record for this email
- Old evaluation marked as "superseded" in DB
- New evaluation uses the new resume data
Teardown: Delete test records.

---

**E2E Test: Edge Case — Gibberish (P0)**
Flow: Send gibberish email → Receive fun response → No evaluation created
Setup: Test email with random characters.
Assertions:
- Response email received, is lighthearted and appropriate
- No candidate evaluation record in DB
- Log entry exists with classification "gibberish"
Teardown: None needed.

---

**E2E Test: Edge Case — Non-PDF Attachment (P0)**
Flow: Send email with .docx instead of PDF → Receive "wrong format" email
Setup: Test email with a .docx attachment.
Assertions:
- Response email asks for PDF format specifically
- Candidate status is "Incomplete"
- Log entry captures the file type detected
Teardown: Delete test record.

---

**E2E Test: Dashboard — Google SSO Login (P0)**
Flow: Navigate to dashboard URL → Google SSO → Redirect to dashboard → See application table
Setup: Authorized Google account.
Assertions:
- Unauthenticated access redirects to Google SSO
- After login, dashboard loads with application table
- Unauthorized Google accounts are denied access
Teardown: None.

---

**E2E Test: Dashboard — Manual Review Action (P0)**
Flow: Login → Filter by "Manual Review" → Click candidate → Click "Pass" → Confirm → Email sent
Setup: Seed a candidate record with score 55, status "Manual Review."
Assertions:
- Candidate appears in filtered view
- Detail view shows all scores and reasoning
- After clicking Pass and confirming, status changes to "Passed (Manual)"
- Pass email received by test candidate email
Teardown: Delete test record.

---

**E2E Test: Dashboard — Settings Update (P1)**
Flow: Login → Settings → Change weights → Save → Submit new application → Verify new weights applied
Setup: Current weights at defaults. New application ready.
Assertions:
- Settings save successfully
- New application evaluated with updated weights
- Old evaluations unchanged
Teardown: Restore default weights.

---

**E2E Test: Dashboard — Poll Now (P1)**
Flow: Login → Send email → Click "Poll Now" → New application appears
Setup: Application email sent but polling hasn't triggered yet.
Assertions:
- Before poll: application not visible
- After poll: application appears in table within seconds
Teardown: Delete test record.

---

**E2E Test: Infrastructure Retry — GitHub API Failure (P1)**
Flow: Application submitted → GitHub API simulated failure → Retries → Eventually succeeds → Evaluation completes
Setup: Mock or intercept GitHub API to return 5xx for first 2 attempts, then succeed.
Assertions:
- Retry log entries present with timestamps
- Evaluation eventually completes with GitHub data
- Candidate score includes GitHub dimension
- Candidate was NOT penalized for the delay
Teardown: Remove mock. Delete test record.

---

**E2E Test: Reminder Flow (P1)**
Flow: Incomplete application → "Missing items" email → Wait for reminder period → Reminder email sent → No further auto-reminders
Setup: Incomplete application. Reminder period set to short interval for testing.
Assertions:
- First "missing items" email received immediately
- Reminder email received after configured period
- No third email sent after another waiting period
- Candidate status remains "Incomplete"
Teardown: Delete test record. Restore reminder period.

---

**E2E Test: Secondary Source Discovery — GitHub in Portfolio (P1)**
Flow: Application with no GitHub in email → Agent finds GitHub on portfolio page → Evaluates normally
Setup: Portfolio page that contains a GitHub link. Email does not include GitHub link.
Assertions:
- Agent does NOT send "missing GitHub" email
- GitHub data is fetched and scored
- Log shows "GitHub discovered from portfolio page"
Teardown: Delete test record.

---

**E2E Test: Secondary Source Discovery — Resume in Portfolio (P1)**
Flow: Application with no resume attached → Agent finds downloadable resume on portfolio page → Evaluates normally
Setup: Portfolio page with a linked PDF resume. Email has GitHub and portfolio links but no attachment.
Assertions:
- Agent does NOT send "missing resume" email
- Resume is downloaded from portfolio and parsed
- Log shows "Resume discovered from portfolio page"
- Evaluation includes resume-derived data
Teardown: Delete test record.

---

**E2E Test: Graceful Degradation — Completely Broken Input (P0)**
Flow: Send email with massive attachment, empty body, no links → Agent responds without crashing
Setup: Email with large zip file, no body text.
Assertions:
- Agent does not crash or enter error state
- Response email sent (fun, appropriate)
- Log entry captures the edge case
- Agent continues to process subsequent emails normally
Teardown: None.

---

**E2E Test: Concurrent Applications in Same Poll Cycle (P0)**
Flow: 5 different candidates email simultaneously → All processed in same polling cycle → No cross-contamination
Setup: 5 test emails from 5 different addresses, each with unique resume/GitHub/portfolio data. All sent before the next poll.
Assertions:
- All 5 receive acknowledgment emails addressed to the correct candidate
- All 5 evaluations appear on dashboard with correct data (no candidate A getting candidate B's scores)
- Each evaluation references the correct resume, GitHub, and portfolio data
- No shared state leaks between evaluations (verify by checking unique data points per candidate)
- All processing logs are correctly tagged to the right candidate
Teardown: Delete all 5 test records.

## 10. Metrics

| Metric | Measures | Capture Point | Target |
|--------|----------|---------------|--------|
| Acknowledgment latency | Time from email received to acknowledgment sent | Timestamp diff: email received → ack email sent | < 2x polling interval |
| Evaluation latency | Time from email received to decision made | Timestamp diff: email received → score computed | < 5 minutes |
| Decision email latency | Time from evaluation complete to decision email sent | Timestamp diff: score computed → email sent | < 30 seconds |
| Edge case classification accuracy | % of non-application emails correctly classified | Manual review of classification logs (sample) | > 90% |
| Pass/fail accuracy | % of auto-pass/auto-fail decisions hiring manager agrees with | Hiring manager overrides on dashboard vs. auto-decisions | < 10% override rate |
| Incomplete recovery rate | % of incomplete applications that become complete after "missing items" email | Count: incomplete → evaluated / total incomplete | > 50% |
| Infrastructure retry success rate | % of retried requests that eventually succeed | Retry queue resolution logs | > 95% |
| Agent uptime | % of time the polling service is running and responsive | Health check endpoint | > 99% |
| Dashboard load time | Time to load the application table | Frontend performance measurement | < 2 seconds |
| Processing error rate | % of applications that end in "Processing Error" status | DB status counts | < 2% |
| Email bounce rate | % of outbound emails that bounce or fail to deliver | Gmail API delivery status | < 1% |
| Duplicate detection accuracy | % of duplicate applications correctly identified | Audit of duplicate vs. new records | > 98% |

---

## Appendix A: Email Templates — Tone & Structure

All candidate-facing emails follow a consistent structure. The body remains the same; scenario-specific text is injected as a middle section.

### Base Template Structure

```
Subject: [Scenario-specific subject line]

Hey [Candidate First Name]! 👋

[Scenario-specific opening — 1-2 sentences, sets the context]

[Scenario-specific body — the actual message, 2-4 sentences]

[Scenario-specific CTA or sign-off — what to do next, if anything]

Cheers,
The [Company Name] Hiring Bot 🤖
(Yes, I'm an AI. But I promise I read every word.)

---
This is an automated message from [Company Name]'s hiring system.
If you think something went wrong, reply to this email and a human will take a look.
```

### Scenario-Specific Text Blocks

**1. Acknowledgment (Complete Application)**
> Subject: We got your application — and we're already impressed 👀
>
> Your application just landed and it's already making friends with the other resumes in our inbox.
>
> We've got your resume, spotted your GitHub, and found your portfolio. Our review bots are warming up their reading glasses as we speak. Expect to hear from us soon.
>
> Sit tight — good things are coming.

**2. Pass Decision**
> Subject: You made the cut! 🎉 Here's what's next
>
> We've reviewed your application and — drumroll — you've caught our attention.
>
> Your profile stood out and we'd love to take this further. [Configurable next steps text inserted here]
>
> Looking forward to the next chapter!

**3. Fail Decision (Lite, Warm Close)**
> Subject: Thanks for applying to [Company Name] 🙏
>
> Thanks for sharing your work with us — we mean that. It takes effort to put yourself out there.
>
> For this particular role, we're going to explore a few other directions. [Brief, gentle reason — 1 sentence max, e.g., "We're looking for a bit more depth in production deployments."]
>
> Keep building — and don't be a stranger if future roles catch your eye.

**4. Missing Items (General)**
> Subject: Almost there — we just need a couple more things 📎
>
> We got your email and we're excited to dig in — but we're missing a few pieces of the puzzle.
>
> Here's what we still need: [bulleted list of missing items]. Just reply to this email with the missing bits and we'll take it from there.
>
> Almost there — we're rooting for you!

**5. Non-PDF Attachment**
> Subject: Quick heads up about your resume format 📄
>
> We got your application — thanks for sending it over! One small thing though: we spotted an attachment, but it's not in PDF format.
>
> Could you re-send your resume as a PDF? It helps our systems parse everything smoothly. Just reply to this email with the PDF attached and we'll pick right back up.
>
> Small ask, big impact!

**6. Duplicate / Updated Application**
> Subject: Updated application received! 🔄
>
> Look who's back! We got your updated application and consider the old one officially retired.
>
> We're reviewing your latest and greatest now. Same process as before — sit tight and we'll be in touch soon.
>
> Thanks for keeping us on our toes!

**7. Gibberish / Unreadable**
> Subject: We got your email but... we're a bit confused 🤔
>
> We received your email and gave it our best shot, but we couldn't quite figure out what it says. Our AI is smart, but apparently not THAT smart.
>
> If you meant to apply for a role, here's what we need: a resume (PDF), a link to your GitHub profile, and a link to your portfolio or projects. Just reply to this email with those and we'll get the ball rolling.
>
> No judgment — inboxes are weird sometimes.

**8. Spam / Sales Email**
> Subject: Re: Your email
>
> Appreciate the hustle — truly. But this inbox is reserved for job applications, not product pitches.
>
> If you ARE a human looking for a role though, we'd love to hear from you. Send us your resume (PDF), GitHub link, and portfolio link, and we'll give your application the attention it deserves.
>
> Good luck out there!

**9. Question About the Role**
> Subject: Great question! Here's the scoop 💡
>
> Thanks for reaching out! We love the curiosity.
>
> [AI-generated answer to their specific question, kept brief and helpful]. When you're ready to apply, just reply to this email (or send a fresh one) with your resume (PDF), GitHub link, and portfolio link.
>
> We hope to see your application soon!

**10. Empty Email (No Body, No Attachments)**
> Subject: We got your email — but it was a bit... empty 📭
>
> Looks like your email came through without any content or attachments. It happens to the best of us.
>
> To apply, send us: a resume (PDF attachment), a link to your GitHub profile, and a link to your portfolio or projects. Reply to this email with all three and you're good to go.
>
> We'll be here when you're ready!

**11. Auto-Reply / Out-of-Office**
> [NO RESPONSE SENT — logged and ignored]

**12. Portfolio is LinkedIn**
> Subject: Quick note about your portfolio link 🔗
>
> We see you shared your LinkedIn profile — and we appreciate the transparency! But we're actually looking for a portfolio or project showcase: a personal site, a GitHub Pages project, a Behance, or anything that shows off what you've built.
>
> LinkedIn is great for networking, but we want to see your work in action. Reply with a link to your projects and we'll pick things right back up.
>
> Show us what you've built!

**13. GitHub Profile 404 / Private**
> Subject: We couldn't access your GitHub profile 🔒
>
> We tried checking out your GitHub profile, but it looks like the link doesn't work or the profile might be set to private.
>
> Could you double-check and send us an updated link? Make sure your profile is set to public so we can see your repos and contributions. Reply to this email with the corrected link and we'll take it from there.
>
> We're eager to see your code!

**14. Portfolio URL is Down**
> Subject: Heads up — your portfolio link isn't loading 🌐
>
> We tried visiting your portfolio but the link seems to be down or not loading. It might be a temporary thing, but we wanted to let you know.
>
> Could you double-check the URL and send us an updated link if needed? Reply to this email and we'll retry.
>
> We really do want to see your work!

**15. Reminder (Missing Items Follow-Up)**
> Subject: Friendly nudge about your application 👋
>
> Hey, just a quick reminder — we're still waiting on a few things to complete your application.
>
> We still need: [same bulleted list of missing items]. No rush... okay, maybe a little rush. We've got reviewers ready to go and we'd hate for your application to go stale.
>
> Reply to this email with the missing pieces and we'll jump right on it!

**16. Multiple Rapid Emails (Candidate Correcting Themselves)**
> Subject: Got it — we're on it! ✅
>
> We noticed a few emails from you in quick succession (we've all been there). Don't worry — we've grabbed the latest one with all the goods.
>
> We're reviewing your most recent submission now. You can relax — one application, fully received.
>
> Stay tuned!

**17. Unclassifiable But Not Gibberish**
> Subject: Thanks for your email! Quick question though 🤔
>
> We got your email and appreciate you reaching out. We're not 100% sure if this was meant to be a job application though.
>
> If you're looking to apply, here's what we need: resume (PDF), GitHub link, and portfolio link. If you had a different question, just reply and let us know — a human on our team will get back to you.
>
> Either way, glad you're here!

---

## Appendix B: V2+ Features (Explicitly Out of Scope for V1)

1. **Multi-role matching** — Agent automatically routes candidates to the best-fit open role.
2. **Candidate status checking via email** — Candidates email to ask "where's my application?"
3. **Recruiter-triggered third reminder** — Dashboard button to send a final follow-up for incomplete applications.
4. **Specific actionable feedback in rejection emails** — Detailed improvement tips.
5. **Interview scheduling** — Agent coordinates calendar availability between candidate and interviewers.
6. **Scanned/image PDF handling** — OCR for resumes that are scanned images.
7. **Password-protected PDF handling** — Prompt candidate to re-send unlocked.
8. **Non-English resume handling** — Translation or multilingual parsing.
9. **Name mismatch detection** — Flag when GitHub profile name doesn't match resume name.
10. **Email thread handling** — Parse forwarded chains or reply threads.
11. **Hyperlinked text extraction** — Parse "click here" links in email body.
12. **Inline images as resume** — Detect when resume is pasted as images instead of PDF.
13. **Candidate database / talent pool** — Persist all candidates for future role outreach.
14. **Dashboard: hiring manager feedback/notes** — Add comments on candidate evaluations.
15. **Dashboard: team collaboration** — Multiple reviewers with role-based permissions.
16. **Dashboard: export to CSV/Excel** — Download candidate data.
17. **Analytics dashboard** — Funnel metrics, time-to-hire, pass rates over time.
18. **Webhook integration** — Push evaluation events to Slack, ATS systems, etc.

**18. Tech Stack**

> Python + FastAPI + PostgreSQL (Railway) + Gmail API 

> Claude (Sonnet + Opus) + PyMuPDF + python-docx 

> GitHub REST API + Playwright + Railway + Python structured logging