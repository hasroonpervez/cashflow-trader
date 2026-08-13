"""Paper execution: ledger + Signal -> gate -> kelly -> venue pipeline."""
from .paper_ledger import PaperLedger
from .pipeline import PaperPipeline, PipelineResult

__all__ = ["PaperLedger", "PaperPipeline", "PipelineResult"]
