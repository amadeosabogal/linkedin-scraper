"""
Database service using SQLite for local storage of leads, search history, and CRM pipeline.
"""
import sqlite3
import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "leads_platform.db")


def get_connection() -> sqlite3.Connection:
    """Get database connection with dict row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize database tables."""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Table for saved leads (Candidates, Decision Makers, Jobs, Companies)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_type TEXT NOT NULL,          -- 'person', 'job', 'company'
                linkedin_url TEXT UNIQUE NOT NULL,
                title TEXT,                       -- Name or Job Title or Company Name
                subtitle TEXT,                    -- Headline or Company or Industry
                location TEXT,
                score INTEGER DEFAULT 0,
                score_breakdown TEXT,             -- JSON string
                raw_data TEXT,                    -- Full JSON data
                crm_status TEXT DEFAULT 'Nuevo',  -- 'Nuevo', 'Contactado', 'En seguimiento', 'Interesado', 'Descartado'
                notes TEXT DEFAULT '',
                tags TEXT DEFAULT '',             -- Comma separated tags
                phone TEXT DEFAULT '',
                email TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Table for search history
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS search_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                search_type TEXT NOT NULL,        -- 'jobs', 'people', 'company', 'inspect'
                query_params TEXT NOT NULL,       -- JSON string
                results_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Table for saved search presets
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS search_presets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                preset_type TEXT NOT NULL,        -- 'job_matcher', 'b2b_leads', 'company_signals'
                criteria TEXT NOT NULL,           -- JSON string
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()


def save_or_update_lead(
    item_type: str,
    linkedin_url: str,
    title: str,
    subtitle: str,
    location: str,
    score: int,
    score_breakdown: Dict[str, Any],
    raw_data: Dict[str, Any],
    crm_status: str = "Nuevo",
    notes: str = "",
    tags: str = "",
    phone: str = "",
    email: str = ""
) -> int:
    """Save or update a lead in the database."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO leads (
                item_type, linkedin_url, title, subtitle, location, 
                score, score_breakdown, raw_data, crm_status, notes, tags, phone, email, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(linkedin_url) DO UPDATE SET
                title = excluded.title,
                subtitle = excluded.subtitle,
                location = excluded.location,
                score = excluded.score,
                score_breakdown = excluded.score_breakdown,
                raw_data = excluded.raw_data,
                updated_at = CURRENT_TIMESTAMP
        """, (
            item_type,
            linkedin_url,
            title,
            subtitle,
            location,
            score,
            json.dumps(score_breakdown, ensure_ascii=False),
            json.dumps(raw_data, ensure_ascii=False),
            crm_status,
            notes,
            tags,
            phone,
            email
        ))
        conn.commit()
        return cursor.lastrowid


def get_all_leads(item_type: Optional[str] = None, crm_status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve leads with optional filters."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        query = "SELECT * FROM leads WHERE 1=1"
        params = []
        
        if item_type:
            query += " AND item_type = ?"
            params.append(item_type)
        if crm_status:
            query += " AND crm_status = ?"
            params.append(crm_status)
            
        query += " ORDER BY score DESC, updated_at DESC"
        cursor.execute(query, params)
        
        rows = cursor.fetchall()
        leads = []
        for r in rows:
            lead = dict(r)
            if lead.get("score_breakdown"):
                try:
                    lead["score_breakdown"] = json.loads(lead["score_breakdown"])
                except Exception:
                    pass
            if lead.get("raw_data"):
                try:
                    lead["raw_data"] = json.loads(lead["raw_data"])
                except Exception:
                    pass
            leads.append(lead)
        return leads


def update_lead_status_or_notes(lead_id: int, crm_status: Optional[str] = None, notes: Optional[str] = None, tags: Optional[str] = None, phone: Optional[str] = None, email: Optional[str] = None):
    """Update CRM status, tags, notes, phone or email for a lead."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        updates = []
        params = []
        
        if crm_status is not None:
            updates.append("crm_status = ?")
            params.append(crm_status)
        if notes is not None:
            updates.append("notes = ?")
            params.append(notes)
        if tags is not None:
            updates.append("tags = ?")
            params.append(tags)
        if phone is not None:
            updates.append("phone = ?")
            params.append(phone)
        if email is not None:
            updates.append("email = ?")
            params.append(email)
            
        if not updates:
            return
            
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(lead_id)
        
        query = f"UPDATE leads SET {', '.join(updates)} WHERE id = ?"
        cursor.execute(query, params)
        conn.commit()


def delete_lead(lead_id: int):
    """Delete a lead by ID."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
        conn.commit()


def record_search_history(search_type: str, query_params: Dict[str, Any], results_count: int):
    """Record an executed search."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO search_history (search_type, query_params, results_count)
            VALUES (?, ?, ?)
        """, (search_type, json.dumps(query_params, ensure_ascii=False), results_count))
        conn.commit()


def get_search_history(limit: int = 15) -> List[Dict[str, Any]]:
    """Retrieve recent search history."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM search_history ORDER BY created_at DESC LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        result = []
        for r in rows:
            item = dict(r)
            try:
                item["query_params"] = json.loads(item["query_params"])
            except Exception:
                pass
            result.append(item)
        return result
