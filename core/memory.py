"""
GhostFix AI - Cloud Memory System
Supabase-based error-fix memory with self-learning
"""
import json
import warnings
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"supabase(\.|$)")
warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"postgrest(\.|$)")
warnings.filterwarnings("ignore", category=DeprecationWarning, message=r"The 'timeout' parameter is deprecated.*")
warnings.filterwarnings("ignore", category=DeprecationWarning, message=r"The 'verify' parameter is deprecated.*")

from collections import Counter
import hashlib

from utils.env import SUPABASE_URL, SUPABASE_KEY

try:
    from supabase import create_client
except Exception:
    create_client = None


@dataclass
class ErrorRecord:
    """Error record for memory storage"""
    error_type: str
    error_message: str
    language: str
    context: str
    cause: str
    fix: str
    success: bool
    source: str = "memory"
    created_at: str = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()

def fingerprint(error: str, cause: str, fix: str, context: str) -> str:
    raw = f"{error}|{cause}|{fix}|{context}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

class LocalOnlyMemory:
    """No-op memory backend for fresh local installs without cloud credentials."""

    mode = "local-only"

    def save_error(self, *args, **kwargs) -> int:
        return -1

    def search_memory(self, *args, **kwargs) -> Optional[dict]:
        return None

    def get_top_errors(self, limit: int = 10) -> list:
        return []

    def save_telemetry(self, *args, **kwargs) -> int:
        return -1

    def get_statistics(self) -> dict:
        return {
            "total_records": 0,
            "successful_fixes": 0,
            "success_rate": 0,
            "top_error_types": [],
            "mode": self.mode,
        }

    def export_training_data(self, output_path: Path) -> int:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("", encoding="utf-8")
        return 0


