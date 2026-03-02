# Pipeline Diagnostics & Azure Acceleration Analysis

## End-to-End Pipeline Timing Architecture

The LLM Council pipeline has been fully instrumented with wall-clock timing across **16 named stages**. Every request now emits a `timing` object within the `cost_summary` SSE event, providing:

- **Total pipeline duration** (ms)
- **Per-stage breakdown** with distribution percentages
- **Per-model latencies** within Stage 1 and Stage 2
- **Provider-level aggregation** (Bayer myGenAssist vs Google AI Studio)
- **Bottleneck identification** (stage consuming the highest % of total time)
- **Slowest model per stage**

### Pipeline Stage Flow & Timing Spans

```
User Query
    ↓
[prompt_guard]      — Prompt suitability evaluation (regex + optional LLM)
    ↓ (parallel)
[memory_recall]     — Pre-Stage 1 agent: semantic/episodic/procedural memory
    ↓
[stage1]            — Parallel model queries (4 models × 60–120s timeout)
  ├─ per-model      — Individual model API call latency
  └─ includes fallback healing if model fails
    ↓
[title_generation]  — Auto-generate conversation title (parallel with S1)
[context_classify]  — Domain/type/complexity classification
    ↓ (parallel)
[stage2]            — Parallel peer review evaluations (4 models × 60–120s)
  ├─ per-model      — Individual model API call latency
  └─ [evidence_retrieval] — Runs IN PARALLEL with Stage 2 queries
    ↓
[grounding_compute] — Compute pharma safety metrics (TP/FP/FN, F1, etc.)
    ↓
[stage3_streaming]  — Chairman synthesis via streaming (or stage3_fallback)
    ↓ (parallel with Stage 3)
[ca_validation]     — Context Awareness validation pass (skipped in speed mode)
    ↓
[doubting_thomas]   — Adversarial self-reflection review
    ↓
[citation_enrich]   — PubMed link enrichment
[citation_validate] — URL reachability check (skipped in speed mode)
    ↓
[agent_team]        — 21 specialist agents (parallel)
[learning]          — Post-pipeline memory + ECA adaptation
```

## Estimated Time Distribution (Typical Pharma Query)

Based on the architecture and API characteristics:

| Stage | Estimated Duration | % of Total | Notes |
|-------|-------------------|------------|-------|
| prompt_guard | 5–50ms | <0.1% | Regex-first, LLM only if ambiguous |
| memory_recall | 200–800ms | 1–2% | Cosmos DB lookup + semantic search |
| **stage1** | **8–25s** | **25–35%** | Bottleneck candidate — 4 parallel API calls, bounded by slowest model |
| title_generation | 1–3s | — | Runs parallel with Stage 1 |
| context_classify | 5–20ms | <0.1% | Local regex classification |
| **stage2** | **10–30s** | **30–40%** | Bottleneck candidate — 4 parallel API calls with longer prompts |
| evidence_retrieval | 2–5s | — | Runs parallel with Stage 2 |
| grounding_compute | 10–50ms | <0.1% | Pure computation (no API calls) |
| **stage3_streaming** | **8–20s** | **20–30%** | Chairman streaming — single model, long generation |
| ca_validation | 3–8s | 5–10% | Parallel with Stage 3, skipped in speed mode |
| doubting_thomas | 3–10s | 5–10% | Sequential (must inspect Stage 3 output) |
| citation_enrich | 50–200ms | <0.5% | Regex-based, no API calls |
| citation_validate | 1–5s | 2–5% | HTTP HEAD requests, skipped in speed mode |
| agent_team | 3–8s | 5–10% | 21 agents in parallel |
| learning | 1–3s | 1–3% | Memory + ECA adaptation |
| **TOTAL** | **35–90s** | 100% | Speed mode: 20–45s |

### Key Observations

1. **The critical path is: Stage 1 → Stage 2 → Stage 3** (sequential, each bounded by slowest model)
2. **Evidence retrieval runs parallel with Stage 2** — negligible additional latency
3. **CA validation runs parallel with Stage 3** — free if Stage 3 takes longer
4. **Agent team + learning run parallel** after Stage 3 completes
5. **Speed mode** cuts ~40% latency by: reducing timeouts (60s), capping tokens, skipping CA/citation validation

## API Provider Analysis: Azure-Hosted vs Google Direct

### Provider Architecture

| Provider | Endpoint | Models | Routing |
|----------|----------|--------|---------|
| **Bayer myGenAssist** | `chat.int.bayer.com/api/v2` | claude-opus/sonnet-4.6, gpt-5.2, gpt-5-mini, o4-mini, grok-3, gemini-2.5-pro/flash | Via Azure-hosted enterprise gateway → vendor API |
| **Google AI Studio** | `generativelanguage.googleapis.com/v1beta` | google/gemini-3-pro, google/gemini-3-flash, google/gemini-2.5-pro/flash/flash-lite, deep-research-pro | Direct API, bypasses gateway |

### Latency Impact Analysis

**Bayer myGenAssist (Azure-Hosted Gateway)**:
- ➕ Enterprise compliance, audit logging, cost tracking
- ➕ 30–50% cost savings via enterprise pricing
- ➖ **Additional hop latency**: Client → Zscaler/Corp Proxy → Azure App Service → Bayer Gateway → Vendor API → reverse path
- ➖ **Zscaler TLS interception**: Adds 50–150ms per connection (TLS re-handshake at corporate proxy)
- ➖ **Gateway processing**: ~20–50ms per request for auth, logging, rate limiting
- ➖ **Estimated overhead**: 100–300ms per API call vs direct
- ➖ **Keepalive challenges**: Corporate proxies (Zscaler/Netskope) may close idle connections after 30–60s. Backend already mitigates with SSE ping comments every 10s.

