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

from typing import Any

from ai.profile_adapter import load_canonical_profile
from utils.logging_setup import get_logger

log = get_logger("profile_condensed")

MAX_PROJECTS = 8
MAX_SKILLS = 30


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
    return (flagship + ai_projects + professional)[:MAX_PROJECTS]


def _first_dict(value: Any) -> dict:
    """Return the first useful mapping from a dict/list/nested schema."""
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and item:
                return item
    return {}


def _find_first_alias(data: Any, aliases: set[str]) -> Any:
    """Find the first non-empty value whose normalized key matches an alias."""
    normalized = {"".join(ch for ch in alias.lower() if ch.isalnum()) for alias in aliases}

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            for key, value in node.items():
                key_norm = "".join(ch for ch in str(key).lower() if ch.isalnum())
                if key_norm in normalized and value not in (None, "", [], {}):
                    return value
                found = walk(value)
                if found not in (None, "", [], {}):
                    return found
        elif isinstance(node, list):
            for item in node:
                found = walk(item)
                if found not in (None, "", [], {}):
                    return found
        return None

    return walk(data)


def _education_details(data: dict) -> tuple[str, str, Any, Any, Any]:
    """Extract education facts across supported canonical-profile shapes."""
    raw = data.get("education")
    education = _first_dict(raw)

    degree = education.get("degree") or education.get("program")
    # Prefer the canonical short institution name when present because it is
    # the stable display label used by matching/tests; fall back to the full
    # institution name only when no short name exists.
    institution = education.get("institution_short") or education.get("institution")
    branch = education.get("branch") or education.get("discipline") or education.get("major")
    graduation = (
        education.get("graduation_year")
        or education.get("year")
        or education.get("end_year")
    )
    score = education.get("cgpa") or education.get("gpa")

    if not institution:
        institution = _find_first_alias(data, {"institution_short", "institution"})
    if not branch:
        branch = _find_first_alias(data, {"branch", "major", "discipline"})
    if not degree:
        degree = _find_first_alias(data, {"degree", "program"})
    if not graduation:
        graduation = _find_first_alias(data, {"graduation_year", "end_year", "graduation"})
    if not score:
        score = _find_first_alias(data, {"cgpa", "gpa"})

    if isinstance(score, dict):
        score = score.get("value")

    return str(degree or ""), str(institution or ""), graduation, branch, score


def build_condensed_profile() -> str:
    """Return a compact, evaluator-ready candidate summary."""
    try:
        data = load_canonical_profile()
        identity = data.get("identity", {}) if isinstance(data.get("identity"), dict) else {}
        skills = _collect_skills(data)
        projects = _top_projects(data)
        experiences = data.get("experience", []) or []
        bios = data.get("professional_profile", {}) or {}
        objective = data.get("career_objective", "")
        prefs = data.get("job_preferences", {}) or {}
        cp = data.get("competitive_programming", {}) or {}
        degree, institution, graduation, branch, score = _education_details(data)

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
        detail_parts = [degree]
        if branch:
            detail_parts.append(f"in {branch}")
        if institution:
            detail_parts.append(institution)
        detail = " — ".join(x for x in detail_parts if x)
        if graduation:
            detail += f" ({graduation})"
        lines.append(detail if detail else "Not available")
        if score not in (None, ""):
            lines.append(f"CGPA/GPA: {score}")

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
