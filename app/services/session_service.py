"""
Session management service for LinkedIn authentication.
"""
import os
import json
import time
from typing import Dict, Any
from linkedin_scraper.core.browser import BrowserManager
from linkedin_scraper.core.auth import wait_for_manual_login

SESSION_FILE = "linkedin_session.json"


def get_session_file_path() -> str:
    """Get absolute path to linkedin_session.json in root or app directory."""
    # Check in project root
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    root_path = os.path.join(root_dir, SESSION_FILE)
    if os.path.exists(root_path):
        return root_path
    
    # Check current working directory
    cwd_path = os.path.join(os.getcwd(), SESSION_FILE)
    if os.path.exists(cwd_path):
        return cwd_path
        
    return root_path


def check_session_status() -> Dict[str, Any]:
    """Check if LinkedIn session file exists and is populated."""
    path = get_session_file_path()
    if not os.path.exists(path):
        return {
            "exists": False,
            "status": "No configurada",
            "message": "No se ha encontrado el archivo linkedin_session.json. Inicia sesión para activarlo.",
            "path": path,
            "cookies_count": 0,
            "last_modified": None
        }
        
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        cookies = data.get("cookies", []) if isinstance(data, dict) else []
        mod_time = os.path.getmtime(path)
        mod_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mod_time))
        
        # Check if li_at cookie exists
        has_li_at = any(c.get("name") == "li_at" for c in cookies if isinstance(c, dict))
        
        if has_li_at and len(cookies) > 0:
            return {
                "exists": True,
                "status": "Activa",
                "message": f"Sesión cargada con {len(cookies)} cookies (li_at detectada).",
                "path": path,
                "cookies_count": len(cookies),
                "last_modified": mod_str
            }
        else:
            return {
                "exists": True,
                "status": "Incompleta / Expirada",
                "message": "El archivo de sesión existe pero parece no contener las cookies de autenticación necesarias.",
                "path": path,
                "cookies_count": len(cookies),
                "last_modified": mod_str
            }
    except Exception as e:
        return {
            "exists": True,
            "status": "Error",
            "message": f"Error al leer el archivo de sesión: {str(e)}",
            "path": path,
            "cookies_count": 0,
            "last_modified": None
        }


async def launch_manual_login(timeout: int = 300000) -> Dict[str, Any]:
    """
    Launch non-headless browser to allow user to log in manually on LinkedIn
    and save the session upon detection.
    """
    session_path = get_session_file_path()
    async with BrowserManager(headless=False) as browser:
        # Navigate to LinkedIn login
        await browser.page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        
        # Wait for user to finish login
        try:
            await wait_for_manual_login(browser.page, timeout=timeout)
            await browser.save_session(session_path)
            return {
                "success": True,
                "message": "¡Sesión guardada exitosamente!",
                "path": session_path
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Tiempo de espera agotado o error: {str(e)}",
                "path": session_path
            }
