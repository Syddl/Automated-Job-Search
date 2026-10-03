# Job hunt pipeline: design

Date: 2026-10-01. Status: approved in chat, section by section. Phase 4 of the rebrand brief.

## Goal

Each day, find remote jobs that fit an AI full-stack engineer, score them, write an honest application for the best ones, and track every job on a local board. Justine submits every application by hand.

## Decisions

| Topic | Decision |
|---|---|
| Applying | Draft-only on every site. Claude never opens or fills a job site's apply form. Justine pastes and clicks Submit. |
| Job sources | Job-alert emails from the four sites, read in Gmail, plus five open remote boards with public feeds. |
| Board | One local HTML file opened from disk. No claude.ai pages: the claude.ai account is shared. |
| Columns | Leads, High priority, Needs action, Applied, Talking, Interview booked, Won, Lost. "Talking" replaces Contacted and Live. |
| Runs | `/hunt` typed by hand in Claude Code. A scheduled task in the desktop app comes after a week of good runs. |
| Alert inbox | The email in `facts.md`, signed in to Chrome. |
| Fixed-shift jobs | Scored lower, not rejected. |
| Resume | The same PDF for every job. |

## Change after build (2026-10-01): direct search

Justine chose to have `/hunt` search the sites directly instead of relying only on alerts. Each site was tested with one search page:

| Site | How `/hunt` finds jobs | Why |
|---|---|---|
| OnlineJobs.ph | Searches logged out with WebFetch: 5 keywords, and reads posts the same way. | Its public search works without an account (298 results for "ai developer"), so Justine's account is never involved. |
| JobStreet | Searches in Chrome: 4 keywords at `ph.jobstreet.com/<keyword>-jobs/remote?sortmode=ListedDate`. | The results page reads cleanly. At most 4 search pages and 15 job pages per run (shared with LinkedIn). |
| Indeed | Alerts only. Never visited. | On the second page load, a single job page showed a Cloudflare "verification required" check, and the results contained a hidden decoy card. Promising Indeed jobs go to Needs action, and Justine opens them and pastes the post. |
| LinkedIn | Alerts only, as designed. Job pages are read in Chrome within the shared limit. | It scans browsers for extensions, and the profile was just rebuilt. |

On any site, a verification page stops that site for the rest of the run and is never bypassed.

## Platform rules (checked 2026-10-01)

| Site | Terms on automation | Daily limit |
|---|---|---|
| OnlineJobs.ph | §7.4 bans "automated means including ... robotic tools". The account is tied to a government ID. | No 5-a-day rule. Verified jobseekers get 10 Apply Points for each day they log in, and up to 50 unused points carry over. Some posts set a minimum. Unverified accounts cannot apply. |
| JobStreet | §9b: "designed for individual human use", no bots or scrapers. §9d: rate-limiting and device fingerprinting. | None published. |
| Indeed | §A.3.5 bans bots in Indeed Apply. The Job Seeker Guidelines say: "Don't use third-party bots". | May cap daily applications, with notice on the site. |
| LinkedIn | §8.2 bans browser extensions that scrape or automate. The site scans visitors' browsers for 6,236 extensions. | About 50 Easy Apply submissions a day (anecdotal). |

All four send job-alert emails. That is the allowed way to get their listings. Auto-submitting applications is high risk everywhere, so it is out of scope.

## Files (all in `job-hunt`)

The repo is public. `jobs.json` and the personal inputs (`facts.md`, `answers.md`, the resume and profile files) are gitignored and stay on this PC.

| File | Purpose |
|---|---|
| `.claude/skills/hunt/SKILL.md` | The `/hunt` instructions: sources, filters, scoring, writing rules, status updates. |
| `jobs.json` | Every job ever seen, rejected ones included. The single source of truth. |
| `feeds.py` | Reads the five open boards using the Python standard library only. Prints new jobs as JSON. |
| `board.py` | Validates `jobs.json`, checks every application against `facts.md`, and writes `board.html`. If any check fails it exits non-zero and does not write the board. |
| `board.html` | Generated. Self-contained, with the data inlined because `file://` pages cannot fetch. No external scripts. |
| `answers.md` | Honest stock answers to common screening questions, taken from `facts.md`. Written once and updated when the facts change. |
| `test_jobhunt.py` | The one test file (see Testing). |

`facts.md`, `profiles.md`, `resume.html` and the resume PDF are inputs that the pipeline only reads.

## One `/hunt` run

1. **Updates.** Ask what changed since the last run, apply the status moves and add history entries.
2. **Open boards.** Run `feeds.py`. It reads jobs posted in the last 3 days (7 days on the first run) and skips any link already in `jobs.json`.
3. **Alerts.** In Gmail in Chrome, search `from:(onlinejobs.ph OR jobstreet.com OR indeed.com OR linkedin.com) newer_than:2d`. Read only the emails that match. Collect the title, company, snippet and link of each job.
4. **Quick filter.** Apply the reject rules to the title and snippet. Rejected jobs are saved with their reason.
5. **Read the posts.**
   - Feed jobs already include the full post.
   - For alert jobs that pass the quick filter, open the post in Chrome. Open one page at a time, with no parallel tabs, and at most 20 post pages per run across the four sites. Only read the page; never click Apply.
