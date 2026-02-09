"""Orchestrate sandbox execution of untrusted Python code."""

import asyncio
import mimetypes
import shutil
import textwrap
from typing import TypedDict

from server.config import TIMEOUT_SECONDS, TMP_DIR
from server.sandbox.downloader import download_files
from server.sandbox.env import create_virtualenv

__all__ = ["run_code"]


# Precise schema for each artifact entry.
class ArtifactMeta(TypedDict):
    name: str
    relative_path: str
    size: int
    mime: str


# Typed return for run_code results.
class RunCodeResult(TypedDict):
    """Result of running code in the sandbox.
    Optionally includes a feedback field with suggestions or warnings (list of strings).
    """

    stdout: str
    stderr: str
    artifacts: list[ArtifactMeta]
    feedback: str


async def run_code(
    *,
    code: str,
    requirements: list[str],
    files: list[dict[str, str]],
    run_id: str,
    session_id: str | None = None,
) -> RunCodeResult:
    """Execute *code* inside an isolated virtual-env and return captured output. Artifacts are returned as paths relative to the output directory. Only files inside output/ are included."""

    if session_id:
        # Persist workspace for the lifetime of the client session.
        work = TMP_DIR / f"session_{session_id}"
        work.mkdir(parents=True, exist_ok=True)
    else:
        # One-shot execution, clean up workspace after run.
        work = TMP_DIR / f"run_{run_id}"
        work.mkdir(parents=True, exist_ok=True)

    # Prepare directories
    mounts_dir = work / "mounts"
    output_dir = work / "output"
    mounts_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Download files if provided
    if files:
        await download_files(files, mounts_dir)

    # Create virtual environment
    venv_path = work / "venv"
    create_virtualenv(venv_path)

    # Install requirements
    if requirements:
        # Install packages in the virtual environment
        import subprocess
        pip_exe = venv_path / "bin" / "pip"
        for req in requirements:
            subprocess.run([str(pip_exe), "install", req], check=True, capture_output=True)

    # Execute code
    import subprocess
    python_exe = venv_path / "bin" / "python"
    script_path = work / "script.py"
    with open(script_path, "w") as f:
        f.write(code)

    result = subprocess.run(
        [str(python_exe), str(script_path)],
        cwd=str(work),
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS
    )

    # Collect artifacts
    artifacts = []
    for item in output_dir.iterdir():
        if item.is_file():
            mime, _ = mimetypes.guess_type(str(item))
            artifacts.append({
                "name": item.name,
                "relative_path": str(item.relative_to(output_dir)),
                "size": item.stat().st_size,
                "mime": mime or "application/octet-stream"
            })

    # Clean up one-shot workspace
    if not session_id:
        shutil.rmtree(work, ignore_errors=True)

    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "artifacts": artifacts,
        "feedback": ""
    }