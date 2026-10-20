# prompts.py

SCORING_PROMPT = """Compare the job with the candidate for a senior data engineering role.
Candidate resume:
{resume_profile}
Candidate preferences:
{candidate_profile}
Job:
{job}
List concrete technical skills required by the job: matched skills must also
appear in the candidate profile; missing skills must be absent from it.
Never infer a requirement from the candidate profile alone. Prioritize the most
important requirements, at most 10 skills per list. If the description is weak
or incomplete, say so. Mention seniority, leadership, domain or location only
when relevant to fit. The reason must be one sentence of at most 25 words.
Return JSON only, without markdown or extra keys:
{{"matched_skills":[],"missing_skills":[],"reason":""}}
"""
