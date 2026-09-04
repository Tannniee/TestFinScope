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

    def create_transaction(self, data: Dict[str, Any]) -> int:
        return TransactionRepository.create(data)

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

    def update_transaction(self, tx_id: int, data: Dict[str, Any]) -> bool:
        return TransactionRepository.update(tx_id, data)

    def delete_transaction(self, tx_id: int) -> bool:
        return TransactionRepository.delete(tx_id)

    def duplicate_transaction(self, tx_id: int) -> Optional[int]:
        return TransactionRepository.duplicate(tx_id)

    # --- Analytics & BI ---
    def get_month_summary(self, month: str, account_id: Optional[int] = None) -> Dict[str, Any]:
        return AnalyticsService.get_month_summary(month, account_id)

    def get_calendar_data(self, month: str, account_id: Optional[int] = None) -> Dict[str, Any]:
        return AnalyticsService.get_calendar_data(month, account_id)

    def get_analytics_deep_dive(self, month: str, account_id: Optional[int] = None) -> Dict[str, Any]:
        return AnalyticsService.get_analytics_deep_dive(month, account_id)

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
