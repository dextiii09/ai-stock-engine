import os
import time
import zipfile
import glob
from typing import Dict, Any, List


class AutomatedBackupEngine:
    """
    Automated Disaster Recovery Backup Engine.
    
    Creates timestamped zip snapshots of all critical ML models, trade journals,
    hyperparameter weights, and the SQLite trading ledger with 30-day rotation.
    """

    _instance = None

    def __init__(self, base_dir: str = None):
        if base_dir is None:
            # Anchor to backend/data/backups
            self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "backups"))
        else:
            self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    @classmethod
    def instance(cls) -> "AutomatedBackupEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_backup_targets(self) -> List[str]:
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        backend_data = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))

        potential_files = [
            os.path.join(backend_data, "trade_journal.json"),
            os.path.join(backend_data, "bot_state.json"),
            os.path.join(backend_data, "rl_state.json"),
            os.path.join(backend_data, "hyperparams.json"),
            os.path.join(backend_data, "performance_log.json"),
            os.path.join(backend_data, "backtest_leaderboard.json"),
            os.path.join(root_dir, "ai_stock.db"),
            os.path.join(root_dir, "journal.json"),
        ]
        return [f for f in potential_files if os.path.exists(f)]

    def create_backup(self, max_retention: int = 30) -> Dict[str, Any]:
        """Creates a timestamped compressed backup archive."""
        targets = self.get_backup_targets()
        if not targets:
            return {
                "success": False,
                "error": "No state or database files found to backup.",
                "files_count": 0
            }

        timestamp_str = time.strftime("%Y%m%d_%H%M%S")
        archive_name = f"ai_stock_backup_{timestamp_str}.zip"
        archive_path = os.path.join(self.base_dir, archive_name)

        try:
            with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for file_path in targets:
                    arcname = os.path.basename(file_path)
                    zipf.write(file_path, arcname=arcname)

            archive_size = os.path.getsize(archive_path)
            
            # Clean up old backups exceeding retention limit
            self._rotate_old_backups(max_retention)

            return {
                "success": True,
                "archive_name": archive_name,
                "archive_path": archive_path,
                "size_kb": round(archive_size / 1024, 2),
                "files_count": len(targets),
                "files_included": [os.path.basename(f) for f in targets],
                "time_str": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "files_count": len(targets)
            }

    def _rotate_old_backups(self, max_retention: int = 30):
        """Rotates out old backup archives keeping the most recent max_retention files."""
        pattern = os.path.join(self.base_dir, "ai_stock_backup_*.zip")
        archives = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
        if len(archives) > max_retention:
            for old_archive in archives[max_retention:]:
                try:
                    os.remove(old_archive)
                except Exception:
                    pass


if __name__ == "__main__":
    engine = AutomatedBackupEngine()
    res = engine.create_backup()
    print("Backup Result:", res)
