"""
Quick Capture Service for FinScope CORE.
Provides unified preview and commit pipelines with provenance tracking.
"""

from typing import Dict, Any, Optional
from app.backend.capture.models import QuickCapturePreviewResponse
from app.backend.capture.parser import parse_quick_capture
from app.backend.capture.enrichment import enrich_capture
from app.backend.repositories.transaction_repo import TransactionRepository

class QuickCaptureService:
    @staticmethod
    def preview(
        raw_text: str,
        default_account_id: Optional[int] = None,
        reference_date: Optional[str] = None
    ) -> QuickCapturePreviewResponse:
        """
        Parses text and enriches with category, account, and confidence.
        """
        parse_res = parse_quick_capture(raw_text, reference_date=reference_date)
        enrichment = enrich_capture(parse_res, default_account_id=default_account_id)

        val_msgs = list(parse_res.parse_errors) + list(enrichment.validation_errors)
        can_commit = len(val_msgs) == 0 and (parse_res.amount is not None and parse_res.amount > 0)

        if not enrichment.account_id and not any("account" in m.lower() for m in val_msgs):
            can_commit = False
            val_msgs.append("No active account available to assign transaction.")

        if enrichment.requires_settlement_resolution:
            can_commit = False
            val_msgs.append(f"Requires settlement amount in {enrichment.account_currency} for {enrichment.input_currency} purchase.")

        return QuickCapturePreviewResponse(
            parse=parse_res,
            enrichment=enrichment,
            can_commit=can_commit,
            validation_messages=val_msgs
        )

    @staticmethod
    def commit(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Persists a quick capture transaction into the ledger with full provenance and mandatory hash guard (P0-02, P0-03, P0-04).
        """
        import hmac
        from decimal import Decimal

        client_hash = payload.get("preview_hash")
        if not client_hash:
            raise ValueError("preview_hash is required.")

        raw_text = payload.get("raw_text", "").strip()
        default_account_id = payload.get("default_account_id") or payload.get("account_id")

        # Generate fresh parse and enrichment
        preview_res = QuickCaptureService.preview(raw_text, default_account_id=default_account_id)
        parse_res = preview_res.parse
        enrichment = preview_res.enrichment

        # If preview could not commit without explicit settlement
        has_explicit_settlement = payload.get("settlement_amount") is not None
        if not preview_res.can_commit:
            if enrichment.requires_settlement_resolution and has_explicit_settlement:
                # Allowed: client provided manual settlement resolution
                pass
            else:
                msg = preview_res.validation_messages[0] if preview_res.validation_messages else "Quick capture validation failed."
                raise ValueError(msg)

        # Enforce preview hash check using hmac.compare_digest
        if not hmac.compare_digest(str(client_hash), str(enrichment.preview_hash)):
            raise ValueError("Preview hash mismatch. Transaction context has changed.")

        # Guard against client-side tampering of verified preview semantics (P0-03)
        if payload.get("amount") is not None and parse_res.amount is not None:
            try:
                if Decimal(str(payload["amount"])).normalize() != Decimal(str(parse_res.amount)).normalize():
                    raise ValueError("Payload amount differs from verified preview. Generate a new preview hash before committing.")
            except Exception as e:
                if isinstance(e, ValueError):
                    raise
                raise ValueError("Invalid amount in commit payload.")

        if payload.get("category_id") is not None and payload.get("category_id") != enrichment.category_id:
            raise ValueError("Payload category differs from verified preview. Generate a new preview hash before committing.")

        # Persist server preview values directly
        final_amount = parse_res.amount
        if final_amount is None or final_amount <= 0:
            raise ValueError("Valid transaction amount is required.")

        final_account_id = enrichment.account_id
        if not final_account_id:
            raise ValueError("Account is required.")

        final_category_id = enrichment.category_id
        final_merchant = enrichment.canonical_merchant or "Quick Expense"
        final_date = parse_res.date_str
        final_type = parse_res.transaction_type
        final_essentiality = enrichment.essentiality

        # Multi-currency handling
        orig_currency = enrichment.input_currency or parse_res.currency or enrichment.account_currency
        settlement_amt = payload.get("settlement_amount")

        # Provenance is strictly preserved from verified preview (P0-04)
        category_source = enrichment.category_source
        category_confidence = enrichment.category_confidence
        essentiality_source = enrichment.essentiality_source
        essentiality_confidence = enrichment.essentiality_confidence

        needs_review = enrichment.needs_review
        review_reason = enrichment.review_reason

        tx_dict = {
            "account_id": final_account_id,
            "category_id": final_category_id,
            "amount": final_amount,
            "original_currency": orig_currency,
            "merchant_name": final_merchant,
            "raw_merchant_name": parse_res.merchant_raw or final_merchant,
            "transaction_type": final_type,
            "transaction_date": final_date,
            "essentiality": final_essentiality,
            "essentiality_source": essentiality_source,
            "essentiality_confidence": essentiality_confidence,
            "category_source": category_source,
            "category_confidence": category_confidence,
            "capture_method": "quick_capture",
            "parser_version": parse_res.parser_version,
            "needs_review": needs_review,
            "review_reason": review_reason,
            "note": payload.get("note", "")
        }
        if settlement_amt is not None:
            tx_dict["settlement_amount"] = settlement_amt

        tx_id = TransactionRepository.create(tx_dict)

        created_tx = TransactionRepository.get_by_id(tx_id)
        return {
            "success": True,
            "transaction_id": tx_id,
            "transaction": created_tx,
            "preview_hash": enrichment.preview_hash
        }
