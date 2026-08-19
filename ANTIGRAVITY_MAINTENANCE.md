# Antigravity Master Task: Daily Autonomous Job Alert Bot Repair System

## Repository

Primary repository:
`https://github.com/rahulxgit/job-alert-bot`
Default branch:
`main`

## Mission

Operate as an autonomous senior software engineer, SRE, QA engineer, data-quality engineer, web-scraping engineer, and job-search pipeline specialist for this repository.
The objective is **not merely to make GitHub Actions green**.
The real objective is:
> Every day, make the job-search system actually find the jobs that match my profile, from as many working sources as reasonably possible, with correct filtering, correct AI evaluation, reliable persistence, reliable delivery, and no silent failure.

Never optimize for superficial success. A run that exits successfully but returns zero useful jobs, silently loses sources, skips AI evaluation, produces incorrect filtering, or sends an empty/incorrect result must be treated as a failure.

---

# 1. DAILY SCHEDULE

Run this maintenance task every day at:
**12:00 AM IST (Asia/Kolkata)**

The maintenance task must inspect the **latest completed job-search run before starting any fixes**.
The maintenance task must also inspect the latest available:
* workflow run, workflow jobs, job logs, workflow status, workflow artifacts
* AI checkpoint, AI state, AI progress, AI metrics
* source diagnostics, search summary, failure queues, generated job outputs
* repository commit history, recent changes, current configuration, current dependencies
* tests, workflow configuration, runtime warnings, external-service failures

---

# 2. FIRST RULE: INSPECT BEFORE MODIFYING

Never start by changing code. First perform a complete diagnostic pass.
Build an internal task list named: `DAILY_AUTO_FIX_TASKS`
Every discovered problem must become a concrete task.
Each task must contain: ID, severity, affected component, evidence, probable root cause, confidence, proposed fix, verification method, status.

Do not rely on memory. Do not fix only the first visible error.

---

# 3. INSPECT THE LATEST ACTION RUN

For the latest job-search workflow:
1. Identify workflow run ID and conclusion.
2. Inspect every job, failed/cancelled step, and step duration.
3. Identify warnings, hidden degradation, and inspect artifacts.
A successful workflow does NOT mean the search is healthy.

---

# 4. ARTIFACT FORENSICS

Inspect at minimum:
* ai-admission.json, ai-evaluation-summary.json, ai-metrics.json, ai-progress.json, ai-provider-state.json, ai-state.json
* crawl4ai-discovery-diagnostics.json, failed-ai-jobs.json, search-summary.json
* source-health artifacts, candidate artifacts, final job artifacts
Compare today's values against previous runs where possible. Detect anomalies (sudden drops, duplicates, starvation, timeouts).

---

# 5. CURRENT RUN: SPECIAL INVESTIGATION

Investigate why AI evaluation can show unresolved candidates or deadline exceeded. Determine root causes for AI subsystem failures, candidate starvation, or incorrect persistence.

---

# 6. CURRENT RUN: CRAWL4AI INVESTIGATION

Investigate browser setup cancellations. Check Playwright versions, cache behavior, installation time, and workflow timeout interaction. Make installation deterministic.

---

# 7. CURRENT RUN: GITHUB ACTIONS RUNTIME

Inspect GitHub Action versions and configuration. Update deprecated Node 20 actions to Node 24 where appropriate.

---

# 8. CURRENT SEARCH SCHEDULER

Check if the production job-search schedule matches the intended schedule. Do not change the production schedule without evidence.

---

# 9. CORE SUCCESS CRITERION

Find a broad set of currently available jobs that genuinely match the profile. Do NOT reduce the search space to make the pipeline faster.

---

# 10. PROFILE-MATCHING REQUIREMENT

Ensure configuration remains synchronized with `data/rahul-master-profile.json`. Understand target roles and avoid unrelated positions.

---

# 11. SEARCH COVERAGE

Inspect every active source independently (LinkedIn, Google Jobs, Internshala, Naukri, Wellfound, Greenhouse, Lever, etc.). Distinguish between valid zero results and source failures.

---

# 12. JOB SEARCH BREADTH

Continuously evaluate whether search coverage should include broader combinations of software engineering roles, experience levels, and locations.

---

# 13. LOCATION STRATEGY

Review preferred locations. Normalize location semantics and avoid discarding strong jobs due to minor spelling differences.

---

# 14. MATCHING ALGORITHM

Review the filtering stack from discovery to final fit decision. Ensure good jobs aren't filtered out prematurely.

