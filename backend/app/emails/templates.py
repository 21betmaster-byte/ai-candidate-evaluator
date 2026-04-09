"""Email templates from PRD Appendix A.

All 17 scenarios. Each renders to (subject, body_text). Templates are intentionally
plain-text to match the friendly/witty/bold/playful brand voice without HTML noise.

CRITICAL (PRD §7): candidate-facing emails NEVER include numeric scores, rubric
dimension names, or any internal evaluation data. Only the pass/fail decision and
a brief human-readable reason.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RenderedEmail:
    subject: str
    body: str
    template_key: str


def _wrap(name: str | None, body: str, company: str) -> str:
    greeting = f"Hey {name}! 👋" if name else "Hey there! 👋"
    return (
        f"{greeting}\n\n"
        f"{body}\n\n"
        f"Cheers,\n"
        f"The {company} Hiring Team\n\n"
        f"---\n"
        f"If you think something went wrong, just reply to this email and we'll take a look."
    )


def acknowledgment(name: str | None, company: str) -> RenderedEmail:
    body = (
        "Your application just landed and it's already making friends with the other resumes in our inbox.\n\n"
        "We're warming up our reading glasses as we speak. We'll take a look and reach out if we need "
        "anything from you.\n\n"
        "Sit tight — good things are coming."
    )
    return RenderedEmail(
        subject="We got your application — and we're already impressed 👀",
        body=_wrap(name, body, company),
        template_key="acknowledgment",
    )


def pass_decision(name: str | None, next_steps: str, company: str) -> RenderedEmail:
    body = (
        "We've reviewed your application and — drumroll — you've caught our attention.\n\n"
        f"Your profile stood out and we'd love to take this further. {next_steps}\n\n"
        "Looking forward to the next chapter!"
    )
    return RenderedEmail(
        subject="You made the cut! 🎉 Here's what's next",
        body=_wrap(name, body, company),
        template_key="pass_decision",
    )


def fail_decision(name: str | None, reason_snippet: str, company: str) -> RenderedEmail:
    """Lite, warm close. Reason snippet is one short sentence, no scores."""
    body = (
        "Thanks for sharing your work with us — we mean that. It takes effort to put yourself out there.\n\n"
        f"For this particular role, we're going to explore a few other directions. {reason_snippet}\n\n"
        "Keep building — and don't be a stranger if future roles catch your eye."
    )
    return RenderedEmail(
        subject=f"Thanks for applying to {company} 🙏",
        body=_wrap(name, body, company),
        template_key="fail_decision",
    )


def missing_items(name: str | None, missing: list[str], company: str) -> RenderedEmail:
    bullets = "\n".join(f"  • {m}" for m in missing)
    body = (
        "We got your email and we're excited to dig in — but we're missing a few pieces of the puzzle.\n\n"
        f"Here's what we still need:\n{bullets}\n\n"
        "Just reply to this email with the missing bits and we'll take it from there.\n\n"
        "Almost there — we're rooting for you!"
    )
    return RenderedEmail(
        subject="Almost there — we just need a couple more things 📎",
        body=_wrap(name, body, company),
        template_key="missing_items",
    )


def non_pdf_attachment(name: str | None, company: str) -> RenderedEmail:
    body = (
        "Thanks for reaching out — we weren't able to read the file you attached.\n\n"
        "Could you resend your resume as a PDF or Word document (.pdf or .docx)? Just reply to this email "
        "with the file attached and we'll pick right back up.\n\n"
        "Small ask, big impact!"
    )
    return RenderedEmail(
        subject="Quick heads up about your resume format 📄",
        body=_wrap(name, body, company),
        template_key="non_pdf_attachment",
    )


def duplicate_update(name: str | None, company: str) -> RenderedEmail:
    body = (
        "Look who's back! We got your updated application and consider the old one officially retired.\n\n"
        "We're reviewing your latest and greatest now. Same process as before — sit tight and we'll be in "
        "touch soon.\n\n"
        "Thanks for keeping us on our toes!"
    )
    return RenderedEmail(
        subject="Updated application received! 🔄",
        body=_wrap(name, body, company),
        template_key="duplicate_update",
    )


def gibberish(name: str | None, company: str) -> RenderedEmail:
    body = (
        "We received your email and gave it our best shot, but we couldn't quite figure out what it says. "
        "Our AI is smart, but apparently not THAT smart.\n\n"
        "If you meant to apply for a role, here's what we need: a resume (PDF), a link to your GitHub "
        "profile, and a link to your portfolio or projects. Just reply to this email with those and we'll "
        "get the ball rolling.\n\n"
        "No judgment — inboxes are weird sometimes."
    )
    return RenderedEmail(
        subject="We got your email but... we're a bit confused 🤔",
        body=_wrap(name, body, company),
        template_key="gibberish",
    )


def spam_sales(name: str | None, company: str) -> RenderedEmail:
    body = (
        "Appreciate the hustle — truly. But this inbox is reserved for job applications, not product pitches.\n\n"
        "If you ARE a human looking for a role though, we'd love to hear from you. Send us your resume "
        "(PDF), GitHub link, and portfolio link, and we'll give your application the attention it deserves.\n\n"
        "Good luck out there!"
    )
    return RenderedEmail(
        subject="Re: Your email",
        body=_wrap(name, body, company),
        template_key="spam_sales",
    )


def question_response(name: str | None, answer: str, company: str) -> RenderedEmail:
    body = (
        "Thanks for reaching out! We love the curiosity.\n\n"
        f"{answer}\n\n"
        "When you're ready to apply, just reply to this email (or send a fresh one) with your resume "
        "(PDF), GitHub link, and portfolio link.\n\n"
        "We hope to see your application soon!"
    )
    return RenderedEmail(
        subject="Great question! Here's the scoop 💡",
        body=_wrap(name, body, company),
        template_key="question_response",
    )


def empty_email(name: str | None, company: str) -> RenderedEmail:
    body = (
        "Looks like your email came through without any content or attachments. It happens to the best of us.\n\n"
        "To apply, send us: a resume (PDF attachment), a link to your GitHub profile, and a link to your "
        "portfolio or projects. Reply to this email with all three and you're good to go.\n\n"
        "We'll be here when you're ready!"
    )
    return RenderedEmail(
        subject="We got your email — but it was a bit... empty 📭",
        body=_wrap(name, body, company),
        template_key="empty_email",
    )


def portfolio_is_linkedin(name: str | None, company: str) -> RenderedEmail:
    body = (
        "We see you shared your LinkedIn profile — and we appreciate the transparency! But we're actually "
        "looking for a portfolio or project showcase: a personal site, a GitHub Pages project, a Behance, "
        "or anything that shows off what you've built.\n\n"
        "LinkedIn is great for networking, but we want to see your work in action. Reply with a link to "
        "your projects and we'll pick things right back up.\n\n"
        "Show us what you've built!"
    )
    return RenderedEmail(
        subject="Quick note about your portfolio link 🔗",
        body=_wrap(name, body, company),
        template_key="portfolio_is_linkedin",
    )


def github_unreachable(name: str | None, company: str) -> RenderedEmail:
    body = (
        "We tried checking out your GitHub profile, but it looks like the link doesn't work or the profile "
        "might be set to private.\n\n"
        "Could you double-check and send us an updated link? Make sure your profile is set to public so we "
        "can see your repos and contributions. Reply to this email with the corrected link and we'll take "
        "it from there.\n\n"
        "We're eager to see your code!"
    )
    return RenderedEmail(
        subject="We couldn't access your GitHub profile 🔒",
        body=_wrap(name, body, company),
        template_key="github_unreachable",
    )


def portfolio_unreachable(name: str | None, company: str) -> RenderedEmail:
    body = (
        "We tried visiting your portfolio but the link seems to be down or not loading. It might be a "
        "temporary thing, but we wanted to let you know.\n\n"
        "Could you double-check the URL and send us an updated link if needed? Reply to this email and "
        "we'll retry.\n\n"
        "We really do want to see your work!"
    )
    return RenderedEmail(
        subject="Heads up — your portfolio link isn't loading 🌐",
        body=_wrap(name, body, company),
        template_key="portfolio_unreachable",
    )


def reminder(name: str | None, missing: list[str], company: str) -> RenderedEmail:
    bullets = "\n".join(f"  • {m}" for m in missing)
    body = (
        "Hey, just a quick reminder — we're still waiting on a few things to complete your application.\n\n"
        f"We still need:\n{bullets}\n\n"
        "No rush... okay, maybe a little rush. We've got reviewers ready to go and we'd hate for your "
        "application to go stale.\n\n"
        "Reply to this email with the missing pieces and we'll jump right on it!"
    )
    return RenderedEmail(
        subject="Friendly nudge about your application 👋",
        body=_wrap(name, body, company),
        template_key="reminder",
    )


def rapid_emails(name: str | None, company: str) -> RenderedEmail:
    body = (
        "We noticed a few emails from you in quick succession (we've all been there). Don't worry — we've "
        "grabbed the latest one with all the goods.\n\n"
        "We're reviewing your most recent submission now. You can relax — one application, fully received.\n\n"
        "Stay tuned!"
    )
    return RenderedEmail(
        subject="Got it — we're on it! ✅",
        body=_wrap(name, body, company),
        template_key="rapid_emails",
    )


def processing_error_notice(name: str | None, company: str) -> RenderedEmail:
    body = (
        "We ran into an unexpected hiccup while processing your application and couldn't finish reviewing "
        "it automatically. This is on our side, not yours.\n\n"
        "Could you reply to this email with your resume (PDF), GitHub link, and portfolio link one more "
        "time? We'll make sure a human picks it up from here.\n\n"
        "Sorry for the bump in the road!"
    )
    return RenderedEmail(
        subject="We hit a snag with your application — quick resend? 🛠️",
        body=_wrap(name, body, company),
        template_key="processing_error_notice",
    )


def caveat_acknowledgment(name: str | None, company: str) -> RenderedEmail:
    body = (
        "Thanks for sharing the context along with your application — that kind of detail genuinely helps.\n\n"
        "Your background doesn't quite fit our usual checklist, and we don't want to shoehorn it into one. "
        "So instead of bouncing automated requests back at you, we're passing this over to someone on our "
        "team to take a proper look.\n\n"
        "You'll hear back from us once they've had a chance to dig in. Nothing more needed from you for now."
    )
    return RenderedEmail(
        subject="Thanks for the context — we're taking a closer look 👀",
        body=_wrap(name, body, company),
        template_key="caveat_acknowledgment",
    )


def unclassifiable(name: str | None, company: str) -> RenderedEmail:
    body = (
        "We got your email and appreciate you reaching out. We're not 100% sure if this was meant to be a "
        "job application though.\n\n"
        "If you're looking to apply, here's what we need: resume (PDF), GitHub link, and portfolio link. "
        "If you had a different question, just reply and let us know — a human on our team will get back "
        "to you.\n\n"
        "Either way, glad you're here!"
    )
    return RenderedEmail(
        subject="Thanks for your email! Quick question though 🤔",
        body=_wrap(name, body, company),
        template_key="unclassifiable",
    )
