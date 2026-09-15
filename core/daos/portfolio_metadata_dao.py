import uuid

from core.database import db


class PortfolioMetadataDAO:
    """Owns stable metadata stored inside each portfolio database."""

    def initialize_tables(self, conn) -> None:
        """Create and initialize the single-row portfolio metadata table."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS portfolio_metadata (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                portfolio_id TEXT NOT NULL UNIQUE
            )
        """)
        conn.execute(
            "INSERT OR IGNORE INTO portfolio_metadata (id, portfolio_id) VALUES (1, ?)",
            (str(uuid.uuid4()),),
        )


db.register_schema(PortfolioMetadataDAO())
