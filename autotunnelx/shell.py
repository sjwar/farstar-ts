from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def run(args: list[str], *, timeout: int = 30, check: bool = False, env: dict[str, str] | None = None) -> CommandResult:
    proc = subprocess.run(
        args,
        text=True,
        capture_output=True,
        timeout=timeout,
        env={**os.environ, **(env or {})},
    )
    result = CommandResult(args=args, returncode=proc.returncode, stdout=proc.stdout.strip(), stderr=proc.stderr.strip())
    if check and result.returncode != 0:
        rendered = " ".join(shlex.quote(part) for part in args)
        raise RuntimeError(f"Command failed ({result.returncode}): {rendered}\n{result.stderr}")
    return result


def shell(script: str, *, timeout: int = 30, check: bool = False) -> CommandResult:
    return run(["bash", "-lc", script], timeout=timeout, check=check)


def atomic_write(path: str | os.PathLike[str], content: str, *, mode: int = 0o640) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(target.parent), delete=False) as tmp:
        tmp.write(content)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_name = tmp.name
    os.chmod(tmp_name, mode)
    os.replace(tmp_name, target)


def chmod(path: str | os.PathLike[str], mode: int) -> None:
    os.chmod(path, mode)


def exists(binary: str) -> bool:
    return run(["bash", "-lc", f"command -v {shlex.quote(binary)} >/dev/null 2>&1"]).ok
