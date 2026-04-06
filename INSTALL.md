# Installation

These instructions assume:

- A Creality K2 (260 mm standard) on stock firmware
- SSH access to the printer (default `root@192.168.x.x`, password from your firmware notes)
- Klipper config files at `/mnt/UDISK/printer_data/config/`
- Klipper extras at `/usr/share/klipper/klippy/extras/`
- A slicer that supports adaptive bed mesh placeholders (OrcaSlicer 2.x recommended)

**Back up your `printer.cfg` and `gcode_macro.cfg` before starting.** Klipper auto-creates a backup before each `SAVE_CONFIG`, but a manual copy is cheap insurance:

```sh
ssh root@192.168.x.x
cd /mnt/UDISK/printer_data/config
cp printer.cfg printer.cfg.bak.before-adaptive-mesh
cp gcode_macro.cfg gcode_macro.cfg.bak.before-adaptive-mesh
```

## Step 1 — Copy the extras module

From the directory where you cloned this repo:

```sh
scp extras/restore_bed_mesh.py root@192.168.x.x:/usr/share/klipper/klippy/extras/restore_bed_mesh.py
```

Verify it's in place:

```sh
ssh root@192.168.x.x "ls -la /usr/share/klipper/klippy/extras/restore_bed_mesh.py && python3 -c 'import ast; ast.parse(open(\"/usr/share/klipper/klippy/extras/restore_bed_mesh.py\").read()); print(\"parse OK\")'"
```

You should see the file listed and `parse OK`.

## Step 2 — Add `[restore_bed_mesh]` to printer.cfg

Edit `/mnt/UDISK/printer_data/config/printer.cfg` and add a single line **after** the `[bed_mesh]` and `[prtouch_v3]` (or `[prtouch_v2]`) sections. A clean spot is right after `[exclude_object]`:

```ini
[exclude_object]

[restore_bed_mesh]
```

> **Important:** the section name must NOT start with `bed_mesh`. Names like `[bed_mesh_override]` will crash Klipper at startup with `IndexError: list index out of range` because Klipper's `bed_mesh.ProfileManager` calls `config.get_prefix_sections('bed_mesh')` and tries to split each match on a space character. `restore_bed_mesh` is safe.

## Step 3 — Replace the macros in gcode_macro.cfg

Open `macros/gcode_macro_snippets.cfg` from this repo and follow the three replacements inside it:

### 3a. Replace `[gcode_macro G29]`

Find your existing `[gcode_macro G29]` block in `gcode_macro.cfg` (it usually starts around line 943–960 in stock Creality firmware) and replace it with the version from `gcode_macro_snippets.cfg`. The new version is a no-op that defers the mesh and emits a fake `[G29_TIME]` log line so master-server is satisfied.

### 3b. Replace `[gcode_macro BED_MESH_CALIBRATE_START_PRINT]`

Find your existing `[gcode_macro BED_MESH_CALIBRATE_START_PRINT]` block (usually around line 1032 in stock firmware) and replace it the same way.

### 3c. Insert the adaptive mesh block into `[gcode_macro START_PRINT]`

Find your existing `[gcode_macro START_PRINT]`. Inside its `gcode:` body, locate the `{% endif %}` that closes the `prepare == 0` / `prepare == 1` if/else block. Right after that `{% endif %}`, before the next `M140 S{params.BED_TEMP}` line, insert the adaptive mesh block from `gcode_macro_snippets.cfg`.

The result should look something like:

```jinja
  {% if printer['gcode_macro START_PRINT'].prepare|int == 0 %}
    ... slicer-path prep ...
    G28 Z
  {% else %}
    PRINT_PREPARE_CLEAR
  {% endif %}

  {% if params.MESH_MIN is defined and params.MESH_MAX is defined %}
    {% set bmin = params.MESH_MIN|float %}
    ... rest of the adaptive mesh block ...
  {% endif %}

  M140 S{params.BED_TEMP}
  ... rest of START_PRINT ...
```

## Step 4 — Update your slicer's start gcode

For OrcaSlicer, paste the contents of `slicer/orca-start-gcode.txt` into:

**Printer Settings → Machine G-code → Machine start G-code**

Then in **Print Settings → Others → Bed mesh**:

- Bed mesh min: `5, 5`
- Bed mesh max: `255, 255`
- Probe point distance: `50, 50`
- Mesh margin: `5`

For other slicers, you need three placeholders in your `START_PRINT` call:
- `MESH_MIN=` ← lower bound of print bounding box (single value, applied to both axes)
- `MESH_MAX=` ← upper bound of print bounding box (single value, applied to both axes)
- `PROBE_COUNT=` ← number of probes per axis

PrusaSlicer/SuperSlicer have similar adaptive mesh placeholders; the macro reads them by name from the START_PRINT params.

## Step 5 — Restart Klipper and verify

```sh
ssh root@192.168.x.x "/etc/init.d/klipper restart"
```

Wait ~10 seconds, then check the log for the override message:

```sh
ssh root@192.168.x.x "tail -200 /mnt/UDISK/printer_data/logs/klippy.log | grep restore_bed_mesh"
```

You should see:

```
[INFO] restore_bed_mesh: BED_MESH_CALIBRATE re-registered to upstream
                        bed_mesh.BedMeshCalibrate.cmd_BED_MESH_CALIBRATE
```

That's the override having taken effect. Slice a small print and send it. Watch the gcode console — you should see the macro fire with concrete adaptive bounds:

```
// Adaptive mesh: (113.0,113.0)..(147.0,147.0) probe=4x4
Generating new points...
```

Followed by the probe walking only the print area.

## Reverting

Three things to undo:

1. Delete the file: `rm /usr/share/klipper/klippy/extras/restore_bed_mesh.py`
2. Remove `[restore_bed_mesh]` from `printer.cfg`
3. Restore the original `gcode_macro.cfg` from your backup
4. Restart Klipper

That fully reverts to stock Creality behavior.

## Troubleshooting

If the override doesn't load, the log shows `IndexError` at startup, or your prints still do a full mesh, see [`docs/troubleshooting.md`](docs/troubleshooting.md).
