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

        val_msgs = list(parse_res.parse_errors)
        can_commit = len(val_msgs) == 0 and (parse_res.amount is not None and parse_res.amount > 0)

        if not enrichment.account_id:
            can_commit = False
            val_msgs.append("No active account available to assign transaction.")

        return QuickCapturePreviewResponse(
            parse=parse_res,
            enrichment=enrichment,
            can_commit=can_commit,
            validation_messages=val_msgs
        )

    @staticmethod
    def commit(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Persists a quick capture transaction into the ledger with full provenance.
        """
        raw_text = payload.get("raw_text", "").strip()
        default_account_id = payload.get("account_id")

        # Generate fresh parse and enrichment
        preview_res = QuickCaptureService.preview(raw_text, default_account_id=default_account_id)
        parse_res = preview_res.parse
        enrichment = preview_res.enrichment

        # Allow user overrides from client payload
        final_amount = payload.get("amount") if payload.get("amount") is not None else parse_res.amount
        if final_amount is None or final_amount <= 0:
            raise ValueError("Valid transaction amount is required.")

        final_account_id = payload.get("account_id") or enrichment.account_id
        if not final_account_id:
            raise ValueError("Account is required.")

        final_category_id = payload.get("category_id") or enrichment.category_id
        final_merchant = payload.get("merchant_name") or enrichment.canonical_merchant or "Quick Expense"
        final_date = payload.get("transaction_date") or parse_res.date_str
        final_type = payload.get("transaction_type") or parse_res.transaction_type
        final_essentiality = payload.get("essentiality") or enrichment.essentiality

        # Determine if category was overridden by user
        category_source = "user" if payload.get("category_id") else enrichment.category_source
        category_confidence = 1.0 if category_source == "user" else enrichment.category_confidence
        essentiality_source = "user" if payload.get("essentiality") else enrichment.essentiality_source
        essentiality_confidence = 1.0 if essentiality_source == "user" else enrichment.essentiality_confidence

        needs_review = payload.get("needs_review")
        if needs_review is None:
            needs_review = enrichment.needs_review
        review_reason = payload.get("review_reason") or enrichment.review_reason

        tx_id = TransactionRepository.create({
            "account_id": final_account_id,
            "category_id": final_category_id,
            "amount": final_amount,
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
        })

        created_tx = TransactionRepository.get_by_id(tx_id)
        return {
            "success": True,
            "transaction_id": tx_id,
            "transaction": created_tx,
            "preview_hash": enrichment.preview_hash
        }
