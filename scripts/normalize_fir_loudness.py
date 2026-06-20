#!/usr/bin/env python3
"""Normalize PrecisEQ FIR WAVs to the official -12 dB pre-gain reference.

The public PrecisEQ third-party repository guide states that all calibration
files must be generated with -12 dB pre-gain. Empirically, official FIR files
sit at about -12 dB magnitude around 1 kHz. This script applies a uniform gain
to existing FIR WAVs so their 1 kHz magnitude equals the chosen reference.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import soundfile as sf

SAMPLE_RATE_SUFFIXES = [44, 48, 96, 192]


def mag_at_hz(samples: np.ndarray, fs: int, hz: float, n_fft: int = 131072) -> float:
    mono = samples[:, 0] if samples.ndim == 2 else samples
    h = np.fft.rfft(mono, n=n_fft)
    f = np.fft.rfftfreq(n_fft, 1 / fs)
    mag = 20 * np.log10(np.maximum(np.abs(h), 1e-30))
    return float(np.interp(np.log10(hz), np.log10(f[1:]), mag[1:]))


def normalize_file(src: Path, dst: Path, target_db: float, ref_hz: float) -> tuple[float, float, float, float]:
    data, fs = sf.read(src, always_2d=True, dtype="float64")
    before = mag_at_hz(data, fs, ref_hz)
    gain_db = target_db - before
    scaled = data * (10 ** (gain_db / 20))
    peak = float(np.max(np.abs(scaled)))
    if peak >= 0.99:
        raise SystemExit(f"Refusing to write {dst}: peak would be {peak:.3f}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    sf.write(dst, scaled.astype("float32"), fs, subtype="FLOAT")
    after_data, after_fs = sf.read(dst, always_2d=True, dtype="float64")
    after = mag_at_hz(after_data, after_fs, ref_hz)
    return before, gain_db, after, peak


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-files", type=Path, default=Path("RepositoryFiles"))
    ap.add_argument("--ids", nargs="+", required=True)
    ap.add_argument("--from-version", type=int, default=1)
    ap.add_argument("--to-version", type=int, default=2)
    ap.add_argument("--target-db", type=float, default=-12.0)
    ap.add_argument("--ref-hz", type=float, default=1000.0)
    args = ap.parse_args()

    for entry_id in args.ids:
        for sr in SAMPLE_RATE_SUFFIXES:
            src = args.repo_files / f"{entry_id}_{args.from_version}_{sr}.wav"
            dst = args.repo_files / f"{entry_id}_{args.to_version}_{sr}.wav"
            if not src.exists():
                raise SystemExit(f"Missing {src}")
            before, gain_db, after, peak = normalize_file(src, dst, args.target_db, args.ref_hz)
            print(
                f"{dst.name}: {args.ref_hz:.0f} Hz {before:.2f} dB -> {after:.2f} dB; "
                f"gain {gain_db:+.2f} dB; peak {peak:.3f}"
            )


if __name__ == "__main__":
    main()
