#!/usr/bin/env python
"""SeekFlow Engineering Tools — One-Click Setup & Auto-Detection.

Detects SolidWorks / NX / ANSYS installations on the current machine,
writes a .env file, and verifies each tool with a health-check.

Usage:
    python setup_engineering.py                          # auto-detect
    python setup_engineering.py --manual                # guided prompts
    python setup_engineering.py --sw "D:\\SW2025" --nx "D:\\nx" --ansys "D:\\ANSYS"
    python setup_engineering.py --verify-only           # re-run health checks
    python setup_engineering.py --output .env            # custom env file path
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional


# ── ANSI colours for terminal output ──────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
RESET = "\033[0m"


def ok(msg: str) -> str:
    return f"{GREEN}[OK]{RESET} {msg}"


def fail(msg: str) -> str:
    return f"{RED}[FAIL]{RESET} {msg}"


def warn(msg: str) -> str:
    return f"{YELLOW}[WARN]{RESET} {msg}"


def info(msg: str) -> str:
    return f"{BOLD}[INFO]{RESET} {msg}"


# ═══════════════════════════════════════════════════════════════════════
# Auto-detection
# ═══════════════════════════════════════════════════════════════════════


def _find_start_menu_shortcuts() -> dict[str, str]:
    """Look for SolidWorks / NX / ANSYS in the Start Menu."""
    start_menu = Path(os.environ.get("PROGRAMDATA", "C:/ProgramData"))
    start_menu = start_menu / "Microsoft/Windows/Start Menu/Programs"
    found: dict[str, str] = {}

    if not start_menu.exists():
        return found

    for folder in start_menu.iterdir():
        if not folder.is_dir():
            continue
        name = folder.name.lower()

        if "solidworks" in name:
            for lnk in folder.glob("*.lnk"):
                if "solidworks" in lnk.stem.lower() and "composer" not in lnk.stem.lower():
                    found["solidworks_start_menu"] = str(lnk)
                    break
        elif "nx" in name or "siemens" in name:
            for lnk in folder.glob("*.lnk"):
                if "nx" in lnk.stem.lower() and "layout" not in lnk.stem.lower():
                    found["nx_start_menu"] = str(lnk)
                    break
        elif "ansys" in name:
            for lnk in folder.glob("*.lnk"):
                if "mechanical apdl" in lnk.stem.lower():
                    found["ansys_start_menu"] = str(lnk)
                    break

    return found


def _resolve_shortcut(lnk_path: str) -> Optional[str]:
    """Resolve a Windows .lnk shortcut to its target path."""
    try:
        import pythoncom
        from win32com.client import Dispatch
        pythoncom.CoInitialize()
        shell = Dispatch("WScript.Shell")
        shortcut = shell.CreateShortcut(lnk_path)
        return shortcut.TargetPath
    except Exception:
        return None


def _find_in_registry(*keys: str) -> Optional[str]:
    """Try each registry key, return first match."""
    import winreg  # type: ignore[import-untyped]

    for full_key in keys:
        parts = full_key.split("\\")
        hive_map = {
            "HKLM": winreg.HKEY_LOCAL_MACHINE,
            "HKCU": winreg.HKEY_CURRENT_USER,
        }
        hive = hive_map.get(parts[0], winreg.HKEY_LOCAL_MACHINE)
        subkey = "\\".join(parts[1:])
        try:
            with winreg.OpenKey(hive, subkey) as key:
                try:
                    return str(winreg.QueryValueEx(key, "")[0])
                except OSError:
                    pass
                try:
                    return str(winreg.QueryValueEx(key, "InstallPath")[0])
                except OSError:
                    pass
                try:
                    return str(winreg.QueryValueEx(key, "Path")[0])
                except OSError:
                    pass
        except OSError:
            continue
    return None


def detect_solidworks() -> dict:
    """Auto-detect SolidWorks installation."""
    result: dict = {"found": False, "exe": None, "template": None, "version": None}

    # 1. Registry
    reg_keys = [
        r"HKLM\SOFTWARE\SolidWorks\Applications\SLDWORKS",
        r"HKLM\SOFTWARE\WOW6432Node\SolidWorks\Applications\SLDWORKS",
        r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\SLDWORKS.exe",
    ]
    exe_path = _find_in_registry(*reg_keys)
    if not exe_path:
        # 2. Start Menu
        sm = _find_start_menu_shortcuts()
        lnk = sm.get("solidworks_start_menu")
        if lnk:
            exe_path = _resolve_shortcut(lnk)

    if exe_path and Path(exe_path).exists():
        result["exe"] = exe_path
        result["found"] = True

    # 3. Find templates
    programdata = Path(os.environ.get("PROGRAMDATA", "C:/ProgramData"))
    sw_data = programdata / "SOLIDWORKS"
    if sw_data.exists():
        # Look for the latest version
        versions = sorted([d for d in sw_data.iterdir() if d.is_dir()],
                          reverse=True)
        for v in versions:
            tpl = v / "templates" / "gb_part.prtdot"
            if tpl.exists():
                result["template"] = str(tpl)
                result["version"] = v.name
                break
            # Try English template
            tpl = v / "templates" / "Part.prtdot"
            if tpl.exists():
                result["template"] = str(tpl)
                result["version"] = v.name
                break

    return result


def detect_nx() -> dict:
    """Auto-detect Siemens NX installation."""
    result: dict = {"found": False, "journal_runner": None, "version": None}

    # 1. Start Menu
    sm = _find_start_menu_shortcuts()
    lnk = sm.get("nx_start_menu")
    exe_path = None
    if lnk:
        exe_path = _resolve_shortcut(lnk)
        # ugraf.exe is in NXBIN; run_journal.exe is there too
        if exe_path and "ugraf.exe" in exe_path.lower():
            nxbin = str(Path(exe_path).parent)
            runner = os.path.join(nxbin, "run_journal.exe")
            if os.path.exists(runner):
                result["journal_runner"] = runner
                result["found"] = True

    # 2. Common paths
    common = [
        r"C:\Program Files\Siemens\NX*\NXBIN\run_journal.exe",
        r"D:\nx\NXBIN\run_journal.exe",
        r"D:\Program Files\Siemens\NX*\NXBIN\run_journal.exe",
    ]
    if not result["found"]:
        import glob
        for pattern in common:
            matches = glob.glob(pattern)
            if matches:
                result["journal_runner"] = matches[0]
                result["found"] = True
                break

    # Detect version
    if result["found"] and result["journal_runner"]:
        # Try to parse version from path
        import re
        m = re.search(r"NX\s*(\d+\.?\d*)", str(result["journal_runner"]), re.I)
        if m:
            result["version"] = m.group(1)

    return result


def detect_ansys() -> dict:
    """Auto-detect ANSYS Mechanical APDL installation."""
    result: dict = {"found": False, "exe": None}

    # 1. Start Menu
    sm = _find_start_menu_shortcuts()
    lnk = sm.get("ansys_start_menu")
    if lnk:
        exe_path = _resolve_shortcut(lnk)
        if exe_path and "launcher.exe" in exe_path.lower():
            # launcher.exe is in v*/ansys/bin/winx64/
            bin_dir = str(Path(exe_path).parent)
            ansys_exe = os.path.join(bin_dir, "ansys181.exe")
            if os.path.exists(ansys_exe):
                result["exe"] = ansys_exe
                result["found"] = True
                return result

    # 2. Common paths
    import glob
    for pattern in [
        r"D:\ANSYS*\ANSYS Inc\v*\ANSYS\bin\winx64\ansys*.exe",
        r"C:\Program Files\ANSYS Inc\v*\ANSYS\bin\winx64\ansys*.exe",
    ]:
        matches = glob.glob(pattern)
        if matches:
            result["exe"] = matches[0]
            result["found"] = True
            break

    return result


# ═══════════════════════════════════════════════════════════════════════
# Health checks
# ═══════════════════════════════════════════════════════════════════════


def verify_solidworks(template: str) -> bool:
    """Check SolidWorks COM is reachable."""
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        sw = win32com.client.Dispatch("SldWorks.Application")
        rev = sw.RevisionNumber  # property, not method
        print(f"    SolidWorks COM: {ok('revision ' + str(rev))}")
        template_path = Path(template)
        if template_path.exists():
            print(f"    Part template:  {ok(str(template_path))}")
        else:
            print(f"    Part template:  {warn('not found — ' + str(template_path))}")
        return True
    except Exception as e:
        print(f"    SolidWorks:     {fail(str(e)[:80])}")
        return False


def verify_nx(journal_runner: str) -> bool:
    """Check NX journal runner exists."""
    if Path(journal_runner).exists():
        print(f"    NX Journal Runner: {ok(journal_runner)}")
        return True
    else:
        print(f"    NX Journal Runner: {fail('not found — ' + journal_runner)}")
        return False


def verify_ansys(ansys_exe: str) -> bool:
    """Check ANSYS executable exists."""
    if Path(ansys_exe).exists():
        print(f"    ANSYS APDL:     {ok(ansys_exe)}")
        return True
    else:
        print(f"    ANSYS APDL:     {fail('not found — ' + ansys_exe)}")
        return False


# ═══════════════════════════════════════════════════════════════════════
# Manual input
# ═══════════════════════════════════════════════════════════════════════


def manual_setup() -> dict:
    """Interactive guided setup."""
    print(f"\n{BOLD}Manual Setup — enter paths (press Enter to skip){RESET}\n")

    config = {}

    print(f"{BOLD}SolidWorks 2025{RESET}")
    sw_template = input("  Part template path [e.g. C:/.../gb_part.prtdot]: ").strip()
    config["solidworks_template"] = sw_template if sw_template else None
    config["solidworks_enabled"] = bool(sw_template)

    print(f"\n{BOLD}Siemens NX{RESET}")
    nx_runner = input("  run_journal.exe path [e.g. D:/nx/NXBIN/run_journal.exe]: ").strip()
    config["nx_journal_runner"] = nx_runner if nx_runner else None
    config["nx_enabled"] = bool(nx_runner)

    print(f"\n{BOLD}ANSYS 18.1{RESET}")
    ansys_exe = input("  ansys*.exe path [e.g. D:/ANSYS181/.../ansys181.exe]: ").strip()
    config["ansys_exe"] = ansys_exe if ansys_exe else None
    config["ansys_enabled"] = bool(ansys_exe)

    workspace = input(f"\n{BOLD}Workspace{RESET}\n  Engineering workspace dir [default: ~/seekflow_workspace]: ").strip()
    config["workspace"] = workspace if workspace else str(Path.home() / "seekflow_workspace")

    return config


# ═══════════════════════════════════════════════════════════════════════
# Env file writer
# ═══════════════════════════════════════════════════════════════════════


def write_env_file(path: str, config: dict) -> None:
    """Write a .env file with engineering tool paths."""
    lines = [
        "# SeekFlow Engineering Tools — auto-generated configuration",
        f"# Generated: {__import__('datetime').datetime.now()}",
        "",
        f"ENGINEERING_WORKSPACE={config.get('workspace', '')}",
        "",
        f"SOLIDWORKS_ENABLED={'1' if config.get('solidworks_enabled') else '0'}",
        f"SOLIDWORKS_PART_TEMPLATE={config.get('solidworks_template', '')}",
        f"SOLIDWORKS_VISIBLE=1",
        "",
        f"NX_ENABLED={'1' if config.get('nx_enabled') else '0'}",
        f"NX_JOURNAL_RUNNER={config.get('nx_journal_runner', '')}",
        f"NX_JOB_ROOT={config.get('workspace', '')}/nx_jobs",
        "",
        f"ANSYS_ENABLED={'1' if config.get('ansys_enabled') else '0'}",
        f"ANSYS181_EXE={config.get('ansys_exe', '')}",
        f"ANSYS_DEFAULT_NPROC={config.get('ansys_nproc', '2')}",
        "",
        f"ENGINEERING_ALLOW_OVERWRITE={'1' if config.get('allow_overwrite') else '0'}",
        "",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n  {ok('Config written to ' + path)}")


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(
        description="SeekFlow Engineering Tools — One-Click Setup",
    )
    parser.add_argument("--manual", action="store_true",
                        help="Interactive guided setup")
    parser.add_argument("--verify-only", action="store_true",
                        help="Only run health checks on existing config")
    parser.add_argument("--output", default=".env.seekflow",
                        help="Output .env file path (default: .env.seekflow)")
    parser.add_argument("--sw", help="SolidWorks part template path")
    parser.add_argument("--nx", help="NX journal runner path")
    parser.add_argument("--ansys", help="ANSYS executable path")
    parser.add_argument("--workspace",
                        default=str(Path.home() / "seekflow_workspace"),
                        help="Engineering workspace directory")
    parser.add_argument("--no-sw", action="store_true", help="Disable SolidWorks")
    parser.add_argument("--no-nx", action="store_true", help="Disable NX")
    parser.add_argument("--no-ansys", action="store_true", help="Disable ANSYS")
    args = parser.parse_args()

    print(f"\n{BOLD}══════════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  SeekFlow Engineering Tools — Setup{RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════════{RESET}")

    config: dict = {}

    # ── Gather paths ──────────────────────────────────────────────────
    if args.manual:
        config = manual_setup()
    else:
        # Auto-detect
        print(f"\n{info('Auto-detecting installations...')}\n")

        # SolidWorks
        if not args.no_sw:
            sw = detect_solidworks()
            if args.sw:
                config["solidworks_template"] = args.sw
                config["solidworks_enabled"] = True
                print(f"  SolidWorks:  {ok('manual — ' + args.sw)}")
            elif sw["found"]:
                config["solidworks_template"] = sw["template"]
                config["solidworks_enabled"] = True
                print(f"  SolidWorks:  {ok('v' + str(sw.get('version', '?')) + ' — ' + str(sw.get('template', '?')))}")
            else:
                config["solidworks_enabled"] = False
                print(f"  SolidWorks:  {warn('not detected')}")
        else:
            config["solidworks_enabled"] = False
            print(f"  SolidWorks:  {warn('disabled by user')}")

        # NX
        if not args.no_nx:
            nx = detect_nx()
            if args.nx:
                config["nx_journal_runner"] = args.nx
                config["nx_enabled"] = True
                print(f"  NX:          {ok('manual — ' + args.nx)}")
            elif nx["found"]:
                config["nx_journal_runner"] = nx["journal_runner"]
                config["nx_enabled"] = True
                print(f"  NX:          {ok('v' + str(nx.get('version', '?')) + ' — ' + str(nx['journal_runner']))}")
            else:
                config["nx_enabled"] = False
                print(f"  NX:          {warn('not detected')}")
        else:
            config["nx_enabled"] = False
            print(f"  NX:          {warn('disabled by user')}")

        # ANSYS
        if not args.no_ansys:
            ansys = detect_ansys()
            if args.ansys:
                config["ansys_exe"] = args.ansys
                config["ansys_enabled"] = True
                print(f"  ANSYS:       {ok('manual — ' + args.ansys)}")
            elif ansys["found"]:
                config["ansys_exe"] = ansys["exe"]
                config["ansys_enabled"] = True
                print(f"  ANSYS:       {ok(str(ansys['exe']))}")
            else:
                config["ansys_enabled"] = False
                print(f"  ANSYS:       {warn('not detected')}")
        else:
            config["ansys_enabled"] = False
            print(f"  ANSYS:       {warn('disabled by user')}")

        config["workspace"] = args.workspace
        config["allow_overwrite"] = False
        config["ansys_nproc"] = 2

    # ── Verify ────────────────────────────────────────────────────────
    if config.get("solidworks_enabled"):
        print(f"\n{BOLD}Verifying SolidWorks...{RESET}")
        sw_ok = verify_solidworks(config.get("solidworks_template", ""))
    else:
        sw_ok = True

    if config.get("nx_enabled"):
        print(f"\n{BOLD}Verifying NX...{RESET}")
        nx_ok = verify_nx(config.get("nx_journal_runner", ""))
    else:
        nx_ok = True

    if config.get("ansys_enabled"):
        print(f"\n{BOLD}Verifying ANSYS...{RESET}")
        ansys_ok = verify_ansys(config.get("ansys_exe", ""))
    else:
        ansys_ok = True

    # ── Write config ──────────────────────────────────────────────────
    write_env_file(args.output, config)

    # ── Summary ───────────────────────────────────────────────────────
    all_ok = sw_ok and nx_ok and ansys_ok
    print(f"\n{BOLD}══════════════════════════════════════════════════════{RESET}")
    if all_ok:
        print(f"  {GREEN}ALL CHECKS PASSED{RESET}")
    else:
        print(f"  {YELLOW}SOME CHECKS FAILED — review above{RESET}")

    print(f"\n  Workspace:     {config.get('workspace')}")
    print(f"  Config file:   {os.path.abspath(args.output)}")
    print(f"\n  Next step:")
    print(f"    pip install -e integrations/engineering_tools")
    print(f"    python integrations/engineering_tools/examples/self_test.py --all")
    print(f"{BOLD}══════════════════════════════════════════════════════{RESET}\n")

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
