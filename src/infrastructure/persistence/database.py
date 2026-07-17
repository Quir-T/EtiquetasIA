"""Builds database engines and health-checks the PostgreSQL connection from settings."""

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from src.config.settings import Settings


@dataclass(slots=True)
class DatabaseClient:
    settings: Settings

    def build_dsn(self) -> str:
        parsed = urlparse(self.settings.database_dsn)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))

        if self.settings.db_ssl_mode and self.settings.db_ssl_mode != "disable":
            query["sslmode"] = self.settings.db_ssl_mode
            if self.settings.db_ssl_ca:
                query["sslrootcert"] = self.settings.db_ssl_ca
            if self.settings.db_ssl_cert:
                query["sslcert"] = self.settings.db_ssl_cert
            if self.settings.db_ssl_key:
                query["sslkey"] = self.settings.db_ssl_key

        return urlunparse(parsed._replace(query=urlencode(query)))

    def create_engine(self) -> Engine:
        return create_engine(self.build_dsn(), pool_pre_ping=True, future=True)

    def health_check(self) -> bool:
        engine = self.create_engine()
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
