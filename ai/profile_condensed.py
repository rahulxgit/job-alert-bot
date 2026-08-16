"""Condensed candidate profile for AI fit evaluation.

Why this exists: ai/profile_adapter.py's get_full_profile_text() serializes
the ENTIRE rahul-master-profile.json (identity, every project field,
verification notes, source citations, portfolio metrics, etc.) into every
single Gemini/gateway prompt. That file is huge — on the 2026-08-16 run,
78 evaluated candidates averaged 65s latency (p95 115s) and 48/93 admitted
candidates came back UNRESOLVED, almost certainly from prompt size pushing
calls past provider timeouts rather than genuine rate-limiting.

This module builds a much smaller, purpose-built block: skills/tech
keywords, one-line project summaries, education, experience, and the
existing short bios (which are already hand-condensed) — everything an
evaluator actually needs to score role/technical/project/education fit,
none of the verification metadata or duplicate technology listings that
don't change the score.

Full profile mode is still available (config.AI_PROFILE_MODE = "full")
for cases where the richer context is worth the cost, but condensed is
the default.
"""
from __future__ import annotations

import json
from typing import Any

from ai.profile_adapter import load_canonical_profile
from utils.logging_setup import get_logger

log = get_logger("profile_condensed")

# Cap on distinct project entries pulled into the prompt — flagship +
# strongest AI/professional projects only. Long tails of low-value repos
# (learning clones, archived stuff) add tokens without adding signal.
MAX_PROJECTS = 8
MAX_SKILLS = 30


def _safe_get(d: dict, *path, default=None):
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def _project_line(project: dict) -> str:
    name = project.get("name", "")
    tagline = project.get("tagline", "")
    tech = project.get("technologies", {})
    verified = tech.get("verified", []) if isinstance(tech, dict) else []
    tech_str = ", ".join(verified[:6])
    bullets = project.get("resume_bullets") or []
    highlight = bullets[0] if bullets else project.get("description", "")[:160]
    line = f"- {name} — {tagline}. Stack: {tech_str}."
    if highlight:
        line += f" {highlight}"
    return line


def _collect_skills(data: dict) -> list[str]:
    seen: dict[str, None] = {}
    projects = data.get("projects", {})
    for bucket in ("flagship_projects", "ai_projects", "professional_projects"):
        for project in projects.get(bucket, []) or []:
            tech = project.get("technologies", {})
            verified = tech.get("verified", []) if isinstance(tech, dict) else []
            for item in verified:
                seen.setdefault(item, None)
    # Prioritize a known core stack first (matches config.PROFILE_KEYWORDS
    # spirit) so truncation to MAX_SKILLS keeps the highest-signal terms.
    priority = [
        "React", "React 19", "Next.js 15", "Node.js", "Express.js 4", "TypeScript 5",
        "MongoDB Atlas", "PostgreSQL", "Prisma", "Docker", "MCP (Model Context Protocol)",
        "JWT (jsonwebtoken)", "Redux Toolkit", "Tailwind CSS 4",
    ]
    ordered = [p for p in priority if p in seen] + [s for s in seen if s not in priority]
    return ordered[:MAX_SKILLS]


def _top_projects(data: dict) -> list[dict]:
    projects = data.get("projects", {})
    flagship = projects.get("flagship_projects", []) or []
    ai_projects = [p for p in (projects.get("ai_projects", []) or []) if p.get("name") != "AI SEO Audit Platform"]
    professional = projects.get("professional_projects", []) or []
    combined = flagship + ai_projects + professional
    return combined[:MAX_PROJECTS]


def build_condensed_profile() -> str:
    """Return a compact, evaluator-ready candidate summary (skills, projects,
    education, experience, CP/achievements, targets) — no verification notes,
    no duplicate tech listings, no portfolio metadata."""
    try:
        data = load_canonical_profile()
        identity = data.get("identity", {})
        education = data.get("education", {})
        skills = _collect_skills(data)
        projects = _top_projects(data)
        experiences = data.get("experience", []) or []
        bios = data.get("professional_profile", {}) or {}
        objective = data.get("career_objective", "")
        prefs = data.get("job_preferences", {}) or {}
        cp = data.get("competitive_programming", {}) or {}

        lines = ["CANDIDATE PROFILE (condensed)"]
        headline = identity.get("headline") or bios.get("headline")
        if headline:
            lines.append(f"Headline: {headline}")
        location = identity.get("location")
        if location:
            lines.append(f"Location: {location}")

        lines.append("\n## Skills")
        lines.append(", ".join(skills) if skills else "Not available")

        lines.append("\n## Projects")
        for project in projects:
            lines.append(_project_line(project))
        if not projects:
            lines.append("- None listed")

        lines.append("\n## Education")
        if isinstance(education, dict):
            degree = education.get("degree") or education.get("program")
            institution = education.get("institution")
            graduation = education.get("graduation_year") or education.get("year")
            if degree or institution:
                detail = " — ".join(x for x in (degree, institution) if x)
                if graduation:
                    detail += f" ({graduation})"
                lines.append(detail)
            score = education.get("cgpa") or education.get("gpa")
            if score:
                lines.append(f"CGPA/GPA: {score}")
        else:
            lines.append("Not available")

        lines.append("\n## Experience")
        for exp in experiences[:6]:
            if not isinstance(exp, dict):
                continue
            company = exp.get("company") or exp.get("organization") or ""
            role = exp.get("role") or exp.get("title") or ""
            duration = exp.get("duration") or exp.get("dates") or ""
            detail = " — ".join(x for x in (role, company) if x)
            if duration:
                detail += f" ({duration})"
            bullets = exp.get("resume_bullets") or exp.get("highlights") or []
            lines.append(f"- {detail}")
            if bullets and isinstance(bullets, list):
                lines.append(f"  {str(bullets[0])[:280]}")
        if not experiences:
            lines.append("- None listed")

        lines.append("\n## Profile")
        for key in ("summary", "bio", "about"):
            value = bios.get(key) if isinstance(bios, dict) else None
            if value:
                lines.append(str(value)[:700])
                break
        if objective:
            lines.append(f"Career objective: {str(objective)[:500]}")

        lines.append("\n## Achievements / Competitive Programming")
        achievement_values = data.get("achievements", []) or []
        if isinstance(achievement_values, list):
            for item in achievement_values[:6]:
                lines.append(f"- {item}")
        if isinstance(cp, dict):
            for key, value in cp.items():
                if value not in (None, "", [], {}):
                    label = str(key).replace("_", " ").title()
                    lines.append(f"- {label}: {value}")

        lines.append("\n## Job Preferences")
        if isinstance(prefs, dict):
            for key in ("roles", "preferred_roles", "locations", "experience", "salary", "compensation"):
                value = prefs.get(key)
                if value not in (None, "", [], {}):
                    label = key.replace("_", " ").title()
                    lines.append(f"- {label}: {value}")

        return "\n".join(lines).strip()
    except Exception as exc:
        log.exception("Failed to build condensed candidate profile: %s", exc)
        raise
