# Cybrom Course Advisor Chatbot — Production Engineering Plan

## 1. Executive Summary & Objective
Transform the Cybrom Course Advisor chatbot into a production-grade, highly reliable, high-converting, and secure conversational assistant. The assistant guides prospective students through lead qualification and course discovery in natural Roman-script Hinglish without hallucinating institutional facts.

---

## 2. Architecture & Phases

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (widget.html)                   │
│   - Stepper driven by backend `step` (1..4)                 │
│   - Render cold-start wake-up state & auto-retry            │
│   - Mobile-responsive, accessible keyboard navigation       │
└──────────────────────────────┬──────────────────────────────┘
                               │ HTTP / JSON
┌──────────────────────────────▼──────────────────────────────┐
│                   FastAPI Backend (app/main.py)              │
│   - Lifespan DB initialization (degraded mode if DB down)   │
│   - Rate limiting & CORS allowlist                          │
│   - Structured JSON logging & PII masking                   │
├──────────────────────────────┬──────────────────────────────┤
│    Conversation Engine       │       Data & Services        │
│  - app/prompts.py (central)  │  - app/db.py (pool + retry)  │
│  - app/browse_resolver.py    │  - app/session_store.py      │
│    (rules + Groq fallback)   │    (Redis/PG/SQLite/Mem)     │
│  - Interruptions & intents   │  - app/whatsapp_notify.py    │
│  - Lead capture timing switch│    (Pluggable Notifier)      │
│  - Injection defenses        │  - app/course_store.py       │
└──────────────────────────────┴──────────────────────────────┘
```

---

## 3. Detailed Execution Plan by Phase

### Phase 1: Reliability
1. **Database Resilience (`app/db.py`)**:
   - Remove module-level `init_db()`.
   - Implement `DatabaseManager` with connection pooling (`ThreadedConnectionPool`).
   - Implement retry with exponential backoff on query execution.
   - Fallback offline queue: If PostgreSQL is unreachable, buffer leads/interests into a local SQLite queue (`data/offline_queue.db`) and flush in the background when connection returns.
   - Move database startup to FastAPI lifespan handler with try/except and logging (`degraded` mode indicator).
2. **Persistent Session Store (`app/session_store.py`)**:
   - Create unified session store interface:
     - `RedisSessionStore` (if `REDIS_URL` configured)
     - `PostgresSessionStore` (uses `sessions` table in Postgres)
     - `SQLiteSessionStore` (local persistent file `data/sessions.db`)
     - `InMemorySessionStore` (last-resort fallback)
   - Store session history, lead data, stages, and 24-hour TTL expiry.
3. **Health Check Endpoint (`/health`)**:
   - Return `{ status: "ok" | "degraded", db: "connected" | "disconnected", session_store: "redis" | "postgres" | "sqlite" | "memory", queue_pending: count }`.
4. **Repo Hygiene & Packaging**:
   - Delete stray file `"-files  findstr requirements"`.
   - Convert `requirements.txt` to UTF-8, pin versions, add `httpx`, `pytest`, `redis`.
   - Create `.env.example` with clear documentation.
   - Create production `Dockerfile` and Gunicorn/Uvicorn entrypoint for Render.

### Phase 2: Smarter Conversation
1. **Catalog-Synchronized Subprogram Matching (`app/browse_resolver.py`)**:
   - Extract all subprograms dynamically from `courses_data.xlsx` on startup to keep them automatically in sync.
   - Comprehensive keyword dictionary for all 9+ subprograms (AI Engineering, MLOps, IoT, Gen AI, Cyber Security, DevOps & Cloud, Data Analytics, Python, Java, MERN).
   - LLM structured fallback: If keyword matching fails, query Groq with strict JSON output constrained to valid subprograms.
2. **Intent Classification & Routing Layer**:
   - Classify user messages into: `greeting`, `general_question`, `course_question`, `handoff_request`, `complaint`, `off_topic`, `abusive`, or `flow_answer`.
   - Politely handle off-topic and abusive inputs with brief neutral responses.
3. **Interruption & Resumption Handling**:
   - If user asks a question during lead capture or browsing (e.g. fees, duration, placement), answer from grounded catalog data. If not in catalog, honestly state so and offer a callback.
   - Politely append the pending prompt (e.g., "By the way, could you tell me your name?") to resume seamlessly without losing progress.
4. **Human Handoff & Counselor Callback**:
   - If user asks for human counselor or expresses frustration, capture callback request in DB, notify admissions via WhatsApp/Webhook, and acknowledge warmly.
5. **Robust Input Handling**:
   - Hinglish typo tolerance, number-to-words parsing, Indian phone normalization (`+91`, spaces, dashes -> 10 digits), whitespace & case trimming on emails.
6. **Prompt Hygiene & Injection Defense (`app/prompts.py`)**:
   - Centralize all prompts into `app/prompts.py`.
   - Add injection guardrails (prevent system prompt leakage, role overriding, or false promise/discount claims).
   - Input length truncation (cap at 1000 characters).

### Phase 3: Conversion and Frontend
1. **Response Schema & Stepper Synchronization**:
   - Add `step: int` (1..4) and `step_label: str` to `ChatResponse`.
   - Update `widget.html` to drive the visual stepper directly from `data.step`.
2. **Cold-Start Resilience in `widget.html`**:
   - Add "Waking up server..." banner with automatic retry if initial request takes > 8 seconds.
   - Display graceful error state if server is unavailable.
3. **Value-First Lead Capture Toggle (`LEAD_CAPTURE_TIMING`)**:
   - Support `LEAD_CAPTURE_TIMING = "early"` (current default: capture contact before browse) vs `"after_value"` (browse first, capture contact before final course syllabus/links).
4. **Course Cards & Mobile UX**:
   - Enhance cards in `widget.html` with clean duration badges, bulleted key modules, ARIA accessibility attributes, and full keyboard navigation.
5. **Pluggable Notifier Interface (`app/whatsapp_notify.py`)**:
   - Base `Notifier` class.
   - `CallMeBotNotifier` (WhatsApp).
   - `WebhookNotifier` (CRM webhook via `CRM_WEBHOOK_URL`).
   - Non-blocking async queue with background worker so notifications never delay user chat responses.

### Phase 4: Security, Compliance, Observability
1. **Rate Limiting & CORS**:
   - Per-IP and per-session rate limits on `/chat` and `/mark-interest`.
   - Environment-driven CORS allowlist.
2. **Admin Security & Features (`/admin/leads`)**:
   - Constant-time password / token authentication.
   - Enforce HTTPS warning/check in production.
   - Pagination (`limit`, `offset`) and `/admin/leads/export` CSV download.
   - `/admin/stats` endpoint: daily leads, conversion rate, stage drop-off, top programs.
3. **Data Compliance & PII Protection**:
   - Mask emails and phone numbers in all log outputs (`98****3210`, `j***@example.com`).
   - Add explicit consent prompt and store `consent=True` + timestamp.
   - Provide retention cleanup script (`scripts/cleanup_retention.py`).

### Phase 5: Testing & Delivery
1. **Pytest Suite (`tests/`)**:
   - Unit tests for validators, session store, resolvers, and intent handling.
   - Integration tests for `/chat` flow with mocked Groq client.
2. **Evaluation Set (`tests/eval_set.py`)**:
   - 60+ curated test cases spanning Hinglish variants, interruptions, edge cases, prompt injections, and typos. Automated scoring targeting $\ge 90\%$.
3. **Load Testing (`load_test_chat.py`)**:
   - 100 concurrent simulated students with p50, p90, p95 latency reporting.
4. **Documentation**:
   - Comprehensive `README.md` and detailed `CHANGELOG.md`.

---

## 4. Risks & Mitigations

| Risk | Impact | Mitigation Strategy |
| :--- | :--- | :--- |
| **PostgreSQL Unreachable** | Startup crash / lead drop | Remove module-level init. Run in degraded mode. Queue leads locally in SQLite fallback and flush in background. |
| **Groq API Latency / Rate Limits** | Chat lag or 500 errors | Rule-based keyword engine takes precedence. Groq timeout set to 8s with warm counselor fallback. |
| **Session Loss on Deploy / Multi-Worker** | Broken user conversations | Persistent sessions via SQLite / PostgreSQL / Redis with 24h TTL. |
| **Prompt Injection / Hallucinations** | Bot promises discounts or wrong info | Strict system guardrails in `prompts.py`, grounded answers only from `courses_data.xlsx`. |
| **Accidental Data Leak in Logs** | PII compliance violation | Regex-based PII mask filter applied to all logger formatters. |

---

## 5. Verification Checklist
- [ ] Server starts with PostgreSQL down and reports degraded mode in `/health`.
- [ ] Sessions persist across server process restarts.
- [ ] Subprogram typing matches correctly for all catalog tracks.
- [ ] Interrupted questions answered accurately, then return to flow.
- [ ] Frontend stepper synchronizes with backend `step` integer.
- [ ] 60+ evaluation suite passes with $\ge 90\%$ accuracy.
- [ ] All unit and integration tests pass.
