# Zuno SpeakX — Hackathon Submission

> Real-time, personalized English-as-a-second-language lessons for children, generated
> by a self-healing multi-agent pipeline and turned into a playable game in minutes.

See also: [`architecture.svg`](./architecture.svg) (agentic system),
[`deployment_architecture.svg`](./deployment_architecture.svg) (infrastructure),
[`skill_complexity.svg`](./skill_complexity.svg) (the SpeakX pedagogical DSL).

---

## Problem to solve

Teaching English as a second language to young children is bottlenecked by **content and
asset production**. Every lesson requires writing pedagogically-sound academic content,
then generating matching assets (images, voice-overs), then re-authoring all of it into a
playable game format — a long, manual, multi-team pipeline. The result is **slow,
expensive, and quality-inconsistent**, and because the content is **pre-defined and
static**, it rarely matches what an individual child actually finds interesting, so
engagement suffers. A child obsessed with dinosaurs still gets the generic "farm animals"
lesson.

## Our solution

We're **democratizing lesson creation** so a child can learn English through *their own
favourite topic*, generated in real time by a **multi-agent AI pipeline** — in minutes,
not weeks.

A learner (or teacher) enters any theme and age; our agent system then:
- **Plans a curriculum blueprint** grounded in a strict pedagogical ladder aligned to
  **Krashen's Natural Approach** — comprehensible input (image + audio grounding),
  input-before-output (receptive recognition before spoken production), natural order
  (vocabulary → concept → sentence → guided/independent speaking), and a low affective
  filter (warm, child-safe tone).
- **Fabricates a structured question matrix** that maps directly to a playable game format.
- **Generates the visual assets** (illustrations) for every question.
- **Self-corrects at every stage** — each generator is paired with an evaluator that sends
  back targeted critiques until the output passes, so a fast/cheap model still hits a
  production-grade spec.

Key features:
- **Real-time, any-topic generation** → a complete, illustrated, game-ready lesson in minutes.
- **Self-healing LangGraph agent pipeline** (generator → evaluator → router loops with
  incremental-repair feedback).
- **Two-lane evaluation** — deterministic rule checks (free, instant) + an LLM-as-Judge —
  gates quality before any expensive asset generation.
- **Vision-audited image generation** with reuse/de-duplication to control cost.
- **Output is a structured JSON "playable"** consumed directly by the Zuno game player.

This is fundamentally an **optimization** of a slow, costly, static process into a fast,
cheap, personalized one.

## Technologies used

**Google Cloud / AI**
- **Google Gemini 2.5 Flash & Flash-Lite** (via **Vertex AI**) — blueprint & question-matrix
  evaluation (LLM-as-Judge) and the multimodal **Vision Critic** that audits generated images.
- **Google Imagen 3.0 (Fast)** (via **Vertex AI**) — text-to-image generation of lesson illustrations.
- **Google `google-genai` SDK** + **Vertex AI** (service-account / ADC auth).

**Agent framework & backend**
- **LangGraph** — multi-agent StateGraph orchestration with self-healing retry loops.
- **LangChain** (langchain-google-vertexai, langchain-anthropic) — model abstraction for cross-family judging.
- **Anthropic Claude Haiku 4.5** — content generation (Planner + Fabricator agents), used
  cross-family to reduce self-preference bias in evaluation.
- **FastAPI** (Python) with **Server-Sent Events** for live agent-trace streaming.

**Data, storage & infra**
- **Supabase (Postgres)** — image-asset ledger (generation status / de-duplication).
- **AWS S3** — durable storage for generated images and run JSON.
- **AWS EC2 + Docker + Caddy** (auto-HTTPS), **AWS Amplify** (Next.js frontend),
  **Route 53**, **GitHub Actions** CI/CD.

## Data sources

- **SpeakX pedagogical framework (`backend/app/core/skill_v6.md`)** — our in-house knowledge
  base encoding the curriculum ladder, 18 question templates, per-age constraints, and
  pedagogical ordering laws (Krashen-aligned). Primary grounding source for the agents.
- **Per-age guidelines** — vocabulary level, sentence-length limits, allowed/forbidden
  templates, speaking-urgency deadlines.
- **Supabase `image_assets` table** — a live ledger the pipeline reads to reuse existing
  images and skip regeneration.
- **No external/scraped datasets** — lessons are generated on demand from the prompt +
  framework; assets are model-generated, not sourced from a corpus.

## Findings and learnings

- **Cheap, fast models can hit a strict spec — if you wrap them in a self-healing loop.**
  A small model (Haiku) alone couldn't reliably satisfy our 26-column, 18-template schema;
  pairing each generator with an evaluator and feeding back *targeted* critiques closed the gap.
- **Naïve retry causes "whack-a-mole."** Regenerating the whole output on each failure fixed
  one error while breaking another. Switching to **incremental repair** — hand the model its
  previous output and say "change only the flagged cells" — made it converge in 1–2 tries.
- **Two-lane evaluation is the real cost optimizer.** Running deterministic Python checks
  *first* and only spending an LLM-judge call on context-sensitive dimensions cut evaluation
  cost dramatically and made the pipeline auditable.
- **Cross-family judging matters.** Claude generating + Gemini judging reduced self-preference
  bias and caught issues a same-model judge waved through.
- **Image quota — not model quality — is the production bottleneck.** We empirically measured
  per-model image quotas (some 429'd after ~2 calls, others sustained 8+) and chose the best,
  plus a dedup ledger, reuse-friendly naming, and adaptive back-off pacing.
- **A multimodal Vision Critic closes the asset-quality loop** — auditing actual pixels
  (white background, no outlines, correct subject) catches what a text-only pipeline never would.
- **Graceful degradation beats hard failure** — proceeding with the best-available output
  (and flagging issues via the eval grade) yields a usable lesson instead of nothing.

## Third-party integrations

- **Anthropic Claude API** (Haiku 4.5) — content generation. Used under our own API key per
  Anthropic's commercial terms. ✅ Authorized.
- **Google Gemini & Imagen via Vertex AI** — evaluation, vision audit, image generation.
  Used under our Google Cloud account. ✅ Authorized.
- **Supabase** — managed Postgres for the asset ledger. Our own project. ✅ Authorized.
- **LangGraph / LangChain** (MIT), **Caddy** (Apache-2.0), **FastAPI** (MIT), **Docker** —
  open-source. ✅
- **AWS** (EC2, S3, Amplify, Route 53) — our own account. ✅
- **All lesson content and images are generated by the models at runtime** — no third-party
  copyrighted text, images, or datasets are ingested.
