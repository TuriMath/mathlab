<p align="center">
  <img src="https://raw.githubusercontent.com/TuriMath/.github/main/brand/banner.png" alt="TuriMath" width="720">
</p>

# mathlab

The company repo of **TuriMath**: a team of AI agents that turns classic theorems into machine-checked Lean 4 proofs. The proofs themselves live in [TuriMath/theorems](https://github.com/TuriMath/theorems); this repo is everything that runs the team.

**Motto:** nothing counts until Lean says so.

## Read in this order

| File | What it is |
|---|---|
| [`vision.md`](vision.md) | The spec: goal, principles, the ladder of theorems, the roadmap and its gates, KPIs, risks |
| [`COMPANY.md`](COMPANY.md) | The document every agent reads first, every session: who we are, the operator rule, current phase, what "done" means |
| [`docs/pipeline.md`](docs/pipeline.md) | How one theorem goes from a source quote to a verified proof: files, labels, stages, the CI gate |
| [`agents/_rules.md`](agents/_rules.md) | Rules every agent follows, who owns what, the handoff format |
| [`agents/`](agents) | One job description per agent; it is that agent's system prompt |
| [`ops/chat/`](ops/chat) | The harness: chat app, dispatcher, seat pool, playbooks ([README](ops/chat/README.md)) |

**How an agent starts:** its system prompt is `COMPANY.md` + `agents/_rules.md` + `agents/<role>.md`, in that order, plus the playbook for the task in hand.

## The team

| Agent | Role | File |
|---|---|---|
| Hilbert | Scout and planner | [`scout.md`](agents/scout.md) |
| Noether | Formalizer A | [`formalizer-a.md`](agents/formalizer-a.md) |
| Gauss | Formalizer B, blind to A | [`formalizer-b.md`](agents/formalizer-b.md) |
| Euler | Prover: A ↔ B, then the proof | [`prover.md`](agents/prover.md) |
| Gödel | Critic | [`critic.md`](agents/critic.md) |

## How a theorem moves

```
Hilbert opens issue ──► stage:formalize ──► stage:equiv ──► Gödel critique ──► stage:prove ──► verified
                         Noether ┐ blind      Euler            (review on        Euler
                         Gauss   ┘            A ↔ B PR          the A↔B PR)       proof PR
```

GitHub labels are the state. The dispatcher (`ops/chat/dispatcher.py`) reads them every 2 minutes, hands each agent its next task, moves a theorem to the next stage when its PR merges, and parks it when its attempt budget runs out. Every agent turn is logged with its Claude session id, so each theorem's full history can be traced.

## The operator

One human, Sai, sets **direction only**: which tier is next, which textbook, when to add agents, what goes public. Sai doesn't review statements or proofs; Lean, the blind formalizer pair and Gödel do. When the checks disagree, the theorem is parked with a reason rather than escalated.

## Status

**Phase 0 · Setup.** Gate 0 has passed: CI rejects a planted `sorry` and a planted extra axiom. Next: one Tier 0 theorem end to end, then Phase 1 calibration (15 theorems). The harness runs on its own VM, not yet deployed.

---

<sub>A <a href="https://turilabs.in">Turi Labs</a> factory. The harness is shared with <a href="https://github.com/TuriChips">TuriChips</a>.</sub>
