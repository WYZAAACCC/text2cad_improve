"""Report task/seed coverage for legacy model batches."""

from __future__ import annotations

from pathlib import Path

OUT = Path("_main_experiment/output")


def scan(batches: list[str], method: str) -> set:
    keys = set()
    for b in batches:
        root = OUT / b / "runs" / method
        if not root.exists():
            continue
        for td in root.iterdir():
            if not td.is_dir():
                continue
            for sd in td.iterdir():
                if not sd.is_dir() or not sd.name.startswith("seed_"):
                    continue
                if (sd / "latest" / "run.json").exists():
                    keys.add((td.name, int(sd.name.split("_")[1])))
    return keys


def main() -> None:
    all_keys = {(f"T{i:02d}", s) for i in range(1, 41) for s in range(10)}
    cases = [
        ("qwen", [
            "_qwen3_7_T01_T10_100", "_qwen3_7_T05_T40_360",
            "_qwen3_7_T15_T24_100", "_qwen3_7_T25_T40_160",
        ], "full_agentic_qwen3_7_plus"),
        ("glm", [
            "_glm_5_2_T01_T04_40", "_glm_5_2_T05_T14_100",
            "_glm_5_2_T15_T24_100", "_glm_5_2_T25_T34_100",
            "_glm_5_2_T31_T40_100",
        ], "full_agentic_glm_5_2"),
        ("flash", [
            "_ds_flash_T01_T10_100", "_ds_flash_T11_T20_100",
            "_ds_flash_T21_T30_100", "_ds_flash_T31_T40_100",
        ], "full_agentic_ds_flash"),
    ]
    for name, batches, method in cases:
        keys = scan(batches, method)
        missing = sorted(all_keys - keys)
        print(name, "keys", len(keys), "missing", len(missing))
        if missing:
            print("  first missing:", missing[:40])


if __name__ == "__main__":
    main()
