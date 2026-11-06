# Job Radar V16 (repaired V15)

## What changed
- **UNDP and IOM repaired.** V15 searched the rendered page for job links. V16 reads the public JSON
  endpoint that the career site itself uses (`recruitingCEJobRequisitions` for listings,
  `recruitingCEJobRequisitionDetails` for each vacancy, including its closing date). If that
  endpoint is refused, the optional Chromium step loads the public career page and calls the same
  endpoint from that browser session. If robots.txt forbids the endpoint, the source stops; no workaround.
- **Eligibility score replaces keyword priority.** Every relevant vacancy gets ELIGIBLE / CHECK / INELIGIBLE,
  a 0-100 score and a "Why this result" list.
- **Deadlines:** taken from the source (Oracle closing date, or a labelled date in the feed text).
  Passed deadlines are removed. If a source publishes no deadline, the job is marked CHECK.
- **Work rights:** internal-only, UNDP Tier 0/1/2-only, nationals-only elsewhere, EU/EEA-only and
  locally recruited posts (NO-A..D, UNICEF NO-1..4, NPSA, G/GS, LICA, national consultant) outside
  your work-rights countries are INELIGIBLE.
- **Retained jobs:** kept only if the source failed this run, last seen within 7 days, AND
  (the vacancy page or Oracle record still answers, OR a future deadline is known, OR last seen within 3 days).
  Vacancies answering 404/410 or "no longer available" are removed.
- robots.txt 4xx now means "no restrictions" (RFC 9309). In V15 it wrongly blocked the source.
- Standard library only. Playwright is an optional fallback; its install step may fail without stopping the run.

## Check your profile first
Open `radar.py` and look at the `PROFILE` block at the top:
- `nationalities` is set to Bosnia and Herzegovina, **inferred from your National Officer post. Confirm it.**
  Add any other citizenship you hold (for example Croatia) **only if true**: it changes which posts are eligible.
- `years_experience` = 25 (2001-2026). `languages` = English, French, Italian and B/C/S.
- `current_staff_of` = empty. You are not current UN staff, so Tier 0/1/2-only UNDP posts are ineligible.

## Eligibility score (0-100)
| Part | Points | Rule |
|---|---:|---|
| Technical match | 40 | Construction / infrastructure / WASH / contracts / facilities / architecture terms |
| Level | 20 | P-4+/NO-C+/specialist/manager 20 · P-3/NO-B/officer/engineer 16 · junior 8 · support 4 |
| Location | 15 | Your work-rights country 15 · home-based 12 · Western Balkans 10 · Europe 8 · other 5 |
| Requirements | 25 | Years of experience, degree level and field, required languages |
| Penalties | - | Required language you lack -25 · civil-engineering-only degree -8 · unknown deadline -3 |

INELIGIBLE = a hard gate failed (score 0). CHECK = something could not be verified or a penalty applies.
ELIGIBLE = no gate failed and everything checkable was met.
**This is a rules-based estimate from the posting text, not an official decision.** Confirm on the vacancy.

## Install (new public repository, browser only)
1. Create a **new public** repository, e.g. `job-radar-v16`, default branch `main`.
2. Upload `radar.py` to the repository root.
3. Add file > Create new file > name it `.github/workflows/publish.yml` > paste the contents of `publish.yml`.
4. Settings > Pages > Source: **GitHub Actions**.
5. Actions > Job Radar V16 > Run workflow.
6. When build and deploy are green: Settings > Pages > Visit site. Bookmark that page.

Disable or delete the V15 workflow if it lives in the same repository.

## Reading the first run
In the run log open **Collect jobs, score eligibility, build dashboard**. For UNDP and IOM you want:
`Oracle JSON: N records, M detailed, K relevant`. If you see `Oracle JSON via browser session`,
the direct endpoint was refused and the fallback worked. If both fail, the log shows both errors:
send them to me.

## What was and was not tested
Tested here: 63 regression tests (run twice), 10 deliberate code breaks all caught by the tests,
an end-to-end run with simulated UNDP/IOM JSON, RSS, HTML and a failing source,
and the dashboard JavaScript in Node (filters, search, empty state, source health).
NOT tested here: real network access. This sandbox blocks all outside traffic, so the earlier
"HTTP 403" results in my test logs came from the sandbox, not from the job sites.
The Oracle field names follow Oracle's documentation and a published guide to these endpoints.
The first GitHub run is the live test.
