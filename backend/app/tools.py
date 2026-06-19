from datetime import datetime, timedelta
import re
from typing import Optional

from app.config import settings
from app.data import CUSTOMERS, EMAIL_INDEX, REFUND_POLICY
from app.llm import llm_json
from app.order_ids import canonical_order_id
from app.prompts import build_policy_evaluation_prompt


def _policy_now() -> datetime:
    try:
        return datetime.strptime(settings.POLICY_EVALUATION_DATE, "%Y-%m-%d")
    except ValueError:
        return datetime.now()


def _json_from_llm(prompt: str) -> dict:
    return llm_json(prompt)


def lookup_customer(identifier: str) -> dict:
    """Look up a customer by email or customer ID."""
    identifier = identifier.strip()
    cid = EMAIL_INDEX.get(identifier.lower()) or (identifier if identifier in CUSTOMERS else None)
    if not cid:
        return {"error": f"No customer found for identifier: {identifier}"}

    customer = CUSTOMERS[cid]
    refund_count_12mo = len(
        [
            r
            for r in customer["refund_history"]
            if r["status"] == "approved"
            and datetime.strptime(r["date"], "%Y-%m-%d") > _policy_now() - timedelta(days=365)
        ]
    )
    recent_denied = any(
        r["status"] == "denied"
        and datetime.strptime(r["date"], "%Y-%m-%d") > _policy_now() - timedelta(days=180)
        for r in customer["refund_history"]
    )

    return {
        "customer_id": customer["id"],
        "name": customer["name"],
        "email": customer["email"],
        "tier": customer["tier"],
        "total_orders": customer["total_orders"],
        "account_created": customer["account_created"],
        "refund_count_12mo": refund_count_12mo,
        "recent_denied": recent_denied,
    }


def get_customer_orders(customer_id: str) -> list[dict]:
    customer = CUSTOMERS.get(customer_id)
    if not customer:
        return []
    return customer.get("orders", [])


def get_order_details(order_id: str) -> dict:
    """Get details of a specific order."""
    requested = (order_id or "").strip()
    canonical = canonical_order_id(requested)
    matches: list[tuple[dict, dict]] = []
    for customer in CUSTOMERS.values():
        for order in customer.get("orders", []):
            exact = order["order_id"].upper() == requested.upper()
            normalized = canonical and order["order_id"].upper() == canonical.upper()
            suffix = re.sub(r"\D", "", requested)
            unique_suffix = len(suffix) == 4 and order["order_id"].endswith(f"-{suffix}")
            if exact or normalized or unique_suffix:
                matches.append((customer, order))

    if len(matches) > 1:
        return {"error": f"Order number {order_id} is ambiguous. Please provide the full order ID."}
    if not matches:
        return {"error": f"Order {order_id} not found."}

    customer, order = matches[0]
    delivery = datetime.strptime(order["delivery_date"], "%Y-%m-%d")
    days_since = (_policy_now() - delivery).days
    return {
        **order,
        "customer_id": customer["id"],
        "customer_name": customer["name"],
        "customer_tier": customer["tier"],
        "days_since_delivery": days_since,
    }


def check_refund_eligibility(
    order_id: str,
    reason: str,
    customer_id: Optional[str] = None,
) -> dict:
    """
    LLM policy evaluator. It uses the CRM facts and the strict policy document
    to approve or deny the refund. Reason can be the user's natural-language
    claim; the policy document and CRM facts are supplied to the model.
    """
    order = get_order_details(order_id)
    if "error" in order:
        return order

    cid = customer_id or order["customer_id"]
    customer = CUSTOMERS.get(cid)
    if not customer:
        return {"error": "Customer not found."}

    refund_count_12mo = len(
        [
            r
            for r in customer.get("refund_history", [])
            if r["status"] == "approved"
            and datetime.strptime(r["date"], "%Y-%m-%d") > _policy_now() - timedelta(days=365)
        ]
    )
    recent_denied = any(
        r["status"] == "denied"
        and datetime.strptime(r["date"], "%Y-%m-%d") > _policy_now() - timedelta(days=180)
        for r in customer.get("refund_history", [])
    )

    customer_risk_facts = {
        "customer_id": customer["id"],
        "tier": customer["tier"],
        "refund_count_12mo": refund_count_12mo,
        "recent_denied": recent_denied,
        "refund_history": customer.get("refund_history", []),
    }

    result = _json_from_llm(
        build_policy_evaluation_prompt(
            evaluation_date=_policy_now().date().isoformat(),
            order=order,
            customer_risk_facts=customer_risk_facts,
            reason=reason,
        )
    )

    result.setdefault("eligible", False)
    result.setdefault("decision", "APPROVED" if result.get("eligible") else "DENIED")
    result.setdefault("reason", "POLICY_EVALUATED")
    result.setdefault("detail", "The refund was evaluated against the policy document.")
    result.setdefault("policy_rule", "N/A")
    result.setdefault("refund_amount", order["amount"] if result.get("eligible") else 0)
    result.setdefault("refund_timeline", "N/A")
    result.setdefault("requires_evidence", False)
    return result


def get_refund_policy(section: Optional[str] = None) -> dict:
    """Return the refund policy text, optionally filtered by section."""
    if section:
        lines = REFUND_POLICY.split("\n")
        relevant = [line for line in lines if section.lower() in line.lower()]
        return {"section": section, "content": "\n".join(relevant) or "Section not found."}
    return {"policy": REFUND_POLICY}


def process_refund(order_id: str, reason: str, customer_id: str, notes: str = "") -> dict:
    """Finalize and log a refund decision."""
    eligibility = check_refund_eligibility(order_id, reason, customer_id)
    decision = "APPROVED" if eligibility.get("eligible") else "DENIED"
    return {
        "refund_id": f"REF-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "order_id": order_id,
        "customer_id": customer_id,
        "decision": decision,
        "reason": eligibility.get("reason"),
        "detail": eligibility.get("detail"),
        "refund_amount": eligibility.get("refund_amount", 0) if decision == "APPROVED" else 0,
        "timeline": eligibility.get("refund_timeline", "N/A"),
        "requires_evidence": eligibility.get("requires_evidence", False),
        "notes": notes,
        "processed_at": datetime.now().isoformat(),
        "policy_rule_applied": eligibility.get("policy_rule", "N/A"),
    }


TOOLS = {
    "lookup_customer": lookup_customer,
    "get_order_details": get_order_details,
    "get_refund_policy": get_refund_policy,
    "check_refund_eligibility": check_refund_eligibility,
    "process_refund": process_refund,
}
