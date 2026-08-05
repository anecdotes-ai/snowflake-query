import asyncio

import snowflake.connector

from cryptography.hazmat.primitives import serialization
from snowflake.connector.constants import QueryStatus

class SnowflakeConnector:
    def __init__(self, account_name: str, username: str, password: str = None, private_key: str = None):
        """
        Authenticates by key-pair when private_key is given, by password otherwise.

        Snowflake removes password authentication for service users around October 2026, so the key
        path is the one to prefer. Password stays supported so callers pinned to an older tag are
        unaffected by upgrading, and so a caller can migrate its own secret independently.

        Args:
            private_key: unencrypted PKCS#8 PEM. Accepts real newlines or literal `\\n` escapes —
                GitHub secrets are routinely stored single-line, and both spellings reach here.
        """
        if not private_key and not password:
            raise ValueError(
                "no credentials supplied: set snowflake_private_key (preferred) or snowflake_password"
            )
        self.account_name = account_name
        self.username = username
        self.password = password
        self.private_key_der = self._to_der(private_key) if private_key else None

    @staticmethod
    def _to_der(private_key: str) -> bytes:
        """
        The connector takes DER, not PEM. A parse failure is re-raised naming the cause: an
        unadorned cryptography traceback reads as a library bug rather than a malformed secret.
        """
        pem = private_key.strip().replace("\\n", "\n")
        try:
            key = serialization.load_pem_private_key(pem.encode(), password=None)
        except Exception as exc:
            raise ValueError(
                "snowflake_private_key is not a readable unencrypted PKCS#8 PEM "
                f"({type(exc).__name__}). Expected the contents of an rsa_key.p8."
            ) from exc
        return key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

    def __enter__(self):
        if self.private_key_der:
            self.con = snowflake.connector.connect(
                user=self.username,
                private_key=self.private_key_der,
                account=self.account_name)
        else:
            self.con = snowflake.connector.connect(
                user=self.username,
                password=self.password,
                account=self.account_name)

        return self

    def __exit__(self, *exc):
        self.con.close()

    def set_db_warehouse(self, warehouse: str):
        results = self.query(f'USE WAREHOUSE {warehouse}')
        return asyncio.run(results.fetch_results())
    
    def set_user_role(self, role: str):
        results = self.query(f'USE ROLE {role}')
        return asyncio.run(results.fetch_results())

    def query(self, query_str: str):
        cursor = self.con.cursor()
        cursor.execute_async(query_str)

        return QueryResult(self.con, cursor.sfqid)

class QueryResult:
    def __init__(self, con: SnowflakeConnector, query_id: str):
        self.query_id = query_id
        self.con = con
        self.cursor = con.cursor()

    def is_query_done_successfully(self):
        return self.con.get_query_status(self.query_id) == QueryStatus.SUCCESS
    
    def is_query_running(self):
        return (self.con.get_query_status(self.query_id) == QueryStatus.RUNNING or
                self.con.get_query_status(self.query_id) == QueryStatus.NO_DATA)

    def _fetch_results(self):
        """
        Raises ProgrammingError in case of SQL error,
        by get_results_from_sfqid
        """        
        self.cursor.get_results_from_sfqid(self.query_id)

        row = self.cursor.fetchone()
        while row is not None:
            yield row
            row = self.cursor.fetchone()

    async def fetch_results(self):
        while self.is_query_running():
            await asyncio.sleep(0.1)

        return self._fetch_results()

    def fetch_results_sync(self):
        self.cursor.get_results_from_sfqid(self.query_id)
        return self.cursor.fetchall()
