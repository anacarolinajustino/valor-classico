"""
Backup do Postgres local do Valor Clássico.

Disparado automaticamente pelo app.py após cada coleta bem-sucedida
(admin_coletar). Também pode ser executado manualmente:
    python -m src.pipeline.backup
"""
from __future__ import annotations

import logging
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent
BACKUP_DIR = PROJECT_ROOT / "backups"
PG_DUMP = r"C:\Program Files\PostgreSQL\18\bin\pg_dump.exe"
RETENCAO_DIAS = 30

DB_HOST = "localhost"
DB_PORT = "5432"
DB_NAME = "valorclassicodb"
DB_USER = "valorclassico_local"
DB_PASSWORD = "valorclassico_local"


def fazer_backup() -> Optional[Path]:
    """Gera um dump timestampado do banco local em backups/ e limpa backups antigos."""
    BACKUP_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = BACKUP_DIR / f"valorclassico_{timestamp}.sql"

    env = {**os.environ, "PGPASSWORD": DB_PASSWORD}
    try:
        subprocess.run(
            [
                PG_DUMP, "-h", DB_HOST, "-p", DB_PORT, "-U", DB_USER, "-d", DB_NAME,
                "--no-owner", "--no-privileges", "-f", str(out_file),
            ],
            env=env, check=True, capture_output=True, text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        logger.error("[backup] falha ao gerar backup: %s", exc)
        return None

    logger.info("[backup] backup criado: %s (%d bytes)", out_file, out_file.stat().st_size)
    _limpar_backups_antigos()
    return out_file


def _limpar_backups_antigos() -> None:
    limite = datetime.now() - timedelta(days=RETENCAO_DIAS)
    for f in BACKUP_DIR.glob("valorclassico_*.sql"):
        if datetime.fromtimestamp(f.stat().st_mtime) < limite:
            f.unlink()
            logger.info("[backup] removido backup antigo: %s", f.name)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    resultado = fazer_backup()
    if resultado is None:
        raise SystemExit(1)
