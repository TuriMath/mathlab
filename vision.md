# Turi Math Factory: Spec (v2)

25 Nov 2026 · Tadisetty Sai Yashwanth

The Turi Math Factory is an agent swarm that turns human mathematics into machine-checked Lean 4 proofs. It climbs a ladder of classic theorems, oldest first, the same way TuriChips climbs historical chips. A result counts only if Lean compiles it with no `sorry` and no extra axioms, so anyone can check every output. It is the second of three Turi Labs factories (chips, math, AI research). Turi Labs is the user's lab and runs all three.

**Operating constraint.** The founder does not know Lean and is not a mathematician. The factory must run with the founder setting **direction only**. No step in the pipeline may depend on a human judging whether a Lean statement or proof is correct. Every trust check is mechanical or done by agents. When in doubt, the factory parks the item; it does not escalate to the founder.

**Motto (draft):** *Nothing counts until Lean says so.*

---

## Goal

The factory's first goal: publish 40 machine-checked theorems and a 200-task RL environment, with the founder spending no more than **1 hour a week**, on direction only. All targets are proposed starting points, to be revised after Phase 1.

**Core goals**

- **40 theorems** formalized in the public repo, each passing the gate: `lake build` green from a clean clone, no `sorry`, axioms limited to Lean's standard three.
- **An RL environment of 200 tasks** (Lean statement in, verified proof out), built from the factory's own outputs. This is the main commercial asset (see *Where the value builds up*).
- **One textbook chapter** fully formalized, end to end, as proof that the factory can handle connected theory as well as standalone results.
- **A public theorem list** on the Turi Labs site, matching the TuriChips chip list: one page per theorem with the informal proof, the Lean proof and the agent log.

**Stretch goals**

- **10 Mathlib PRs submitted, 3 merged.** This is a stretch goal, not a core one, because Mathlib review expects a human author who understands the code and stands behind it, and the founder cannot answer Lean review comments. It becomes core if a Lean-literate collaborator joins to own PRs. Until then, the outside check is the public log plus the blind-equivalence check (below).

---

## Vision

The goal is an open, machine-verified history of mathematics, built by agents, where every step is checked and every log is public. TuriChips rebuilds computing one chip at a time. The math factory rebuilds mathematics one theorem at a time, from Euclid toward 20th-century results.

- **Why it matters now.** AI math results are arriving faster than humans can check them. A factory whose only judge is Lean produces output that requires no trust in the agents.
- **Where the value builds up.** Each verified theorem is also a training task: a statement, a checker and a known-good proof. Over time the factory produces a growing, uncontaminated RL dataset. The **task set + verifier** is Turi Labs' own work and can be sold as RL environments. Raw agent traces are a possible second product, but Anthropic's Commercial Terms restrict using model outputs to train competing models, so check this before counting on trace revenue. Every task writes structured metadata from day one (see *Trace metadata*) so the data is labelled, not just logged.
- **How it fits the other factories.** The AI research factory takes the math factory's tasks as RLVR environments. Later, Lean can state and prove properties of TuriChips designs (for example, that an adder adds correctly), so the three factories feed one another.

---

## Principles

Seven rules the factory never bends. Most of them exist to stop one failure: a correct-looking proof of the wrong statement.

1. **Lean is the only judge.** A theorem is done when CI builds it with no `sorry` and `#print axioms` shows only `propext`, `Classical.choice` and `Quot.sound`. An agent saying "done" means nothing.
2. **Statements are locked before proving starts.** A statement passes the statement-fidelity pipeline (below), then is frozen. Provers cannot edit statement files; CI rejects any diff to them.
3. **No human judges maths.** Statement fidelity is checked by mechanical tests and independent agents, never by asking the founder. If the checks disagree, the theorem is parked with notes.
4. **Check before building.** The scout searches Mathlib and the public theorem lists first. Re-proving something already in Mathlib is allowed only as a labelled calibration exercise.
5. **Pin everything.** One Lean toolchain and one Mathlib commit per phase, upgraded on purpose, never mid-proof.
6. **Budget per theorem.** Each theorem gets a fixed number of prover attempts. When they run out, it is parked with notes, not retried forever.
7. **Publish failures too.** Parked theorems, rejected statements and wrong turns go in the public log next to the successes.

---

## Statement fidelity: replacing human review

Lean checks proofs, not meaning. An agent can prove a wrong or trivial statement and Lean will accept it. These checks replace the human reviewer, strongest first.

