import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if "pymysql" not in sys.modules:
    pymysql = types.ModuleType("pymysql")
    cursors = types.ModuleType("pymysql.cursors")
    cursors.DictCursor = object
    pymysql.cursors = cursors
    pymysql.connect = lambda *args, **kwargs: None
    sys.modules["pymysql"] = pymysql
    sys.modules["pymysql.cursors"] = cursors

import scripts.migrate as migrate


class FakeCursor:
    def fetchone(self):
        return None

    def fetchall(self):
        return []


class FakeConnection:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return FakeCursor()


class MigrateScriptTest(unittest.TestCase):
    def test_split_sql_statements_ignores_comments_and_preserves_semicolons_in_strings(self):
        sql = """
        -- line comment
        CREATE TABLE demo (id INTEGER PRIMARY KEY, note VARCHAR(255));
        INSERT INTO demo (note) VALUES ('value;still-string');
        # hash comment
        /* block comment ; */
        UPDATE demo SET note = "quoted;value" WHERE id = 1;
        """

        statements = migrate.split_sql_statements(sql)

        self.assertEqual(
            statements,
            [
                "CREATE TABLE demo (id INTEGER PRIMARY KEY, note VARCHAR(255))",
                "INSERT INTO demo (note) VALUES ('value;still-string')",
                'UPDATE demo SET note = "quoted;value" WHERE id = 1',
            ],
        )

    def test_run_sql_file_executes_statements_in_order(self):
        with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as handle:
            handle.write(
                """
                CREATE TABLE demo (id INTEGER PRIMARY KEY);
                INSERT INTO demo (id) VALUES (1);
                """
            )
            sql_path = Path(handle.name)

        conn = FakeConnection()
        self.addCleanup(sql_path.unlink, missing_ok=True)

        with patch.object(migrate, "db_connect", return_value=conn):
            count = migrate.run_sql_file(sql_path)

        self.assertEqual(count, 2)
        self.assertEqual(
            conn.calls,
            [
                ("CREATE TABLE demo (id INTEGER PRIMARY KEY)", None),
                ("INSERT INTO demo (id) VALUES (1)", None),
            ],
        )

    def test_run_sql_file_rejects_missing_sql_file(self):
        with self.assertRaises(FileNotFoundError):
            migrate.run_sql_file(Path("/tmp/definitely-missing-face-migration.sql"))

    def test_run_sql_file_rejects_empty_sql_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as handle:
            handle.write(" \n -- comment only\n")
            sql_path = Path(handle.name)

        self.addCleanup(sql_path.unlink, missing_ok=True)

        with self.assertRaises(ValueError):
            migrate.run_sql_file(sql_path)


if __name__ == "__main__":
    unittest.main()
