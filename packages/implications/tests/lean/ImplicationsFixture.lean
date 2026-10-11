/-! A small corpus, in Lean's core library only, for the pipeline's regression tests. `Good` and `Fine` are
structures, so nothing unfolds them and no arithmetic tactic proves them: a derivation has to go through the sources. -/

namespace Fx

structure Good (n : Nat) : Prop where
  big : 2 ≤ n

structure Fine (n : Nat) : Prop where
  pos : 0 < n

/-- First link of a chain. -/
theorem good_of_two (n : Nat) (h : 2 ≤ n) : Good n := ⟨h⟩

/-- Second link. -/
theorem fine_of_good (n : Nat) (h : Good n) : Fine n := ⟨by have := h.big; omega⟩

/-- The chain's end: what the two links give together. -/
theorem fine_of_two (n : Nat) (h : 2 ≤ n) : Fine n := fine_of_good n (good_of_two n h)

/-- An instance of `fine_of_good`. -/
theorem fine_of_good_five (h : Good 5) : Fine 5 := fine_of_good 5 h

/-- Another name for the chain's end. -/
theorem fine_of_two' : ∀ n, 2 ≤ n → Fine n := @fine_of_two

/-- A statement whose released proof goes through `fine_of_two`. -/
theorem fine_and_true (n : Nat) (h : 2 ≤ n) : Fine n ∧ True := ⟨fine_of_two n h, trivial⟩

/-- An equation and an order statement, for rewriting and bound transfer. -/
theorem double_eq (n : Nat) : n + n = 2 * n := by omega
theorem fine_double (n : Nat) (h : Fine (2 * n)) : Fine (n + n) := double_eq n ▸ h

/-- A bound, and a weaker one that follows from it by arithmetic. -/
def size (n : Nat) : Nat := n * n + 1
theorem size_ge (n : Nat) : n + 1 ≤ size n := by unfold size; cases n <;> simp [Nat.mul_succ] <;> omega
theorem size_pos (n : Nat) : 1 ≤ size n := by unfold size; omega

/-- The same existence, its parts in the other order: the witness carries over. -/
theorem exists_fine : ∃ n, Fine n ∧ 2 ≤ n := ⟨2, ⟨by decide⟩, by decide⟩
theorem exists_big_fine : ∃ n, 2 ≤ n ∧ Fine n := ⟨2, by decide, ⟨by decide⟩⟩

/-- Nothing derives this within the rules: no source says anything about `Fine 0`. -/
theorem not_fine_zero : ¬ Fine 0 := fun h => by have := h.pos; omega

/-- `fine_of_two` stated through a definition, as challenge files state their main claims. -/
def FineFromTwo : Prop := ∀ n, 2 ≤ n → Fine n
theorem fine_from_two : FineFromTwo := @fine_of_two

end Fx
