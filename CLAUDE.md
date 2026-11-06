# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI-driven personalized tutoring system. Teachers create learning sessions with students; AI agents evaluate teaching strategies, generate personalized study materials, and recommend resources based on student performance and preferences.

## Running the System

```bash
# Start all services
docker-compose up

# Rebuild after dependency changes
docker-compose build

# Access points
# Orchestrator: http://localhost:5000
# Adminer (DB browser): http://localhost:8080
```

## Running Tests

```bash
# From the agente_sessao service directory
cd agente_sessao
pytest tests/test_session_strategy.py
```

## Architecture

Five Flask microservices communicating via internal HTTP:

| Service | Port | Responsibility |
|---------|------|----------------|
| `orquestrador` | 5000 | Main gateway, UI (Jinja2), agent orchestration |
| `agente_sessao` | 5001 | Session lifecycle, performance tracking, ratings |
| `user` | 5002 | Student/teacher profiles, learning preferences |
| `strategies` | 5003 | Teaching strategies, personalization agents |
| `domain` | 5004 | Knowledge base (exercises, PDFs, videos, RAG) |

Service URLs are registered in `orquestrador/routes/services_routs.py`. These match Docker Compose service names (e.g., `http://user:5002`). Vercel production URLs are commented out in the same file.

## AI Agent Layer

All LLM calls use the `openai` Python SDK pointed at Groq's API (`base_url="https://api.groq.com/openai/v1"`, model `openai/gpt-oss-120b` with `extra_body={"reasoning_effort": "low"}`; it is a reasoning model, so keep `max_tokens` generous — reasoning tokens count toward it). Each service has its own `GROQ_API_KEY` in `.env`.

**Agent endpoints** (prefixed `/agent/` per service):
- `agente_sessao` → `/sessions/<id>/agent_summary` — session performance summary
- `user` → `/agent/summarize_logged_user`, `/agent/generate_student_feedback`
- `strategies` → `/agent/critique`, `/agent/recommend_youtube_video`, `/agent/generate_personalized_study_text`
- `domain` → `/get_content/<id>` — RAG PDF extraction (used as context by orchestrator)

**Orchestrator agent routes** (in `orquestrador/routes/orchestrator/`):
- `agente_control_routes.py` → aggregates difficulty + preferences, calls learning support
- `agente_strategies_routes.py` → fetches PDF context from domain, then calls strategy critique
- `agente_user_routes.py` → aggregates grades/chat/context, routes to tutoring agent

## Data Layer

Four PostgreSQL databases (one per worker service). `agente_sessao` uses raw SQL with `RealDictCursor`; `domain` uses SQLAlchemy ORM; `user` and `strategies` use both.

Schema files: `<service>/<service>-db.sql`. Migration helper: `agente_sessao/update_schema.py`.

## Key Patterns

- **Blueprint routing**: all routes registered as Flask Blueprints, split into CRUD routes and `/agent/` routes.
- **Personalization flow**: student answers → detect difficulty → call strategies agents with student preference + difficulty context → return YouTube URL or custom study text.
- **Session lifecycle**: create → enroll students/teachers → start → iterate tactics → submit answers → agent summary → personalized feedback.
- **No authentication** on inter-service calls; services are internal-only in Docker network.
