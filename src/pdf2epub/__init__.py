"""pdf2epub: convert PDF books, born-digital or scanned, into reflowable EPUB 3 books.

The Python API below (``plan_batch``, ``run_batch`` and their types) is documented but
provisional: it may change in any 0.x release. The stable contract for front ends is the
``--json`` wire protocol of the ``pdf2epub`` command.
"""

from pdf2epub.batch import BatchPlan, InputSpec, plan_batch, run_batch
from pdf2epub.cancel import CancelToken
from pdf2epub.conversion import PlannedConversion
from pdf2epub.events import Event, EventSink
from pdf2epub.issues import Issue, IssueCode, Outcome, Severity
from pdf2epub.options import BatchOptions, ConversionOptions, DiscoveryOptions, OcrOptions
from pdf2epub.passwords import Candidate, PasswordProvider, Secret
from pdf2epub.results import BatchReport, ConversionResult, OcrSummary, Totals
from pdf2epub.version import TOOL_VERSION

__version__ = TOOL_VERSION

__all__ = [
    "BatchOptions",
    "BatchPlan",
    "BatchReport",
    "CancelToken",
    "Candidate",
    "ConversionOptions",
    "ConversionResult",
    "DiscoveryOptions",
    "Event",
    "EventSink",
    "InputSpec",
    "Issue",
    "IssueCode",
    "OcrOptions",
    "OcrSummary",
    "Outcome",
    "PasswordProvider",
    "PlannedConversion",
    "Secret",
    "Severity",
    "Totals",
    "__version__",
    "plan_batch",
    "run_batch",
]
