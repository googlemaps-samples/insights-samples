# Architecture Decision Record: Explicit vs Implicit Vertex Context Caching (2026-10)

## Status
Accepted — **Rely on Vertex implicit prefix caching; do not create explicit `CachedContent` resources.**

## Context
Each panoramic notebook issues between 4 and 86 Gemini calls (`gemini_client.DEFAULT_MODEL` via Vertex AI). Every call sends a prompt string, an optional JSON schema hint, and a distinct perspective view JPEG rendered from a Street View Insights rosette. We evaluated whether to provision explicit Vertex `CachedContent` resources (`client.caches.create(...)`) for the shared text prefix across calls within a notebook run.

## Measured Prefix & Per-`media_resolution` Token Counts (`gemini_client.preview_tokens` / `count_tokens`)
Using `gemini_client.preview_tokens` on `gemini_client.DEFAULT_MODEL` (`global`) across `media_resolution in ("LOW", "MEDIUM", "HIGH")`:
- **UC1 (`HouseView` prompt + schema hint, `1024x768` view)**: `182` text-only prefix tokens; with 1 image: `LOW = 462` tokens (`280` media tokens), `MEDIUM = 742` tokens (`560` media tokens), `HIGH = 1,302` tokens (`1,120` media tokens).
- **UC2 (`FrameDetections` prompt + schema hint, `1024x1280` view)**: `196` text-only prefix tokens; with 1 image: `LOW = 476` tokens (`280` media tokens), `MEDIUM = 756` tokens (`560` media tokens), `HIGH = 1,316` tokens (`1,120` media tokens).
- **UC3 (`WindowLabel` prompt v1 + schema hint, `1280x960` road view)**: `318` text-only prefix tokens; with 1 image: `LOW = 598` tokens (`280` media tokens), `MEDIUM = 878` tokens (`560` media tokens), `HIGH = 1,438` tokens (`1,120` media tokens).
- **UC4 (`RoofEdges` prompt + schema hint, `1200x900` roof view)**: `244` text-only prefix tokens; with 1 image: `LOW = 524` tokens (`280` media tokens), `MEDIUM = 804` tokens (`560` media tokens), `HIGH = 1,364` tokens (`1,120` media tokens).

## Decision
1. **Do not create explicit `CachedContent` resources.** Vertex AI explicit context caching requires a minimum of `2,048` (or `4,096` depending on model tier) static prefix tokens and incurs a per-hour storage charge. Because each call inspects a **different** camera view image, only the text+schema prefix (`182–318` tokens) is shared across calls in a batch — well below the explicit-cache minimum threshold by `6x–11x`.
2. **Surface implicit caching in `CostTracker`.** Vertex AI automatically applies implicit prefix caching when requests share a common prefix, reporting hits in `usage_metadata.cached_content_token_count`. `CostTracker` records `cached_tokens` and prints `input=I (cached C)` in every `runner.cost.summary()` line so any implicit cache savings are transparently reported.
3. **Revisit trigger.** Re-evaluate explicit `CachedContent` only if a future use case introduces a shared multi-page rubric, few-shot image bank, or system instruction exceeding `2,048` tokens across `>= 20` calls per run.
