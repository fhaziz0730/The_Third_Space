import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.backup_database import create_backup, postgres_environment


class BackupTests(unittest.TestCase):
    def test_connection_secrets_are_passed_through_environment(self):
        env = postgres_environment(
            "postgresql+psycopg://reader:secret%40value@db.example:5433/app?sslmode=require"
        )
        self.assertEqual(env["PGPASSWORD"], "secret@value")
        self.assertEqual(env["PGHOST"], "db.example")
        self.assertEqual(env["PGPORT"], "5433")
        self.assertEqual(env["PGSSLMODE"], "require")
        with self.assertRaises(ValueError):
            postgres_environment("sqlite:///database.db")

    def test_weak_backup_passphrase_is_rejected_before_starting_tools(self):
        with (
            patch.dict(
                os.environ,
                {
                    "BACKUP_DATABASE_URL": "postgresql://user:password@host/db",
                    "BACKUP_PASSPHRASE": "weak",
                },
            ),
            patch("subprocess.Popen") as process,
        ):
            with self.assertRaises(ValueError):
                create_backup()
            process.assert_not_called()

    @unittest.skipUnless(
        os.getenv("TEST_BACKUP_TOOLS") == "true", "Requires PostgreSQL and GnuPG client tools"
    )
    def test_encrypted_dump_can_be_decrypted_and_restored_to_an_empty_test_database(self):
        import uuid

        original = postgres_environment(os.environ["TEST_POSTGRES_URL"])
        restored_name = "third_space_restore_" + uuid.uuid4().hex[:12]
        password = "local-integration-test-passphrase-" + uuid.uuid4().hex
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                os.environ,
                {
                    "BACKUP_DATABASE_URL": os.environ["TEST_POSTGRES_URL"],
                    "BACKUP_PASSPHRASE": password,
                },
            ),
        ):
            archive = create_backup(directory)
            self.assertTrue(archive.stat().st_size > 0)
            self.assertNotEqual(archive.read_bytes()[:5], b"PGDMP")
            passfile = Path(directory) / "restore-passphrase"
            passfile.write_text(password)
            passfile.chmod(0o600)
            homedir = Path(directory) / "gpg-home"
            homedir.mkdir(mode=0o700)
            decrypted = subprocess.run(
                [
                    "gpg",
                    "--homedir",
                    str(homedir),
                    "--batch",
                    "--pinentry-mode",
                    "loopback",
                    "--passphrase-file",
                    str(passfile),
                    "--decrypt",
                    str(archive),
                ],
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["createdb", restored_name], env=original, check=True, capture_output=True
            )
            try:
                target = {**original, "PGDATABASE": restored_name}
                subprocess.run(
                    [
                        "pg_restore",
                        "--dbname",
                        restored_name,
                        "--exit-on-error",
                        "--single-transaction",
                        "--no-owner",
                        "--no-acl",
                    ],
                    input=decrypted.stdout,
                    env=target,
                    check=True,
                    capture_output=True,
                )
                result = subprocess.run(
                    ["psql", "-Atc", "SELECT version_num FROM alembic_version"],
                    env=target,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.stdout.strip(), "0003_auth_limits")
            finally:
                subprocess.run(
                    ["dropdb", restored_name], env=original, check=True, capture_output=True
                )
