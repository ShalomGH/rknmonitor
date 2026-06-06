import csv
import logging
from rknmon.db import execute

logger = logging.getLogger(__name__)

async def ingest_csv(path: str, source: str = "csv", category: str | None = None) -> int:
    """Ingest targets from a CSV with columns: url,domain[,ip][,category]"""
    inserted = 0
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            url = row.get("url", "").strip()
            domain = row.get("domain", "").strip()
            if not url and not domain:
                continue
            if not url:
                url = f"https://{domain}"
            if not domain:
                domain = url.replace("https://", "").replace("http://", "").split("/")[0]
            ip = row.get("ip", None)
            cat = row.get("category", category)
            try:
                await execute(
                    """
                    INSERT INTO targets (url, domain, ip, category, source)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (domain) DO UPDATE SET
                        url = EXCLUDED.url,
                        ip = COALESCE(EXCLUDED.ip, targets.ip),
                        category = COALESCE(EXCLUDED.category, targets.category),
                        updated_at = now()
                    """,
                    url, domain, ip, cat, source
                )
                inserted += 1
            except Exception as e:
                logger.warning(f"Failed to ingest {domain}: {e}")
    logger.info(f"Ingested {inserted} targets from {path}")
    return inserted
