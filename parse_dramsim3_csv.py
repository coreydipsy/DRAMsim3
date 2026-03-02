#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Dict


CHAN_HDR_RE = re.compile(r"^##\s+Statistics of Channel\s+(\d+)\s*$")
KV_RE = re.compile(
    r"^\s*([A-Za-z0-9_.\-\[\]]+)\s*=\s*([+\-]?\d+(?:\.\d+)?(?:[eE][+\-]?\d+)?)"
)

NEEDED_KEYS = {
    "average_bandwidth",
    "average_request_latency",
    "num_read_row_hits",
    "num_write_row_hits",
    "average_power",
    "all_bank_idle_cycles.0",  # <-- NEW for (5)
}


def parse_channels(text: str) -> Dict[int, Dict[str, float]]:
    channels: Dict[int, Dict[str, float]] = {}
    current: int | None = None

    for line in text.splitlines():
        m = CHAN_HDR_RE.match(line)
        if m:
            current = int(m.group(1))
            channels.setdefault(current, {})
            continue

        if current is None:
            continue

        m = KV_RE.match(line)
        if not m:
            continue

        key, val_s = m.group(1), m.group(2)
        if key in NEEDED_KEYS:
            channels[current][key] = float(val_s)

    return channels


def require(channels: Dict[int, Dict[str, float]], ch: int, key: str, src: str) -> float:
    if ch not in channels:
        raise ValueError(f"{src}: Missing Channel {ch} block.")
    if key not in channels[ch]:
        raise ValueError(f"{src}: Missing '{key}' in Channel {ch} block.")
    return channels[ch][key]


def compute_row(path: Path, ch0: int, ch1: int) -> Dict[str, object]:
    text = path.read_text(errors="replace")
    channels = parse_channels(text)
    src = str(path)

    bw_sum = require(channels, ch0, "average_bandwidth", src) + require(
        channels, ch1, "average_bandwidth", src
    )

    lat_avg = (
        require(channels, ch0, "average_request_latency", src)
        + require(channels, ch1, "average_request_latency", src)
    ) / 2.0

    row_hits_sum = (
        require(channels, ch0, "num_read_row_hits", src)
        + require(channels, ch0, "num_write_row_hits", src)
        + require(channels, ch1, "num_read_row_hits", src)
        + require(channels, ch1, "num_write_row_hits", src)
    )

    pwr_sum = require(channels, ch0, "average_power", src) + require(
        channels, ch1, "average_power", src
    )

    bank_idle_sum = require(channels, ch0, "all_bank_idle_cycles.0", src) + require(
        channels, ch1, "all_bank_idle_cycles.0", src
    )

    return {
        "file": path.name,
        "avg_bw_sum": bw_sum,
        "avg_req_lat_avg": lat_avg,
        "row_buffer_hits_sum": int(row_hits_sum),
        "avg_power_sum": pwr_sum,
        "bank_idle_cycles_sum": int(bank_idle_sum),
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Parse DRAMSim3 stats files and emit one-row-per-file CSV."
    )
    ap.add_argument(
        "inputs",
        nargs="+",
        help="Input files or directories. Directories are searched recursively for *.txt by default.",
    )
    ap.add_argument("--ch0", type=int, default=0, help="First channel id (default: 0)")
    ap.add_argument("--ch1", type=int, default=1, help="Second channel id (default: 1)")
    ap.add_argument(
        "-o",
        "--out",
        default="-",
        help="Output CSV path (default: '-' for stdout)",
    )
    ap.add_argument(
        "--pattern",
        default="*.txt",
        help="When an input is a directory, glob pattern to include (default: *.txt)",
    )
    ap.add_argument(
        "--skip-bad",
        action="store_true",
        help="Skip files that are missing fields instead of failing.",
    )
    args = ap.parse_args()

    # Collect input files
    files: list[Path] = []
    for item in args.inputs:
        p = Path(item)
        if p.is_dir():
            files.extend(sorted(p.rglob(args.pattern)))
        else:
            files.append(p)

    if not files:
        raise SystemExit("No input files found.")

    fieldnames = [
        "file",
        "avg_bw_sum",
        "avg_req_lat_avg",
        "row_buffer_hits_sum",
        "avg_power_sum",
        "bank_idle_cycles_sum",
    ]

    out_fh = None
    try:
        if args.out == "-":
            import sys

            out_fh = sys.stdout
        else:
            out_fh = open(args.out, "w", newline="", encoding="utf-8")

        writer = csv.DictWriter(out_fh, fieldnames=fieldnames)
        writer.writeheader()

        for f in files:
            try:
                row = compute_row(f, args.ch0, args.ch1)
                writer.writerow(row)
            except Exception:
                if args.skip_bad:
                    continue
                raise

    finally:
        if out_fh is not None and args.out != "-":
            out_fh.close()


if __name__ == "__main__":
    main()