from datetime import datetime

from fastapi import APIRouter

from app.agent import run_agent
from app.config import settings
from app.data import CRM_DATA
from app.schemas import ChatRequest

router = APIRouter()


@router.post("/api/chat")
async def chat(req: ChatRequest):
    messages = [{"role": m.role, "content": m.content} for m in req.messages]
    return run_agent(messages, session_id=req.session_id)


@router.get("/api/customers")
async def list_customers():
    return {
        "customers": [
            {
                "id": customer["id"],
                "name": customer["name"],
                "email": customer["email"],
                "tier": customer["tier"],
                "total_orders": customer["total_orders"],
                "refund_count": len(customer.get("refund_history", [])),
            }
            for customer in CRM_DATA["customers"]
        ]
    }


@router.get("/api/health")
async def health():
    return {
        "status": "ok",
        "provider": "gemini",
        "model": settings.GEMINI_MODEL,
        "fallback_model": settings.GEMINI_FALLBACK_MODEL,
        "api_key_configured": settings.is_api_key_configured,
        "timestamp": datetime.now().isoformat(),
    }