**Google AI Studio (Direct)**:
- ➕ Lower latency: Client → Google endpoint (no intermediaries)
- ➕ Access to latest Gemini 3.x models before gateway availability
- ➖ No enterprise pricing discount
- ➖ Separate API key management
- ➖ No Bayer audit trail

### Expected Provider Latency Delta

The `PipelineTimer` now aggregates per-provider averages. Expected findings:

- **Google Direct**: ~10–30% faster per-call latency vs same-generation models on Bayer Gateway
- **The gap narrows with longer generation times** (TTFB difference is fixed overhead; generation time dominates)
- **Stage 1** (shorter responses): Google advantage more pronounced
- **Stage 3** (long chairman synthesis): Gateway overhead is negligible relative to 8–20s generation

## Azure Acceleration Recommendations

### 1. Azure API Management (APIM) Response Caching
**Impact: 60-90% latency reduction on repeated queries**

- Deploy APIM in front of the backend
- Cache Stage 1 responses for identical model+prompt combinations (TTL: 1h)
- Especially effective for follow-up questions in same conversation
- Cost: ~$0.03/10k calls (Consumption tier)

### 2. Azure Front Door for Edge Routing
**Impact: 20-40ms reduction on initial connection**

- Global edge network reduces first-byte latency
- Persistent connections to backend app service
- Built-in WAF replaces some prompt_guard overhead
- Already have App Service — Front Door integrates natively

### 3. Azure Cache for Redis — Memory Recall Acceleration
**Impact: 5-10x faster memory_recall stage (800ms → 80ms)**

- Current: Cosmos DB point-read + vector search for memory recall
- Proposed: Hot-cache frequently accessed user profiles + recent episodic memories in Redis
- Write-through: Cosmos DB remains source of truth; Redis caches latest N episodes
- Tier: C1 Standard (6GB) — sufficient for all active users
- Cost: ~$40/month

### 4. Connection Pool Optimization (Already Implemented)
**Current state: Good — 40 max connections, 20 keepalive, 120s expiry**

- ✅ TCP connection reuse via httpx.AsyncClient
- ✅ TLS session reuse across calls
- ✅ SSE keepalive pings every 10s (mitigates Zscaler idle timeout)
- 🔧 **Potential upgrade**: Enable HTTP/2 multiplexing on `httpx.AsyncClient(http2=True)` to reduce head-of-line blocking for parallel model queries (requires `httpx[http2]` package)

### 5. Azure App Service Premium v3 (P1mv3)
**Impact: 15-25% faster CPU-bound stages (grounding_compute, ranking parse)**

- Current: S2 Standard (2 vCPU, 3.5GB RAM)
- Proposed: P1mv3 (2 vCPU, 8GB RAM, faster processor, zone redundancy)
- Benefits: Faster Python execution for grounding math, larger connection pool headroom
- Cost delta: ~$50/month additional

### 6. Parallel Stage 1+2 Warm-Up (Speculative)
**Impact: Overlap Stage 1 tail with Stage 2 head, save 2-5s**

- As each Stage 1 model completes, immediately start its Stage 2 evaluation
- Current: Wait for ALL Stage 1 → then fire ALL Stage 2
- Proposed: Incremental — start Stage 2 for model X as soon as model X's Stage 1 response arrives
- Complexity: Medium (requires refactoring stage2 to not assume all S1 results available)

### 7. Model Selection Optimization
**Impact: 5-15s reduction by identifying and replacing consistently slow models**

- The `PipelineTimer` now tracks slowest_models per stage
- If grok-3 consistently adds 8s+ to Stage 1 while others finish in 5s:
  - The entire stage is bounded by grok-3
  - Consider replacing with a faster model OR reducing its timeout
- Review timing data after 50+ queries to identify chronic bottlenecks
- Automated: Could add logic to `model_sync.py` to demote consistently slow models

### 8. Azure Container Apps (Future Scale-Out)
**Impact: Auto-scaling for burst traffic**

- If concurrent user count grows beyond what S2/P1mv3 handles
- ACA provides per-request scaling with KEDA
- Supports min 0 → max N replicas
- Better isolation per request (no GIL contention between concurrent councils)

### Priority Matrix

| # | Recommendation | Impact | Effort | Cost/month |
|---|---------------|--------|--------|------------|
| 1 | Redis memory cache | High | Low | $40 |
| 2 | HTTP/2 multiplexing | Medium | Low | $0 |
| 3 | APIM response caching | High | Medium | $3-10 |
| 4 | Front Door edge routing | Medium | Medium | $35 |
| 5 | P1mv3 App Service | Medium | Low | +$50 |
| 6 | Incremental S1→S2 overlap | High | High | $0 |
| 7 | Slow model detection | Medium | Low | $0 |
| 8 | Container Apps migration | High | High | Variable |

### Quick Wins (Implement This Week)

1. **Enable HTTP/2**: `pip install httpx[http2]` + set `http2=True` on AsyncClient
2. **Review timing data**: Run 10+ queries, analyze the `cost_summary.timing` in the PipelineTiming dashboard
3. **Identify bottleneck models**: Check `slowest_models` in timing output — replace chronic laggards
4. **Redis for memory**: Deploy Azure Cache for Redis C1, update `memory_store.py` with Redis hot-cache layer
