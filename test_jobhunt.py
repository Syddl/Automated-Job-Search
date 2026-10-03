"""Run: py -X utf8 -m unittest test_jobhunt -v"""
import datetime as dt
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

import board
import feeds

FACTS = "Cost: $0.876 per output minute over 47 real jobs. Rounded: under $0.90. 40 h/week. UTC+8."


def record(**overrides):
    job = {
        "id": 1, "source": "olj", "url": "https://example.com/job/1", "title": "AI Developer", "company": "Acme",
        "pay": "$6/hour", "posted": "2026-10-01", "found": "2026-10-01", "post": "Need 2 years of Python.",
        "score": 82, "why": "Claude API pipeline work", "flags": [], "status": "high", "reason": None,
        "application": {
            "subject": "AI Developer application",
            "body": "I kept cost under $0.90 per minute across 47 real jobs. I can work 40 hours a week, UTC+8. You asked for 2 years.",
        },
        "apply_points": 2, "history": [{"date": "2026-10-01", "status": "high"}],
    }
    job.update(overrides)
    return job


def data(*jobs):
    return {"last_run": None, "jobs": list(jobs)}


class CheckTest(unittest.TestCase):
    def test_clean_record_passes(self):
        self.assertEqual(board.check(data(record()), FACTS), [])

    def test_invented_number_fails(self):
        errors = board.check(data(record(application={"body": "I cut costs by 60% across 47 jobs."})), FACTS)
        self.assertEqual(errors, ["#1: number 60 is not in facts.md or the post"])

    def test_do_not_claim_term_fails(self):
        errors = board.check(data(record(application={"body": "I built a RAG search over 47 real jobs."})), FACTS)
        self.assertEqual(errors, ["#1: 'RAG' is on the Do not claim list"])

    def test_high_priority_needs_an_application(self):
        self.assertIn("#1: high priority needs an application", board.check(data(record(application=None)), FACTS))

    def test_linkedin_note_is_at_most_300_characters(self):
        errors = board.check(data(record(application={"note": "a" * 301})), FACTS)
        self.assertEqual(errors, ["#1: LinkedIn note is over 300 characters"])

    def test_rejected_needs_no_score_and_ids_and_links_are_unique(self):
        rejected = record(id=2, url="https://example.com/job/2", status="rejected", score=None, application=None)
        self.assertEqual(board.check(data(record(), rejected), FACTS), [])
        self.assertEqual(board.check(data(record(), record()), FACTS),
                         ["#1: id must be a unique integer", "#1: url must be a unique http(s) link"])

    def test_link_must_be_http(self):
        errors = board.check(data(record(url="javascript:alert(1)")), FACTS)
        self.assertEqual(errors, ["#1: url must be a unique http(s) link"])

    def test_real_facts_accept_the_portfolio_rounding(self):
        facts = board.FACTS.read_text(encoding="utf-8")
        self.assertTrue({"0.90", "90", "680"} <= board.numbers(facts))


class ApplyTest(unittest.TestCase):
    def test_adds_from_inbox_then_moves(self):
        d = data(record())
        inbox = [{"n": 4, "source": "wwr", "url": "https://wwr.example/9", "title": "Full-stack Engineer", "company": "Beta",
                  "pay": None, "posted": "2026-09-30", "post": "Remote, anywhere.", "location": "Anywhere in the World"}]
        changes = {"run": {"failed_sources": ["remotive: HTTP Error 403"]},
                   "jobs": [{"inbox": 4, "status": "leads", "score": 61, "why": "React and Node"}]}
        board.apply_changes(d, changes, inbox, "2026-10-02 09:00")
        new = d["jobs"][1]
        self.assertEqual((new["id"], new["source"], new["found"], new["status"]), (2, "wwr", "2026-10-02", "leads"))
        self.assertEqual(new["history"], [{"date": "2026-10-02", "status": "leads"}])
        self.assertEqual(d["last_run"], {"at": "2026-10-02 09:00", "failed_sources": ["remotive: HTTP Error 403"]})
        board.move(d, ["2=applied"], "2026-10-03 10:00")
        self.assertEqual(d["jobs"][1]["status"], "applied")
        self.assertEqual(d["jobs"][1]["history"][-1], {"date": "2026-10-03", "status": "applied"})
        self.assertEqual(board.check(d, FACTS), [])

    def test_duplicate_link_is_skipped_and_rejected_jobs_drop_the_post(self):
        d = data(record())
        notes = board.apply_changes(d, {"jobs": [
            {"source": "olj", "url": "https://example.com/job/1", "title": "Same", "company": "Acme", "status": "leads", "score": 60},
            {"source": "indeed", "url": "https://example.com/job/2", "title": "Onsite dev", "company": "Gamma",
             "status": "rejected", "reason": "on-site", "post": "long text"},
        ]}, [], "2026-10-02 09:00")
        self.assertEqual(notes, ["skipped duplicate https://example.com/job/1"])
        self.assertEqual(len(d["jobs"]), 2)
        self.assertIsNone(d["jobs"][1]["post"])
        self.assertEqual(board.check(d, FACTS), [])


