# Theorem issue template

Hilbert opens one issue per theorem, in that theorem's own repo `TuriMath/<kebab-slug>` (made from `TuriMath/theorem-template`; see `agents/scout.md`).

**Title:** `Theorem: <common name>`
**Labels:** `theorem`, `tier:<n>`, `stage:formalize` (and `budget:<n>` only to override the defaults: equiv 4, prove 6)

**Body:**

```markdown
**Slug:** WilsonTheorem
**Tier:** 1 (calibration: in Mathlib as `ZMod.wilsons_lemma`)

### Source statement (quoted exactly)
> For a natural number n > 1, n is prime if and only if (n − 1)! ≡ −1 (mod n).

Reference: Hardy & Wright, *An Introduction to the Theory of Numbers*, 6th ed., Thm 80 / Wikipedia "Wilson's theorem".

### What Mathlib has
- `ZMod.wilsons_lemma : ((p - 1)! : ZMod p) = -1` for `[Fact p.Prime]` (one direction only).
- `Nat.prime_iff_fac_equiv_neg_one` (both directions).

### Notes for formalizers
Anything the quote leaves implicit (e.g. "natural number" means ℕ). Don't describe how to write the Lean.
```

The quote is the only thing the formalizers see of the source. If it's ambiguous, the theorem will be.
