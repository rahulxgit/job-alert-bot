"""Builds the candidate-profile text every AI provider reads, directly
from profile-data.json — the same source-of-truth file the
resume-portfolio-sync skill uses. Updating the resume/portfolio flows
through here automatically without touching this code."""
import json
import config
from utils.logging_setup import get_logger

log = get_logger("profile")

_FALLBACK_PROFILE = """
Final-year CSE student targeting SDE-1 / Junior Software Engineer roles and
paid internships at Indian product companies and AI-first startups.
NOT a fit for: senior/staff/lead/principal roles, roles requiring 3+ years
of professional experience, unpaid internships.
"""


def build_candidate_profile() -> str:
    try:
        with open(config.PROFILE_DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        log.warning(f"could not load profile-data.json ({exc}) — using minimal fallback profile")
        return _FALLBACK_PROFILE

    lines = []
    name = data.get("contact", {}).get("name", "")
    lines.append(f"{name} — {data.get('headline', '')}.")
    lines.append(f"Targeting: {', '.join(data.get('target_roles', []))} at {data.get('target_focus', '')}.")

    for edu in data.get("education", []):
        lines.append(f"\nEducation: {edu.get('degree', '')}, {edu.get('institution', '')} ({edu.get('duration', '')}), {edu.get('gpa', '')}. {edu.get('notes', '')}")

    for exp in data.get("experience", []):
        lines.append(f"\nExperience: {exp.get('role', '')} at {exp.get('company', '')} ({exp.get('duration', '')}, {exp.get('location', '')}). {' '.join(exp.get('highlights', []))}")

    if data.get("projects"):
        lines.append("\nKey projects:")
        for proj in data["projects"]:
            lines.append(f"- {proj.get('name', '')}: {proj.get('tagline', '')}. Tech: {', '.join(proj.get('tech', []))}.")

    if data.get("skills"):
        all_skills = [s for group in data["skills"].values() for s in group]
        lines.append(f"\nTech stack: {', '.join(all_skills)}.")

    if data.get("achievements"):
        lines.append(f"\nAchievements: {'; '.join(data['achievements'])}.")

    positioning = data.get("about_narrative", {}).get("positioning", "")
    if positioning:
        lines.append(f"\nStrongest positioning: {positioning}")

    lines.append("\nNOT a fit for: senior/staff/lead/principal roles, roles requiring 3+ years of professional experience, unpaid internships.")
    return "\n".join(lines)
