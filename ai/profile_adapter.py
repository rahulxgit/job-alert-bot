"""
Profile Adapter - Parses the canonical master profile JSON and extracts
structured evidence for job matching.
"""
import json
import os
import config
from utils.logging_setup import get_logger

log = get_logger("profile_adapter")

MASTER_PROFILE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "rahul-master-profile.json")

class ProfileLoadError(Exception):
    pass

def load_canonical_profile():
    try:
        with open(MASTER_PROFILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        log.error(f"Failed to load canonical profile from {MASTER_PROFILE_PATH}: {exc}")
        raise ProfileLoadError(f"Failed to load master profile: {exc}")

def build_structured_profile() -> dict:
    """Extracts structured evidence from the master profile."""
    data = load_canonical_profile()
    if not data:
        raise ProfileLoadError("Canonical profile data is empty.")

    # Extract Identity
    identity = data.get("identity", {})
    career_stage = identity.get("career_stage", "entry-level")

    # Extract Education
    education = []
    for edu in data.get("education", []):
        education.append({
            "degree": edu.get("degree", ""),
            "branch": edu.get("branch", ""),
            "graduation_year": edu.get("graduation_year", "") or edu.get("end_year", ""),
            "institution": edu.get("institution", ""),
            "cgpa": edu.get("cgpa", {}).get("value", "") if isinstance(edu.get("cgpa"), dict) else edu.get("cgpa", "")
        })

    # Extract Skills
    skills = []
    for category, skill_list in data.get("skills", {}).items():
        if isinstance(skill_list, list):
            for skill in skill_list:
                if isinstance(skill, dict):
                    if skill.get("proficiency") in ["strong", "moderate", "exposure", "regular use", "claimed"]:
                        skills.append(f"{skill.get('name', '')} ({skill.get('proficiency', '')})")
                elif isinstance(skill, str):
                    skills.append(skill)

    # Extract Experience
    experience = []
    for exp in data.get("experience", []):
        experience.append({
            "role": exp.get("role", ""),
            "company": exp.get("company", ""),
            "duration": exp.get("duration", ""),
            "technologies": exp.get("technologies", []),
            "verification": exp.get("verification", {}).get("status", "unverified") if isinstance(exp.get("verification"), dict) else "unverified"
        })

    # Extract Job Preferences
    job_prefs = data.get("job_preferences", {}).get("career_preferences", {})
    target_roles = job_prefs.get("target_roles", [])
    preferred_locations = job_prefs.get("preferred_locations", [])
    target_company_types = job_prefs.get("target_company_types", [])

    # Extract AI Engineering
    ai_engineering = []
    for ai_cap in data.get("ai_engineering", {}).get("capabilities", []):
        if ai_cap.get("verified", False):
            ai_engineering.append(f"{ai_cap.get('skill', '')}: {ai_cap.get('description', '')}")

    # Extract Projects
    projects = []
    projects_data = data.get("projects", {})
    all_projects = (
        projects_data.get("flagship_projects", []) +
        projects_data.get("ai_projects", []) +
        projects_data.get("professional_projects", [])
    )
    for proj in all_projects:
        status = proj.get("status", "unknown")
        projects.append({
            "name": proj.get("name", ""),
            "description": proj.get("description", ""),
            "technologies": proj.get("technologies", {}).get("verified", []) if isinstance(proj.get("technologies"), dict) else [],
            "status": status
        })

    # Build raw text representation for LLM prompt context
    raw_text = []
    name = identity.get("full_name", "")
    raw_text.append(f"Name: {name}")
    raw_text.append(f"Career Stage: {career_stage}")
    raw_text.append(f"Target Roles: {', '.join(target_roles)}")
    raw_text.append(f"Preferred Locations: {', '.join(preferred_locations)}")
    raw_text.append(f"Target Company Types: {', '.join(target_company_types)}")
    raw_text.append(f"Education: " + "; ".join([f"{e['degree']} in {e['branch']} from {e['institution']} ({e['graduation_year']}) CGPA: {e['cgpa']}" for e in education]))

    raw_text.append(f"\nVerified Experience:")
    for e in experience:
        techs = ", ".join(e['technologies'])
        raw_text.append(f"- {e['role']} at {e['company']} ({e['duration']}) [Status: {e['verification']}] Tech: {techs}")

    raw_text.append(f"\nSkills: {', '.join(skills)}")

    raw_text.append(f"\nVerified AI Engineering Capabilities:")
    for ai_cap in ai_engineering:
        raw_text.append(f"- {ai_cap}")

    raw_text.append("\nVerified Projects:")
    for p in projects:
        techs = ", ".join(p["technologies"])
        raw_text.append(f"- {p['name']}: {p['description'][:200]}... [Tech: {techs}] [Status: {p['status']}]")

    return {
        "identity": {"career_stage": career_stage, "name": name},
        "education": education,
        "experience": experience,
        "skills": skills,
        "projects": projects,
        "job_preferences": job_prefs,
        "ai_engineering": ai_engineering,
        "raw_text": "\n".join(raw_text)
    }

def get_profile_text() -> str:
    """Returns the text representation of the canonical profile."""
    return build_structured_profile().get("raw_text", "")
