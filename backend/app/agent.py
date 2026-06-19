from datetime import datetime
from typing import Any, Literal, TypedDict

from app.llm import LLMError, llm_json
from app.order_ids import normalize_order_mentions
from app.prompts import (
    build_product_verification_prompt,
    build_response_prompt,
    build_understanding_prompt,
)
from app.tools import TOOLS
from langgraph.graph import END, StateGraph

SESSION_STORE: dict[str, dict[str, Any]] = {}


class AgentState(TypedDict, total=False):
    messages: list[dict[str, str]]
    session_id: str
    context: dict[str, Any]
    reasoning_log: list[dict[str, Any]]
    response: str
    status: str


def _timestamp() -> str:
    return datetime.now().isoformat()


def _log(reasoning_log: list[dict[str, Any]], event_type: str, **payload: Any) -> None:
    reasoning_log.append({"type": event_type, "timestamp": _timestamp(), **payload})


def _session(session_id: str) -> dict[str, Any]:
    return SESSION_STORE.setdefault(
        session_id,
        {
            "messages": [],
            "context": {
                "customer_email": None,
                "order_id": None,
                "refund_reason": None,
                "reported_product": None,
                "crm_customer": None,
                "crm_order": None,
                "policy_result": None,
                "decision_status": None,
                "intent": None,
                "validation_results": {},
                "understanding": None,
            },
        },
    )


def _llm_json(prompt: str) -> dict:
    return llm_json(prompt)


def _llm_error_message(action: str, exc: Exception) -> str:
    return (
        f"I could not {action} because the LLM request failed. "
        "Please check the Gemini API key, quota, and model configuration, then try again."
    )


def _merge_messages(session_id: str, incoming: list[dict[str, str]]) -> list[dict[str, str]]:
    session = _session(session_id)
    stored = session.get("messages", [])
    incoming = [
        {
            **message,
            "content": normalize_order_mentions(message.get("content", ""))
            if message.get("role") == "user"
            else message.get("content", ""),
        }
        for message in incoming
    ]
    if len(incoming) >= len(stored):
        merged = incoming
    else:
        merged = [*stored, *incoming]
    session["messages"] = merged
    return merged


