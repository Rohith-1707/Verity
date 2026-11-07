# VERITY – Evidence-Driven Intelligent Brand Governance Platform

> Every claim needs evidence. Every publication needs accountability.

VERITY checks content against approved organisational documents and brand guidelines, explains every issue, screens the text with AI, and leaves the final decision to a human reviewer. Light and dark modes are both supported.

## Contents

- [Core workflow](#core-workflow)
- [Features](#features)
- [Roles and access](#roles-and-access)
- [How verification works](#how-verification-works)
- [Risk scoring](#risk-scoring)
- [Data storage](#data-storage)
- [Project structure](#project-structure)
- [Running and hosting](#running-and-hosting)
- [Manual test checklist](#manual-test-checklist)
- [Security notes](#security-notes)
- [Known limitations](#known-limitations)
- [Roadmap](#roadmap)

## Core workflow

1. The owner (administrator) adds approved documents, prohibited terms and required text.
2. A creator submits content with its context: audience, purpose, platform, category, tone and deadline.
3. Rule-based checks compare claims to approved evidence and apply the brand guidelines.
4. AI screening reads the whole text and flags credibility signals for experts to check.
5. A transparent, weighted risk assessment is produced.
6. The submission enters a prioritised review queue.
7. A reviewer records a genuineness judgement (Genuine, Misleading or Cannot determine) and approves, requests a revision or rejects.
8. Every decision and action is written to the audit log.

High-risk content is never approved automatically. It needs a human decision with a written justification.

## Features

**Original innovations**

- **Evidence-linked claim verification.** Each claim is classified as verified, unsupported, contradictory, potentially outdated or needing human review. Findings show the source document, version, dates and passage. Where evidence is missing, the finding says so. Nothing is invented.
- **Cross-content change impact analysis.** When an approved document is replaced by a new version, registered submissions that still carry the old wording are flagged, with the affected sentence and its location. Reviewers can mark each one resolved.
- **Adaptive governance intelligence.** Recurring issues in content that reviewers sent back become suggestions for administrators. Guidelines are never changed automatically.

**Enhancements**

- **Evidence freshness.** Tracks version, effective date, review date and current or superseded status. A claim supported by a source past its review date, or matching only a superseded version, is warned about. Missing dates are shown as uncertainty.
- **Explainable risk scoring.** Weighted factors with editable weights.
- **Revision tracking.** Word-level diff between versions, with resolved, still unresolved and newly introduced issues.
- **Brand health score.** A 0 to 100 indicator with its formula, data period and an empty state when there is no data.
- **Context-aware checking.** Tone context affects advisory checks only. Mandatory rules always apply.
- **Review prioritisation.** Ranked by risk, contradictions, open issues, deadline and age, with filters and sorting. In-app notifications only. No email or messaging is sent.

**Pages**

Public: landing page with features, how it works and about sections, plus sign-in.
Signed in: Dashboard, Content Verification, Review and Approval, Verification Reports (with per-report detail), Knowledge Base, Brand Guidelines, Change Impact, Governance Intelligence, Brand Health, Audit History, Settings and the Owner Console.

## Roles and access

| Role | How you get it | What it can do |
|---|---|---|
| Owner (administrator) | You are the account that owns the hosted app | Manage documents and guidelines, set risk weights, view governance and audit pages, use the Owner Console, view the app as any role |
| Reviewer | Chosen at sign-in | Inspect submissions, view evidence and AI screening, record judgements, approve, request revision or reject, resolve impact alerts |
| Creator | Chosen at sign-in | Submit content, view findings, revise and resubmit, track status |

Administrator cannot be chosen by anyone except the owner. The owner-only pages are hidden from other users, and the database rejects document and settings writes from non-owners.

## How verification works

1. Input validation (required fields, 20,000-character limit for content).
2. Claim extraction: sentences with numbers, number words or claim-like words (for example guarantee, best, only, free, warranty).
3. Evidence retrieval: keyword overlap against passages of approved documents, with current and superseded versions searched separately.
4. Comparison: numbers in the claim are compared to numbers in the best passage. A mismatch is contradictory. A weak or ambiguous match goes to human review.
5. Freshness check against review dates and superseded versions.
6. Guideline check: prohibited terms and required text, plus an advisory tone check.
7. AI screening of the whole text for credibility signals such as sensational wording, unsourced claims, suspicious statistics and urgency pressure.
8. Risk assessment and report generation.
9. Human review.

Matching is keyword-based, not semantic embeddings. Uncertain matches are routed to people rather than passed as verified. The AI has no internet access and cannot confirm facts. Its output is advisory and is not evidence.

If AI screening fails or is not permitted, the creator sees an error and can choose to submit without it. Reviewers see that the screening was skipped.

## Risk scoring

Default weights, editable by the owner in Settings:

| Factor | Weight |
|---|---|
| Contradictory claim | 30 |
| Outdated evidence | 20 |
| Unsupported claim | 15 |
| Guideline violation | 12 |
| Missing required text | 10 |
| Needs human review | 8 |
| AI signal | 5 |
| Tone (advisory) | 3 |

Levels: **High** if any claim is contradictory or the total is 30 or more, **Medium** at 10 or more, otherwise **Low**. Every report shows the factor table. A risk level is a triage aid, not a guarantee of factual correctness.

## Data storage

Shared data is kept in the hosting platform's database as JSON documents.

| Collection | Contents | Who can write |
|---|---|---|
| `accounts` | Display name, organisation, role, timestamps, blocked flag, keyed by account ID | Owner, plus each person for their own record. Only the owner can read the list |
| `docs` | Approved documents and versions | Owner only |
| `cfg` | Guidelines and risk weights | Owner only |
| `subs` | Submissions, versions, findings, decisions | Signed-in contributors |
| `impacts` | Change impact alerts | Signed-in contributors |
| `notes` | In-app notifications | Signed-in contributors |
| `audit` | Audit log | Signed-in contributors |

Each browser stores only the signed-in display name and organisation. Passwords are not stored. Identity comes from the hosting platform's account.

## Project structure

The project has three source files and no build step:

```
index.html     Page shell
style.css      Design tokens, light and dark themes, layout
app.js         Engine, pages, router, database sync
README.md      This file
```

`style.css` holds the design tokens for light and dark mode. `app.js` holds the verification engine (`verify`, `risk`, `diff`, `impact`, `aiScan`), the page renderers (`P.*`), a hash router (`route`) and the database sync layer (`sync`, `listen`).

## Running and hosting

The sign-in, owner access, shared database, AI screening and downloads rely on runtime features of the platform that hosts this page. Opening the file locally or on GitHub Pages will load the interface, but sign-in will report that the account database is unavailable.

To run it elsewhere, replace the platform-specific calls (`claude.use('user' | 'db' | 'sample' | 'downloads')` in the code) with your own services. A typical setup:

| Need | Suggested replacement |
|---|---|
| Accounts and owner-only access | Supabase Auth with row-level security |
| Database | Supabase PostgreSQL (tables matching the collections above) |
| Document storage | Supabase Storage |
| AI screening | A small server (for example FastAPI) calling an LLM API, with the key kept in server environment variables |
| Page hosting | GitHub Pages, Vercel or Netlify |

Never put private API keys in the front-end code.

## Manual test checklist

1. Sign in as the owner. Load the sample dataset from the dashboard, or add your own documents and guidelines.
2. Sign in as a creator. Open Content Verification, insert the sample content and submit. Expect a verified claim, a contradictory claim, an unsupported claim, a guideline violation, missing required text, a High risk level and an AI screening panel.
3. Sign in as a reviewer. Open the queue, open the report, choose a genuineness judgement and record a decision. High-risk approval needs a justification.
4. As the creator, revise and resubmit. Check the diff and the resolved, unresolved and new issue lists.
5. As the owner, add the Product Warranty Policy again with changed wording. Open Change Impact and confirm the affected content is flagged.
6. Check Brand Health, Governance Intelligence and Audit History.
7. Switch between light and dark mode and test on a narrow screen.

## Security notes

- Owner-only pages are enforced by the database rules, not only by hiding menus.
- Creators and reviewers share submission data. Do not treat submissions as secret from other signed-in contributors.
- Blocking an account affects access inside this app only.
- Content shown on pages is escaped before rendering.
- No automated tests, rate limiting or server-side file scanning exist yet.

## Known limitations

- Only pasted text and `.txt` files are accepted. PDF, DOCX and image extraction need a server.
- Evidence matching is keyword-based. A semantic model would catch paraphrases better.
- Documents are limited to about 200,000 characters each.
- Change impact scans registered submissions only. It does not monitor external websites.
- There are no email or messaging notifications.
- Concurrent edits to one record use last write wins.
- No automated test suite and no production deployment configuration are included.

## Roadmap

1. Server component (FastAPI) for PDF, DOCX and image extraction.
2. Semantic retrieval with sentence embeddings and a vector store.
3. Migration to Supabase with row-level security for portable hosting.
4. Automated backend and front-end tests.
5. Approval step for new reviewers.
6. Split the front end into modules with a build step.
