import ComparatorChallenges.DirichletSevenEighths
import ComparatorChallenges.SiegelZeros

/-!
# Seven-eighths nonvanishing gives an explicit real-zero gap

A bridge for the curated edge `seven-eighths-gives-an-explicit-real-zero-gap` (implications.toml). It is checked
against the statements openai/math's comparator holds the solutions to (ComparatorChallenges/), which import Mathlib
at the commit openai/math pins. The source is a hypothesis: nothing here uses its released proof.

`seven_eighths_gap` is the edge's contract: from the source, every real zero `β < 1` of a Dirichlet L-function of
modulus `q ≥ 3` satisfies `log 3 / 8 ≤ (1 - β) log q`.

`seven_eighths_gap_gives_absolute_gap` is the relation to the target: the contract gives
`OAI.SiegelZeros.WeightedTorusJets.exists_absolute_real_zero_gap`'s statement, with `c = log 3 / 8`.
-/

set_option autoImplicit false

theorem seven_eighths_gap
    (source1 : ∀ {q : ℕ} [NeZero q] (χ : DirichletCharacter ℂ q) {s : ℂ},
      (7 / 8 : ℝ) < s.re → ¬ (χ = 1 ∧ s = 1) → DirichletCharacter.LFunction χ s ≠ 0) :
    ∀ (q : ℕ) [NeZero q] (hq : 3 ≤ q) (χ : DirichletCharacter ℂ q) (β : ℝ) (hβ : β < 1)
      (hzero : χ.LFunction (β : ℂ) = 0), Real.log 3 / 8 ≤ (1 - β) * Real.log (q : ℝ) := by
  intro q _ hq χ β hβ hzero
  -- the zero is at most 7/8: past it, the source says the L-function does not vanish (s = β ≠ 1, so no pole)
  have hβ78 : β ≤ 7 / 8 := by
    by_contra h
    have hre : (7 / 8 : ℝ) < (β : ℂ).re := by simpa using lt_of_not_ge h
    have hpole : ¬ (χ = 1 ∧ (β : ℂ) = 1) := by
      rintro ⟨-, h1⟩
      have : β = 1 := by exact_mod_cast h1
      exact absurd this (ne_of_lt hβ)
    exact source1 χ hre hpole hzero
  have hlog3 : 0 < Real.log 3 := Real.log_pos (by norm_num)
  have hlogq : Real.log 3 ≤ Real.log (q : ℝ) := Real.log_le_log (by norm_num) (by exact_mod_cast hq)
  nlinarith

theorem seven_eighths_gap_gives_absolute_gap
    (contract : ∀ (q : ℕ) [NeZero q] (hq : 3 ≤ q) (χ : DirichletCharacter ℂ q) (β : ℝ) (hβ : β < 1)
      (hzero : χ.LFunction (β : ℂ) = 0), Real.log 3 / 8 ≤ (1 - β) * Real.log (q : ℝ)) :
    ∃ c : ℝ, 0 < c ∧
      ∀ (q : ℕ) [NeZero q], 3 ≤ q →
      ∀ χ : DirichletCharacter ℂ q,
        χ.IsPrimitive → χ ≠ 1 → (∀ a : ZMod q, (χ a).im = 0) →
        ∀ β : ℝ, 0 < β → β < 1 → χ.LFunction (β : ℂ) = 0 →
          c ≤ (1 - β) * Real.log (q : ℝ) :=
  ⟨Real.log 3 / 8, div_pos (Real.log_pos (by norm_num)) (by norm_num),
    fun q _ hq χ _ _ _ β _ hβ hzero => contract q hq χ β hβ hzero⟩
