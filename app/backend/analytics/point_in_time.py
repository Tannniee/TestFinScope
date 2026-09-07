"""
Point-in-Time Historical Replay Filtering for FinScope Analytics.
Ensures zero look-ahead bias during historical replay evaluations by filtering out
transactions created after the evaluation cutoff date/time.
"""

from typing import Tuple, List, Any, Optional


def pit_filter_sql(
    as_of_cutoff: Optional[str],
    table_alias: str = "t",
    is_replay: bool = False
) -> Tuple[str, List[Any]]:
    """
    Returns SQL fragment and parameters enforcing point-in-time isolation.
    When is_replay is True and as_of_cutoff is provided:
        AND ({table_alias}.created_at IS NULL OR datetime({table_alias}.created_at) <= datetime(?))
    """
    if not is_replay or not as_of_cutoff:
        return "", []

    cutoff_ts = f"{as_of_cutoff[:10]} 23:59:59"
    sql = f" AND ({table_alias}.created_at IS NULL OR datetime({table_alias}.created_at) <= datetime(?))"
    return sql, [cutoff_ts]
