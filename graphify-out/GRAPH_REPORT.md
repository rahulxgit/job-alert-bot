# Graph Report - job-alert-bot  (2026-08-17)

## Corpus Check
- 94 files · ~45,516 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 670 nodes · 1567 edges · 28 communities (23 shown, 5 thin omitted)
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 130 edges (avg confidence: 0.52)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `55ba661f`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- JobListing
- test_evaluator.py
- profile_adapter.py
- FitVerdict
- evaluator.py
- test_firecrawl.py
- EvaluationState
- crawl4ai_discovery.py
- test_crawl_provider.py
- run_artifacts.py
- recruiter_email.py
- SourceHealth
- compute_admission_limit
- mock_post
- What You Must Do When Invoked
- test_new_sources.py
- graphify reference: extra exports and benchmark
- jobspy_common.py
- graphify reference: query, path, explain
- Complete files — no manual editing needed
- graphify reference: add a URL and watch a folder
- graphify reference: commit hook and native CLAUDE.md integration
- graphify reference: incremental update and cluster-only
- graphify reference: GitHub clone and cross-repo merge
- graphify reference: transcribe video and audio
- CLAUDE.md
- .claude/CLAUDE.md
- extraction-spec.md

## God Nodes (most connected - your core abstractions)
1. `JobListing` - 123 edges
2. `JobSource` - 32 edges
3. `EvaluationState` - 27 edges
4. `get_logger()` - 27 edges
5. `review_candidates()` - 22 edges
6. `keyword_prefilter_score()` - 21 edges
7. `FitVerdict` - 21 edges
8. `run_pipeline()` - 20 edges
9. `get_full_profile_text()` - 17 edges
10. `AIStateStore` - 17 edges

## Surprising Connections (you probably didn't know these)
- `_load_failed_ai_jobs()` --uses--> `JobListing`  [INFERRED]
  ai/evaluator.py → models.py
- `_job_from_dict()` --uses--> `JobListing`  [INFERRED]
  ai/evaluator.py → models.py
- `test_apollo_disabled_state_is_reset_for_each_enrichment_run()` --uses--> `JobListing`  [INFERRED]
  tests/test_runtime_resilience.py → models.py
- `_verdict()` --uses--> `FitVerdict`  [INFERRED]
  tests/test_ai_checkpoint_resume.py → models.py
- `_verdict()` --uses--> `FitVerdict`  [INFERRED]
  tests/test_ai_concurrency.py → models.py

## Import Cycles
- None detected.

## Communities (28 total, 5 thin omitted)

### Community 0 - "JobListing"
Cohesion: 0.05
Nodes (68): All configuration in one place: env vars, search terms, keyword lists, tunable…, Logger, build_email_body(), Builds the plain-text digest body. Jobs with a found contact are marked with 📧…, get_gmail_service(), Gmail API client — sends the daily digest via OAuth (refresh token, no password…, send_email(), dedupe() (+60 more)

### Community 1 - "test_evaluator.py"
Cohesion: 0.14
Nodes (23): _apply_verdict(), _contains_any(), _education_score(), _freshness_score(), keyword_prefilter_score(), _location_score(), _parse_experience(), prefilter() (+15 more)

### Community 2 - "profile_adapter.py"
Cohesion: 0.07
Nodes (49): _build_prompt(), _profile(), build_structured_profile(), _find_alias_value(), _find_alias_values(), get_full_profile_text(), get_profile_text(), load_canonical_profile() (+41 more)

### Community 3 - "FitVerdict"
Cohesion: 0.07
Nodes (55): AIProvider, ABC, AI provider interface — any provider (Gemini, the gateway, a future addition)…, Must never raise — catch internally, return a FitVerdict with hit_rate_limit or…, GatewayProvider, Primary AI provider — self-hosted multi-provider gateway…, Return a normalized verdict, or None so the caller can use Gemini. Gateway…, GeminiProvider (+47 more)

### Community 4 - "evaluator.py"
Cohesion: 0.05
Nodes (46): candidate_set_hash(), checkpoint_identity(), compatible(), evaluation_key(), profile_hash(), Versioned identity helpers for resumable AI evaluation checkpoints., stable_hash(), _deadline_reached() (+38 more)

### Community 5 - "test_firecrawl.py"
Cohesion: 0.08
Nodes (49): validate(), RuntimeError, _extract_job_links(), _fetch_job_detail(), FirecrawlSource, _guess_company(), _guess_location(), _guess_posting_date() (+41 more)

### Community 6 - "EvaluationState"
Cohesion: 0.10
Nodes (25): EvaluationState, from_dict(), _is_permanent_error(), migrate_legacy_progress(), migrate_legacy_retry_jobs(), Any, Backward-compatible migration from legacy AI progress/retry files., Convert completed checkpoint entries into unified evaluation states. (+17 more)

### Community 7 - "crawl4ai_discovery.py"
Cohesion: 0.08
Nodes (42): BestFirstCrawlingStrategy, _allowed_host(), Crawl4AIDiscoverySource, _crawl_seed(), _discover(), discover_job_listings(), _discovery_domains(), _discovery_seeds() (+34 more)

### Community 8 - "test_crawl_provider.py"
Cohesion: 0.13
Nodes (21): skipif, Crawl4AIError, _crawl_batch(), _crawl_url_with_crawler(), Exception, Raised when Crawl4AI cannot return usable content., Run an async Crawl4AI operation from the synchronous source API., Crawl a batch with one browser session and bounded concurrency. (+13 more)

### Community 9 - "run_artifacts.py"
Cohesion: 0.46
Nodes (7): _export(), export_stage(), export_summary(), _job_rows(), _jsonable(), Any, Export sanitized pipeline snapshots for GitHub Actions recovery/debugging.

### Community 10 - "recruiter_email.py"
Cohesion: 0.18
Nodes (17): _apollo_find_contact(), enrich_with_emails(), _hunter_domain_search(), Recruiter/company email enrichment — a three-tier chain, each tried only if the…, Find and enrich one recruiter/HR contact; authorization failures disable Apollo…, Tests for pure-logic text helpers — no network, no secrets needed., test_extract_email_from_text_finds_real_email(), test_extract_email_from_text_returns_empty_when_none() (+9 more)

### Community 11 - "SourceHealth"
Cohesion: 0.22
Nodes (16): _export_search_summary(), fetch_all(), Run every source independently and record health/coverage metrics., test_classify_timeout_and_http_errors(), test_search_summary_reports_source_diversity(), test_source_error_with_no_jobs_is_failed(), test_source_error_with_partial_results_is_degraded(), test_zero_results_are_healthy_but_explicitly_marked() (+8 more)

### Community 12 - "compute_admission_limit"
Cohesion: 0.21
Nodes (14): admit_candidates(), apply_admission_control(), compute_admission_limit(), _load_previous_metrics(), _positive_float(), _positive_int(), Any, Adaptive AI candidate admission control. The controller computes a safe first-… (+6 more)

### Community 13 - "mock_post"
Cohesion: 0.50
Nodes (3): fixture, mock_post(), Shared Firecrawl POST mock for tests that request it by fixture name.

### Community 14 - "What You Must Do When Invoked"
Cohesion: 0.07
Nodes (26): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+18 more)

