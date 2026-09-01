"""
Scraper Service: Coordinates Playwright scrapers, progress tracking, and scoring.
"""
import asyncio
import logging
from typing import Dict, Any, List, Optional, Callable
from urllib.parse import urlencode, quote_plus

from linkedin_scraper.core.browser import BrowserManager
from linkedin_scraper.scrapers.person import PersonScraper
from linkedin_scraper.scrapers.job_search import JobSearchScraper
from linkedin_scraper.scrapers.job import JobScraper
from linkedin_scraper.scrapers.company import CompanyScraper
from linkedin_scraper.scrapers.company_posts import CompanyPostsScraper
from linkedin_scraper.callbacks import ProgressCallback

from app.services.session_service import get_session_file_path
from app.scoring import calculate_job_match, calculate_lead_fit, calculate_company_intent
from app.services.db_service import save_or_update_lead, record_search_history

logger = logging.getLogger(__name__)


class CustomProgressCallback(ProgressCallback):
    """Callback that reports real-time progress to an async queue or callback function."""
    
    def __init__(self, on_update_fn: Optional[Callable[[str, int, str], None]] = None):
        self.on_update_fn = on_update_fn

    async def on_start(self, scraper_name: str, target: str) -> None:
        if self.on_update_fn:
            await self.on_update_fn("iniciando", 5, f"Iniciando {scraper_name} en {target[:45]}...")

    async def on_progress(self, message: str, percent: int) -> None:
        if self.on_update_fn:
            await self.on_update_fn("progreso", percent, message)

    async def on_complete(self, scraper_name: str, result: Any) -> None:
        if self.on_update_fn:
            await self.on_update_fn("completado", 100, f"{scraper_name} finalizado con éxito.")

    async def on_error(self, scraper_name: str, error: Exception) -> None:
        if self.on_update_fn:
            await self.on_update_fn("error", 0, f"Error en {scraper_name}: {str(error)}")