1. **Prefer human-written statements.** Wherever possible, take statements that Lean experts already wrote and reviewed: Mathlib (Tiers 0–1) and DeepMind's `formal-conjectures` (Tier 5). This moves the trust outside the factory.
2. **Blind double formalization.** Two formalizers write the statement independently, with no access to each other's work. A prover must then prove **A ↔ B** in Lean. If they cannot be proved equivalent, the theorem is parked. This is the main check.
3. **Back-translation.** An agent that has never seen the source translates the Lean statement back into English. A judge agent compares it to the source text.
4. **Automatic red flags.**
   - The statement is closed by `simp`, `decide` or `trivial`: probably weakened.
   - The hypotheses cannot be shown satisfiable by a concrete example: probably vacuous.
   - Known-false variants of the statement must be disprovable.
5. **Planted-error tests run by the system.** Each month the harness injects a deliberately wrong statement into the queue and reports whether the pipeline caught it. Target: 100% caught.

A statement is locked only when checks 2–4 pass (or when it comes from check 1).

---

## Team

Start with **5 agents**, chosen around the statement-fidelity pipeline. Add the rest once the first-pass gate rate holds at ≥ 60%.

| Agent | Phase | Job |
|---|---|---|
| Scout | start | Searches Mathlib and the trackers, picks targets, proposes options for direction decisions |
| Formalizer A | start | Writes the Lean statement from the source |
| Formalizer B | start | Writes the same statement independently, blind to A |
| Prover | start | Proves theorems and the A ↔ B equivalence proofs |
| Critic | start | Back-translation, red-flag checks, planted-error tests; tries to break statements |
| Librarian | later | Finds Mathlib lemmas, golfs proofs, prepares upstream PRs |
| Prover B | later | Second prover for throughput |
| Writer | later | Plain-English proof sketches, theorem pages, posts |

Infra (Lean toolchain, Mathlib cache, CI, VPS) is handled by the shared factory harness, copied from TuriChips.

---

## The ladder

The early tiers are mostly already in Lean, so they test the pipeline; the real new work starts at Tier 2. On Freek Wiedijk's 100-theorems list, roughly 80 of 100 are already formalized in Lean (Lean tracker). His larger 1000+ list, built from theorems named on Wikipedia, has far more left to do (1000+ tracker). The scout pulls the current "not yet in Lean" pages in week 1, because these counts change.

| Tier | Source | Examples | Purpose |
|---|---|---|---|
| 0 | Antiquity | Irrationality of √2, infinitude of primes, Pythagorean theorem | Calibration: already in Mathlib, re-proved in our repo to test the gate |
| 1 | 1600–1800 classics | Fermat's little theorem, Wilson's theorem, binomial theorem | Calibration plus write-ups; first runs of the statement-fidelity pipeline |
| 2 | Missing items on the 100 list | Picked from the tracker's "not yet in Lean" page | First genuinely new formalizations |
| 3 | Missing items on the 1000+ list | Picked by era and by how much Mathlib support exists | Main body of new work |
| 4 | One textbook chapter | Scout proposes 3 options with Mathlib coverage numbers in Phase 3 | Connected theory, not standalone results |
| 5 | Stretch | Formalized open-problem statements (e.g. DeepMind `formal-conjectures`, Erdős problems) | Only after Phase 3, with a hard budget |

---

## Roadmap

Four gated phases take the factory from an empty repo to the goal. No phase starts until the gate before it passes. If a gate fails, the phase is extended rather than skipped. Phase 1 is the one most likely to run long, because statement locking and attempt budgets are still being tuned there.

| Phase | Work | Gate to pass |
|---|---|---|
| **0 · Setup** | Repo, pinned Lean and Mathlib, CI gate (no `sorry`, axioms check), statement lock. Agent roles live; one Tier 0 theorem taken end to end, including a blind A ↔ B equivalence proof | **Gate 0:** CI rejects a planted `sorry` and a planted extra axiom |
| **1 · Calibration** | Tiers 0 and 1, about 15 theorems. Tune attempt budgets; test the statement-fidelity pipeline with deliberately wrong statements | **Gate 1:** 15 verified, and the pipeline catches the planted wrong statement |
| **2 · Climb** | Tier 2: missing items from the 100 list. Theorem pages live on the Turi Labs site. First Mathlib PRs only if a Lean-literate author is on board (stretch) | **Gate 2:** 30 verified *(stretch: 5 Mathlib PRs submitted)* |
| **3 · Contribute** | Tier 3 from the 1000+ list, plus the Tier 4 textbook chapter. Package 200 verified tasks as an RL environment | **Gate 3 (first goal):** 40 verified, RL environment runs *(stretch: 10 PRs submitted, 3 merged)* |
| **4 · Beyond** | Tier 5 stretch work, with a hard budget. Hand tasks to the AI research factory; explore Lean proofs about TuriChips designs | — |

