def double (n : Nat) : Nat := n + n

theorem double_two : double 2 = 4 := rfl

theorem atlas_true_left : True → True := fun h => h

theorem atlas_true_right : True → True := fun h => h

theorem atlas_requires_true (h : True) : True := h
