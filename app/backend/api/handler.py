import logging
from typing import Dict, Any, List, Optional
from app.backend.config import open_data_folder
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.category_repo import CategoryRepository
from app.backend.repositories.transaction_repo import TransactionRepository
from app.backend.repositories.budget_repo import BudgetRepository
from app.backend.services.analytics_service import AnalyticsService
from app.backend.services.budget_service import BudgetService
from app.backend.services.backup_service import BackupService
from app.backend.services.sample_data import seed_sample_data
from app.backend.services.settings_service import SettingsService
from app.backend.services.merchant_service import MerchantService

logger = logging.getLogger(__name__)

class ApiHandler:
    """Unified API dispatcher exposed to both PyWebView and HTTP Server."""

    # --- Accounts ---
    def get_accounts(self, include_archived: bool = False) -> List[Dict[str, Any]]:
        return AccountRepository.get_all(include_archived)

    def create_account(self, name: str, account_type: str = "Everyday", institution: str = "", opening_balance: float = 0.0, currency: str = "USD") -> int:
        return AccountRepository.create(name, account_type, institution, opening_balance, currency)

    def update_account(self, account_id: int, **fields) -> bool:
        return AccountRepository.update(account_id, **fields)

    def delete_account(self, account_id: int) -> bool:
        return AccountRepository.delete(account_id)

    # --- Categories ---
    def get_categories(self, include_archived: bool = False, cat_type: Optional[str] = None) -> List[Dict[str, Any]]:
        return CategoryRepository.get_all(include_archived, cat_type)

    def create_category(self, name: str, cat_type: str = "expense", icon: str = "tag", color: str = "#5B8CFF", parent_category_id: Optional[int] = None) -> int:
        return CategoryRepository.create(name, cat_type, icon, color, parent_category_id)

    def update_category(self, category_id: int, **fields) -> bool:
        return CategoryRepository.update(category_id, **fields)

    def delete_category(self, category_id: int) -> bool:
        return CategoryRepository.delete(category_id)

    # --- Transactions ---
    def get_transactions(
        self,
        month: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        account_id: Optional[int] = None,
        category_id: Optional[int] = None,
        transaction_type: Optional[str] = None,
        essentiality: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> Dict[str, Any]:
        return TransactionRepository.get_all(
            month=month,
            start_date=start_date,
            end_date=end_date,
            account_id=account_id,
            category_id=category_id,
            transaction_type=transaction_type,
            essentiality=essentiality,
            search=search,
            limit=limit,
            offset=offset
        )

    def get_transaction(self, tx_id: int) -> Optional[Dict[str, Any]]:
        return TransactionRepository.get_by_id(tx_id)

    def create_transaction(self, data: Optional[Dict[str, Any]] = None, **kwargs) -> int:
        payload = data if isinstance(data, dict) and data else kwargs
        return TransactionRepository.create(payload)

    def create_transfer(
        self,
        from_account_id: int,
        to_account_id: int,
        amount: float,
        transaction_date: str,
        transaction_time: str = "12:00",
        description: str = "Account Transfer",
        note: str = ""
    ) -> Dict[str, Any]:
        return TransactionRepository.create_transfer(
            from_account_id=from_account_id,
            to_account_id=to_account_id,
            amount=amount,
            transaction_date=transaction_date,
            transaction_time=transaction_time,
            description=description,
            note=note
        )

    def create_refund(
        self,
        original_tx_id: Optional[int] = None,
        original_transaction_id: Optional[int] = None,
        amount: float = 0.0,
        transaction_date: str = "",
        account_id: Optional[int] = None,
        note: str = "",
        **kwargs
    ) -> int:
        orig_id = original_tx_id or original_transaction_id or kwargs.get("original_tx_id")
        if not orig_id:
            raise ValueError("original_tx_id or original_transaction_id is required for a linked refund.")
        return TransactionRepository.create_refund(orig_id, amount, transaction_date, account_id, note)

    def update_transfer(
        self,
        transfer_group_id: Optional[str] = None,
        tx_id: Optional[int] = None,
        from_account_id: Optional[int] = None,
        to_account_id: Optional[int] = None,
        amount: Optional[float] = None,
        transaction_date: Optional[str] = None,
        transaction_time: Optional[str] = None,
        description: Optional[str] = None,
        note: Optional[str] = None,
        **kwargs
    ) -> bool:
        from app.backend.services.transfer_service import TransferService
        return TransferService.update_transfer(
            transfer_group_id=transfer_group_id or kwargs.get("transfer_group_id"),
            tx_id=tx_id or kwargs.get("tx_id"),
            from_account_id=from_account_id or kwargs.get("from_account_id"),
            to_account_id=to_account_id or kwargs.get("to_account_id"),
            amount=amount if amount is not None else kwargs.get("amount"),
            transaction_date=transaction_date or kwargs.get("transaction_date"),
            transaction_time=transaction_time or kwargs.get("transaction_time"),
            description=description or kwargs.get("description"),
            note=note if note is not None else kwargs.get("note")
        )

    def update_refund(
        self,
        tx_id: int,
        amount: Optional[float] = None,
        transaction_date: Optional[str] = None,
        note: Optional[str] = None,
        account_id: Optional[int] = None,
        **kwargs
    ) -> bool:
        return TransactionRepository.update_refund(
            tx_id=tx_id,
            amount=amount if amount is not None else kwargs.get("amount"),
            transaction_date=transaction_date or kwargs.get("transaction_date"),
            note=note if note is not None else kwargs.get("note"),
            account_id=account_id or kwargs.get("account_id")
        )

    def update_transaction(self, tx_id: int, data: Optional[Dict[str, Any]] = None, **kwargs) -> bool:
        payload = data if isinstance(data, dict) and data else kwargs
        return TransactionRepository.update(tx_id, payload)

    def delete_transaction(self, tx_id: int) -> bool:
        return TransactionRepository.delete(tx_id)

    def undo_delete_transaction(self, tx_id: int) -> bool:
        return TransactionRepository.undo_delete(tx_id)

    def duplicate_transaction(self, tx_id: int) -> Optional[int]:
        return TransactionRepository.duplicate(tx_id)

    # --- Merchant Intelligence & Suggestions ---
    def get_merchant_suggestions(self, query: str, limit: int = 6) -> List[Dict[str, Any]]:
        return MerchantService.suggest_merchants(query, limit)

    def get_recent_payees(self, limit: int = 5) -> List[Dict[str, Any]]:
        return MerchantService.get_recent_payees(limit)

    # --- Review Queue & Data Quality ---
    def get_review_queue(self, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        return TransactionRepository.get_review_queue(limit, offset)

    def resolve_review(self, tx_id: int, category_id: int, merchant_name: Optional[str] = None) -> bool:
        return TransactionRepository.resolve_review(tx_id, category_id, merchant_name)

    # --- Analytics & BI V2 ---
    def get_analytics_context(
        self,
        month: Optional[str] = None,
        account_id: Optional[int] = None,
        category_id: Optional[int] = None,
        merchant_id: Optional[int] = None,
        comparison_mode: Optional[str] = None
    ) -> Dict[str, Any]:
        return AnalyticsService.get_analytics_context(month, account_id, category_id, merchant_id, comparison_mode)

    def get_month_summary(self, month: str, account_id: Optional[int] = None) -> Dict[str, Any]:
        return AnalyticsService.get_month_summary(month, account_id)

    def get_calendar_data(self, month: str, account_id: Optional[int] = None) -> Dict[str, Any]:
        return AnalyticsService.get_calendar_data(month, account_id)

    def get_analytics_deep_dive(self, month: str, account_id: Optional[int] = None) -> Dict[str, Any]:
        return AnalyticsService.get_analytics_deep_dive(month, account_id)

    def get_rolling_metrics(
        self,
        metric: str = "expense",
        category_id: Optional[int] = None,
        account_id: Optional[int] = None,
        as_of_month: Optional[str] = None
    ) -> Dict[str, Any]:
        return AnalyticsService.get_rolling_metrics(metric, category_id, account_id, as_of_month)

    def get_what_changed(
        self,
        current_month: str,
        comparison_month: Optional[str] = None,
        account_id: Optional[int] = None,
        max_day: Optional[int] = None,
        comparison_mode: Optional[str] = None
    ) -> Dict[str, Any]:
        return AnalyticsService.get_what_changed(current_month, comparison_month, account_id, max_day, comparison_mode)

    def get_merchant_drilldown(
        self,
        category_id: int,
        current_month: Optional[str] = None,
        account_id: Optional[int] = None,
        comparison_mode: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        return AnalyticsService.get_merchant_drilldown(category_id, current_month, account_id, comparison_mode)

    def get_spending_fingerprint(
        self,
        months_window: int = 6,
        account_id: Optional[int] = None,
        as_of_month: Optional[str] = None
    ) -> Dict[str, Any]:
        return AnalyticsService.get_spending_fingerprint(months_window, account_id, as_of_month)

    def get_anomalies(self, month: str, account_id: Optional[int] = None, k_range: float = 2.5) -> List[Dict[str, Any]]:
        return AnalyticsService.get_anomalies(month, account_id, k_range)

    def get_normal_ranges(self, account_id: Optional[int] = None, as_of_date: Optional[str] = None) -> List[Dict[str, Any]]:
        return AnalyticsService.get_normal_ranges(account_id, as_of_date)

    def get_forecast(self, month: str, account_id: Optional[int] = None, as_of_date: Optional[str] = None) -> Dict[str, Any]:
        return AnalyticsService.get_forecast(month, account_id, as_of_date)

    def get_ranked_insights(self, month: str, account_id: Optional[int] = None, limit: int = 5) -> Dict[str, Any]:
        return AnalyticsService.get_ranked_insights(month, account_id, limit)

    def dismiss_insight(self, insight_key: str) -> bool:
        return AnalyticsService.dismiss_insight(insight_key)

    def get_backtest_evaluation(self, account_id: Optional[int] = None) -> Dict[str, Any]:
        return AnalyticsService.get_backtest_evaluation(account_id)

    # --- Budgets ---
    def get_monthly_budget(self, month: str, account_id: Optional[int] = None, **kwargs) -> Dict[str, Any]:
        acc_id = account_id if account_id is not None else kwargs.get("account_id")
        return BudgetService.get_monthly_budget_status(month, account_id=acc_id)

    def set_category_budget(self, category_id: int, month: str, amount: float) -> int:
        return BudgetRepository.set_budget(category_id, month, amount)

    # --- Backup & Storage ---
    def create_backup(self) -> Dict[str, Any]:
        return BackupService.create_backup()

    def list_backups(self) -> List[Dict[str, Any]]:
        return BackupService.list_backups()

    def restore_backup(self, filepath: str) -> Dict[str, Any]:
        return BackupService.restore_backup(filepath)

    def export_csv(
        self,
        month: Optional[str] = None,
        account_id: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        **kwargs
    ) -> str:
        return BackupService.export_csv(
            month=month or kwargs.get("month"),
            account_id=account_id if account_id is not None else kwargs.get("account_id"),
            start_date=start_date or kwargs.get("start_date"),
            end_date=end_date or kwargs.get("end_date")
        )

    def get_storage_health(self) -> Dict[str, Any]:
        return BackupService.get_storage_health()

    # --- Bank CSV Import Wizard ---
    def preview_csv_import(
        self,
        csv_content: str,
        mapping: Optional[Dict[str, str]] = None,
        account_id: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        from app.backend.services.import_service import ImportService
        return ImportService.preview_csv(
            csv_content=csv_content,
            mapping=mapping or kwargs.get("mapping"),
            account_id=account_id or kwargs.get("account_id")
        )

    def commit_csv_import(
        self,
        csv_content: str,
        mapping: Optional[Dict[str, str]] = None,
        account_id: Optional[int] = None,
        deduplicate: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        from app.backend.services.import_service import ImportService
        acc_id = account_id or kwargs.get("account_id")
        if not acc_id:
            raise ValueError("account_id is required to import bank transactions.")
        return ImportService.commit_import(
            csv_content=csv_content,
            mapping=mapping or kwargs.get("mapping", {}),
            account_id=acc_id,
            deduplicate=deduplicate if deduplicate is not None else kwargs.get("deduplicate", True)
        )

    # --- Recurring Rules & Bills ---
    def get_recurring_rules(self, account_id: Optional[int] = None, active_only: bool = False, **kwargs) -> List[Dict[str, Any]]:
        from app.backend.services.recurring_service import RecurringService
        return RecurringService.get_all(
            account_id=account_id or kwargs.get("account_id"),
            active_only=active_only or kwargs.get("active_only", False)
        )

    def create_recurring_rule(
        self,
        name: str,
        amount: float,
        transaction_type: str = "expense",
        category_id: Optional[int] = None,
        account_id: Optional[int] = None,
        frequency: str = "monthly",
        next_due_date: Optional[str] = None,
        **kwargs
    ) -> int:
        from app.backend.services.recurring_service import RecurringService
        return RecurringService.create_rule(
            name=name,
            amount=amount,
            transaction_type=transaction_type,
            category_id=category_id,
            account_id=account_id,
            frequency=frequency,
            next_due_date=next_due_date
        )

    def update_recurring_rule(self, rule_id: int, **fields) -> bool:
        from app.backend.services.recurring_service import RecurringService
        return RecurringService.update_rule(rule_id, **fields)

    def delete_recurring_rule(self, rule_id: int, **kwargs) -> bool:
        from app.backend.services.recurring_service import RecurringService
        r_id = rule_id or kwargs.get("rule_id")
        return RecurringService.delete_rule(r_id)

    def get_upcoming_bills(self, month: str, account_id: Optional[int] = None, **kwargs) -> List[Dict[str, Any]]:
        from app.backend.services.recurring_service import RecurringService
        return RecurringService.get_upcoming_bills_for_month(
            month=month,
            account_id=account_id or kwargs.get("account_id")
        )

    def seed_demo_data(self, clear_existing: bool = False) -> Dict[str, Any]:
        return seed_sample_data(clear_existing=clear_existing)

    def open_data_dir(self) -> str:
        return open_data_folder()

    # --- Settings ---
    def get_settings(self) -> Dict[str, str]:
        return SettingsService.get_all_settings()

    def update_settings(self, settings: Dict[str, str]) -> bool:
        SettingsService.update_settings(settings)
        return True
