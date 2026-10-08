# Changelog

All notable changes to the Cybrom Course Advisor Chatbot are documented below.

## [2.0.0] - 2026-10-08

### Phase 1: Reliability & Infrastructure
- **Removed Module-Level DB Execution**: Eliminated `init_db()` call from module root in `app/db.py`. Database setup is now managed safely within FastAPI lifespan context.
- **Connection Pooling & Reconnect Cooldown**: Implemented `psycopg2.pool.ThreadedConnectionPool` with 30s reconnect cooldown to prevent blocking requests when PostgreSQL is unreachable.
- **Resilient Offline SQLite Queue**: Added `data/offline_queue.db`. If PostgreSQL connection drops, lead submissions and course interests buffer locally without throwing 500 errors and flush automatically in the background.
- **Multi-Tier Persistent Session Store**: Replaced in-memory dictionary with `BaseSessionStore` supporting Redis, PostgreSQL `sessions` table, and SQLite persistent store (`data/sessions.db`) with 24-hour TTL. Sessions survive restarts and multi-worker deployments.
- **Degraded Health Probe**: Updated `/health` endpoint to return `{ status, database, session_store, offline_queue_pending }` safely without crashing.
- **Repo Hygiene & Docker**: Deleted stray shell redirect file, converted `requirements.txt` to UTF-8 with pinned dependencies (including `httpx`, `pytest`, `redis`, `gunicorn`), added `.env.example`, updated `.gitignore`, and authored production `Dockerfile`.

### Phase 2: Conversational Intelligence & Guardrails
- **Comprehensive Subprogram Matching**: Expanded keyword mappings across all 9+ catalog tracks (AI Engineering, MLOps, IoT, Gen AI, Ethical Hacking, DevOps/Cloud, Data Analytics, Python, Java, MERN) with automatic keyword synchronization from `courses_data.xlsx`.
- **LLM Structured JSON Fallback**: Added Groq fallback schema enforcing exact subprogram matches when keyword rules are inconclusive.
- **Interruption Handling**: Enabled mid-conversation questions regarding course fees, durations, and placements without losing conversational state. The bot provides grounded answers and smoothly resumes the pending step.
- **Intent Classification Layer**: Built classification routing for greetings, technical Q&A, course inquiries, counselor callbacks, complaints, off-topic questions, and abusive inputs.
- **Human Counselor Escalation**: Added automated handoff triggers saving callback requests to the database and alerting admissions staff via WhatsApp/webhook.
- **Robust Entity Normalization**: Implemented `clean_phone` (+91 stripping, space/dash removal, word digit conversion), `clean_name` (conversational prefix and emoji removal), and `clean_email`.
- **Prompt Hygiene**: Centralized all prompt templates in `app/prompts.py` with anti-injection and anti-hallucination guardrails, enforcing Roman-script Hinglish counselor persona.

### Phase 3: Conversion & Frontend Experience
- **Step Synchronization**: Added `step: int` (1..4) and `step_label` to every `ChatResponse`. The progress stepper in `widget.html` now binds directly to backend state, resolving previous label mismatches.
- **Render Cold-Start Resilience**: Added a dynamic warning banner in `widget.html` with an animated spinner and retry mechanism when backend cold-starts exceed 4 seconds.
- **Value-First Timing Switch**: Added `LEAD_CAPTURE_TIMING = "early" | "after_value"` configuration setting.
- **Course Card Redesign**: Enhanced cards with duration badges, top syllabus modules, and prominent primary CTA buttons. Added full ARIA accessibility and mobile viewport responsiveness.
- **Pluggable Notifier Interface**: Created `BaseNotifier` interface with `CallMeBotNotifier`, `WebhookNotifier`, and background `NotificationDispatcher` with retry logic.

### Phase 4: Security, Compliance & Observability
- **Sliding-Window Rate Limiter**: Added IP and session-level sliding-window rate limiting on `/chat` and `/mark-interest`.
- **PII Masking**: Implemented automated phone and email masking in all application logs (`98****3210`, `r****@domain.com`).
- **Structured JSON Logging**: Created `JSONFormatter` producing machine-readable JSON log events.
- **Admin Endpoints**: Strengthened `/admin/leads` with constant-time password verification and pagination. Added `/admin/leads/export` for direct CSV downloading and `/admin/stats` for real-time conversion metrics.
- **Data Retention & DPDP Script**: Authored `scripts/cleanup_retention.py` to prune expired records and fulfill student deletion requests.

### Phase 5: Verification & Delivery
- **Automated Test Suite**: Created modular pytest suites for reliability, conversational intelligence, frontend conversion, security, and full end-to-end conversation simulation.
- **Evaluation Benchmark**: Created 65-case benchmark (`tests/eval_set.py`) covering interruptions, prompt injections, entity parsing, and edge cases (achieved 100% pass rate).
- **Load Testing**: Updated `load_test_chat.py` to simulate 100 concurrent students and report p50, p90, and p95 latency distributions.
