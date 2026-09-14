"""Linux supervised worker process groups with deadline and aggregate RSS limits.

Workers are operator-installed/trusted, not arbitrary model-authored programs.
No shell, inherited credentials, or user-controlled executable paths are used.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .models import CFDError


def run_windows_worker(
    command: list[str],
    job_dir: Path,
    timeout_s: float,
    cpu_count: int,
    memory_mb: int,
    max_output_bytes: int,
    log_prefix: str,
):
    """Windows Job Object supervisor with timeout, process-tree kill and output caps.

    Resource accounting is performed by the parent at the same sampling
    granularity as the Linux supervisor. Memory is enforced as a Job Object
    process-memory limit; CPU is enforced as an explicit affinity mask. The job
    is assigned KILL_ON_JOB_CLOSE so no child or grandchild can survive the call.
    """
    try:
        import win32api
        import win32con
        import win32event
        import win32job
        import win32process
    except ImportError as exc:  # pragma: no cover - depends on optional win32
        raise CFDError(
            "process_isolation",
            "Windows supervisor requires pywin32",
            "runner",
            "capability_gap",
        ) from exc

    if not command or not Path(command[0]).is_absolute():
        raise CFDError(
            "worker_executable",
            "Operator must configure an absolute installed executable",
            "runner",
            "capability_gap",
        )
    if not Path(command[0]).is_file():
        raise CFDError(
            "worker_executable",
            f"Configured executable not found: {command[0]}",
            "runner",
            "capability_gap",
        )

    job_dir = Path(job_dir).resolve()
    job_dir.mkdir(parents=True, exist_ok=True)
    job_name = "seekflow-cfd-" + log_prefix
    job = win32job.CreateJobObject(None, job_name)
    try:
        info = win32job.QueryInformationJobObject(
            job, win32job.JobObjectExtendedLimitInformation
        )
        flags = (
            info["BasicLimitInformation"]["LimitFlags"]
            | win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            | win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY
        )
        info["BasicLimitInformation"]["LimitFlags"] = flags
        info["ProcessMemoryLimit"] = int(memory_mb) * 1024 * 1024
        win32job.SetInformationJobObject(
            job, win32job.JobObjectExtendedLimitInformation, info
        )

        cmdline = subprocess.list2cmdline(command)
        startup = win32process.STARTUPINFO()
        startup.dwFlags |= win32process.STARTF_USESHOWWINDOW
        startup.wShowWindow = win32con.SW_HIDE
        env = os.environ.copy()
        env["OMP_NUM_THREADS"] = str(cpu_count)
        env["OPENBLAS_NUM_THREADS"] = str(cpu_count)
        creation = win32process.CREATE_NEW_CONSOLE
        try:
            creation |= win32process.CREATE_SUSPENDED
        except AttributeError:
            creation = win32process.CREATE_SUSPENDED
        process, thread, _, _ = win32process.CreateProcess(
            None,
            cmdline,
            None,
            None,
            0,
            creation,
            env,
            str(job_dir),
            startup,
        )
        try:
            win32job.AssignProcessToJobObject(job, process)
            _, system_mask = win32process.GetProcessAffinityMask(process)
            selected = 0
            for bit in range(64):
                if system_mask & (1 << bit):
                    selected |= 1 << bit
                    if bin(selected & system_mask).count("1") >= max(1, cpu_count):
                        break
            win32process.SetProcessAffinityMask(process, selected)
        finally:
            try:
                win32process.ResumeThread(thread)
            finally:
                win32api.CloseHandle(thread)

        out_path = job_dir / (log_prefix + ".stdout")
        err_path = job_dir / (log_prefix + ".stderr")
        started = time.monotonic()
        stdout = stderr = b""
        try:
            while True:
                remaining_ms = int(
                    max(0, timeout_s - (time.monotonic() - started)) * 1000
                )
                status = win32event.WaitForSingleObject(process, 250)
                if status == win32event.WAIT_OBJECT_0:
                    code = win32process.GetExitCodeProcess(process)
                    win32api.CloseHandle(process)
                    if code:
                        raise CFDError(
                            "worker_exit",
                            f"Worker exited with code {code}; see {err_path.name}",
                            "runner",
                            "failed",
                        )
                    return {
                        "returncode": code,
                        "elapsed_s": time.monotonic() - started,
                        "logs": [out_path.name, err_path.name],
                    }
                if remaining_ms <= 0:
                    raise CFDError(
                        "worker_timeout",
                        "Worker exceeded remaining task deadline",
                        "runner",
                        "timeout",
                    )
                total = 0
                for p in job_dir.rglob("*"):
                    if p.is_symlink():
                        raise CFDError(
                            "unsafe_output",
                            "Worker created a symlink",
                            "runner",
                            "failed",
                        )
                    if p.is_file():
                        total += p.stat().st_size
                if total > max_output_bytes:
                    raise CFDError(
                        "output_budget",
                        "Worker exceeded job output budget",
                        "runner",
                        "failed",
                    )
        finally:
            try:
                win32job.TerminateJobObject(job, 1)
            except Exception:  # noqa: BLE001 - process may already have exited
                pass
            try:
                stdout = out_path.read_bytes()
                stderr = err_path.read_bytes()
            except OSError:
                pass
            if stdout or stderr:
                out_path.write_bytes(stdout[: max_output_bytes])
                err_path.write_bytes(stderr[: max_output_bytes])
    finally:
        try:
            win32api.CloseHandle(job)
        except Exception:  # noqa: BLE001 - job handle cleanup
            pass


def _group_rss(pgid: int) -> int:
    total = 0
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():
            continue
        try:
            stat = (p / "stat").read_text().rsplit(")", 1)[1].split()
            if int(stat[2]) == pgid:
                total += int(stat[21]) * os.sysconf("SC_PAGE_SIZE")
        except (OSError, ValueError, IndexError):
            continue
    return total


def run_worker(
    command: list[str],
    job_dir: Path,
    timeout_s: float,
    cpu_count: int,
    memory_mb: int,
    max_output_bytes: int,
    log_prefix: str,
):
    if sys.platform.startswith("win"):
        return run_windows_worker(
            command,
            job_dir,
            timeout_s,
            cpu_count,
            memory_mb,
            max_output_bytes,
            log_prefix,
        )
    if (
        not sys.platform.startswith("linux")
        or not hasattr(os, "sched_getaffinity")
        or not Path("/proc/self/stat").is_file()
    ):
        raise CFDError(
            "process_isolation",
            "Default supervisor requires Linux CPU affinity and readable /proc; supply a certified local supervisor on other platforms",
            "runner",
            "capability_gap",
        )
    if (
        not command
        or not Path(command[0]).is_absolute()
        or not Path(command[0]).is_file()
    ):
        raise CFDError(
            "worker_executable",
            "Operator must configure an absolute installed executable",
            "runner",
            "capability_gap",
        )
    env = {
        "PATH": os.defpath,
        "LANG": "C.UTF-8",
        "OMP_NUM_THREADS": str(cpu_count),
        "OPENBLAS_NUM_THREADS": str(cpu_count),
    }
    # Preserve the installed framework search path, never pass solver secrets from a task.
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    out_path, err_path = (
        job_dir / (log_prefix + ".stdout"),
        job_dir / (log_prefix + ".stderr"),
    )
    wrapper = [
        sys.executable,
        "-m",
        "seekflow_cfd.process",
        str(cpu_count),
        str(memory_mb),
        str(max_output_bytes),
        *command,
    ]
    started = time.monotonic()
    with out_path.open("wb") as out, err_path.open("wb") as err:
        proc = subprocess.Popen(
            wrapper,
            cwd=job_dir,
            env=env,
            stdout=out,
            stderr=err,
            start_new_session=True,
        )
        try:
            while True:
                if time.monotonic() - started > timeout_s:
                    raise CFDError(
                        "worker_timeout",
                        "Worker exceeded remaining task deadline",
                        "runner",
                        "timeout",
                    )
                if _group_rss(proc.pid) > memory_mb * 1024 * 1024:
                    raise CFDError(
                        "memory_budget",
                        "Worker process group exceeded RSS budget",
                        "runner",
                        "failed",
                    )
                total = 0
                for p in job_dir.rglob("*"):
                    if p.is_symlink():
                        raise CFDError(
                            "unsafe_output",
                            "Worker created a symlink",
                            "runner",
                            "failed",
                        )
                    if p.is_file():
                        total += p.stat().st_size
                if total > max_output_bytes:
                    raise CFDError(
                        "output_budget",
                        "Worker exceeded job output budget",
                        "runner",
                        "failed",
                    )
                code = proc.poll()
                if code is not None:
                    if code:
                        raise CFDError(
                            "worker_exit",
                            f"Worker exited with code {code}; see {err_path.name}",
                            "runner",
                            "failed",
                        )
                    return {
                        "returncode": code,
                        "elapsed_s": time.monotonic() - started,
                        "logs": [out_path.name, err_path.name],
                    }
                time.sleep(0.05)
        finally:
            # Also kill orphaned solver children after parent exits.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()


def _entry():
    import resource

    cpu, mem, out = map(int, sys.argv[1:4])
    available = sorted(os.sched_getaffinity(0))
    os.sched_setaffinity(0, set(available[:cpu]))
    resource.setrlimit(resource.RLIMIT_AS, (mem * 1024 * 1024, mem * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (out, out))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.execv(sys.argv[4], sys.argv[4:])


if __name__ == "__main__":
    _entry()
