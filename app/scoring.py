"""
Scoring and Match Calculation Engine.
Calculates percentage affinity (% Match) for Jobs, B2B Leads (Decision Makers), and Company Signals.
"""
import re
from typing import Dict, Any, List, Optional, Tuple


def _normalize(text: Optional[str]) -> str:
    """Normalize text: lowercase, strip, remove accents/special chars."""
    if not text:
        return ""
    text = text.lower().strip()
    replacements = {
        'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
        'ü': 'u', 'ñ': 'n'
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text


def _extract_keywords(text: str) -> List[str]:
    """Extract individual words or tokens for semantic checking."""
    text_norm = _normalize(text)
    # Split by commas, slashes, whitespace
    tokens = re.split(r'[,;|\s/]+', text_norm)
    return [t for t in tokens if len(t) > 2]


SENIORITY_RANKS = {
    # High decision maker
    "ceo": 100, "cto": 100, "cfo": 100, "cmo": 100, "coo": 100, "cio": 100, "cro": 100,
    "founder": 100, "cofounder": 100, "fundador": 100, "owner": 95, "dueno": 95, "propietario": 95,
    "president": 95, "presidente": 95, "vice president": 90, "vicepresidente": 90, "vp": 90,
    "partner": 90, "socio": 90, "director": 85, "directora": 85, "head": 85, "gerente general": 90,
    "gerente": 75, "manager": 75, "lead": 70, "lider": 70, "chief": 90,
    # Mid / Individual contributor
    "senior": 60, "sr": 60, "specialist": 55, "especialista": 55, "consultant": 55, "consultor": 55,
    "executive": 55, "ejecutivo": 55, "coordinator": 50, "coordinador": 50, "analyst": 45, "analista": 45,
    "junior": 30, "jr": 30, "trainee": 20, "intern": 15, "pasante": 15, "practicante": 15
}


def calculate_lead_fit(person: Dict[str, Any], criteria: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calculate B2B Lead Fit (% Match) for a person/decision maker.
    
    Criteria structure:
      - target_roles: list or str of ideal job titles (e.g. "Director, Gerente, VP, Sales Manager")
      - target_keywords: list or str of product/domain/pain points (e.g. "SaaS, Logistica, B2B, CRM")
      - target_locations: list or str of target cities/countries (e.g. "Mexico, Colombia, Remote, Lima")
      - min_seniority: 'any', 'manager_plus', 'director_plus', 'c_level'
    """
    score_breakdown = {
        "title_score": 0,
        "keywords_score": 0,
        "location_score": 0,
        "seniority_score": 0,
        "matched_keywords": [],
        "missing_keywords": [],
        "notes": []
    }
    
    title = person.get("job_title") or ""
    if not title and person.get("experiences") and len(person["experiences"]) > 0:
        title = person["experiences"][0].get("position_title") or ""
    
    current_company = person.get("company") or ""
    if not current_company and person.get("experiences") and len(person["experiences"]) > 0:
        current_company = person["experiences"][0].get("institution_name") or ""
        
    location = person.get("location") or ""
    about = person.get("about") or ""
    
    # Combined textual profile
    all_experiences_text = " ".join([
        f"{e.get('position_title', '')} {e.get('institution_name', '')} {e.get('description', '')}"
        for e in person.get("experiences", [])
    ])
    full_profile_text = f"{title} {current_company} {about} {all_experiences_text}"
    full_text_norm = _normalize(full_profile_text)
    
    # 1. Title / Role Match (Weight: 35%)
    target_roles = criteria.get("target_roles", [])
    if isinstance(target_roles, str):
        target_roles = [r.strip() for r in target_roles.split(",") if r.strip()]
    
    title_norm = _normalize(title)
    title_points = 0
    if target_roles:
        matched_roles = []
        for role in target_roles:
            role_norm = _normalize(role)
            if role_norm and (role_norm in title_norm or role_norm in full_text_norm):
                matched_roles.append(role)
        if matched_roles:
            ratio = len(matched_roles) / len(target_roles)
            title_points = min(100, int(60 + (ratio * 40)))
            score_breakdown["notes"].append(f"Cargo coincide con: {', '.join(matched_roles)}")
        else:
            # Partial match by words
            any_word = False
            for role in target_roles:
                for word in _extract_keywords(role):
                    if word in title_norm:
                        any_word = True
                        title_points = 45
                        break
            if not any_word:
                title_points = 15
                score_breakdown["notes"].append("El cargo actual difiere de los roles objetivo.")
    else:
        title_points = 70  # neutral if no specific role defined
        
    score_breakdown["title_score"] = title_points

    # 2. Decision Maker Seniority (Weight: 20%)
    seniority_points = 30
    highest_rank = 0
    for key, rank in SENIORITY_RANKS.items():
        if key in title_norm:
            if rank > highest_rank:
                highest_rank = rank
    
    if highest_rank > 0:
        seniority_points = highest_rank
    else:
        # Check in experiences
        if len(person.get("experiences", [])) >= 3:
            seniority_points = 60
    score_breakdown["seniority_score"] = seniority_points

    # 3. Product / Domain Keywords & Pain Points (Weight: 30%)
    target_keywords = criteria.get("target_keywords", [])
    if isinstance(target_keywords, str):
        target_keywords = [k.strip() for k in target_keywords.split(",") if k.strip()]
        
    keyword_points = 0
    if target_keywords:
        matched_kws = []
        missing_kws = []
        for kw in target_keywords:
            kw_norm = _normalize(kw)
            if kw_norm and kw_norm in full_text_norm:
                matched_kws.append(kw)
            else:
                missing_kws.append(kw)
        
        score_breakdown["matched_keywords"] = matched_kws
        score_breakdown["missing_keywords"] = missing_kws
        
        if target_keywords:
            keyword_points = int((len(matched_kws) / len(target_keywords)) * 100)
            if matched_kws:
                score_breakdown["notes"].append(f"Palabras clave encontradas: {len(matched_kws)}/{len(target_keywords)}")
    else:
        keyword_points = 70
        
    score_breakdown["keywords_score"] = keyword_points

    # 4. Location Match (Weight: 15%)
    target_locations = criteria.get("target_locations", [])
    if isinstance(target_locations, str):
        target_locations = [l.strip() for l in target_locations.split(",") if l.strip()]
        
    loc_norm = _normalize(location)
    location_points = 0
    if target_locations:
        matched_loc = False
        for target_loc in target_locations:
            target_loc_norm = _normalize(target_loc)
            if target_loc_norm in loc_norm or "remot" in target_loc_norm or "cualquier" in target_loc_norm:
                matched_loc = True
                break
        if matched_loc:
            location_points = 100
            score_breakdown["notes"].append(f"Ubicación coincide: {location}")
        else:
            location_points = 25
            score_breakdown["notes"].append(f"Ubicación ({location}) fuera del filtro prioritario.")
    else:
        location_points = 80
    score_breakdown["location_score"] = location_points

    # Final Weighted Calculation
    total_score = int(
        (score_breakdown["title_score"] * 0.35) +
        (score_breakdown["keywords_score"] * 0.30) +
        (score_breakdown["seniority_score"] * 0.20) +
        (score_breakdown["location_score"] * 0.15)
    )
    total_score = max(5, min(99, total_score))

    # Badge classification
    if total_score >= 78:
        badge = {"label": "Alta Afinidad (Lead Calificado)", "level": "high", "color": "green"}
    elif total_score >= 50:
        badge = {"label": "Afinidad Media (Potencial)", "level": "medium", "color": "amber"}
    else:
        badge = {"label": "Baja Afinidad", "level": "low", "color": "gray"}

    # Generate Icebreaker suggestions
    name = person.get("name") or "Hola"
    first_name = name.split()[0] if name != "Hola" else "estimado/a"
    company_name = current_company or "tu empresa"
    role_name = title or "tu rol"
    
    icebreakers = [
        f"Hola {first_name}, estuve revisando tu trayectoria liderando como {role_name} en {company_name} y me llamó la atención su enfoque. ¿Estarías abierto a conectar?",
        f"Hola {first_name}, veo que gestionas iniciativas clave en {company_name}. Estamos ayudando a líderes en {role_name} a optimizar procesos; me encantaría compartirte un par de ideas."
    ]

    return {
        "score": total_score,
        "badge": badge,
        "breakdown": score_breakdown,
        "icebreakers": icebreakers
    }


def calculate_job_match(job: Dict[str, Any], criteria: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calculate Job Match (% Compatibility) between a job posting and candidate profile.
    
    Criteria structure:
      - desired_titles: list or str (e.g. "Software Engineer, Full Stack, Python Developer")
      - user_skills: list or str of skills (e.g. "Python, React, FastAPI, AWS, Docker, SQL")
      - preferred_locations: list or str
      - remote_only: bool
    """
    score_breakdown = {
        "title_score": 0,
        "skills_score": 0,
        "location_score": 0,
        "freshness_score": 0,
        "matched_skills": [],
        "missing_skills": [],
        "notes": []
    }
    
    job_title = job.get("job_title") or ""
    description = job.get("job_description") or ""
    location = job.get("location") or ""
    posted_date = job.get("posted_date") or ""
    
    title_norm = _normalize(job_title)
    desc_norm = _normalize(description)
    full_job_text = f"{title_norm} {desc_norm}"

    # 1. Title Alignment (Weight: 35%)
    desired_titles = criteria.get("desired_titles", [])
    if isinstance(desired_titles, str):
        desired_titles = [t.strip() for t in desired_titles.split(",") if t.strip()]
        
    title_score = 0
    if desired_titles:
        matched_titles = []
        for t in desired_titles:
            t_norm = _normalize(t)
            if t_norm in title_norm:
                matched_titles.append(t)
        if matched_titles:
            title_score = 100
            score_breakdown["notes"].append(f"Título coincide con: {', '.join(matched_titles)}")
        else:
            # Word-level match
            words_matched = 0
            all_target_words = []
            for t in desired_titles:
                all_target_words.extend(_extract_keywords(t))
            for w in set(all_target_words):
                if w in title_norm:
                    words_matched += 1
            if words_matched > 0:
                title_score = min(80, words_matched * 30)
            else:
                title_score = 25
    else:
        title_score = 75
    score_breakdown["title_score"] = title_score

    # 2. Skills Match (Weight: 35%)
    user_skills = criteria.get("user_skills", [])
    if isinstance(user_skills, str):
        user_skills = [s.strip() for s in user_skills.split(",") if s.strip()]
        
    skills_score = 0
    if user_skills:
        matched = []
        missing = []
        for skill in user_skills:
            skill_norm = _normalize(skill)
            # Use regex border for short terms like 'go', 'c', 'r', 'ai'
            if len(skill_norm) <= 2:
                pattern = r'\b' + re.escape(skill_norm) + r'\b'
                if re.search(pattern, full_job_text):
                    matched.append(skill)
                else:
                    missing.append(skill)
            else:
                if skill_norm in full_job_text:
                    matched.append(skill)
                else:
                    missing.append(skill)
        
        score_breakdown["matched_skills"] = matched
        score_breakdown["missing_skills"] = missing
        
        if user_skills:
            skills_score = int((len(matched) / len(user_skills)) * 100)
            score_breakdown["notes"].append(f"Habilidades detectadas: {len(matched)} de {len(user_skills)}")
    else:
        skills_score = 70
    score_breakdown["skills_score"] = skills_score

    # 3. Location / Remote Preference (Weight: 20%)
    preferred_locations = criteria.get("preferred_locations", [])
    if isinstance(preferred_locations, str):
        preferred_locations = [l.strip() for l in preferred_locations.split(",") if l.strip()]
    remote_only = criteria.get("remote_only", False)
    
    loc_norm = _normalize(location)
    is_remote = "remot" in loc_norm or "remoto" in loc_norm or "teletrabajo" in loc_norm or "hibrid" in loc_norm
    
    location_score = 50
    if remote_only:
        if is_remote:
            location_score = 100
            score_breakdown["notes"].append("Modalidad Remota/Híbrida confirmada.")
        else:
            location_score = 20
            score_breakdown["notes"].append("El puesto no parece especificar modalidad remota.")
    elif preferred_locations:
        matched_loc = False
        for pl in preferred_locations:
            pl_norm = _normalize(pl)
            if pl_norm in loc_norm or (pl_norm in ["remoto", "remote"] and is_remote):
                matched_loc = True
                break
        if matched_loc:
            location_score = 100
            score_breakdown["notes"].append(f"Ubicación adecuada: {location}")
        else:
            location_score = 30
    else:
        location_score = 80
    score_breakdown["location_score"] = location_score

    # 4. Freshness & Applicant Ratio (Weight: 10%)
    freshness_score = 70
    posted_norm = _normalize(posted_date)
    if "hour" in posted_norm or "hora" in posted_norm or "day" in posted_norm or "dia" in posted_norm:
        freshness_score = 100
    elif "week" in posted_norm or "semana" in posted_norm:
        freshness_score = 75
    elif "month" in posted_norm or "mes" in posted_norm:
        freshness_score = 40
    score_breakdown["freshness_score"] = freshness_score

    # Calculate Total Score
    total_score = int(
        (score_breakdown["title_score"] * 0.35) +
        (score_breakdown["skills_score"] * 0.35) +
        (score_breakdown["location_score"] * 0.20) +
        (score_breakdown["freshness_score"] * 0.10)
    )
    total_score = max(5, min(99, total_score))

    if total_score >= 80:
        badge = {"label": "Match Excelente", "level": "high", "color": "green"}
    elif total_score >= 55:
        badge = {"label": "Match Bueno", "level": "medium", "color": "amber"}
    else:
        badge = {"label": "Baja Compatibilidad", "level": "low", "color": "gray"}

    return {
        "score": total_score,
        "badge": badge,
        "breakdown": score_breakdown
    }


BUYING_SIGNALS = [
    ("Contratación activa / Expansión", ["hiring", "contratando", "buscamos", "unete", "vacante", "open positions", "we are hiring", "crecimiento", "expansion"]),
    ("Lanzamiento de Producto", ["nuevo producto", "lanzamiento", "launching", "new feature", "announcing", "anuncio", "version"]),
    ("Financiamiento o Alianzas", ["funding", "ronda", "inversion", "partnership", "alianza", "acuerdo", "adquisicion", "series a", "series b"]),
    ("Adopción Tecnológica / Modernización", ["transformacion digital", "migracion", "ia", "inteligencia artificial", "automatizacion", "cloud", "saas", "software"])
]


def calculate_company_intent(company: Dict[str, Any], posts: List[Dict[str, Any]], criteria: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calculate Buying Intent & Commercial Signals for a company.
    """
    detected_signals = []
    total_signals_score = 20  # Base score
    
    # Check about_us and specialties
    about = _normalize(company.get("about_us", ""))
    specialties = _normalize(company.get("specialties", ""))
    
    # Evaluate Posts
    for post in posts:
        post_text = post.get("text", "")
        post_text_norm = _normalize(post_text)
        if not post_text_norm:
            continue
            
        for signal_name, triggers in BUYING_SIGNALS:
            for trigger in triggers:
                if trigger in post_text_norm:
                    preview = post_text[:140] + "..." if len(post_text) > 140 else post_text
                    detected_signals.append({
                        "category": signal_name,
                        "trigger": trigger,
                        "quote": preview,
                        "post_url": post.get("linkedin_url", "")
                    })
                    break

    # Calculate score based on unique signals found
    unique_categories = len(set(s["category"] for s in detected_signals))
    total_signals_score += (unique_categories * 25) + min(20, len(detected_signals) * 5)
    total_signals_score = min(98, total_signals_score)

    if total_signals_score >= 75:
        badge = {"label": "Alta Actividad y Señales Comerciales", "level": "high", "color": "green"}
    elif total_signals_score >= 45:
        badge = {"label": "Actividad Moderada", "level": "medium", "color": "amber"}
    else:
        badge = {"label": "Pocas Señales Recientes", "level": "low", "color": "gray"}

    return {
        "score": total_signals_score,
        "badge": badge,
        "signals_count": len(detected_signals),
        "signals": detected_signals[:10],
        "posts_analyzed": len(posts)
    }
