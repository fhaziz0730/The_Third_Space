"""Create a PostgreSQL custom-format dump encrypted with GnuPG (AES-256)."""

from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import tempfile

from sqlalchemy.engine import make_url


def postgres_environment(database_url):
    url = make_url(database_url)
    if url.get_backend_name() not in {"postgresql", "postgres"}:
        raise ValueError("A PostgreSQL backup URL is required.")
    env = os.environ.copy()
    env.update({"PGHOST": url.host or "", "PGPORT": str(url.port or 5432),
                "PGDATABASE": url.database or "", "PGUSER": url.username or "",
                "PGPASSWORD": url.password or ""})
    for query, variable in (("sslmode", "PGSSLMODE"), ("channel_binding", "PGCHANNELBINDING"),
                            ("sslrootcert", "PGSSLROOTCERT")):
        if query in url.query:
            env[variable] = url.query[query]
    return env


def create_backup(output_dir="backups"):
    database_url = os.environ["BACKUP_DATABASE_URL"]
    passphrase = os.environ["BACKUP_PASSPHRASE"]
    if len(passphrase) < 32 or "\n" in passphrase or "\r" in passphrase:
        raise ValueError("Use a single-line random BACKUP_PASSPHRASE of at least 32 characters.")
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / ("third-space-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".dump.gpg")
    with tempfile.TemporaryDirectory(prefix="third-space-backup-") as working:
        working = Path(working)
        password_file = working / "passphrase"
        password_file.write_text(passphrase, encoding="utf-8")
        password_file.chmod(0o600)
        gpg_home = working / "gnupg"
        gpg_home.mkdir(mode=0o700)
        pg_env = postgres_environment(database_url)
        # Passwords never appear in command arguments; plaintext dumps never touch disk.
        dump = subprocess.Popen(["pg_dump", "--format=custom", "--no-owner", "--no-acl"],
                                env=pg_env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            encrypted = subprocess.run([
                "gpg", "--homedir", str(gpg_home), "--batch", "--yes", "--pinentry-mode", "loopback",
                "--passphrase-file", str(password_file), "--symmetric", "--cipher-algo", "AES256",
                "--output", str(output),
            ], stdin=dump.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            dump.stdout.close()
            if dump.wait() or encrypted.returncode:
                output.unlink(missing_ok=True)
                raise RuntimeError("Backup failed. Check PostgreSQL client version, credentials, and connectivity.")
        except BaseException:
            dump.kill()
            dump.wait()
            output.unlink(missing_ok=True)
            raise
    return output


if __name__ == "__main__":
    try:
        print(create_backup())
    except Exception:
        # Upstream errors must not accidentally print credentials into CI logs.
        raise SystemExit("Encrypted backup failed; verify backup configuration and tools.")
