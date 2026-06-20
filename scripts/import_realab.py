#!/usr/bin/env python3
"""Import a ReaLab headphone measurement page into this PrecisEQ repository.

Pipeline:
  ReaLab URL -> embedded window.__INITIAL_DATA__ -> provenance CSV/JSON
  -> selected Frequency Response curve -> AutoEq zero-target minimum-phase WAVs
  -> RepositoryFiles metadata and MANIFEST update.

This intentionally keeps ReaLab target_data separate from FIR generation. Target
curves are exported under target_import_material/ as import/reference material.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

REPO_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_FILES = REPO_ROOT / "RepositoryFiles"
MEASUREMENTS = REPO_ROOT / "measurements" / "0_in-ear"
TARGETS = REPO_ROOT / "targets"
DOCS = REPO_ROOT / "docs"
TARGET_IMPORT = REPO_ROOT / "target_import_material"
SOURCE_ARCHIVE = REPO_ROOT / "source_pages"
AUTOEQ_PYTHON_DEFAULT = "/tmp/preciseq_py311_fixed/bin/python"
ZERO_TARGET_URL = "https://raw.githubusercontent.com/yokodev-pro/PrecisEQ-Repository-oratory1990-Unofficial/main/targets/0_zero.csv"
FIR_TAPS = 16384


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Hermes-Agent"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return resp.read().decode("utf-8", "replace")


def extract_initial_data(html: str) -> dict[str, Any]:
    marker = "window.__INITIAL_DATA__ = "
    start = html.find(marker)
    if start < 0:
        raise RuntimeError("window.__INITIAL_DATA__ marker not found")
    start += len(marker)
    end = html.find("</script>", start)
    if end < 0:
        raise RuntimeError("closing </script> after __INITIAL_DATA__ not found")
    raw = html[start:end].strip().rstrip(";")
    return json.loads(raw)


def slug_ascii(text: str) -> str:
    # Keep ASCII alnum only for PrecisEQ id compatibility, similar to upstream sanitize_id.
    # ReaLab bilingual names often use `English/中文`; keep the English side to avoid
    # duplicated slugs like `appleapple...`.
    text = re.sub(r"([A-Za-z0-9 &+.-]+)/[\u3400-\u9fff]+", r"\1", text)
    text = text.replace("&", "and")
    return re.sub(r"[^A-Za-z0-9]+", "", text).lower()


def safe_file_stem(text: str, limit: int = 150) -> str:
    text = text.replace("B&K", "BK").replace("&", "and")
    text = re.sub(r"[\\/:*?\"<>|]+", "_", text)
    text = re.sub(r"\s+", "_", text.strip())
    text = re.sub(r"_+", "_", text)
    return (text[:limit] or "untitled").strip("_")


def metadata_from_data(url: str, data: dict[str, Any]) -> dict[str, Any]:
    d = data.get("Data", {})
    desc = d.get("description") or ""
    desc_text = re.sub(r"<[^>]+>", " ", desc).strip()
    return {
        "source_url": url,
        "brand": d.get("brand"),
        "title": d.get("title"),
        "description": desc,
        "description_text": desc_text,
        "cover": d.get("cover"),
        "cat": d.get("cat"),
        "tag": d.get("tag"),
    }


def get_type_name(item: dict[str, Any]) -> str:
    typ = item.get("type")
    if isinstance(typ, dict):
        return typ.get("name") or ""
    return f"type_{typ}"


def choose_fr_curve(items: list[dict[str, Any]], preferred_title_regex: str | None = None) -> tuple[int, dict[str, Any]]:
    fr = [(i, it) for i, it in enumerate(items) if "Frequency Response" in get_type_name(it) or "频率响应" in get_type_name(it)]
    if not fr:
        raise RuntimeError("No Frequency Response curve found")
    if preferred_title_regex:
        rx = re.compile(preferred_title_regex, re.I)
        for i, it in fr:
            if rx.search(it.get("title") or ""):
                return i, it
    # ReaLab TWS pages often expose THD at Volume-6; prefer FR Volume-6 if available.
    # Match both "Volume-6" and "Volume6", but not "Volume Max".
    for i, it in fr:
        title = it.get("title") or ""
        if re.search(r"Volume\s*-?\s*6(?:\D|$)", title, re.I):
            return i, it
    return fr[0]


def write_curve_csv(path: Path, rows: list[list[Any]], header: tuple[str, str] = ("frequency", "raw")) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(list(header))
        for r in rows[1:]:
            if len(r) >= 2 and str(r[0]).strip() and str(r[1]).strip():
                w.writerow([float(r[0]), float(r[1])])


def write_raw_csv(path: Path, rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows(rows)


def ensure_zero_target() -> Path:
    TARGETS.mkdir(exist_ok=True)
    p = TARGETS / "0_zero.csv"
    if not p.exists():
        p.write_bytes(urllib.request.urlopen(ZERO_TARGET_URL, timeout=45).read())
    return p


def run_autoeq(autoeq_python: str, measurement_csv: Path, target_csv: Path, work_name: str) -> Path:
    py = Path(autoeq_python)
    if not py.exists():
        raise RuntimeError(f"AutoEq Python not found: {py}. Create it with python3.11 venv + pip install autoeq soundfile.")
    temp = Path(tempfile.mkdtemp(prefix="preciseq_realab_autoeq_"))
    in_dir = temp / "input" / "0_in-ear"
    combined_work_dir = temp / "combined" / "0_in-ear" / work_name
    in_dir.mkdir(parents=True)
    combined_work_dir.mkdir(parents=True)
    in_csv = in_dir / f"{work_name}.csv"
    shutil.copy2(measurement_csv, in_csv)

    # Official PrecisEQ repository WAVs use 32-bit float PCM and 16384-tap FIRs
    # for every sample rate. AutoEq's --f-res controls FIR length as fs / f_res,
    # so run each sample rate separately to keep the tap count fixed.
    for fs in (44100, 48000, 96000, 192000):
        out_dir = temp / f"output_{fs}"
        out_dir.mkdir(parents=True)
        f_res = fs / FIR_TAPS
        cmd = [
            str(py), "-m", "autoeq",
            "--input-dir", str(temp / "input"),
            "--output-dir", str(out_dir),
            "--target", str(target_csv),
            "--fs", str(fs),
            "--convolution-eq",
            "--phase", "minimum",
            "--bit-depth", "32",
            "--f-res", str(f_res),
            "--preamp", "-11.8",
        ]
        log_path = temp / f"autoeq_{fs}.log"
        with log_path.open("w", encoding="utf-8") as log:
            subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=True)
        matches = list((out_dir / "0_in-ear" / work_name).glob(f"* minimum phase {fs}Hz.wav"))
        if not matches:
            raise RuntimeError(f"Missing AutoEq output WAV for {fs} Hz in {out_dir}")
        shutil.copy2(matches[0], combined_work_dir / matches[0].name)
    return combined_work_dir


def write_official_style_wav(src: Path, dst: Path, expected_rate: int) -> None:
    data, sr = sf.read(src, always_2d=True)
    if sr != expected_rate:
        raise RuntimeError(f"Unexpected sample rate for {src}: {sr}, expected {expected_rate}")
    if data.shape[0] != FIR_TAPS:
        raise RuntimeError(f"Unexpected FIR length for {src}: {data.shape[0]}, expected {FIR_TAPS}")
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    elif data.shape[1] != 2:
        raise RuntimeError(f"Unexpected channel count for {src}: {data.shape[1]}")
    sf.write(dst, data.astype("float32"), sr, subtype="FLOAT", format="WAV")


def copy_wavs(output_dir: Path, hp_id: str, version: int) -> list[Path]:
    fs_map = {"44100": "44", "48000": "48", "96000": "96", "192000": "192"}
    copied: list[Path] = []
    for hz, short in fs_map.items():
        matches = list(output_dir.glob(f"* minimum phase {hz}Hz.wav"))
        if not matches:
            raise RuntimeError(f"Missing AutoEq output WAV for {hz} Hz in {output_dir}")
        dst = REPOSITORY_FILES / f"{hp_id}_{version}_{short}.wav"
        write_official_style_wav(matches[0], dst, int(hz))
        copied.append(dst)
    return copied


def load_headphone_list() -> list[dict[str, Any]]:
    p = REPOSITORY_FILES / "headphone_list.json"
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


def save_headphone_list(entries: list[dict[str, Any]]) -> None:
    entries = sorted(entries, key=lambda x: x.get("id", ""))
    (REPOSITORY_FILES / "headphone_list.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_brand_model(title: str, brand: str | None) -> tuple[list[str], list[str]]:
    # ReaLab title usually: Apple/苹果 AirPods Pro 2
    title = title or "Unknown"
    parts = title.split(maxsplit=1)
    if brand and "/" in brand:
        en, zh = brand.split("/", 1)
        brand_names = [en, zh]
    else:
        brand_names = [brand or parts[0]]
    model = parts[1] if len(parts) > 1 else title
    return brand_names, [model]


def export_target_material(page_slug: str, meta: dict[str, Any], target_items: list[dict[str, Any]]) -> list[Path]:
    written: list[Path] = []
    if not target_items:
        return written
    item = target_items[0]
    rows = item.get("data") or []
    if not rows:
        return written
    prefix = f"{page_slug}_ReaLab_Target_Response_2024"
    source = TARGET_IMPORT / f"{prefix}_source_export.csv"
    raw = TARGET_IMPORT / f"{prefix}_frequency_raw.csv"
    db = TARGET_IMPORT / f"{prefix}_frequency_db.csv"
    nohdr = TARGET_IMPORT / f"{prefix}_freq_db_no_header.txt"
    write_raw_csv(source, rows)
    write_curve_csv(raw, rows, ("frequency", "raw"))
    write_curve_csv(db, rows, ("frequency", "dB"))
    with nohdr.open("w", encoding="utf-8") as f:
        for r in rows[1:]:
            if len(r) >= 2:
                f.write(f"{float(r[0]):.6f}\t{float(r[1]):.6f}\n")
    info = {
        "name": f"{meta.get('title')} ReaLab Target Response 2024",
        "source_url": meta.get("source_url"),
        "rows": len(rows) - 1,
        "header": rows[0],
        "first": rows[1] if len(rows) > 1 else None,
        "last": rows[-1] if len(rows) > 1 else None,
        "note": "Grey dotted target curve from the ReaLab page. Not a corrected headphone measurement and not baked into RepositoryFiles FIRs.",
    }
    info_path = TARGET_IMPORT / f"{prefix}_README.json"
    info_path.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    written.extend([source, raw, db, nohdr, info_path])
    return written


def update_repo_info() -> None:
    p = REPOSITORY_FILES / "repo_info.json"
    info = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    info.update({
        "name": "ReaLab experimental PrecisEQ repository",
        "maintainer": "feriaref / Hermes Agent generated",
        "description": "Experimental PrecisEQ FIR repository generated from ReaLab embedded measurement data. FIRs use selected measured frequency responses with AutoEq zero/flat target; ReaLab target curves are exported separately under target_import_material and are not baked into the FIRs. Rig compensation to PrecisEQ/oratory basis is unresolved.",
    })
    p.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")


def update_manifest() -> None:
    manifest = []
    for p in sorted(REPO_ROOT.rglob("*")):
        if ".git" in p.parts:
            continue
        if p.is_file():
            manifest.append({
                "path": str(p.relative_to(REPO_ROOT)),
                "size": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            })
    (REPO_ROOT / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--preferred-title-regex", default=None)
    ap.add_argument("--autoeq-python", default=AUTOEQ_PYTHON_DEFAULT)
    ap.add_argument("--volume-label", default=None, help="Optional label appended in model name/id, defaults to selected curve title-derived label.")
    ap.add_argument("--id-override", default=None, help="Optional stable PrecisEQ id override for regenerating legacy entries without changing filenames.")
    args = ap.parse_args()

    for d in [REPOSITORY_FILES, MEASUREMENTS, TARGETS, DOCS, TARGET_IMPORT, SOURCE_ARCHIVE]:
        d.mkdir(parents=True, exist_ok=True)

    html = fetch_text(args.url)
    data = extract_initial_data(html)
    meta = metadata_from_data(args.url, data)
    D = data.get("Data", {})
    title = meta.get("title") or "Unknown Headphone"
    page_slug = slug_ascii(title) or "realabheadphone"
    page_dir = SOURCE_ARCHIVE / page_slug
    page_dir.mkdir(parents=True, exist_ok=True)
    (page_dir / "source.html").write_text(html, encoding="utf-8")
    (page_dir / "initial_data.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (page_dir / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    idx, curve = choose_fr_curve(D.get("data") or [], args.preferred_title_regex)
    curve_title = curve.get("title") or f"curve_{idx}"
    rows = curve.get("data") or []
    if len(rows) < 2:
        raise RuntimeError("Selected curve has no data rows")

    # Work label and ID. Current pages use ANC on / BK5128 / Volume-6.
    vol_match = re.search(r"Volume(?:\s*Max|-?\d+)", curve_title, re.I)
    vol_label = args.volume_label or (vol_match.group(0).replace(" ", "") if vol_match else f"curve{idx}")
    mode_label = "ANC on" if re.search(r"ANC\s*on", curve_title, re.I) else ""
    rig_label = "BK5128" if "5128" in curve_title else ""
    hp_id = args.id_override or slug_ascii(f"{title} {mode_label} {rig_label} {vol_label}")
    version = 1
    work_name = f"{title} {mode_label} {rig_label} {vol_label}".strip()

    measurement_csv = MEASUREMENTS / f"{safe_file_stem(work_name)}.csv"
    write_curve_csv(measurement_csv, rows)
    raw_curve_csv = page_dir / f"selected_curve_{idx:02d}_{safe_file_stem(curve_title)}.csv"
    write_raw_csv(raw_curve_csv, rows)

    target_path = ensure_zero_target()
    autoeq_output = run_autoeq(args.autoeq_python, measurement_csv, target_path, safe_file_stem(work_name, 120))
    wavs = copy_wavs(autoeq_output, hp_id, version)

    brand_names, model_base = parse_brand_model(title, meta.get("brand"))
    model_en = f"{model_base[0]} {mode_label} - ReaLab {rig_label} {vol_label} experimental flat".replace("  ", " ").strip()
    model_zh = model_en
    if len(brand_names) > 1 and brand_names[1] == "苹果":
        model_zh = model_en.replace("AirPods", "AirPods").replace("ANC on", "降噪开").replace("experimental flat", "实验平直")
    entry = {
        "id": hp_id,
        "type": 0,
        "brandName": brand_names,
        "modelName": [model_en, model_zh],
        "version": version,
        "noDspOffsetDb": 0.0,
    }
    entries = [e for e in load_headphone_list() if e.get("id") != hp_id]
    entries.append(entry)
    save_headphone_list(entries)
    update_repo_info()

    target_written = export_target_material(page_slug, meta, D.get("target_data") or [])

    summary = {
        "url": args.url,
        "title": title,
        "selected_curve_index": idx,
        "selected_curve_title": curve_title,
        "selected_curve_rows": len(rows) - 1,
        "id": hp_id,
        "version": version,
        "measurement_csv": str(measurement_csv.relative_to(REPO_ROOT)),
        "raw_curve_csv": str(raw_curve_csv.relative_to(REPO_ROOT)),
        "wavs": [str(p.relative_to(REPO_ROOT)) for p in wavs],
        "target_material": [str(p.relative_to(REPO_ROOT)) for p in target_written],
        "note": "FIR generated to zero/flat AutoEq target; ReaLab target_data exported separately.",
    }
    (page_dir / "import_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    update_manifest()
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
