/-! Demo declarations for lean4-explainer. Source-level only; Lean is not run. -/

namespace Demo

/-- The empty set has no members. -/
-- L4DEL: title: Empty set has no members
-- L4DEL: intuition: Nothing is a member of the empty set, so membership is always false.
-- L4DEL: term: empty set = a set with no members
theorem empty_set_has_no_members (x : Nat) : x ∈ (∅ : Set Nat) → False := by
  intro h
  exact h

-- L4DEL: title: Nonempty sets are not empty
-- L4DEL: prereq: Demo.empty_set_has_no_members
-- L4DEL: step: Assume a set has an element.
-- L4DEL: step: The empty set rule then does not apply to it.
-- L4DEL: see: Demo.Missing.lemma
theorem nonempty_is_not_empty (s : Set Nat) (x : Nat) (hx : x ∈ s) : s ≠ ∅ := by
  sorry

/-- Refers to the rule above in its statement. -/
theorem uses_empty (h : empty_set_has_no_members) : True := trivial

theorem plain_fact : True := trivial

end Demo
