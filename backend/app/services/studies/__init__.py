"""Active learn studies: numeric analogies over cached bars (no LLM in the gate).

The 7B may *propose* StudyQuery entries (JSON schema, extra keys rejected); all
probabilities are computed from OHLC bars only.
"""

from app.services.studies.models import StudyQuery, StudyResult, StudySnapshot

__all__ = ["StudyQuery", "StudyResult", "StudySnapshot"]
