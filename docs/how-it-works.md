# How K2-Adaptive-BedMesh works

A walkthrough of the wrapper hijack mechanism, why each piece exists, and how to apply the same pattern to other Creality `.so`-overridden commands.

## The original problem

Creality's K2 ships with three things stacked on top of vanilla Klipper that defeat adaptive bed mesh:

### 1. `prtouch_v3_wrapper.so` hijacks `BED_MESH_CALIBRATE`

`klippy/extras/prtouch_v3.py` is a 31-line shim that loads the compiled wrapper:

```python
from . import prtouch_v3_wrapper
from . import probe as probes

def load_config(config):
    prtouch = prtouch_v3_wrapper.PRTouchEndstopWrapper(config)
    config.get_printer().add_object('axis_twist_compensation', prtouch)
    config.get_printer().add_object('probe', probes.PrinterProbe(config, prtouch))
    return prtouch
```

`PRTouchEndstopWrapper.__init__` (inside the binary) calls `gcode.register_command('BED_MESH_CALIBRATE', self.cmd_BED_MESH_CALIBRATE, ...)`, replacing whatever `bed_mesh.py` registered moments earlier.

The wrapper's `cmd_BED_MESH_CALIBRATE`:
- Ignores `MESH_MIN`/`MESH_MAX`/`PROBE_COUNT` runtime parameters.
- Falls back to a hardcoded full mesh based on the static `[bed_mesh]` config.
- Crashes with `IndexError: list index out of range` at line 1922 if you do pass adaptive params.
- Accepts `GCODE_FILE='...'` as an undocumented parameter but ignores it for adaptivity (it appears to read the file headers only for collision-checking, not for shrinking the mesh area).

### 2. `master-server` independently triggers full meshes

`/usr/bin/master-server` is the proprietary C++ daemon that drives the touchscreen UI and the Creality print pipeline. It contains hardcoded calls to `G29 BED_TEMP=NN` and `BED_MESH_CALIBRATE GCODE_FILE='...'`, fired from `Control/AppModeSdPrint.c` and `Control/PrintfManager.c`. It uses an internal state machine (`bed_mesh_calibate_state` — sic, the typo is in the binary — and `forced_leveling`) to decide when to mesh.

Crucially, **master-server fires its mesh call independently of any slicer pipeline**. Sending prints via Moonraker upload doesn't bypass it. Even if your `START_PRINT` macro runs adaptive mesh perfectly, master-server has already triggered a full one a moment earlier.

### 3. Section name collision

Klipper's `bed_mesh.ProfileManager` iterates `config.get_prefix_sections('bed_mesh')` and assumes every match is a `[bed_mesh <profile_name>]` block, doing `name.split(' ', 1)[1]`. If you name your override section `[bed_mesh_override]`, the split returns a single-element list and `[1]` raises `IndexError` during connect, killing Klipper at startup. The fix is to use a section name that does NOT start with `bed_mesh`.

## The three-part solution

### Part 1: re-register `BED_MESH_CALIBRATE` to the upstream handler

`extras/restore_bed_mesh.py` is a small extras module that runs on the `klippy:connect` event:

```python
gcode = self.printer.lookup_object('gcode')
bed_mesh = self.printer.lookup_object('bed_mesh')
bmc = bed_mesh.bmc                           # the BedMeshCalibrate object
gcode.register_command('BED_MESH_CALIBRATE', None)            # unregister
gcode.register_command('BED_MESH_CALIBRATE',
                       bmc.cmd_BED_MESH_CALIBRATE,
                       desc=bmc.cmd_BED_MESH_CALIBRATE_help)  # re-register upstream
```

This relies on a critical insight: **Creality only overrode the gcode command registration, not the underlying `BedMeshCalibrate` class**. The upstream `cmd_BED_MESH_CALIBRATE` method is still alive and well at `printer.lookup_object('bed_mesh').bmc.cmd_BED_MESH_CALIBRATE`. We just have to grab it and re-register it.

The probe object stays the prtouch_v3 wrapper's `PRTouchEndstopWrapper` (registered as `probe`), so when upstream `bed_mesh.py` calls `probe.run_probe()` it goes through Creality's strain-gauge sensor code as normal. Only the high-level adaptive logic is upstream's.

The `klippy:connect` event handler ensures we run AFTER `prtouch_v3.py` has loaded and AFTER the wrapper has registered its command. We unregister, then re-register. Klipper is happy with this pattern.

### Part 2: hijack `G29` and `BED_MESH_CALIBRATE_START_PRINT`

