import ImplicationsFixture
set_option autoImplicit false

/-- The two links give the chain's end: each source is a hypothesis. -/
theorem bridge_good (source1 : ∀ n : Nat, 2 ≤ n → Fx.Good n) (source2 : ∀ n : Nat, Fx.Good n → Fx.Fine n) :
    ∀ (n : Nat) (h : 2 ≤ n), Fx.Fine n :=
  fun n h => source2 n (source1 n h)

/-- A stronger bound than `Fx.size_pos`, from `Fx.size_ge`. -/
theorem bridge_bound (source1 : ∀ n : Nat, n + 1 ≤ Fx.size n) : ∀ n : Nat, n + 1 ≤ Fx.size n := source1

/-- The stronger bound gives `Fx.size_pos`'s statement. -/
theorem relation_bound (contract : ∀ n : Nat, n + 1 ≤ Fx.size n) : ∀ n : Nat, 1 ≤ Fx.size n :=
  fun n => by have := contract n; omega
