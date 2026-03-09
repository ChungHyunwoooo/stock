# Trading Platform Change Goals (Single-Doc Plan)

## 1) Objective
Current system is hard to modify because core logic is concentrated and partially hardcoded.
Target is to migrate to a configurable, extensible architecture while keeping the current alert bot running during transition.

This plan intentionally stays in one document and avoids creating new directory structures first.

---

## 2) Non-Negotiables
1. Keep current alert bot available during migration.
2. No big-bang rewrite.
3. No immediate broad directory restructuring.
4. Prefer compatibility layer over breaking API/UI changes.
5. Runtime behavior changes must be configurable (not code-only).

---

## 3) Current Problems to Solve
1. Large single-module bottleneck (`upbit_scanner.py`) makes safe edits difficult.
2. Exchange coupling (mostly Upbit-centric paths).
3. Strategy/detector lifecycle is not easy to add/remove without code touches.
4. Time/cooldown/alert behavior still partly code-driven.
5. Analysis depth is limited for cross-exchange context (leader/follower, premium).
6. Validation path (backtest/simulation before production) is not strictly enforced by workflow.

---

## 4) Target Product Shape
### 4.1 Functional separation
- `analysis`: signal generation and market structure analysis
- `automation`: conditional execution/orchestration
- `notification`: channel delivery (Discord first)

### 4.2 Configuration-first operation
- scan intervals
- alert time windows
- cooldown
- strategy on/off
- detector priority
- risk thresholds
All editable without source code edits.

### 4.3 Exchange extensibility
- Start with Upbit + Binance.
- Same analysis pipeline should run across exchanges via adapter abstraction.

### 4.4 Advanced analysis
- Leader/Follower exchange detection (price discovery, lead-lag)
- Kimchi premium / reverse premium
- Execution exchange price matching against reference exchange
- Extended indicator stack including OBV + POC/Volume Profile + structure line logic

---

## 5) Migration Strategy (Safe Rollout)
## Phase 0: Baseline lock
1. Freeze current bot behavior snapshot (signals, latency, error rate).
2. Define acceptance metrics for replacement.

## Phase 1: Shadow bot (new bot alongside old)
1. Create new bot entry path (v2) without disabling old bot.
2. Run same market input, compare outputs.
3. Route v2 alerts to test webhook/channel first.

## Phase 2: Config externalization
1. Move hardcoded runtime options to config schema.
2. Expose read/write API for those options.
3. Ensure runtime reload path (or controlled restart path).

## Phase 3: Detector plugin model
1. Standard detector interface (input/output contract).
2. Registry-based enable/disable + ordering + params.
3. Add/remove detector with minimal or zero core-code edits.

## Phase 4: Exchange abstraction
1. Data adapter port for OHLCV/ticker/market metadata.
2. Upbit adapter + Binance adapter.
3. Symbol normalization layer.

## Phase 5: Advanced analysis modules
1. Lead-lag module.
2. Premium module (FX-adjusted).
3. Execution match module.
4. Parameterized timeframe/window controls.

## Phase 6: Cutover
1. Partial rollout (subset symbols/strategies).
2. 50% traffic.
3. 100% cutover after quality gates pass.
4. Keep rollback switch available.

---

## 6) Quality Gates (Before Full Switch)
1. Signal miss rate <= agreed threshold vs baseline.
2. Alert latency within agreed range.
3. Error rate not worse than baseline.
4. Config update success and persistence verified.
5. Backtest/simulation pass for newly added detector/strategy.

---

## 7) TDD/DDD Adoption Timing
TDD/DDD is required, but after initial structural decoupling starts.

1. First: isolate seams (ports, detectors, config contracts).
2. Then: write tests around isolated units.
3. Then: domain boundaries and aggregates are hardened.

Reason: introducing strict DDD/TDD before decoupling would increase migration friction.

---

## 8) UI Direction (Requested Scope Control)
UI must be separable by functional area so changes can be done in focused slices.

Required UI capabilities:
1. Detector management (on/off, priority, params)
2. Analysis parameters (timeframe, windows, thresholds)
3. Alert schedule/cooldown/channel settings
4. Workflow mapping (`analysis -> automation -> notification`)

---

## 9) YouTube/Script Ingestion (Future)
Supported as a staged pipeline:
1. Input: URL/script/subtitle
2. Parse: extract candidate rules
3. Convert: internal detector/rule schema
4. Validate: replay/backtest gate
5. Approve: manual approval before production enable

No direct auto-production publish without validation gate.

---

## 10) Security and Ops Notes
1. Secrets must be moved out of plain config files into environment/secret storage.
2. Add explicit rollback toggles (feature flags).
3. Add comparison logging in shadow mode for deterministic migration decisions.

---

## 11) Immediate Execution Checklist (Start Now)
1. Keep current alert bot active.
2. Add v2 shadow runtime path (no production overwrite).
3. Externalize runtime config fields first (intervals/cooldown/channels).
4. Introduce detector interface + registry.
5. Add Binance adapter with normalized symbol mapping.
6. Build leader/follower + premium analysis as optional modules.
7. Start partial traffic switch only after gate checks.

---

## 12) Definition of Done
Migration is done when:
1. New architecture runs production alerts stably.
2. Detector add/remove is operationally simple.
3. Runtime behavior is configurable from UI/API.
4. Upbit and Binance both operate through shared analysis contracts.
5. Advanced cross-exchange analysis is available and usable.
6. Old bot can be retired without loss of functionality.

---

## 13) Execution Status (Implemented)
- [x] Phase 1: Shadow runtime added (`engine/strategy/upbit_shadow.py`)
- [x] Phase 2: Runtime config externalized for shadow/v2 (`config/*.json` load/save path)
- [x] Phase 3: Detector plugin registry added (`engine/strategy/detector_registry.py`)
- [x] Phase 4: Exchange adapter abstraction added (Upbit/Binance) (`engine/strategy/exchange_adapters.py`)
- [x] Phase 5: Cross-exchange analysis module added (`engine/analysis/cross_exchange.py`)
- [x] Phase 6: Canary/live rollout runtime added (`engine/strategy/alert_v2.py`)
- [x] API controls added:
  - `/api/bot/upbit/shadow/*`
  - `/api/bot/alert-v2/*`
  - `/api/bot/detectors`
  - `/api/bot/analysis/cross-exchange`
