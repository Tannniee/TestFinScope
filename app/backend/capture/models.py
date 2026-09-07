from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any

@dataclass
class QuickCaptureParseResult:
    raw_text: str
    amount: Optional[float] = None
    currency: Optional[str] = None
    transaction_type: str = "expense"
    merchant_raw: Optional[str] = None
    account_hint: Optional[str] = None
    category_hint: Optional[str] = None
    date_str: Optional[str] = None
    parser_version: str = "qc_v1"
    parse_errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

@dataclass
class CaptureEnrichment:
    canonical_merchant: Optional[str] = None
    account_id: Optional[int] = None
    account_name: Optional[str] = None
    account_currency: Optional[str] = None
    input_currency: Optional[str] = None
    settlement_amount_minor: Optional[int] = None
    requires_settlement_resolution: bool = False
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    category_source: str = "user"  # explicit, rule, merchant_history, fallback
    category_confidence: float = 1.0
    essentiality: str = "discretionary"  # essential, discretionary, unknown
    essentiality_source: str = "user"  # explicit, rule, merchant_history, fallback
    essentiality_confidence: float = 1.0
    needs_review: bool = False
    review_reason: Optional[str] = None
    preview_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

@dataclass
class QuickCapturePreviewResponse:
    parse: QuickCaptureParseResult
    enrichment: CaptureEnrichment
    can_commit: bool = False
    validation_messages: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parse": self.parse.to_dict(),
            "enrichment": self.enrichment.to_dict(),
            "can_commit": self.can_commit,
            "validation_messages": self.validation_messages
        }
