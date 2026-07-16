# NambikkAI Guardian

A secure multilingual document-intelligence platform for **Tamil, Tanglish, and English**. It is designed to answer from evidence, attach precise citations, verify claims, detect prompt-injection attempts, and abstain when the available evidence is insufficient.

## Product goal

Most document-chat applications optimize for fluent answers. NambikkAI Guardian optimizes for **trust**:

- every answer is grounded in authorized documents;
- every material claim links to supporting evidence;
- unsupported or contradictory claims are removed;
- suspicious document instructions are treated as untrusted data;
- low-confidence questions receive a refusal or clarification request.

## MVP scope

- User authentication, workspaces, and role-based access
- Secure PDF and image upload
- Parsing, OCR, language detection, normalization, and chunking
- Tamil, Tanglish, and English query processing
- Hybrid lexical and vector retrieval with reranking
- Evidence-grounded answers with page and span citations
- Claim-level verification and calibrated abstention
- Prompt-injection detection and quarantine
- Audit logs, evaluation datasets, monitoring, and deployment

## Starter architecture

```text
Browser / Next.js
       |
FastAPI API
       |
Authorization + workspace boundary
       |
LangGraph query workflow
  normalize -> retrieve -> rerank -> generate -> verify -> abstain/cite
       |
PostgreSQL + pgvector | Redis | S3/MinIO
       |
Async ingestion workers
  validate -> scan -> parse/OCR -> normalize -> chunk -> embed -> index
```

## Repository structure

```text
apps/
  api/                   FastAPI service
  web/                   Next.js application
services/                Planned ingestion, retrieval, verification, and safety modules
packages/                Planned shared contracts, configuration, and observability
infra/                   Planned migrations, containers, and monitoring
 docs/                   Architecture and implementation plan
```

## Local setup

### 1. Start infrastructure

```bash
cp .env.example .env
docker compose up -d
```

### 2. Start the API

```bash
cd apps/api
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000/health`.

### 3. Start the web application

```bash
cd apps/web
npm install
npm run dev
```

Open `http://localhost:3000`.

## Development guidance

Read [`AGENTS.md`](./AGENTS.md) before using Codex, Claude Code, or another coding agent. The complete staged build is in [`docs/IMPLEMENTATION_PLAN.md`](./docs/IMPLEMENTATION_PLAN.md).

## Current status

The repository contains the project foundation. The next milestone is authentication, workspace isolation, database migrations, and the secure upload workflow.