### Community 15 - "test_new_sources.py"
Cohesion: 0.30
Nodes (9): ArbeitnowSource, RemoteOKSource, _mock_response(), patch, Tests for Arbeitnow and RemoteOK sources — network is mocked, so these check…, test_arbeitnow_filters_by_keyword(), test_arbeitnow_returns_empty_on_failure(), test_remoteok_returns_empty_on_failure() (+1 more)

### Community 16 - "graphify reference: extra exports and benchmark"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 17 - "jobspy_common.py"
Cohesion: 0.14
Nodes (15): DataFrame, dataframe_to_listings(), fetch_all_jobspy_listings(), Shared jobspy plumbing used by linkedin.py and google.py — they all go through…, Execute one bounded JobSpy call without changing its timeout semantics., Fetch a bounded set of JobSpy term/location combinations once. The search…, _run_combo(), _scrape_one_combo() (+7 more)

### Community 18 - "graphify reference: query, path, explain"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 19 - "Complete files — no manual editing needed"
Cohesion: 0.40
Nodes (4): Apply (PowerShell, from inside D:\job-alert-bot), Complete files — no manual editing needed, Still want CP stats (DSA count, LeetCode rating, etc.) in the prompt?, What changed, one line each

### Community 20 - "graphify reference: add a URL and watch a folder"
Cohesion: 0.50
Nodes (3): For /graphify add, For --watch, graphify reference: add a URL and watch a folder

### Community 21 - "graphify reference: commit hook and native CLAUDE.md integration"
Cohesion: 0.50
Nodes (3): For git commit hook, For native CLAUDE.md integration, graphify reference: commit hook and native CLAUDE.md integration

### Community 22 - "graphify reference: incremental update and cluster-only"
Cohesion: 0.50
Nodes (3): For --cluster-only, For --update (incremental re-extraction), graphify reference: incremental update and cluster-only

## Knowledge Gaps
- **47 isolated node(s):** `graphify`, `Usage`, `What graphify is for`, `Step 0 - GitHub repos and multi-path merge (only if a URL or several paths)`, `Step 1 - Ensure graphify is installed` (+42 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **5 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `JobListing` connect `JobListing` to `test_evaluator.py`, `profile_adapter.py`, `FitVerdict`, `evaluator.py`, `test_firecrawl.py`, `crawl4ai_discovery.py`, `test_crawl_provider.py`, `run_artifacts.py`, `recruiter_email.py`, `SourceHealth`, `test_new_sources.py`, `jobspy_common.py`?**
  _High betweenness centrality (0.220) - this node is a cross-community bridge._
- **Why does `get_logger()` connect `JobListing` to `profile_adapter.py`, `FitVerdict`, `evaluator.py`, `test_firecrawl.py`, `crawl4ai_discovery.py`, `recruiter_email.py`, `jobspy_common.py`?**
  _High betweenness centrality (0.049) - this node is a cross-community bridge._
- **Why does `EvaluationState` connect `EvaluationState` to `evaluator.py`?**
  _High betweenness centrality (0.038) - this node is a cross-community bridge._
- **Are the 69 inferred relationships involving `JobListing` (e.g. with `_apply_verdict()` and `_build_prompt()`) actually correct?**
  _`JobListing` has 69 INFERRED edges - model-reasoned connections that need verification._
- **Are the 9 inferred relationships involving `EvaluationState` (e.g. with `_legacy_state_store()` and `review_candidates()`) actually correct?**
  _`EvaluationState` has 9 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `review_candidates()` (e.g. with `MetricsCoordinator` and `EvaluationState`) actually correct?**
  _`review_candidates()` has 4 INFERRED edges - model-reasoned connections that need verification._
- **What connects `graphify`, `Usage`, `What graphify is for` to the rest of the system?**
  _47 weakly-connected nodes found - possible documentation gaps or missing edges._