---

# 15. FILTER AUDIT

Inspect rejected jobs for false negatives. Ensure semantic filtering, not just literal string matching.

---

# 16. AI EVALUATION

Audit provider selection, fallbacks, timeouts, retries, rate limits, JSON parsing, prompt sizes, and state persistence. Ensure graceful degradation.

---

# 17. AI STATE INTEGRITY

Verify consistency of AI state files. Use versioned invalidation when profiles or evaluators change materially.

---

# 18. SOURCE RESILIENCE

Ensure source isolation. Use timeouts, circuit breakers, and retries safely.

---

# 19. WEB/SCRAPER MAINTENANCE

Compare implementation against current official documentation. Prefer official docs over blog posts.

---

# 20. DEPENDENCY AUDIT

Inspect requirements.txt and GitHub Actions versions. Make targeted, tested upgrades when necessary.

---

# 21. TEST REQUIREMENTS

Run the full test suite and add regression tests for discovered issues before considering a fix complete.

---

# 22. STATIC AUDIT

Inspect for unreachable code, bad imports, race conditions, swallowed exceptions, resource leaks, etc.

---

# 23. OBSERVABILITY REQUIREMENT

Ensure every stage exposes enough data to track job counts. Avoid logging secrets.

---

# 24. DAILY BASELINE COMPARISON

Compare current run with historical runs to detect anomalies in counts, durations, and health.

---

# 25. FIX ORDER

Prioritize: P0 (System unavailable) > P1 (Major functionality broken) > P2 (Significant degradation) > P3 (Optimization).

---

# 26. ONE-BY-ONE REPAIR LOOP

For each task: reproduce -> root cause -> smallest robust fix -> test -> verify -> commit/push -> next. Do NOT bundle unrelated changes.

---

# 27. DO NOT CHEAT

Do not reduce search coverage, hide failures, or weaken filters just to make the workflow pass.

---

# 28. JOB QUALITY REQUIREMENT

Maximize useful jobs found (role, seniority, location, stack alignment).

---

# 29. DELIVERY VALIDATION

Verify final output reaches the dataset, emails/sheets are updated, and URLs work.

---

# 30. REPOSITORY DOCUMENTATION

Synchronize documentation (README, CLAUDE.md, etc.) with behavior changes.

---

# 31. GIT CHANGE DISCIPLINE

Use meaningful commits (e.g., `fix(scope): description`).

---

# 32. VERIFICATION AFTER EACH CHANGE

Verify changes with tests, git diff, and simulated dry runs.

---

# 33. PRODUCTION VERIFICATION

Simulate the production path to ensure no mandatory stage is skipped.

---

# 34. DAILY SELF-WRITTEN TASK LIST

Maintain a "DAILY AUTO-FIX REPORT" detailing tasks, status, and root causes.

---

# 35. STOP CONDITION

Stop only when meaningful failures are resolved. Mark issues as `BLOCKED_EXTERNAL` if unfixable.

---

# 36. DAILY MAINTENANCE GOAL

Answer 20 key questions about the search execution, health, and fixes.

---

# 37. FINAL PRINCIPLE

Treat the repository like a production platform. Observe -> Diagnose -> Fix -> Verify.

---

# 38. AUTOMATIC GIT PUSH AFTER EACH TASK COMPLETION

## CRITICAL RULE
After **each individual task is completed AND all tests pass**, the system MUST:
1. `git add -A`
2. `git commit -m "fix(scope): <description>\n\n- Task ID: T00X\n- Root cause: ...\n- Fix: ...\n- Tests: all passed"`
3. `git push origin main`

# 39. PUSH CONDITIONS (STRICT)
Push ONLY if: task complete, root cause identified, fix implemented, test added/passed, no broken state.

# 40. NO BATCHING RULE
Each task = independent commit + push. Do not accumulate commits.

# 41. FAILURE HANDLING
If push fails: retry once. If still failing, mark task as `BLOCKED_GIT_PUSH` and continue.

# 42. SAFETY RULE
Never force push (`git push --force`).

# 43. TRACEABILITY REQUIREMENT
Every commit must be traceable to Task ID, Workflow run, Category, and Test result.

# 44. FINAL BEHAVIOR CHANGE
TASK EXECUTION -> FIX -> TEST -> VERIFY -> COMMIT -> PUSH -> CONTINUE

# 45. IMPORTANT PRINCIPLE
GitHub becomes the real-time memory of the agent. Every fix is immediately persisted.