def _latest_user_text(messages: list[dict[str, str]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return msg.get("content", "")
    return ""


def _understand_request(messages: list[dict[str, str]], context: dict[str, Any]) -> dict:
    return _llm_json(build_understanding_prompt(messages, context))


def _verify_product_with_llm(reported_product: str, crm_product: str, claim: str) -> dict:
    return _llm_json(build_product_verification_prompt(reported_product, crm_product, claim))


def _generate_response(
    response_type: str,
    state: AgentState,
    details: dict[str, Any] | None = None,
) -> str:
    result = _llm_json(
        build_response_prompt(
            response_type=response_type,
            context=state.get("context", {}),
            latest_user_message=_latest_user_text(state.get("messages", [])),
            details=details,
        )
    )
    response = result.get("response")
    if not response:
        raise LLMError("Response generation did not return a response field.")
    return response


def _call_tool(reasoning_log: list[dict[str, Any]], tool_name: str, **kwargs: Any) -> dict:
    _log(reasoning_log, "tool_call", tool=tool_name, args=kwargs)
    result = TOOLS[tool_name](**kwargs)
    _log(reasoning_log, "tool_result", tool=tool_name, result=result)
    return result


def _intent_node(state: AgentState) -> AgentState:
    context = state["context"]
    try:
        understanding = _understand_request(state.get("messages", []), context)
    except Exception as exc:
        state["status"] = "llm_error"
        _log(state["reasoning_log"], "llm_error", stage="intent_detection", error=str(exc))
        state["response"] = _llm_error_message("understand the request", exc)
        return state

    previous_order_id = context.get("order_id")
    next_order_id = understanding.get("order_id")
    order_changed = bool(previous_order_id and next_order_id and previous_order_id != next_order_id)
    if order_changed:
        context.update(
            {
                "customer_email": None,
                "crm_customer": None,
                "crm_order": None,
                "policy_result": None,
                "decision_status": None,
                "validation_results": {},
            }
        )
        if not understanding.get("customer_email"):
            understanding["customer_email"] = None

    context["understanding"] = understanding
    context["intent"] = understanding.get("intent")

    for source_key, context_key in [
        ("customer_email", "customer_email"),
        ("order_id", "order_id"),
        ("refund_reason", "refund_reason"),
        ("reported_product", "reported_product"),
    ]:
        value = understanding.get(source_key)
        if value:
            context[context_key] = value

    _log(
        state["reasoning_log"],
        "intent",
        intent=context.get("intent"),
        is_refund_related=understanding.get("is_refund_related"),
        understanding=understanding,
    )

    if not understanding.get("is_refund_related"):
        state["status"] = "out_of_scope"
        state["response"] = understanding.get("assistant_response") or _generate_response("out_of_scope", state)
    else:
        state["status"] = "intent_detected"
    return state


def _information_node(state: AgentState) -> AgentState:
    if state.get("status") in {"out_of_scope", "llm_error"}:
        return state

    context = state["context"]
    missing = []
    if not context.get("order_id"):
        missing.append("order_id")
    if not context.get("refund_reason"):
        missing.append("refund_reason")

    _log(
        state["reasoning_log"],
        "information_collection",
        collected={
            "customer_email": context.get("customer_email"),
            "order_id": context.get("order_id"),
            "refund_reason": context.get("refund_reason"),
            "reported_product": context.get("reported_product"),
        },
        missing=missing,
    )

    if missing:
        state["status"] = "needs_information"
        state["response"] = (context.get("understanding") or {}).get("assistant_response") or _generate_response(
            "missing_information",
            state,
            {"missing_fields": missing},
        )
    else:
        state["status"] = "ready_for_crm"
    return state


def _crm_lookup_node(state: AgentState) -> AgentState:
    if state.get("status") != "ready_for_crm":
        return state

    context = state["context"]
    reasoning_log = state["reasoning_log"]

    if context.get("customer_email"):
        context["crm_customer"] = _call_tool(
            reasoning_log,
            "lookup_customer",
            identifier=context["customer_email"],
        )
    context["crm_order"] = _call_tool(
        reasoning_log,
        "get_order_details",
        order_id=context["order_id"],
    )
    if "error" not in context["crm_order"]:
        # Store the authoritative full ID returned by CRM so downstream policy
        # tools never depend on the abbreviated or spoken input form.
        context["order_id"] = context["crm_order"]["order_id"]

    state["status"] = "crm_complete"
    return state


def _verification_node(state: AgentState) -> AgentState:
    if state.get("status") != "crm_complete":
        return state

    context = state["context"]
    customer = context.get("crm_customer")
    order = context.get("crm_order")
    validation = {
        "customer_exists": None,
        "order_exists": None,
        "customer_order_match": None,
        "product_match": None,
        "product_match_explanation": None,
    }

    if customer is not None:
        validation["customer_exists"] = "error" not in customer
    if order is not None:
        validation["order_exists"] = "error" not in order
        if validation["order_exists"] and customer is None:
            validation["customer_exists"] = True

    if customer and order and "error" not in customer and "error" not in order:
        validation["customer_order_match"] = customer.get("customer_id") == order.get("customer_id")

    if context.get("reported_product") and order and "error" not in order:
        try:
            product_check = _verify_product_with_llm(
                context["reported_product"],
                order.get("product", ""),
                context.get("refund_reason", ""),
            )
            _log(state["reasoning_log"], "llm_product_verification", result=product_check)
        except Exception as exc:
            state["status"] = "llm_error"
            _log(state["reasoning_log"], "llm_error", stage="product_verification", error=str(exc))
            state["response"] = _llm_error_message("verify the product", exc)
            return state
        validation["product_match"] = product_check.get("matches")
        validation["product_match_explanation"] = product_check.get("explanation")

    context["validation_results"] = validation
    _log(state["reasoning_log"], "validation_results", results=validation)

    if customer is not None and validation["customer_exists"] is False:
        state["status"] = "verification_failed"
        state["response"] = _generate_response("customer_not_found", state, {"validation": validation})
    elif validation["order_exists"] is False:
        state["status"] = "verification_failed"
        state["response"] = _generate_response("order_not_found", state, {"validation": validation})
    elif validation["customer_order_match"] is False:
        state["status"] = "verification_failed"
        state["response"] = _generate_response("customer_order_mismatch", state, {"validation": validation})
    elif validation["product_match"] is False:
        state["status"] = "verification_failed"
        state["response"] = _generate_response("product_mismatch", state, {"validation": validation})
    else:
        state["status"] = "verified"
    return state


def _policy_node(state: AgentState) -> AgentState:
    if state.get("status") != "verified":
        return state

    context = state["context"]
    order = context.get("crm_order") or {}
    customer = context.get("crm_customer") or {}
    customer_id = customer.get("customer_id") or order.get("customer_id")

    try:
        context["policy_result"] = _call_tool(
            state["reasoning_log"],
            "check_refund_eligibility",
            order_id=context["order_id"],
            reason=context["refund_reason"],
            customer_id=customer_id,
        )
    except Exception as exc:
        state["status"] = "llm_error"
        _log(state["reasoning_log"], "llm_error", stage="policy_validation", error=str(exc))
        state["response"] = _llm_error_message("evaluate the refund policy", exc)
        return state

    state["status"] = "policy_complete"
    return state


def _decision_node(state: AgentState) -> AgentState:
    if state.get("status") != "policy_complete":
        return state

    context = state["context"]
    policy = context.get("policy_result") or {}
    order = context.get("crm_order") or {}
    decision = policy.get("decision") or ("APPROVED" if policy.get("eligible") else "DENIED")
    context["decision_status"] = decision

    _log(
        state["reasoning_log"],
        "final_decision",
        decision=decision,
        policy_rule_triggered=policy.get("policy_rule"),
        policy_result=policy,
    )

    state["response"] = _generate_response(
        "final_decision",
        state,
        {"decision": decision, "policy_result": policy, "order": order},
    )
    state["status"] = "final"
    return state


def _respond_node(state: AgentState) -> AgentState:
    session = _session(state.get("session_id", "default"))
    session["context"] = state.get("context", session["context"])
    response = state.get("response")
    if not response:
        raise LLMError("Agent reached respond node without a generated response.")
    state["response"] = response
    _log(state["reasoning_log"], "agent_response", response=response, status=state.get("status"))
    return state


def _next_after_info(state: AgentState) -> Literal["crm_lookup", "respond"]:
    return "crm_lookup" if state.get("status") == "ready_for_crm" else "respond"


def _next_after_verification(state: AgentState) -> Literal["policy_validation", "respond"]:
    return "policy_validation" if state.get("status") == "verified" else "respond"


def _build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("intent_detection", _intent_node)
    graph.add_node("information_collection", _information_node)
    graph.add_node("crm_lookup", _crm_lookup_node)
    graph.add_node("verification", _verification_node)
    graph.add_node("policy_validation", _policy_node)
    graph.add_node("decision", _decision_node)
    graph.add_node("respond", _respond_node)

    graph.set_entry_point("intent_detection")
    graph.add_edge("intent_detection", "information_collection")
    graph.add_conditional_edges(
        "information_collection",
        _next_after_info,
        {"crm_lookup": "crm_lookup", "respond": "respond"},
    )
    graph.add_edge("crm_lookup", "verification")
    graph.add_conditional_edges(
        "verification",
        _next_after_verification,
        {"policy_validation": "policy_validation", "respond": "respond"},
    )
    graph.add_edge("policy_validation", "decision")
    graph.add_edge("decision", "respond")
    graph.add_edge("respond", END)
    return graph.compile()


GRAPH = _build_graph()


def run_agent(messages: list[dict], session_id: str = "default") -> dict:
    merged_messages = _merge_messages(session_id, messages)
    state = GRAPH.invoke(
        {
            "messages": merged_messages,
            "session_id": session_id,
            "context": _session(session_id)["context"],
            "reasoning_log": [],
            "response": "",
            "status": "pending",
        }
    )

    response = state.get("response", "")
    session = _session(session_id)
    session["messages"] = [*merged_messages, {"role": "assistant", "content": response}]
    session["context"] = state.get("context", session["context"])

    return {
        "response": response,
        "reasoning_log": state.get("reasoning_log", []),
        "context": session["context"],
    }
