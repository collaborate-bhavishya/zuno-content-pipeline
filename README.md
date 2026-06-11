# Zuno SpeakX — Self-Healing Lesson Pipeline

A full-stack app around the LangGraph multi-agent pipeline. Enter a theme and an
age; watch four agents plan, critique, and self-correct their way to an
illustrated speaking lesson; review the output in a split screen and approve,
give feedback, or re-run.

```
zuno-app/
├── backend/         FastAPI + LangGraph (SSE streaming)
│   └── app/
│       ├── main.py            API: /api/generate, /api/feedback, /api/admin/*
│       ├── core/
│       │   ├── config.py      runtime config the admin panel edits (models, keys, prompts)
│       │   ├── llm.py         client factory (supports cross-family judging)
│       │   ├── storage.py     LocalStorage now / GCSStorage (S3-equivalent) ready
│       │   ├── state.py       LangGraph state schema
│       │   ├── validators.py  deterministic safety + structure checks
│       │   └── graph.py       graph assembly
│       └── nodes/graph_nodes.py   all generator / evaluator / image nodes
└── frontend/        Next.js + React
    ├── app/page.tsx           input form + live feed + split-screen output
    ├── app/admin/page.tsx     password-gated admin panel
    ├── components/            ProcessFeed, OutputPanel
    └── lib/api.ts             SSE client
```

## Quick start

### 1. Backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add your GOOGLE_API_KEY, set ADMIN_PASSWORD
uvicorn app.main:app --reload --port 8000
```

### 2. Frontend (new terminal)
```bash
cd frontend
npm install
cp .env.local.example .env.local   # NEXT_PUBLIC_API_BASE=http://localhost:8000
npm run dev                          # http://localhost:3000
```

Open http://localhost:3000. Admin is at /admin (default password `zuno-demo`).

## How it works

The backend exposes the pipeline as a Server-Sent Events stream. As LangGraph
executes each node, the server emits an event; the frontend renders it as a stage
in the live feed. A failed evaluation shows the critique that gets fed back into
the generator — so the self-healing retry loop is visible, not hidden in logs.

Three retry loops, each capped at `max_retries`:
1. planner → blueprint_evaluator (safety + structure + LLM quality judge)
2. fabricator → matrix_evaluator (structural validation)
3. image_factory → vision_critic (multimodal audit of the actual PNG)

When the run completes, the right half of the screen shows the blueprint,
questions, and approved images, with Approve / Add feedback / Re-run actions.
Feedback is seeded into the next run as a correction notice.

## Admin panel

- Models: per-role provider + model + temperature. Default judge is cross-family-ready
  (switch the judge provider to `anthropic` or `openai` to avoid self-preference bias).
- API keys: session-scoped, shown masked, type to replace.
- Prompts: edit the generator / judge / vision-critic system prompts; changes apply
  on the next run, no restart.
- Demo limits: questions, images, retries.

Config is in-memory (not persisted) — perfect for a live demo where you tweak a
prompt and immediately re-run, but it resets when the server restarts.

## Storage

Default is local (`backend/storage/images`, served at `/files/...`). To use
Google Cloud Storage (the S3 equivalent — not Google Drive), set in `.env`:

```
STORAGE_BACKEND=gcs
GCS_BUCKET=your-bucket
GOOGLE_APPLICATION_CREDENTIALS=/path/service-account.json
```

No other code changes needed — the storage interface is swapped at boot.

## Deploy (optional)

- Backend → Render / Railway / Fly (any container host). Set env vars there.
- Frontend → Vercel. Set `NEXT_PUBLIC_API_BASE` to the deployed backend URL.
- For a public deploy, switch storage to GCS so images have stable URLs, and
  add a rate limit on `/api/generate` so a judge mashing the button doesn't burn
  your API quota.

## Demo script (90 seconds)

1. Type "Trucks", age 5, Generate. Narrate the feed: planner → evaluator. If the
   evaluator rejects, point at the critique being injected back.
2. When the split screen appears, flip through Blueprint / Questions / Images.
3. Open Admin, change the generator prompt or swap the judge to Claude, save.
4. Back to the app, Re-run — show the behavior changed live.
5. (If asked about internals) open LangGraph Studio on the same graph to show
   the node/state/retry structure visually.