v2 change from the original roadmap: Mathlib PR counts moved out of the gates into stretch targets, so a phase never blocks on work that needs a Lean-literate human. "Reviewer" is now the statement-fidelity pipeline.

---

## Founder involvement

The founder's job is direction, about 1 hour a week:

- Read the **weekly digest**: theorems verified, parked (with reasons), first-pass gate rate, planted-error result, seat usage, next targets.
- Make **direction decisions** the scout lays out as options: move to the next tier, pick the textbook, start or stop stretch work, add agents.
- Approve outward-facing things: going public, posts, Mathlib PRs.

The founder is never asked whether a statement or proof is correct.

---

## KPIs and what gets published

The headline number is verified theorems per week. Everything else exists to keep that number honest.

| KPI | Target | How it is measured |
|---|---|---|
| Verified theorems (cumulative) | 40 | CI gate passes on main |
| First-pass gate rate | ≥ 60% | Theorems that pass within their attempt budget ÷ theorems attempted |
| Statement errors caught before proving | 100% of planted errors | System injects a deliberately wrong statement monthly |
| Blind-equivalence pass rate | Tracked | A ↔ B proved ÷ pairs attempted |
| RL environment tasks | 200 | Tasks with locked statement + verified proof + metadata |
| Parked theorems | Logged, each with a reason | Public log |
| Founder time | ≤ 1 hour a week, direction only | Founder's own tally |
| Mathlib PRs (stretch) | 10 submitted, 3 merged | GitHub |

**Published for every theorem:** the source reference, the locked Lean statement, the proof, a plain-English proof sketch, the agent log and the axioms check. **Published weekly:** a short changelog, plus a post every 2 to 3 days, the same cadence as TuriChips.

### Trace metadata

Every task writes a record next to its agent transcript, from day one:

- task id, tier, source reference
- statement provenance (human-written / blind-double / other) and fidelity-check results
- verdict: proved, parked (reason), or statement rejected
- axioms used, attempts used vs budget, wall time, agent and model
- Mathlib and toolchain commit

Failed attempts are kept too. They are part of the dataset.

---

## Risks and open questions

The biggest risk is proving the wrong statement. That is why statement fidelity comes before everything else.

| Risk | What happens | Mitigation |
|---|---|---|
| Wrong or weakened statement | Lean accepts a proof of something easier than the theorem | Human-written statements first, blind double formalization + equivalence proof, back-translation, red flags, monthly planted-error test |
| No human can judge the maths | A subtle error gets through every agent check | Park on any disagreement; prefer externally reviewed statements; public logs invite outside checking |
| Duplicate work | The factory re-proves something already in Mathlib | Scout checks Mathlib and the trackers before any theorem starts |
| Others got there first | AI tools are already being used to formalize missing list items (Zulip thread) | Count verified, published, logged results; Mathlib acceptance is a stretch bar |
| Mathlib PRs need a human author | Reviewers ask Lean questions the founder can't answer | PRs are stretch; find a Lean-literate collaborator before submitting |
| Stuck proofs burn the quota | One hard theorem eats a week of plan capacity | Attempt budget per theorem, then park |
| Shared rate limits | Math and TuriChips compete for the same Claude Code plans | Stagger the factories' active hours; separate seats if possible |
| Mathlib version churn | An upgrade breaks finished proofs | Pin per phase; upgrade as a planned task |
| Trace resale terms | Selling Claude-generated traces to labs may breach Anthropic's Commercial Terms | Lead with the RL environment (own work); check terms before selling traces |

### Infrastructure

- Own VPS, separate from TuriChips. Lean + Mathlib is memory-heavy: at least 4 vCPU / 16 GB RAM.
- Harness copied from TuriChips (`ops/chat`, dispatcher, seat pool, guardrails, `_rules.md` pattern).
- Public site: `math.turilabs.in` or `turimath.github.io` (either is fine).

### Open questions

- [x] Name: "Turi Math" (repo: `mathlab`).
- [x] Start with 5 agents (see *Team*).
- [ ] Which textbook for Tier 4? Scout proposes options in Phase 3.
- [ ] What is Mathlib's current policy on AI-assisted contributions? Check before any PR.
- [ ] Anthropic Commercial Terms: what can be done with traces? Check before selling them.
- [ ] Site domain: `math.turilabs.in` vs `turimath.github.io`.
- [x] Phase table for the roadmap.

---

## Sources

- Lean 100 theorems tracker
- Lean 1000+ theorems tracker
- Freek Wiedijk, *Formalizing 100 Theorems*
- DeepMind `formal-conjectures` (Lean statements of open conjectures)
