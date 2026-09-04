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

    # --- Analytics & BI ---
    def get_month_summary(self, month: str, account_id: Optional[int] = None) -> Dict[str, Any]:
        return AnalyticsService.get_month_summary(month, account_id)

    def get_calendar_data(self, month: str, account_id: Optional[int] = None) -> Dict[str, Any]:
        return AnalyticsService.get_calendar_data(month, account_id)

    def get_analytics_deep_dive(self, month: str, account_id: Optional[int] = None) -> Dict[str, Any]:
        return AnalyticsService.get_analytics_deep_dive(month, account_id)

    def get_rolling_metrics(self, metric: str = "expense", category_id: Optional[int] = None, account_id: Optional[int] = None) -> Dict[str, Any]:
        return AnalyticsService.get_rolling_metrics(metric, category_id, account_id)

    def get_what_changed(self, current_month: str, comparison_month: Optional[str] = None, account_id: Optional[int] = None, max_day: Optional[int] = None) -> Dict[str, Any]:
        return AnalyticsService.get_what_changed(current_month, comparison_month, account_id, max_day)

    def get_spending_fingerprint(self, months_window: int = 6, account_id: Optional[int] = None) -> Dict[str, Any]:
        return AnalyticsService.get_spending_fingerprint(months_window, account_id)

    def get_anomalies(self, month: str, account_id: Optional[int] = None, k_range: float = 2.5) -> List[Dict[str, Any]]:
        return AnalyticsService.get_anomalies(month, account_id, k_range)

    def get_forecast(self, month: str, account_id: Optional[int] = None, as_of_date: Optional[str] = None) -> Dict[str, Any]:
        return AnalyticsService.get_forecast(month, account_id, as_of_date)

    def get_ranked_insights(self, month: str, account_id: Optional[int] = None, limit: int = 5) -> Dict[str, Any]:
        return AnalyticsService.get_ranked_insights(month, account_id, limit)

    def get_backtest_evaluation(self, account_id: Optional[int] = None) -> Dict[str, Any]:
        return AnalyticsService.get_backtest_evaluation(account_id)

    # --- Budgets ---
    def get_monthly_budget(self, month: str) -> Dict[str, Any]:
        return BudgetService.get_monthly_budget_status(month)

    def set_category_budget(self, category_id: int, month: str, amount: float) -> int:
        return BudgetRepository.set_budget(category_id, month, amount)

    # --- Backup & Storage ---
    def create_backup(self) -> Dict[str, Any]:
        return BackupService.create_backup()

    def list_backups(self) -> List[Dict[str, Any]]:
        return BackupService.list_backups()

    def restore_backup(self, filepath: str) -> Dict[str, Any]:
        return BackupService.restore_backup(filepath)

    def export_csv(self) -> str:
        return BackupService.export_csv()

    def get_storage_health(self) -> Dict[str, Any]:
        return BackupService.get_storage_health()

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