async def extract_people_search_urls(page, keywords: str, title: Optional[str] = None, location: Optional[str] = None, limit: int = 10) -> List[str]:
    """Search people on LinkedIn and extract profile URLs with pagination support."""
    query_parts = []
    if keywords:
        query_parts.append(keywords)
    if title:
        query_parts.append(f'"{title}"')
    if location:
        query_parts.append(location)
        
    query_str = " ".join(query_parts)
    base_search_url = f"https://www.linkedin.com/search/results/people/?keywords={quote_plus(query_str)}"
    
    found_urls = []
    seen = set()
    current_page = 1
    max_pages = max(1, (limit // 10) + 2)

    while len(found_urls) < limit and current_page <= max_pages:
        page_url = f"{base_search_url}&page={current_page}" if current_page > 1 else base_search_url
        logger.info(f"Navigating to people search (page {current_page}): {page_url}")
        
        try:
            await page.goto(page_url, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(2)
            
            # Scroll down to load cards
            for _ in range(3):
                await page.evaluate("window.scrollBy(0, 800)")
                await asyncio.sleep(0.8)
                
            # Extract links with /in/
            profile_links = await page.locator('a[href*="/in/"]').all()
            prev_count = len(found_urls)
            
            for link in profile_links:
                if len(found_urls) >= limit:
                    break
                try:
                    href = await link.get_attribute("href")
                    if href and "/in/" in href:
                        clean = href.split("?")[0].split("#")[0].rstrip("/")
                        if not clean.startswith("http"):
                            clean = f"https://www.linkedin.com{clean}"
                        if "/in/" in clean and clean not in seen and not clean.endswith("/in") and not "/overlay/" in clean:
                            found_urls.append(clean)
                            seen.add(clean)
                except Exception:
                    continue
            
            # If no new links were added on this page, stop paginating
            if len(found_urls) == prev_count:
                break
                
            current_page += 1
        except Exception as e:
            logger.warning(f"Error fetching people search page {current_page}: {e}")
            break
            
    return found_urls[:limit]


class ScraperService:
    """Service to handle all scraping actions with scoring and database caching."""
    
    @staticmethod
    async def search_and_score_jobs(
        keywords: str,
        location: str,
        limit: int,
        target_criteria: Dict[str, Any],
        progress_fn: Optional[Callable] = None,
        is_stopped_fn: Optional[Callable[[], bool]] = None
    ) -> List[Dict[str, Any]]:
        """Search jobs, scrape details, calculate match %, and stream results 1 by 1."""
        session_path = get_session_file_path()
        results = []
        
        async def emit(status: str, percent: int, msg: str, item: Optional[Dict[str, Any]] = None):
            if progress_fn:
                await progress_fn(status, percent, msg, item)

        await emit("iniciando", 5, f"Buscando ofertas para '{keywords}'...")
        
        async with BrowserManager(headless=True) as browser:
            try:
                await browser.load_session(session_path)
            except Exception:
                await emit("advertencia", 10, "Aviso: No se pudo cargar sesión de LinkedIn previa.")
            
            search_scraper = JobSearchScraper(browser.page)
            await emit("progreso", 15, "Obteniendo enlaces de publicaciones de empleo...")
            job_urls = await search_scraper.search(keywords=keywords, location=location, limit=limit)
            
            await emit("progreso", 25, f"Se encontraron {len(job_urls)} ofertas. Extrayendo de 1 en 1...")
            
            job_scraper = JobScraper(browser.page)
            for idx, job_url in enumerate(job_urls):
                if is_stopped_fn and is_stopped_fn():
                    await emit("progreso", 100, f"Búsqueda detenida por el usuario. {len(results)} ofertas procesadas.")
                    break
                    
                try:
                    pct = int(25 + ((idx + 1) / max(1, len(job_urls)) * 70))
                    await emit("progreso", pct, f"Procesando oferta {idx+1} de {len(job_urls)}...")
                    
                    job_obj = await job_scraper.scrape(job_url)
                    job_dict = job_obj.to_dict()
                    
                    # Calculate % Match
                    match_result = calculate_job_match(job_dict, target_criteria)
                    job_dict["score"] = match_result["score"]
                    job_dict["badge"] = match_result["badge"]
                    job_dict["score_breakdown"] = match_result["breakdown"]
                    
                    # Save to DB
                    save_or_update_lead(
                        item_type="job",
                        linkedin_url=job_url,
                        title=job_dict.get("job_title") or "Puesto de empleo",
                        subtitle=job_dict.get("company") or "Empresa no especificada",
                        location=job_dict.get("location") or location,
                        score=match_result["score"],
                        score_breakdown=match_result["breakdown"],
                        raw_data=job_dict,
                        crm_status="Nuevo"
                    )
                    
                    results.append(job_dict)
                    # Emit individual item immediately!
                    await emit("item_found", pct, f"Oferta {idx+1}/{len(job_urls)}: {job_dict.get('job_title')}", job_dict)
                except Exception as e:
                    logger.error(f"Error scraping job {job_url}: {e}")
                    continue
                    
        # Sort by score descending
        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        record_search_history("jobs", {"keywords": keywords, "location": location, "criteria": target_criteria}, len(results))
        await emit("completado", 100, f"Proceso finalizado. {len(results)} ofertas procesadas.")
        return results

    @staticmethod
    async def search_and_score_leads(
        keywords: str,
        title: Optional[str],
        location: Optional[str],
        limit: int,
        target_criteria: Dict[str, Any],
        progress_fn: Optional[Callable] = None,
        is_stopped_fn: Optional[Callable[[], bool]] = None
    ) -> List[Dict[str, Any]]:
        """Search people on LinkedIn, scrape full profiles 1 by 1, and stream results."""
        session_path = get_session_file_path()
        results = []
        
        async def emit(status: str, percent: int, msg: str, item: Optional[Dict[str, Any]] = None):
            if progress_fn:
                await progress_fn(status, percent, msg, item)

        await emit("iniciando", 5, f"Buscando tomadores de decisión para '{keywords or title}'...")
        
        async with BrowserManager(headless=True) as browser:
            try:
                await browser.load_session(session_path)
            except Exception:
                await emit("advertencia", 10, "Aviso: No se pudo cargar sesión de LinkedIn.")

            # Search people with pagination support
            await emit("progreso", 15, f"Buscando hasta {limit} perfiles en LinkedIn...")
            profile_urls = await extract_people_search_urls(browser.page, keywords, title, location, limit=limit)
            
            await emit("progreso", 25, f"Se encontraron {len(profile_urls)} perfiles. Extrayendo de 1 en 1...")
            
            person_scraper = PersonScraper(browser.page)
            for idx, purl in enumerate(profile_urls):
                if is_stopped_fn and is_stopped_fn():
                    await emit("progreso", 100, f"Búsqueda detenida por el usuario. {len(results)} leads guardados.")
                    break
                    
                try:
                    pct = int(25 + ((idx + 1) / max(1, len(profile_urls)) * 70))
                    await emit("progreso", pct, f"Analizando lead {idx+1} de {len(profile_urls)}...")
                    
                    person_obj = await person_scraper.scrape(purl)
                    person_dict = person_obj.to_dict()
                    
                    if target_criteria.get("require_email"):
                        has_email = any(c.get("type") == "email" for c in person_dict.get("contacts", []))
                        if not has_email:
                            await emit("progreso", pct, f"Lead descartado: {person_dict.get('name', 'Perfil')} no tiene correo público.")
                            continue
                            
                    # Calculate B2B Lead Fit
                    lead_fit = calculate_lead_fit(person_dict, target_criteria)
                    person_dict["score"] = lead_fit["score"]
                    person_dict["badge"] = lead_fit["badge"]
                    person_dict["score_breakdown"] = lead_fit["breakdown"]
                    person_dict["icebreakers"] = lead_fit["icebreakers"]
                    
                    # Save to DB
                    save_or_update_lead(
                        item_type="person",
                        linkedin_url=purl,
                        title=person_dict.get("name") or "Perfil LinkedIn",
                        subtitle=f"{person_dict.get('job_title') or ''} @ {person_dict.get('company') or ''}".strip(" @"),
                        location=person_dict.get("location") or location or "",
                        score=lead_fit["score"],
                        score_breakdown=lead_fit["breakdown"],
                        raw_data=person_dict,
                        crm_status="Nuevo"
                    )
                    
                    results.append(person_dict)
                    # Emit individual item immediately!
                    await emit("item_found", pct, f"Lead {idx+1}/{len(profile_urls)}: {person_dict.get('name')}", person_dict)
                except Exception as e:
                    logger.error(f"Error scraping profile {purl}: {e}")
                    continue
                    
        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        record_search_history("people", {"keywords": keywords, "title": title, "location": location, "criteria": target_criteria}, len(results))
        await emit("completado", 100, f"Búsqueda finalizada. {len(results)} leads calificados.")
        return results

    @staticmethod
    async def analyze_company(
        company_url: str,
        include_posts: bool = True,
        target_criteria: Optional[Dict[str, Any]] = None,
        progress_fn: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """Scrape company profile, extract recent posts, and detect buying signals."""
        session_path = get_session_file_path()
        target_criteria = target_criteria or {}
        
        async def emit(status: str, percent: int, msg: str):
            if progress_fn:
                await progress_fn(status, percent, msg)

        await emit("iniciando", 10, f"Analizando empresa: {company_url}...")
        
        async with BrowserManager(headless=True) as browser:
            try:
                await browser.load_session(session_path)
            except Exception:
                pass
                
            company_scraper = CompanyScraper(browser.page)
            await emit("progreso", 30, "Extrayendo datos de la empresa...")
            company_obj = await company_scraper.scrape(company_url)
            company_dict = company_obj.to_dict()
            
            posts_list = []
            if include_posts:
                await emit("progreso", 60, "Extrayendo publicaciones recientes...")
                try:
                    posts_scraper = CompanyPostsScraper(browser.page)
                    posts = await posts_scraper.scrape(company_url, limit=6)
                    posts_list = [p.to_dict() for p in posts]
                except Exception as e:
                    logger.warning(f"Could not scrape company posts: {e}")
                    
            await emit("progreso", 85, "Evaluando señales comerciales y de compra...")
            intent_analysis = calculate_company_intent(company_dict, posts_list, target_criteria)
            
            company_dict["posts"] = posts_list
            company_dict["score"] = intent_analysis["score"]
            company_dict["badge"] = intent_analysis["badge"]
            company_dict["signals"] = intent_analysis["signals"]
            company_dict["signals_count"] = intent_analysis["signals_count"]
            company_dict["posts_analyzed"] = intent_analysis["posts_analyzed"]
            
            # Save to DB
            save_or_update_lead(
                item_type="company",
                linkedin_url=company_url,
                title=company_dict.get("name") or "Empresa",
                subtitle=f"{company_dict.get('industry') or ''} • {company_dict.get('company_size') or ''}".strip(" •"),
                location=company_dict.get("headquarters") or "",
                score=intent_analysis["score"],
                score_breakdown={"signals": intent_analysis["signals"], "badge": intent_analysis["badge"]},
                raw_data=company_dict,
                crm_status="Nuevo"
            )
            
            record_search_history("company", {"company_url": company_url}, 1)
            await emit("completado", 100, f"Análisis de {company_dict.get('name')} completado.")
            return company_dict

    @staticmethod
    async def inspect_url(
        url: str,
        target_criteria: Optional[Dict[str, Any]] = None,
        progress_fn: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """Inspect any direct LinkedIn URL (Person, Job, Company)."""
        target_criteria = target_criteria or {}
        session_path = get_session_file_path()
        
        async def emit(status: str, percent: int, msg: str):
            if progress_fn:
                await progress_fn(status, percent, msg)

        url_clean = url.strip()
        
        async with BrowserManager(headless=True) as browser:
            try:
                await browser.load_session(session_path)
            except Exception:
                pass
                
            if "/in/" in url_clean:
                await emit("progreso", 40, "Inspeccionando perfil de persona...")
                scraper = PersonScraper(browser.page)
                person_obj = await scraper.scrape(url_clean)
                data = person_obj.to_dict()
                lead_fit = calculate_lead_fit(data, target_criteria)
                data["score"] = lead_fit["score"]
                data["badge"] = lead_fit["badge"]
                data["score_breakdown"] = lead_fit["breakdown"]
                data["icebreakers"] = lead_fit["icebreakers"]
                data["item_type"] = "person"
                
                save_or_update_lead(
                    item_type="person",
                    linkedin_url=url_clean,
                    title=data.get("name") or "Perfil LinkedIn",
                    subtitle=f"{data.get('job_title') or ''} @ {data.get('company') or ''}".strip(" @"),
                    location=data.get("location") or "",
                    score=lead_fit["score"],
                    score_breakdown=lead_fit["breakdown"],
                    raw_data=data,
                    crm_status="Nuevo"
                )
                await emit("completado", 100, "Perfil procesado.")
                return data
                
            elif "/jobs" in url_clean:
                await emit("progreso", 40, "Inspeccionando oferta de empleo...")
                scraper = JobScraper(browser.page)
                job_obj = await scraper.scrape(url_clean)
                data = job_obj.to_dict()
                match = calculate_job_match(data, target_criteria)
                data["score"] = match["score"]
                data["badge"] = match["badge"]
                data["score_breakdown"] = match["breakdown"]
                data["item_type"] = "job"
                
                save_or_update_lead(
                    item_type="job",
                    linkedin_url=url_clean,
                    title=data.get("job_title") or "Puesto de empleo",
                    subtitle=data.get("company") or "",
                    location=data.get("location") or "",
                    score=match["score"],
                    score_breakdown=match["breakdown"],
                    raw_data=data,
                    crm_status="Nuevo"
                )
                await emit("completado", 100, "Oferta procesada.")
                return data
                
            elif "/company/" in url_clean:
                await emit("progreso", 40, "Inspeccionando página de empresa...")
                scraper = CompanyScraper(browser.page)
                comp_obj = await scraper.scrape(url_clean)
                data = comp_obj.to_dict()
                
                # Fetch posts
                posts = []
                try:
                    p_scraper = CompanyPostsScraper(browser.page)
                    posts_objs = await p_scraper.scrape(url_clean, limit=4)
                    posts = [p.to_dict() for p in posts_objs]
                except Exception:
                    pass
                    
                data["posts"] = posts
                intent = calculate_company_intent(data, posts, target_criteria)
                data["score"] = intent["score"]
                data["badge"] = intent["badge"]
                data["signals"] = intent["signals"]
                data["signals_count"] = intent["signals_count"]
                data["item_type"] = "company"
                
                save_or_update_lead(
                    item_type="company",
                    linkedin_url=url_clean,
                    title=data.get("name") or "Empresa",
                    subtitle=f"{data.get('industry') or ''} • {data.get('company_size') or ''}".strip(" •"),
                    location=data.get("headquarters") or "",
                    score=intent["score"],
                    score_breakdown={"signals": intent["signals"], "badge": intent["badge"]},
                    raw_data=data,
                    crm_status="Nuevo"
                )
                await emit("completado", 100, "Empresa procesada.")
                return data
            else:
                raise ValueError("URL no reconocida. Debe ser de un perfil (/in/), empleo (/jobs/) o empresa (/company/).")