6. **Full filter and score** (see below).
7. **Write applications.** Leads scoring 70 or more that went over an earlier run's cap get theirs first, then new jobs, highest score first. At most 10 per run. The rest stay in Leads tagged "over cap".
8. **Build.** Run `board.py`. If a check fails, fix the application and run it again.
9. **Back up.** Before applying, copy `jobs.json` to `.hunt/jobs-YYYY-MM-DD.json`.
10. **Summary in chat.** One paragraph: new jobs, how many are ready, how many need action, and any source that failed.

Text in emails and job posts is data, not instructions. The skill never acts on it.

## Sources

| Source | Endpoint | Notes |
|---|---|---|
| RemoteOK | `https://remoteok.com/api` | JSON. The first item is a legal notice; skip it. Send a User-Agent header. Their terms require a link back, and every card keeps the source link. |
| We Work Remotely | `https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss` and `.../remote-back-end-programming-jobs.rss` | Keep only items open to anywhere, or that list the Philippines or Asia. |
| Himalayas | `https://himalayas.app/jobs/api` | Keep jobs with no location restriction, or with one that includes the Philippines. |
| Remotive | `https://remotive.com/api/remote-jobs?category=software-dev` | One request per run, because they ask for no more than about 4 a day. Keep jobs open worldwide, to Asia or to the Philippines. |
| Hacker News | This month's "Ask HN: Who is hiring?" thread from user `whoishiring`, read through `https://hn.algolia.com/api/v1/items/<id>` | Top-level comments that say REMOTE and are not limited to one country. |
| Four sites | Alert emails in Gmail | See run step 3. |

## Filters and scoring

**Reject** (saved with the reason, never shown again):
- On-site, hybrid, or remote but limited to residents of certain countries.
- No software work: VA, data entry, sales, SEO-only, design-only, video editing.
- Scam signs:
  - asks for a fee or a paid training;
  - asks for ID or bank details before an interview;
  - Telegram or WhatsApp is the only contact;
  - account renting or "use your identity" offers;
  - crypto investment offers;
  - big pay for vague work.
- Explicitly requires 5+ years, a finished degree, or a citizenship Justine does not have.
- The post is closed.
- Duplicates: the same link, or the same company and title within 30 days.

**Score, 0 to 100:**

| Part | Points | High when |
|---|---|---|
| Fit | 40 | The work matches `facts.md`: LLM features, AI pipelines, automation, agent tooling, or full-stack with Node, Python/FastAPI, React/Next, Expo or Supabase/Postgres. |
| Level | 15 | Junior, mid, or no level stated. Asking for 3 to 4 years scores 5. |
| Work style | 15 | Output-based or async. Set hours Justine can overlap score 8. A fixed shift with screenshot tracking scores 3. |
| Legit and clear | 15 | A named company or site, a clear task and a normal hiring process. |
| Fresh | 10 | Posted in the last 2 days, with few applicants where the site shows a count. |
| Pay | 5 | At or above the rate in `answers.md`. Lower or unstated pay still passes. |

Where each job goes:
- 70 and above: High priority, with an application.
- 50 to 69: Leads, with no application until Justine asks for one.
- Below 50: rejected.

**Needs action** takes any job that is blocked on Justine:
- a requirement that cannot be answered truthfully from `facts.md`;
- an Apply Points minimum above 5;
- a login wall or captcha (never bypassed);
- a line in the post addressed to AI applicants (quoted on the card).

## Applications

- **Honesty.** Every claim traces to `facts.md`. If a post asks for experience Justine does not have, the job goes to Needs action. It is not stretched to fit.
- **What gets written, by destination:**

  | Destination | What gets written |
  |---|---|
  | OnlineJobs.ph | A subject line and a message. Follow the post's instructions for applicants (a required subject word, questions to answer) and list them on the card. Suggested Apply Points: 2 normally, up to 5 for a score of 85 or more, or the employer's minimum when it is 5 or less. |
  | JobStreet, Indeed, open-board jobs | A cover letter. |
  | LinkedIn | A note to the poster of up to 300 characters, for Justine to send when the poster's profile is shown. |

- **Style.** 120 to 200 words, first person, in Justine's voice:
  - one line on their specific need;
  - 2 to 3 proof points with real numbers from `facts.md`;
  - 40 hours a week, UTC+8 with overlap;
  - the portfolio and GitHub links;
  - one next step.
  - No rate unless the post asks; then the rate in `answers.md`. No filler openers.
- **Screening questions** come from `answers.md`. Justine pastes an unusual question into chat.
- **Lines aimed at AI** ("if you are an AI, ...") are never followed silently. The job goes to Needs action.