Both macros live in `gcode_macro.cfg` (Creality's config file). master-server calls `G29` (from `PrintfManager.c:604`) and sometimes `BED_MESH_CALIBRATE_START_PRINT` (from `AppModeSdPrint.c`). We replace both bodies with no-ops that just emit a fake `[G29_TIME]Execution time: 0.0 seconds` line, because master-server's response parser (in `GcodeCmdResAnl.c`) scans for that exact prefix as the "mesh complete" handshake. If it doesn't see it, master-server may stall waiting forever.

We also `BED_MESH_CLEAR` inside the hijacked macros so any previously-loaded saved profile is wiped before the real adaptive mesh runs.

### Part 3: do the real adaptive mesh inside `START_PRINT`

`START_PRINT` runs from inside the gcode file, AFTER:
- master-server has fired its (now no-op) `G29`
- the slicer's `EXCLUDE_OBJECT_DEFINE` lines have been processed
- the bed and hotend are heated to working temperatures

…and importantly, the slicer can pass `MESH_MIN`/`MESH_MAX`/`PROBE_COUNT` as `START_PRINT` parameters by substituting placeholders into the start gcode template. Orca's `[adaptive_bed_mesh_min]`, `[adaptive_bed_mesh_max]`, `[bed_mesh_probe_count]` are exactly the right inputs.

The adaptive mesh block we inject into `START_PRINT` reads those params, validates them, and calls:

```
BED_MESH_CALIBRATE MESH_MIN=113,113 MESH_MAX=147,147 PROBE_COUNT=4,4
```

…which now goes to upstream `bed_mesh.py`'s `cmd_BED_MESH_CALIBRATE` (thanks to part 1) and does a real adaptive mesh.

## End-to-end flow

1. User uploads gcode to printer via Orca network upload (or touchscreen — same flow either way)
2. Klipper's `virtual_sdcard` starts streaming the file
3. Slicer header runs: `EXCLUDE_OBJECT_DEFINE` lines populate `printer.exclude_object.objects`
4. master-server fires `G29 BED_TEMP=55` → our hijacked G29 sets bed temp, homes XY if needed, clears mesh, emits `[G29_TIME]` for master-server, returns
5. master-server is satisfied, allows the print to proceed
6. The next gcode line is `START_PRINT EXTRUDER_TEMP=220 BED_TEMP=55 MESH_MIN=113 MESH_MAX=147 PROBE_COUNT=4` — our START_PRINT runs
7. START_PRINT heats, homes, then enters its adaptive mesh block
8. `BED_MESH_CALIBRATE MESH_MIN=113,113 MESH_MAX=147,147 PROBE_COUNT=4,4` is called
9. The override (part 1) routes this to upstream `cmd_BED_MESH_CALIBRATE`
10. Upstream code generates a 4×4 adaptive mesh, calls `probe.run_probe()` 16 times via the prtouch wrapper
11. Mesh is saved as `[bed_mesh default]`, fade-in/fade-out applied as the print starts
12. Print proceeds with a tightly-fitted mesh under the actual print area

## Generalising the pattern

The same hijack pattern works for any other Creality `.so`-wrapped command. The recipe is:

1. Find the upstream class that originally registered the command (`grep` Creality's `bed_mesh.py` or equivalent for the `register_command` call).
2. Note the attribute path (`bed_mesh.bmc.cmd_BED_MESH_CALIBRATE` in our case).
3. Write a tiny extras module that, on `klippy:connect`, unregisters and re-registers the command using that attribute.
4. Make sure your section name doesn't collide with a `get_prefix_sections` lookup elsewhere in Klipper.
5. If a Creality C++ daemon also fires the command directly, hijack the corresponding `gcode_macro` to no-op + emit whatever response handshake the daemon's parser expects.

## Caveats and assumptions

- This depends on Creality keeping the `bed_mesh.bmc` attribute name. If they ever rename it in a future firmware update, the override silently fails to find it and falls back to the wrapper. The code logs an error in this case.
- The hijacked `G29` and `BED_MESH_CALIBRATE_START_PRINT` emit a `[G29_TIME]` with `0.0 seconds` — if a future master-server build cares about the actual time value being plausible, we'd need to fake a more realistic number.
- We don't know what side effects the wrapper's `cmd_BED_MESH_CALIBRATE` was doing internally that the upstream version skips (e.g. flash writes, motor preload). Empirically the override-driven flow works and produces clean meshes, but there could be edge cases we haven't hit.
- The `prtouch_v3_wrapper.so` is still in the loaded module set — we're not removing it, just avoiding its `cmd_BED_MESH_CALIBRATE` entry point. The probe object it provides is still in use.

## Source references

Key locations in the printer's filesystem:

| Path | Purpose |
|---|---|
| `/usr/share/klipper/klippy/extras/bed_mesh.py` | Upstream Klipper bed mesh — has `BedMesh.bmc.cmd_BED_MESH_CALIBRATE` |
| `/usr/share/klipper/klippy/extras/prtouch_v3.py` | 31-line shim that loads the wrapper |
| `/usr/share/klipper/klippy/extras/prtouch_v3_wrapper.cpython-39.so` | Compiled wrapper that hijacks BED_MESH_CALIBRATE |
| `/usr/bin/master-server` | C++ daemon that fires G29 + BED_MESH_CALIBRATE during print prep |
| `/mnt/UDISK/printer_data/config/gcode_macro.cfg` | Where G29 / BED_MESH_CALIBRATE_START_PRINT / START_PRINT live |
| `/mnt/UDISK/printer_data/config/printer.cfg` | Where `[restore_bed_mesh]` gets added |
