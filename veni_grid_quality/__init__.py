"""Q1 explicit, solver-independent candidate scoring. No optimiser or publication."""
from .models import QualityPolicy, QualityResult, Comparison
from .evaluate import score, compare, digest
__all__ = ['QualityPolicy','QualityResult','Comparison','score','compare','digest']
