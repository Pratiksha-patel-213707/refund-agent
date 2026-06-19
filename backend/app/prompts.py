import json
from typing import Any

from app.data import REFUND_POLICY


def build_understanding_prompt(messages: list[dict[str, str]], context: dict[str, Any]) -> str:
    latest_user_message = next(
        (msg.get("content", "") for msg in reversed(messages) if msg.get("role") == "user"),
        "",
    )
    conversation = "\n".join(
        f"{msg.get('role', 'user')}: {msg.get('content', '')}" for msg in messages
    )
    return f"""
You are the language-understanding step for a ShopEase refund-processing agent.

The latest user message is the authority for the current turn. Classify only the latest message, using memory only when the latest message is an explicit refund follow-up such as "is it refundable?", "am I eligible?", or "what about that order?".

Do not carry old order IDs, products, reasons, or emails into a standalone greeting, thanks, unrelated request, or a new order request. If the latest message includes a new order ID, email, product, or refund reason, prefer the latest value over memory.

Refund-domain requests include refund, return, exchange, replacement, refund eligibility, damaged/defective item, wrong item, not-as-described item, never-arrived item, and changed-mind return conversations.

Small talk such as "hi", "hello", "hey", "thanks", or "ok" is not a refund request. For small talk, return intent "small_talk", is_refund_related false, all extracted fields null, and a friendly assistant_response inviting the user to share an order ID and refund issue when ready.

Out-of-scope requests include weather, general knowledge, shipping tracking, account support unrelated to refunds, and non-refund support. For out-of-scope messages, return is_refund_related false and a concise assistant_response explaining that you only help with refund, return, exchange, and refund eligibility requests.

If the message is refund-related but lacks required information, include missing_fields and provide a concise assistant_response asking only for the missing details. Required before CRM/policy work: order_id and refund_reason. Email is optional unless needed to verify customer-order ownership.

Return JSON only:
{{
  "is_refund_related": true or false,
  "intent": "small_talk | out_of_scope | refund_request | return_request | exchange_request | refund_eligibility_check | other concise label",
  "customer_email": string or null,
  "order_id": string or null,
  "refund_reason": string or null,
  "reported_product": string or null,
  "missing_fields": ["order_id", "refund_reason"],
  "assistant_response": "short customer-facing response when no tools should run or when information is missing, otherwise null",
  "notes": "short explanation of your understanding"
}}

Current memory:
{json.dumps({
    "customer_email": context.get("customer_email"),
    "order_id": context.get("order_id"),
    "refund_reason": context.get("refund_reason"),
    "reported_product": context.get("reported_product"),
    "decision_status": context.get("decision_status"),
}, indent=2)}

Latest user message:
{latest_user_message}

Conversation:
{conversation}
"""


def build_product_verification_prompt(reported_product: str, crm_product: str, claim: str) -> str:
    return f"""
You are verifying whether a customer's product claim matches the CRM order product.

Use semantic understanding. If the products are clearly different, return false. If the user's product is vague but plausibly refers to the CRM product, return true. If there is not enough information, return null.

Return JSON only:
{{
  "matches": true or false or null,
  "explanation": "short explanation"
}}

Customer mentioned product:
{reported_product}

CRM order product:
{crm_product}

Customer claim/reason:
{claim}
"""


def build_policy_evaluation_prompt(
    evaluation_date: str,
    order: dict[str, Any],
    customer_risk_facts: dict[str, Any],
    reason: str,
) -> str:
    return f"""
You are a strict e-commerce refund policy evaluator.

Use only the CRM facts and refund policy below. Do not invent facts. Do not create goodwill exceptions. Do not approve a refund unless the policy supports it.

Return JSON only:
{{
  "eligible": true or false,
  "decision": "APPROVED" or "DENIED",
  "reason": "short machine-readable summary in your own words",
  "detail": "customer-facing explanation with exact facts used",
  "policy_rule": "exact policy section and rule that controls the decision",
  "refund_amount": number,
  "refund_timeline": "timeline from policy or N/A",
  "requires_evidence": true or false
}}

Evaluation date: {evaluation_date}

CRM order:
{json.dumps(order, indent=2)}

CRM customer risk facts:
{json.dumps(customer_risk_facts, indent=2)}

Customer refund claim:
{reason}

Refund policy:
{REFUND_POLICY}
"""


def build_response_prompt(
    response_type: str,
    context: dict[str, Any],
    latest_user_message: str,
    details: dict[str, Any] | None = None,
) -> str:
    return f"""
You are ARIA, a polite and concise ShopEase refund-support agent.

Write the customer-facing response for the current state. Do not expose internal tool names, reasoning logs, or implementation details. Use the supplied facts only. Do not mention a product mismatch if the CRM order lookup failed. If an order is not found, ask for the correct order ID or email.

Return JSON only:
{{
  "response": "customer-facing message"
}}

Response type:
{response_type}

Latest user message:
{latest_user_message}

Context:
{json.dumps(context, indent=2, default=str)}

Details:
{json.dumps(details or {}, indent=2, default=str)}
"""
