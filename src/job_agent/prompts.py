"""Prompt templates. Kept model-neutral: no special tokens, no provider-specific tricks."""

from __future__ import annotations

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

TRIAGE_SYSTEM = """\
You screen startup job postings for one candidate. Decide quickly whether a posting deserves a
careful read. Judge the actual work, not the title.

keep = true when ALL of these hold:
- It is a software / technical role: AI or LLM engineering, backend, full-stack, frontend,
  devops / platform / infra, data engineering, ML, mobile, forward-deployed or solutions
  engineering that involves real coding.
- Someone with 0-1 years of full-time experience could realistically get it
  (internships count as experience but do not make a role senior).

keep = false for:
- Non-technical roles: sales, marketing, growth, recruiting, operations, support, finance, legal,
  content, design-only.
- Clearly senior roles: Senior / Staff / Principal / Lead / Head / Director / Manager, or 3+ years
  required. "Founding engineer" is NOT automatically senior; read the requirements.

Do NOT judge location, visa or salary here. That happens later."""

EXTRACT_SYSTEM = """\
You read one startup job posting and extract facts into the given JSON schema.
Only use what the posting says; use null / empty lists when it doesn't say. Be concise.

India eligibility (india_eligible) means: can a person living in India do this job
WITHOUT moving abroad?
- Office in India (Bengaluru, Hyderabad, Mumbai, Delhi NCR, Pune, Chennai, remote-India...) -> yes.
- Remote "anywhere", "worldwide", "global", "APAC", "Asia", "India" -> yes.
- Remote but limited to US/Canada/EU residents, or "US citizen/visa only", or must be in a US
  state -> no.
- Onsite / hybrid outside India -> no (relocation_abroad_required = true).
- Remote with no stated region restriction -> unclear, and quote the closest hint.

visa_sponsorship: "offered" if the posting/visa field says it will sponsor; "not_needed" for
India-based or remote-from-India jobs; "not_offered" if it says citizens/authorized only.

Salary: convert shorthand to plain numbers in the original currency.
"$120K - $150K" -> 120000 / 150000 USD year. "₹12L - ₹18L" -> 1200000 / 1800000 INR year.
"₹50K/month" -> 50000 INR month. Never convert currencies yourself.

dsa_signals: quote phrases about LeetCode, algorithms/data-structures rounds, competitive
programming, or explicit "no leetcode" / "practical interviews". Empty if none.

red_flags: unpaid, commission-only, extreme hours (e.g. "996", "70+ hours"), equity-only,
unclear compensation for a full-time role, or a role that is mostly non-engineering."""


def triage_messages(preferences: str, job_text: str) -> list[BaseMessage]:
    return [
        SystemMessage(TRIAGE_SYSTEM),
        HumanMessage(f"{preferences}\n\n--- POSTING ---\n{job_text}"),
    ]


def extract_messages(job_text: str) -> list[BaseMessage]:
    return [SystemMessage(EXTRACT_SYSTEM), HumanMessage(f"--- POSTING ---\n{job_text}")]
