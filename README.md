# ShopEase Refund Processing Agent

ARIA is a purpose-built refund-processing agent for e-commerce support. It is not a general customer support chatbot. Its primary job is to approve or deny refund, return, exchange, and refund eligibility requests by validating customer and order data against the refund policy.

## Root Cause Analysis

The previous implementation had several assignment gaps:

- The workflow was collapsed into a broad validation/decision path, so it did not clearly enforce Intent Detection -> Information Collection -> CRM Lookup -> Verification -> Policy Validation -> Decision.
- Some responses could be generated without completing all required validation, which made assumption-based reasoning possible.
- Intent, reason, and product interpretation were previously handled with local keyword lists. The current implementation delegates that language understanding to the LLM.
- Conversation memory existed, but incoming frontend history and backend session state could duplicate or lose follow-up intent.
- Reasoning logs focused mostly on tool calls and final responses, leaving intent, validation, policy rule, and final decision less visible.
- The policy engine used the machine clock. The bundled 2024 CRM data became permanently outside the refund window when run in later years, so the evaluation date is now configurable.

## Architecture Review

Backend:

- `backend/app/agent.py` owns the LangGraph workflow and session memory.
- `backend/app/tools.py` owns CRM and policy tools. CRM lookup is factual; policy eligibility is evaluated by the LLM against the strict policy document and CRM facts.
- `backend/app/api.py` exposes `/api/chat`, `/api/customers`, and `/api/health`.
- `data/crm_database.json` is the mock CRM.
- `data/refund_policy.txt` is the policy source.

Frontend:

- `frontend/src/App.js` provides the chat UI and admin reasoning log.
- The admin log now displays intent, information collection, tool calls, tool outputs, validation results, policy rule, and final decision.

## Updated LangGraph Workflow

```text
Intent Detection
  -> Information Collection
  -> CRM Lookup
  -> Verification
  -> Policy Validation
  -> Decision
  -> Respond
```

Conditional exits:

- Out-of-scope intent -> exact out-of-scope response.
- Missing order/email or refund reason -> ask for only the missing details.
- CRM/customer/order/product mismatch -> ask for clarification before policy validation.
- Verified request -> call policy tool, then produce APPROVED or DENIED.

## Supported Intents

- Refund Request
- Return Request
- Exchange Request
- Refund Eligibility Check

Out-of-scope response:

```text
I'm a refund support assistant and can help with refund, return, exchange, and refund eligibility requests. Please provide your order details and refund-related issue.
```

## File-by-File Fixes

### `backend/app/agent.py`

- Replaced broad agent logic with explicit LangGraph nodes:
  - `intent_detection`
  - `information_collection`
  - `crm_lookup`
  - `verification`
  - `policy_validation`
  - `decision`
  - `respond`
- Added durable session context for:
  - customer email
  - order ID
  - refund reason
  - reported product
  - CRM customer/order results
  - policy result
  - decision status
- Added follow-up handling so a user can say:
  - "My item arrived damaged."
  - "rohan.mehta@email.com ORD-2024-9102"
  - "So is it refundable?"
- Added strict out-of-scope handling through LLM request understanding.
- Added LLM-based product mismatch detection before policy validation.
- Ensured final decisions are based on CRM tool outputs plus the policy-evaluation tool, not unsupported chat responses.
- Added structured reasoning log events.

### `backend/app/tools.py`

- Added configurable policy evaluation date via settings.
- Reworked `check_refund_eligibility` so Gemini evaluates the natural-language customer claim against `refund_policy.txt` and the CRM order/customer facts.
- Policy decisions return `eligible`, `decision`, `policy_rule`, `detail`, refund amount, timeline, and evidence requirements where applicable.

### `backend/app/config.py`

- Added `POLICY_EVALUATION_DATE`, defaulting to `2024-06-18` for the bundled CRM dataset.
- You can override it with an environment variable.

### `frontend/src/App.js`

- Expanded the admin reasoning log renderer to show:
  - Intent Detection
  - Information Collection
  - Tool Calls
  - Tool Outputs
  - Validation Results
  - Final Decision
  - Agent Response

## Reasoning Log Schema

Each chat response includes a `reasoning_log` array with events such as:

- `intent`
- `information_collection`
- `tool_call`
- `tool_result`
- `validation_results`
- `final_decision`
- `agent_response`

This makes it clear which tools executed, what they returned, which validations passed, which policy rule triggered, and why the final decision was APPROVED or DENIED.

## Example Conversations

### 1. Missing Information

User:

```text
My item arrived damaged.
```

Agent:

```text
Please provide the order ID or the email used for the purchase so I can verify the refund request.
```

### 2. Follow-Up Understanding

User:

```text
My item arrived damaged.
```

Agent:

```text
Please provide the order ID or the email used for the purchase so I can verify the refund request.
```

User:

```text
rohan.mehta@email.com ORD-2024-9102
```

Agent:

```text
DENIED: Order ORD-2024-9102 for Nike Air Max 270 is not eligible for a refund. Policy rule used: Section 1 - Eligibility Window. Delivery was 36 days ago. Window for footwear is 7 days (Section 1).
```

User:

```text
So is it refundable?
```

Agent uses stored state and returns the same decision directly.

### 3. Product Mismatch

User:

```text
My damaged headphones are on order ORD-2024-9102 rohan.mehta@email.com
```

Agent:

```text
The product you mentioned does not match the CRM order. You mentioned headphones, but order ORD-2024-9102 is for Nike Air Max 270. Please confirm the correct product or order ID.
```

### 4. Approved Refund

User:

```text
I need a refund for ORD-2024-5544. My smartwatch arrived defective.
```

Agent:

```text
APPROVED: Order ORD-2024-5544 for Fossil Gen 6 Smartwatch is eligible for a refund. Policy rule used: Section 2 - Valid Refund Reasons. Refund approved for 'defective'. Gold customer - standard 3-5 day processing. Refund amount: 18995.0. Timeline: 5-7 business days. Evidence is required within 24 hours.
```

### 5. Out-of-Scope

User:

```text
What is the weather today?
```

Agent:

```text
I'm a refund support assistant and can help with refund, return, exchange, and refund eligibility requests. Please provide your order details and refund-related issue.
```

## Running Locally

Backend:

```bash
cd backend
uvicorn main:app --reload --port 8000
```

Create `backend/.env` from `backend/.env.example` and set:

```bash
GEMINI_API_KEY="YOUR_GEMINI_API_KEY_HERE"
GEMINI_MODEL="gemini-1.5-flash"
```

Frontend:

```bash
cd frontend
npm start
```