class RenderTest(unittest.TestCase):
    def test_escapes_post_text_and_tags_follow_ups(self):
        applied = record(id=2, url="https://example.com/job/2", status="applied", title="<script>alert(1)</script>",
                         history=[{"date": "2026-09-20", "status": "applied"}])
        page = board.render(data(record(), applied), dt.date(2026, 10, 1))
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertIn("follow up?", page)
        self.assertIn('Ready to apply</h2><span class="count">1</span>', page)

    def test_ready_cards_have_a_mark_applied_button(self):
        page = board.render(data(record()), dt.date(2026, 10, 1))
        self.assertIn('data-move="1" data-status="applied"', page)

    def test_ready_cards_and_leads_have_a_remove_button(self):
        lead = record(id=2, url="https://example.com/job/2", status="leads", application=None)
        page = board.render(data(record(), lead), dt.date(2026, 10, 1))
        self.assertIn('data-move="1" data-status="rejected"', page)
        self.assertIn('data-move="2" data-status="rejected"', page)

    def test_empty_board_says_what_to_do(self):
        page = board.render(data(), dt.date(2026, 10, 1))
        self.assertIn("Nothing ready. Run /hunt in Claude Code.", page)
        self.assertIn("Last run never", page)


class ServeTest(unittest.TestCase):
    def test_board_button_moves_a_job_and_plain_posts_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            with mock.patch.multiple(board, JOBS=tmp / "jobs.json", BOARD=tmp / "board.html", FACTS=tmp / "facts.md"):
                board.FACTS.write_text(FACTS, encoding="utf-8")
                board.JOBS.write_text(json.dumps(data(record())), encoding="utf-8")
                server = board.HTTPServer(("127.0.0.1", 0), board.Handler)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                self.addCleanup(server.server_close)
                self.addCleanup(server.shutdown)

                def post(kind, job_id=1):
                    body = json.dumps({"id": job_id, "status": "applied"}).encode()
                    request = urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}/move", body,
                                                     {"Content-Type": kind})
                    try:
                        with urllib.request.urlopen(request) as response:
                            return response.status
                    except urllib.error.HTTPError as error:
                        with error:
                            return error.code

                def status():
                    return json.loads(board.JOBS.read_text(encoding="utf-8"))["jobs"][0]["status"]

                self.assertEqual(post("text/plain"), 403)  # what a form on another site could send
                self.assertEqual(status(), "high")
                self.assertEqual(post("application/json", job_id=99), 400)  # no such job; server keeps running
                self.assertEqual(post("application/json"), 200)
                self.assertEqual(status(), "applied")