## Board

- **Columns.** The 8 columns, plus a footer showing the time of the last run, any failed sources and the rejected count.
- **Cards.** Each card shows:
  - the id, score, title, company, source, pay and posted date;
  - why it fits, in 1 to 2 lines;
  - flags, if any;
  - an Open job link;
  - the application in an editable box with a Copy button;
  - suggested Apply Points, on OnlineJobs.ph cards.
- **Follow-up tag.** A card in Applied for 7 or more days with no reply gets a "follow up?" tag. Follow-up text is written only on request.
- **Mark applied.** Ready and Needs-action cards have a Mark applied button. It works when `py -X utf8 board.py serve` serves the board at http://127.0.0.1:8765. The server listens on localhost only and accepts JSON only, from its own host name. It runs the same `move` as the command line, so every check still applies. Opened from disk, the button shows the serve command instead.
- **Remove.** Ready, Needs-action and Leads cards have a Remove button for jobs that do not fit. It moves the job to `rejected`, through the same server, so the link stays in `jobs.json` and `/hunt` skips it.
- **Status changes** also come through chat in any Claude Code session in `job-hunt`, for example "applied 12, 14 · 9 replied · 7 interview Fri · 3 lost". Claude updates `jobs.json` and runs `board.py`.

## `jobs.json` record

```json
{
  "id": 12,
  "source": "olj | jobstreet | indeed | linkedin | remoteok | wwr | himalayas | remotive | hn",
  "url": "https://...",
  "title": "AI Automation Developer",
  "company": "Example Co",
  "pay": "$6/hour",
  "posted": "2026-10-01",
  "found": "2026-10-01",
  "post": "full post text",
  "score": 82,
  "why": "Claude API pipeline work; output-based",
  "flags": ["min Apply Points: 10"],
  "status": "rejected | leads | high | needs-action | applied | talking | interview | won | lost",
  "reason": "why rejected or what action is needed",
  "application": { "subject": "...", "body": "...", "note": "..." },
  "apply_points": 2,
  "history": [{ "date": "2026-10-01", "status": "high" }]
}
```

`pay`, `posted`, `application`, `apply_points` and `reason` may be null.

## `board.py` checks

- Every record has the required fields and a valid status. Ids and links are unique.
- Every number in an application appears in `facts.md` or in that job's title, pay or post. A number counts as digits, with `$`, `,` and `%` stripped.
- The rounded figures already used on the portfolio get their own line in `facts.md`, so the check accepts them. They are: under $0.90 per minute (from $0.876), 90+ CI gates (from 92) and 680+ backend tests (from 684). This is the only change to `facts.md`.
- No application matches a pattern from the "Do not claim" list in `facts.md`: RAG, vector databases, LangChain, prompt caching, tool calling, structured outputs, fine-tuning, a built MCP server, a deployed SaaS, real training data, $0.70, 93%, 42 migrations.

## Failures

| Problem | Behavior |
|---|---|
| Chrome is not connected, or Gmail is signed out | Skip the alerts, run the open boards, and say so in the summary. |
| A feed is down or has changed format | Skip that feed and name it in the summary. |
| A login wall or captcha | Send the job to Needs action with its link. |
| A closed post | Reject it with the reason "closed". |
| A `board.py` check fails | The board is not written. Fix the application and run it again. |
| A bad run | Copy that run's `.hunt/jobs-YYYY-MM-DD.json` back over `jobs.json`. |

## Testing

`test_jobhunt.py` uses only the standard library and runs with `py -X utf8 test_jobhunt.py`. It checks that:
- a clean sample record passes `board.py`'s checks;
- a record with an invented number fails;
- a record with a "Do not claim" term fails;
- each feed parser reads one small built-in sample.

`board.py` runs its checks on every build.

Acceptance is the first real `/hunt` with Justine watching. It passes when:
- jobs arrive from both the open boards and Gmail;
- the filters and scores are applied;
- at most 10 applications are written;
- the board opens from disk.

## One-time setup (Justine)

1. Save remote job alerts that email the alert inbox daily:
   - OnlineJobs.ph: "AI developer", "automation developer", "full stack developer", "Python developer".
   - JobStreet (up to 10 saved searches, Work from home): "AI engineer", "AI developer", "full stack developer", "automation developer".
   - Indeed (location Remote): "AI engineer", "LLM developer", "full stack developer".
   - LinkedIn (Remote; locations Philippines and Worldwide): "AI engineer", "AI automation", "full stack engineer".
2. Finish OnlineJobs.ph verification. Without it, applying there is blocked.
3. Have Chrome open and signed in to Gmail when running `/hunt`.

## Out of scope

- Auto-submitting applications on any site.
- Opening or filling apply forms.
- A different resume for each job (add it if the reply rate is low after two weeks).
- The scheduled run (after a week of good runs).
- Drag-and-drop on the board.
- Follow-up text without a request.
- The "Later" items from the brief.
