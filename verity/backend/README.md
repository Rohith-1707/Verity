# VERITY backend (FastAPI)

Python API for document extraction, evidence retrieval, claim verification, risk scoring, review workflow and audit logging.

## Setup
```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in values
```
1. Create a Supabase project. Run `migrations/001_schema.sql` in the SQL editor.
2. Put the database connection string in `DATABASE_URL` and the project's JWT secret in `SUPABASE_JWT_SECRET`.
3. Set `LLM_API_KEY` and `LLM_MODEL` for AI screening. Without them, submissions return a clear error unless the creator chooses to skip AI.
4. Set `CHROMA_PATH` to a persistent folder (on Render, a disk) for semantic search. If unset, a keyword index is built from the database.
5. Run: `uvicorn app.main:app --reload`, then open `/docs`.

## Tests
`pytest` runs the engine, extraction and authentication tests. API endpoints against a live PostgreSQL database are not yet covered.

## Layout
`app/engine.py` verification rules (pure functions) · `app/retrieval.py` ChromaDB and Sentence Transformers · `app/extract.py` PDF, DOCX, TXT · `app/llm.py` AI screening · `app/main.py` REST API · `migrations/` SQL with row-level security.
