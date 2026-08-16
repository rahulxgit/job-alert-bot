# Complete files — no manual editing needed

Every file here is a full, ready-to-drop-in replacement (or new file).
Overwrite the matching path in your repo with each one.

```
config.py                              -> config.py
ai/profile.py                          -> ai/profile.py
ai/profile_condensed.py                -> ai/profile_condensed.py  (NEW)
sources/crawl4ai_discovery.py          -> sources/crawl4ai_discovery.py
tests/test_master_profile_matching.py  -> tests/test_master_profile_matching.py
tests/test_profile_condensed.py        -> tests/test_profile_condensed.py  (NEW)
```

## Apply (PowerShell, from inside D:\job-alert-bot)

```powershell
Expand-Archive -Path D:\Downloads\job-alert-bot-fixes-v2.zip -DestinationPath D:\Downloads\job-alert-bot-fixes-v2 -Force

Move-Item -Force D:\Downloads\job-alert-bot-fixes-v2\config.py .\config.py
Move-Item -Force D:\Downloads\job-alert-bot-fixes-v2\ai\profile.py .\ai\profile.py
Move-Item -Force D:\Downloads\job-alert-bot-fixes-v2\ai\profile_condensed.py .\ai\profile_condensed.py
Move-Item -Force D:\Downloads\job-alert-bot-fixes-v2\sources\crawl4ai_discovery.py .\sources\crawl4ai_discovery.py
Move-Item -Force D:\Downloads\job-alert-bot-fixes-v2\tests\test_master_profile_matching.py .\tests\test_master_profile_matching.py
Move-Item -Force D:\Downloads\job-alert-bot-fixes-v2\tests\test_profile_condensed.py .\tests\test_profile_condensed.py

python -m pytest tests/ -v
```

If everything's green:

```powershell
git add -A
git commit -m "Condense AI prompt profile to fix high UNRESOLVED rate; add Crawl4AI Discovery diagnostics"
git push
```

## What changed, one line each

- **config.py** — added `AI_PROFILE_MODE` (default `"condensed"`); raised
  `CRAWL4AI_DISCOVERY_MAX_PAGES` 20→40; lowered
  `CRAWL4AI_DISCOVERY_MIN_DESCRIPTION_CHARS` 400→250.
- **ai/profile_condensed.py** (new) — builds a compact candidate summary
  instead of dumping the full master-profile JSON into every AI call.
- **ai/profile.py** — now picks condensed vs full based on
  `config.AI_PROFILE_MODE`.
- **sources/crawl4ai_discovery.py** — writes
  `run-artifacts/crawl4ai-discovery-diagnostics.json` (per-seed
  pages/jobs/status) so a 0-result run is debuggable from the zip you send
  me, instead of only living in stdout logs that never get captured.
- **tests** — updated the one test that asserted full-profile-only
  content, added a new test file for the condensed builder.

## Still want CP stats (DSA count, LeetCode rating, etc.) in the prompt?

Those currently only live in prose bios, so the condensed builder can't
safely pull them out. Add this to `data/rahul-master-profile.json` as a new top-level key and it'll show up in every prompt automatically:

```json
"competitive_programming": {
  "dsa_problems_solved": "500+",
  "leetcode_rating": 1746,
  "naukri_young_turks_2025_percentile": 99.41,
  "ncat_2026_rank": 242
}
```