class LocalMemory:
    """Supabase-based memory system"""
    
    def __init__(self, db_path: Optional[Path] = None):
        if create_client is None:
            raise ValueError("Supabase package is not installed; using local-only mode")
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise ValueError("SUPABASE_URL or SUPABASE_KEY missing; using local-only mode")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            self.client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    def save_error(
        self,
        error_type: str,
        error_message: str,
        cause: str,
        fix: str,
        language: str = "python",
        context: str = None,
        success: bool = False,
        source: str = "rule"
    ) -> int:
        """Save error-fix pair to memory"""
        # We will use ghostfix_training_data schema which we know exists
        table_name = "ghostfix_training_data"
        
        fp = fingerprint(error_message, cause, fix, context or "")
        
        # Check if similar error exists
        res = self.client.table(table_name).select("id, success").eq("fingerprint", fp).execute()
        
        if res.data:
            existing = res.data[0]
            if success and not existing.get('success'):
                # update success
                self.client.table(table_name).update({"success": True}).eq("id", existing["id"]).execute()
            return existing["id"]
        
        # Insert new record
        insert_data = {
            "error": error_message[:500] if error_message else "",
            "error_type": error_type,
            "message": error_message[:500] if error_message else "",
            "cause": cause,
            "fix": fix,
            "source": source,
            "language": language,
            "context": context or "",
            "success": bool(success),
            "fingerprint": fp
        }
        res = self.client.table(table_name).insert(insert_data).execute()
        if res.data:
            return res.data[0]["id"]
        return -1
    
    def search_memory(
        self, 
        error_type: str, 
        error_message: str = None,
        min_success_rate: float = 0.0
    ) -> Optional[dict]:
        """Search memory for similar error"""
        table_name = "ghostfix_training_data"
        query = self.client.table(table_name).select("*").eq("error_type", error_type)
        
        if error_message:
            search_term = f"%{error_message[:100]}%"
            query = query.ilike("message", search_term)
            
        res = query.order("success", desc=True).limit(1).execute()
        
        if res.data:
            result = res.data[0]
            # Convert schema back to what the app expects
            app_result = {
                "error_type": result.get("error_type"),
                "error_message": result.get("message") or result.get("error"),
                "cause": result.get("cause"),
                "fix": result.get("fix"),
                "success": 1 if result.get("success") else 0
            }
            if app_result['success'] >= min_success_rate:
                return app_result
        
        return None
    
    def get_top_errors(self, limit: int = 10) -> list:
        """Get most common errors"""
        table_name = "ghostfix_training_data"
        res = self.client.table(table_name).select("error_type, message, cause, fix, success").limit(limit).execute()
        
        formatted = []
        for row in (res.data or []):
            formatted.append({
                "error_type": row.get("error_type"),
                "error_message": row.get("message"),
                "cause": row.get("cause"),
                "fix": row.get("fix"),
                "use_count": 1,
                "success": 1 if row.get("success") else 0
            })
        return formatted
    
    def save_telemetry(
        self,
        error_raw: str,
        error_type: str,
        suggested_fix: str,
        applied_fix: str = None,
        success: bool = None,
        feedback: str = None
    ) -> int:
        """Save telemetry for learning"""
        # Since we don't know if telemetry table exists, we will map it to ghostfix_training_data for now
        # as a generic log, or skip if it causes issues. Let's try to insert to telemetry, if fails, fallback.
        now = datetime.now().isoformat()
        
        insert_data = {
            "error_raw": error_raw,
            "error_type": error_type,
            "suggested_fix": suggested_fix,
            "applied_fix": applied_fix,
            "success": 1 if success else 0 if success is not None else None,
            "feedback": feedback,
            "created_at": now
        }
        try:
            res = self.client.table("telemetry").insert(insert_data).execute()
            if res.data:
                return res.data[0]["id"]
        except Exception:
            pass # Ignore if telemetry table doesn't exist
        return -1
    
    def get_statistics(self) -> dict:
        """Get memory statistics"""
        table_name = "ghostfix_training_data"
        res_total = self.client.table(table_name).select("id", count="exact").execute()
        total = res_total.count or 0
        
        res_success = self.client.table(table_name).select("id", count="exact").eq("success", True).execute()
        success_count = res_success.count or 0
        
        res_types = self.client.table(table_name).select("error_type").execute()
        type_counts = Counter([row["error_type"] for row in (res_types.data or [])])
        top_types = [{"type": k, "count": v} for k, v in type_counts.most_common(5)]
        
        return {
            "total_records": total,
            "successful_fixes": success_count,
            "success_rate": round(success_count / total * 100, 1) if total > 0 else 0,
            "top_error_types": top_types
        }
    
    def export_training_data(self, output_path: Path) -> int:
        """Export memory as training data"""
        table_name = "ghostfix_training_data"
        res = self.client.table(table_name).select("*").eq("success", True).execute()
        records = res.data or []
        
        export_records = []
        for row in records:
            export_records.append({
                "error": row.get("message") or row.get("error"),
                "language": row.get("language", "python"),
                "context": row.get("context") or "",
                "cause": row.get("cause"),
                "fix": row.get("fix"),
                "success": bool(row.get("success", False))
            })
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            for record in export_records:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
        
        return len(export_records)


# Global instance
_memory: Optional[LocalMemory | LocalOnlyMemory] = None

def get_memory() -> LocalMemory | LocalOnlyMemory:
    """Get global memory instance"""
    global _memory
    if _memory is None:
        try:
            _memory = LocalMemory()
        except Exception:
            _memory = LocalOnlyMemory()
    return _memory


def is_local_only_memory() -> bool:
    return isinstance(get_memory(), LocalOnlyMemory)

# Convenience functions
def save_memory(error_type: str, error_message: str, cause: str, fix: str, **kwargs):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            return get_memory().save_error(error_type, error_message, cause, fix, **kwargs)
    except Exception:
        return -1

def search_memory(error_type: str, error_message: str = None):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            return get_memory().search_memory(error_type, error_message)
    except Exception:
        return None

def save_telemetry(error_raw: str, error_type: str, suggested_fix: str, **kwargs):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            return get_memory().save_telemetry(error_raw, error_type, suggested_fix, **kwargs)
    except Exception:
        return -1