class FeedTest(unittest.TestCase):
    def test_remoteok_skips_the_legal_notice(self):
        raw = json.dumps([{"legal": "x"}, {
            "url": "https://remoteOK.com/remote-jobs/1", "position": "AI Engineer", "company": "Acme ",
            "date": "2026-10-01T08:00:00+00:00", "description": "<p>Build &amp; ship</p>", "location": "Worldwide",
            "salary_min": 0, "salary_max": 0}])
        [job] = feeds.parse_remoteok(raw)
        self.assertEqual((job["title"], job["company"], job["posted"], job["post"], job["pay"]),
                         ("AI Engineer", "Acme", "2026-10-01", "Build & ship", None))

    def test_wwr_splits_company_and_title(self):
        raw = """<rss><channel><item><title>Beta: Full-Stack Developer</title><region>Anywhere in the World</region>
        <description>&lt;p&gt;Next.js&lt;/p&gt;</description><pubDate>Thu, 01 Oct 2026 07:30:56 +0000</pubDate>
        <link>https://weworkremotely.com/remote-jobs/beta-full-stack</link></item></channel></rss>"""
        [job] = feeds.parse_wwr(raw)
        self.assertEqual((job["company"], job["title"], job["posted"], job["location"], job["post"]),
                         ("Beta", "Full-Stack Developer", "2026-10-01", "Anywhere in the World", "Next.js"))

    def test_himalayas_reads_restrictions_and_epoch(self):
        raw = json.dumps({"jobs": [{
            "guid": "https://himalayas.app/companies/c/jobs/x", "title": "Full Stack Engineer", "companyName": "Gamma",
            "pubDate": 1790859294, "description": "<p>Python</p>", "locationRestrictions": ["Philippines", "India"],
            "minSalary": 30000, "maxSalary": 40000, "currency": "USD", "salaryPeriod": "annual"}]})
        [job] = feeds.parse_himalayas(raw)
        self.assertEqual((job["posted"], job["location"], job["pay"]),
                         ("2026-10-01", "Philippines, India", "USD 30,000-40,000/annual"))

    def test_remotive_keeps_software_jobs_only(self):
        raw = json.dumps({"jobs": [
            {"url": "https://remotive.com/remote-jobs/software-dev/a-1", "title": "Python Developer", "company_name": "Delta",
             "category": "Software Development", "publication_date": "2026-09-30T10:00:00", "description": "<p>API</p>",
             "candidate_required_location": "Worldwide", "salary": ""},
            {"url": "https://remotive.com/remote-jobs/all-others/b-2", "title": "Content Reviewer", "company_name": "E",
             "category": "All others", "publication_date": "2026-09-30T10:00:00", "description": "",
             "candidate_required_location": "USA", "salary": ""}]})
        [job] = feeds.parse_remotive(raw)
        self.assertEqual((job["title"], job["pay"], job["location"]), ("Python Developer", None, "Worldwide"))

    def test_hn_keeps_remote_posts_not_locked_to_a_country(self):
        raw = json.dumps({"children": [
            {"id": 11, "created_at_i": 1790859294, "text": "Acme | AI Engineer | REMOTE (Worldwide) | Full-time<p>We use Claude."},
            {"id": 12, "created_at_i": 1790859294, "text": "Beta | Backend Engineer | Remote (US only)<p>More."},
            {"id": 13, "created_at_i": 1790859294, "text": "Gamma | Engineer | Onsite NYC<p>More."},
            {"id": 14, "created_at_i": 1790859294, "text": None}]})
        [job] = feeds.parse_hn(raw)
        self.assertEqual((job["url"], job["company"], job["title"]),
                         ("https://news.ycombinator.com/item?id=11", "Acme", "AI Engineer"))

    def test_select_filters_by_date_fit_place_and_seen(self):
        base = {"source": "wwr", "company": "X", "pay": None, "post": "", "posted": "2026-10-01", "location": ""}
        items = [dict(base, url="https://a/1", title="AI Engineer"),
                 dict(base, url="https://a/2", title="AI Engineer", posted="2026-09-20"),
                 dict(base, url="https://a/3", title="Sales Manager"),
                 dict(base, url="https://a/4", title="Python Developer", location="United States"),
                 dict(base, url="https://a/5", title="React Developer"),
                 dict(base, url="https://a/1", title="AI Engineer")]
        kept = feeds.select(items, "2026-09-28", {"https://a/5"})
        self.assertEqual([item["url"] for item in kept], ["https://a/1"])
