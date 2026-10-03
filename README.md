# Automated Job Search

A daily remote-job hunt run from [Claude Code](https://claude.com/claude-code). `/hunt` collects new jobs from job boards and alert emails, filters out poor fits and scams, scores the rest, drafts honest applications for the best ones and tracks every job on a local board.

It never applies for you. You read each draft and submit it yourself.

## How it works

- **Sources.** Five open remote boards with public feeds: Remote OK, We Work Remotely, Himalayas, Remotive and Hacker News "Who is hiring". OnlineJobs.ph search, logged out. JobStreet and job-alert emails in Gmail, through the Claude in Chrome extension. Indeed jobs come from alert emails only.
- **Filter.** Rejects on-site jobs, jobs limited to other countries, non-software work, scam signs and senior roles. Rejected jobs are kept, so they never come back.
- **Score.** 0 to 100 for fit, level, work style, legitimacy, freshness and pay. 70+ gets an application, 50 to 69 becomes a lead.
- **Honest applications.** Every number in a draft must appear in `facts.md` or the job post, and claims on a "do not claim" list are blocked. `board.py` refuses to save a job that fails a check.
- **Board.** `board.html` with columns from Leads to Won. Served locally, its buttons mark a job applied or remove it.

The run itself is [`.claude/skills/hunt/SKILL.md`](.claude/skills/hunt/SKILL.md). The design is in [`docs/superpowers/specs/`](docs/superpowers/specs/2026-10-01-job-hunt-pipeline-design.md).

## Requirements

- Python 3, standard library only.
- Claude Code, for `/hunt`.
- Optional: the [Claude in Chrome](https://claude.ai/chrome) extension, for JobStreet and Gmail. Without it those two sources are skipped and named on the board.

## Setup

1. Clone the repo.
2. Create your private files. They are gitignored, so they stay on your machine:
   - `facts.md`: everything true about you that an application may claim. Contact details and links, rate, skills, projects with real numbers, and a "Do not claim" list. Required: every application is checked against it.
   - `answers.md`: stock answers to screening questions, such as time zone, work authorization, expected rate and links.
   - `jobs.json` is created on the first run.
3. Make `DO_NOT_CLAIM` in `board.py` match your "Do not claim" list.
4. Adjust the search to you: the keywords in `SKILL.md`, and the location filter (`OPEN` and `HIMALAYAS`) in `feeds.py`, which is set to jobs open to the Philippines.

`py` is the Windows Python launcher. Use `python3` elsewhere.

## Use

In Claude Code, in this folder:

    /hunt

Open the board:

    py -X utf8 board.py serve

Then go to http://127.0.0.1:8765. Opening `board.html` from disk works too, but its buttons need the server.

Other commands:

| Command | Does |
|---|---|
| `py -X utf8 board.py` | Check `jobs.json` and rebuild `board.html` |
| `py -X utf8 board.py move 12=applied 9=talking 3=lost` | Change statuses (or tell Claude "applied 12") |
| `py -X utf8 board.py apply FILE` | Add or update jobs from a changes file |
| `py -X utf8 feeds.py` | Fetch the open boards into `.hunt/inbox.json` |
| `py -X utf8 feeds.py show 3 7` | Print the posts of inbox items 3 and 7 |
| `py -X utf8 -m unittest test_jobhunt` | Run the tests |

Statuses: leads, high, needs-action, applied, talking, interview, won, lost, rejected.

## Privacy

Personal files never go in the repo: `jobs.json`, `facts.md`, `answers.md` and resume files are listed in `.gitignore`. Before each run, `/hunt` copies `jobs.json` to `.hunt/jobs-YYYY-MM-DD.json`. To undo a bad run, copy that file back.
