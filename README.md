# K2-Adaptive-BedMesh

True adaptive bed mesh on the Creality K2 (and K2 Plus / K1 / K1C — see compatibility), unlocked by bypassing Creality's hardcoded `prtouch_v3_wrapper.so` override of `BED_MESH_CALIBRATE`.

## What this gives you

For a 30 mm calibration cube, your K2 used to probe a fixed **7×7 = 49-point full-bed mesh** taking ~108 seconds, even though only a tiny patch in the centre actually needed measurement. With this installed, the same cube triggers a **4×4 = 16-point mesh covering only the print area** in roughly a third of the time, with **~3.7×** higher mesh density right under your part.

The mesh **follows the print** — slice the cube in a corner and the mesh probes the corner. Slice three small parts spread across the bed and the mesh covers their union bounding box. Big prints still get a full 7×7. The slicer figures out the bounding box, the macro on the printer turns it into a real adaptive `BED_MESH_CALIBRATE` call, and Klipper's upstream bed_mesh code does the rest.

## Why this exists

Creality ships the K2 with `klippy/extras/prtouch_v3_wrapper.cpython-39.so` — a compiled binary that **hijacks the `BED_MESH_CALIBRATE` gcode command** with a non-adaptive implementation. The wrapper:

1. **Ignores `MESH_MIN`, `MESH_MAX`, `PROBE_COUNT`** runtime parameters and runs a hardcoded full mesh.
2. **Crashes with `IndexError: list index out of range`** at `prtouch_v3_wrapper.py:1922` when those params are passed.
3. **Doesn't honour `GCODE_FILE`** either — even though Creality's own `master-server` C++ daemon passes it, the wrapper falls back to the default full mesh.

On top of that, **Creality's `master-server` daemon (`/usr/bin/master-server`) independently fires `G29 BED_TEMP=NN` and `BED_MESH_CALIBRATE GCODE_FILE='...'`** during print prep, regardless of which slicer you use or whether you upload via Moonraker. So even with a perfect Orca configuration and a perfect `START_PRINT` macro, master-server triggered a full mesh of its own before your code could run.

This repo solves both problems:

1. A small Python module re-registers `BED_MESH_CALIBRATE` to the **upstream Klipper handler** (`bed_mesh.BedMeshCalibrate.cmd_BED_MESH_CALIBRATE`), which honours runtime params correctly. The prtouch hardware (strain-gauge probe) keeps working because only the high-level command logic is replaced — the probe object itself is still the wrapper's.
2. Three macro replacements **defer the mesh** out of master-server's call path and into `START_PRINT`, where the slicer's adaptive parameters are available. `G29` and `BED_MESH_CALIBRATE_START_PRINT` become no-ops that emit a fake `[G29_TIME]` log line so master-server's response parser is satisfied.

The whole thing is **additive and reversible**. No core Klipper files modified, no `.so` binary patching, no firmware flashing. Just three config changes and one drop-in extras module.

## Compatibility

- **Confirmed working**: Creality K2 (260 mm standard) on stock firmware, Klipper version `09faed31-dirty`, master-server build from January 2026 firmware.
- **Should work** (untested, same wrapper architecture): K2 Plus (350 mm), K1, K1C, K1 Max, K1 SE — all use `prtouch_v3_wrapper.so` or its v2 equivalent.
- **Won't help**: printers that don't have Creality's prtouch wrapper. If your `BED_MESH_CALIBRATE` already accepts `MESH_MIN`/`MESH_MAX`/`PROBE_COUNT`, you don't need this.

## Install

See [`INSTALL.md`](INSTALL.md) for the full step-by-step. Short version:

1. Copy `extras/restore_bed_mesh.py` to `/usr/share/klipper/klippy/extras/` on the printer.
2. Add `[restore_bed_mesh]` to `printer.cfg` (after `[bed_mesh]` and `[prtouch_v3]`).
3. Replace your `G29`, `BED_MESH_CALIBRATE_START_PRINT`, and `START_PRINT` macros with the snippets in `macros/gcode_macro_snippets.cfg`.
4. Replace your slicer's start gcode with `slicer/orca-start-gcode.txt` (or the equivalent for your slicer — needs `MESH_MIN`, `MESH_MAX`, `PROBE_COUNT` placeholders).
5. Restart Klipper. Slice and print.

## Verifying it works

After restarting Klipper, the log should contain:

```
restore_bed_mesh: BED_MESH_CALIBRATE re-registered to upstream
                  bed_mesh.BedMeshCalibrate.cmd_BED_MESH_CALIBRATE
```

When you start a sliced print, you should see:

```
// Adaptive mesh: (113.0,113.0)..(147.0,147.0) probe=4x4
Generating new points...
```

…followed by the probe walking only the print area, not the full bed.

If you don't see those messages but you do see `Mesh Bed Leveling Complete` from a 7×7 grid spanning 5..255, the override didn't load correctly — see [`docs/troubleshooting.md`](docs/troubleshooting.md).

## How it works (technical)

See [`docs/how-it-works.md`](docs/how-it-works.md) for the full walkthrough — the wrapper hijack mechanism, the master-server bypass, the section-name-collision footgun, and why `printer.lookup_object('bed_mesh').bmc.cmd_BED_MESH_CALIBRATE` is the right way to grab the upstream handler from inside a custom extras module.

## Acknowledgements

This is built on top of [Klipper](https://www.klipper3d.org/) by Kevin O'Connor and contributors. The bed_mesh module's adaptive support is upstream Klipper code — Creality just stripped/wrapped it. We're putting it back the way Klipper intended.

Big thanks also to the K2/K1 community on Discord and the [pellcorp/creality](https://github.com/pellcorp/creality) project for the early reverse-engineering work that mapped out which Creality binaries do what.

## Licence

GPL v3, matching Klipper. See [`LICENSE`](LICENSE).
