import ImplicationsFixture
set_option autoImplicit false

/-- A valid theorem with the wrong type: `True`, not the contract. -/
theorem bridge_true (source1 : ∀ n : Nat, Fx.Good n → Fx.Fine n) : True := trivial

/-- An assumption the contract does not record (`3 ≤ n`). -/
theorem bridge_extra (source1 : ∀ n : Nat, 2 ≤ n → Fx.Good n) (source2 : ∀ n : Nat, Fx.Good n → Fx.Fine n) :
    ∀ (n : Nat) (h : 2 ≤ n) (hx : 3 ≤ n), Fx.Fine n :=
  fun n h _ => source2 n (source1 n h)

/-- Another domain: integers where the contract says natural numbers. -/
theorem bridge_domain (source1 : ∀ n : Nat, n + n = 2 * n) : ∀ n : Int, n * 0 = 0 :=
  fun n => by have := source1 0; simp

/-- Another quantifier order. -/
theorem bridge_order (source1 : ∀ n : Nat, n + n = 2 * n) : ∀ (m n : Nat), n ≤ n + m :=
  fun m n => by have := source1 n; omega

/-- Proved by `sorry`. -/
theorem bridge_sorry (source1 : ∀ n : Nat, Fx.Good n → Fx.Fine n) : Fx.Fine 5 := by
  have := source1
  sorry

axiom cheat : Fx.Fine 7

/-- Proved with an axiom of its own. -/
theorem bridge_axiom (source1 : ∀ n : Nat, Fx.Good n → Fx.Fine n) : Fx.Fine 7 := by
  have := source1
  exact cheat

/-- Uses the target itself. -/
theorem bridge_direct (source1 : ∀ n : Nat, Fx.Good n → Fx.Fine n) : ∀ (n : Nat) (h : 2 ≤ n), Fx.Fine n := by
  have := source1
  exact Fx.fine_of_two

/-- Uses the target through another name for it. -/
theorem bridge_alias (source1 : ∀ n : Nat, Fx.Good n → Fx.Fine n) : ∀ (n : Nat) (h : 2 ≤ n), Fx.Fine n := by
  have := source1
  exact Fx.fine_of_two'

/-- Names two sources, uses one. -/
theorem bridge_unused (source1 : ∀ n : Nat, 2 ≤ n → Fx.Good n) (source2 : ∀ n : Nat, Fx.Good n → Fx.Fine n) :
    ∀ (n : Nat) (h : Fx.Good n), Fx.Fine n :=
  fun n h => source2 n h

/-- A relation that does not use the contract. -/
theorem relation_ignores (contract : ∀ n : Nat, n + 1 ≤ Fx.size n) : ∀ n : Nat, 1 ≤ Fx.size n :=
  fun n => by unfold Fx.size; omega

/-- A bridge for the relation-ignores case: the contract holds (it is the source). -/
theorem bridge_bound_copy (source1 : ∀ n : Nat, n + 1 ≤ Fx.size n) : ∀ n : Nat, n + 1 ≤ Fx.size n := source1
