"""C2: explicit option-plan to real teaching-staff / room / lesson placement feasibility."""
from .c2 import (C2Target, C2Input, C2FamilyTeaching, C2BlockWindow, C2Result,
                 build_c2_problem, solve_c2)
__all__ = ["C2Target", "C2Input", "C2FamilyTeaching", "C2BlockWindow",
           "C2Result", "build_c2_problem", "solve_c2"]
