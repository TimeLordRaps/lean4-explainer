theorem and_swap' (p q : Prop) (hp : p) (hq : q) : q ∧ p := by
  constructor
  · exact hq
  · exact hp

theorem add_zero_comm (n : Nat) : 0 + n = n + 0 := by
  induction n with
  | zero => rfl
  | succ k ih =>
    rw [Nat.add_zero] at ih ⊢
    omega

theorem imp_chain (p q r : Prop) : (p → q) → (q → r) → p → r := by
  intro hpq hqr hp
  apply hqr
  exact hpq hp

theorem or_comm' (p q : Prop) : p ∨ q → q ∨ p := by
  intro h
  cases h with
  | inl hp => exact Or.inr hp
  | inr hq => exact Or.inl hq

theorem has_step (a b : Nat) (h : a ≤ b) : a < b + 1 := by
  have h2 : b < b + 1 := Nat.lt_succ_self b
  exact Nat.lt_of_le_of_lt h h2
