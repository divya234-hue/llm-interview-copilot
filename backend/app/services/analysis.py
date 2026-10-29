import re


SKILL_TERMS = sorted({
    "python", "java", "javascript", "typescript", "sql", "git", "docker", "fastapi", "react",
    "machine learning", "deep learning", "natural language processing", "nlp", "llm", "rag",
    "pytorch", "tensorflow", "scikit-learn", "pandas", "numpy", "aws", "azure", "gcp",
    "data structures", "algorithms", "computer vision", "transformers", "chromadb",
})


def extract_skills(text: str) -> list[str]:
    lowered = text.lower()
    return [skill for skill in SKILL_TERMS if re.search(rf"(?<!\w){re.escape(skill)}(?!\w)", lowered)]


def analyze_resume(text: str) -> dict:
    skills = extract_skills(text)
    sections = {
        "education": bool(re.search(r"\b(education|b\.?tech|bachelor|university|college)\b", text, re.I)),
        "experience": bool(re.search(r"\b(experience|intern(ship)?|employment|work history)\b", text, re.I)),
        "projects": bool(re.search(r"\b(projects?|built|developed|implemented)\b", text, re.I)),
    }
    return {
        "skills": skills,
        "sections_found": [name for name, found in sections.items() if found],
        "sections_not_found": [name for name, found in sections.items() if not found],
        "strengths": [f"Resume mentions {skill}." for skill in skills[:5]],
        "suggestions": [
            "Add measurable outcomes and specific contributions where accurate."
        ] if text else [],
        "notice": "Automated keyword/section analysis; verify results manually. No qualifications are inferred.",
    }


def analyze_job(description: str, resume_text: str = "") -> dict:
    all_skills = extract_skills(description)
    job_sentences = re.split(r"(?<=[.!?])\s+|\n+", description)
    preferred = [
        skill for skill in all_skills
        if any(
            re.search(r"\b(preferred|prefer|bonus|nice.to.have|desirable|optional)\b", sentence, re.I)
            and re.search(rf"(?<!\w){re.escape(skill)}(?!\w)", sentence, re.I)
            for sentence in job_sentences
        )
    ]
    requirements = [skill for skill in all_skills if skill not in preferred]
    candidate_skills = extract_skills(resume_text)
    matched = [skill for skill in all_skills if skill in candidate_skills]
    missing = [skill for skill in all_skills if skill not in candidate_skills]
    responsibilities = [
        sentence.strip() for sentence in job_sentences
        if re.search(r"\b(responsible|build|develop|design|collaborat|maintain|lead|analyz)\w*\b", sentence, re.I)
    ][:8]
    experience_requirements = [
        sentence.strip() for sentence in job_sentences
        if re.search(r"\b(experience|years?|intern(ship)?|degree|coursework)\b", sentence, re.I)
    ][:8]
    score = round(100 * len(matched) / len(all_skills)) if all_skills else 0
    resume_sentences = re.split(r"(?<=[.!?])\s+|\n+", resume_text)
    evidence = {}
    for skill in matched:
        snippet = next(
            (
                sentence.strip() for sentence in resume_sentences
                if re.search(rf"(?<!\w){re.escape(skill)}(?!\w)", sentence, re.I)
            ),
            "",
        )
        evidence[skill] = snippet[:240]
    return {
        "required_skills": requirements,
        "preferred_skills": preferred,
        "responsibilities": responsibilities,
        "experience_requirements": experience_requirements,
        "matched_skills": matched,
        "missing_skills": missing,
        "match_score": score,
        "score_label": "Heuristic keyword overlap estimate, not an objective hiring probability.",
        "evidence": evidence,
    }
