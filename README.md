# AirPods Pro 3 ReaLab BK5128 Experimental PrecisEQ Repository

This is a local draft repository for PrecisEQ-Pro.

## Repository URL when hosted

Point PrecisEQ at the static directory containing `headphone_list.json`, `repo_info.json`, and WAV files, e.g.:

```text
https://<host>/<repo>/RepositoryFiles/
```

## Headphone FIR semantics

- Product: Apple/苹果 AirPods Pro 3
- Firmware on source page: 8A357
- Measurement source: https://www.realab.com/data/1758317057514.html
- Selected measured response: `Volume-6_ANC on（B&K 5128）`
- PrecisEQ type: `0` in-ear/TWS
- FIR generation: AutoEq minimum phase, 44.1/48/96/192 kHz, `--preamp -11.8`
- Target baked into FIR: zero/flat AutoEq target, not ReaLab Target Response 2024

Important: B&K 5128 → PrecisEQ/oratory/B&K4195 compensation is unresolved. Treat this as experimental.

## Separate target curve material

The page's grey dotted `ReaLab Target Response(2024)` has been exported separately under:

```text
target_import_material/
```

It is a target frequency-response curve, not a corrected headphone measurement.

APK string analysis suggests PrecisEQ target sharing/import also uses a `preciseq-target:` QR payload with serialized parametric target bands (`s`, `c`, `n`, `d`, `b`, `f`, `g`, `q`, `t`). I did not yet prove that full sampled CSV target-response files can be imported directly by the APK.
