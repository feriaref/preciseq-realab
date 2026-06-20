# ReaLab Experimental PrecisEQ Repository

This repository hosts experimental PrecisEQ-Pro earphone/device calibration FIRs generated from ReaLab embedded measurement data.

## PrecisEQ repository URL

Import this URL in PrecisEQ:

```text
https://raw.githubusercontent.com/feriaref/preciseq-realab/main/RepositoryFiles/
```

`RepositoryFiles/` contains `headphone_list.json`, `repo_info.json`, and the four required WAV sample-rate variants for each calibration entry.

> Naming note: `RepositoryFiles/headphone_list.json` is the official PrecisEQ schema filename. In this repo, an "entry" can be an in-ear/TWS product or an over-ear product; AirPods are `type: 0` in-ear/TWS entries, not over-ear headphones.

## Included calibration entries

| ID | PrecisEQ type | Product / state | Source | Selected measured response | Firmware | Notes |
|---|---:|---|---|---|---|---|
| `appleairpodspro2anconbk5128volume6` | 0 in-ear/TWS | Apple AirPods Pro 2, ANC on | https://www.realab.com/data/1730138728611.html | `Volume-6_ANC on（B&K 5128）` | 8A356 | Experimental flat/zero-target FIR |
| `appleairpodspro3anconbk5128vol6` | 0 in-ear/TWS | Apple AirPods Pro 3, ANC on | https://www.realab.com/data/1758317057514.html | `Volume-6_ANC on（B&K 5128）` | 8A357 | Experimental flat/zero-target FIR |
| `nothingheadphone1anconbk5128balanced` | 2 over-ear closed | Nothing Headphone (1), ANC on, Balanced | https://www.realab.com/data/1752865578437.html | `平衡_ANC on（B&K 5128）` | — | Experimental flat/zero-target FIR |
| `nothingheadphone1anconbk5128bassboost` | 2 over-ear closed | Nothing Headphone (1), ANC on, Bass Boost | https://www.realab.com/data/1752865578437.html | `低音增强_ANC on（B&K 5128）` | — | Experimental flat/zero-target FIR |
| `nothingheadphone1anconbk5128trebleboost` | 2 over-ear closed | Nothing Headphone (1), ANC on, Treble Boost | https://www.realab.com/data/1752865578437.html | `高音增强_ANC on（B&K 5128）` | — | Experimental flat/zero-target FIR |

## FIR semantics

- PrecisEQ type mapping: `0` in-ear/TWS, `1` over-ear open, `2` over-ear closed.
- FIR generation: AutoEq minimum phase, 44.1/48/96/192 kHz; packaged WAVs are normalized to the PrecisEQ repository standard of -12 dB pre-gain at 1 kHz.
- Repository WAV style: official-compatible 32-bit float PCM (`pcm_f32le`), stereo, 16384 taps per sample rate.
- Target baked into FIR: AutoEq zero/flat target.
- ReaLab `Target Response(2024)` / grey dotted target curves are **not** baked into the FIRs.
- B&K 5128 → PrecisEQ/oratory/B&K4195 compensation is unresolved. Treat these entries as experimental.

## Separate target curve material

ReaLab page `target_data` is exported separately under:

```text
target_curve_reference_material/
```

Those files are target frequency-response curves, not corrected product measurements. APK string analysis suggests PrecisEQ target sharing/import can use a `preciseq-target:` QR payload with serialized parametric target bands (`s`, `c`, `n`, `d`, `b`, `f`, `g`, `q`, `t`), but direct dense CSV target-response import has not been proven.

## Reproducible import workflow

A reusable importer is included:

```bash
/tmp/preciseq_py311_fixed/bin/python scripts/import_realab.py <REALAB_URL>
```

Pipeline:

```text
ReaLab URL
→ fetch HTML
→ parse window.__INITIAL_DATA__
→ archive source_pages/<slug>/{source.html,initial_data.json,metadata.json}
→ select Frequency Response curve, preferring Volume-6 when present
→ export AutoEq-compatible measurement CSV
→ run AutoEq zero/flat target FIR generation
→ copy WAVs into RepositoryFiles/<id>_<version>_{44,48,96,192}.wav
→ update official-schema headphone_list.json, repo_info.json, target_curve_reference_material, MANIFEST.json
```

Then verify and push:

```bash
python3 - <<'PY'
import json, wave
from pathlib import Path
base=Path('.')
for e in json.load(open('RepositoryFiles/headphone_list.json', encoding='utf-8')):
    for short, rate in [('44',44100),('48',48000),('96',96000),('192',192000)]:
        p=base/'RepositoryFiles'/f"{e['id']}_{e['version']}_{short}.wav"
        with wave.open(str(p),'rb') as w:
            assert w.getnchannels()==2 and w.getsampwidth()==4 and w.getframerate()==rate
print('OK')
PY

git add . && git commit -m "Import <product> from ReaLab" && git push
```
