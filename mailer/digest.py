"""Builds the plain-text digest body. Jobs with a found contact are
marked with 📧 and sorted first — fit score still the quality gate,
contact-availability only reorders what already passed review."""
from models import JobListing


def build_email_body(listings: list[JobListing], source_counts: dict = None) -> str:
    lines = []
    if source_counts:
        lines.append("Sources today — " + " | ".join(f"{name}: {count}" for name, count in source_counts.items()) + "\n")

    if not listings:
        lines.append("No new matching listings today.")
        return "\n".join(lines)

    contact_count = sum(1 for l in listings if l.recruiter_email)
    lines.append(f"{len(listings)} new job(s) matched today (Gemini-reviewed) — {contact_count} have a contact for outreach, listed first:\n")

    for listing in listings:
        marker = "📧 " if listing.recruiter_email else ""
        email_line = f"  Contact: {listing.recruiter_email}\n" if listing.recruiter_email else ""
        lines.append(
            f"- {marker}{listing.title} @ {listing.company} ({listing.location}) "
            f"— fit {listing.fit_score}/100 [{listing.source}]\n"
            f"  Why: {listing.reason}\n"
            f"{email_line}"
            f"  {listing.job_url}\n"
        )
    return "\n".join(lines)
