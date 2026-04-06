# Troubleshooting

## Klipper won't start after install — `IndexError: list index out of range`

The `[restore_bed_mesh]` section in `printer.cfg` is fine — but if you accidentally named it something starting with `bed_mesh` (e.g. `[bed_mesh_override]`), Klipper's `bed_mesh.ProfileManager` picks it up as a profile and crashes trying to split the name on a space character.

**Fix:** the section name MUST start with `restore_` or some other prefix that does NOT start with `bed_mesh`. Use `[restore_bed_mesh]` exactly as shown.

## Klipper starts but log doesn't show "BED_MESH_CALIBRATE re-registered"

Means the extras module didn't load. Check:

1. The file is at `/usr/share/klipper/klippy/extras/restore_bed_mesh.py` (correct path)
2. The file parses cleanly: `python3 -c "import ast; ast.parse(open('/usr/share/klipper/klippy/extras/restore_bed_mesh.py').read())"`
3. The `[restore_bed_mesh]` section exists in `printer.cfg`
4. The section is AFTER `[bed_mesh]` and `[prtouch_v3]` sections (ordering doesn't strictly matter for `klippy:connect` handlers, but it's a sanity check)
5. Klipper actually restarted (not just `RESTART` from console — do a full `/etc/init.d/klipper restart`)

## Mesh still does a full 7×7 / 11×11

Check the gcode console during a slicer-initiated print. You should see:

```
// Adaptive mesh: (113.0,113.0)..(147.0,147.0) probe=4x4
```

If you don't see this M118 line:

- The slicer didn't pass `MESH_MIN`/`MESH_MAX` params. Verify your slicer's start gcode matches the template in `slicer/orca-start-gcode.txt` and the placeholders are getting substituted (open the sliced .gcode in a text editor and search for `START_PRINT` — it should have concrete numbers, not `[adaptive_bed_mesh_min]`).
- Your `START_PRINT` macro doesn't have the adaptive mesh block. Re-check `macros/gcode_macro_snippets.cfg` step 3c.
- master-server's mesh fired but our hijack didn't intercept it (check that you replaced both `G29` AND `BED_MESH_CALIBRATE_START_PRINT`).

## "Unknown command: M118"

You don't have the `[respond]` section in `printer.cfg`. M118 is provided by the `respond` module which needs to be enabled. Add this to `printer.cfg`:

```ini
[respond]
```

## Mesh is adaptive but not centred on my print

Check the slicer's bed mesh settings:

- **Bed mesh min**: `5, 5` (or your printer's `[bed_mesh] mesh_min`)
- **Bed mesh max**: `255, 255` (or your printer's `[bed_mesh] mesh_max`)
- **Bed size in printer settings**: 260 × 260 for K2 standard. **NOT** 350 × 350 (that's K2 Plus). Wrong bed size = wrong placeholder values.

## Touchscreen prints don't work

Our `START_PRINT` mesh block runs in BOTH `prepare==0` (slicer) and `prepare==1` (touchscreen) paths. If a touchscreen print fails:

- Check it's not because the mesh block crashed — look for `Adaptive mesh:` M118 in the log followed by an error.
- The touchscreen path may pre-load a saved mesh; our `BED_MESH_CLEAR` + fresh probe replaces it. This is intentional but means the touchscreen takes ~30 seconds longer to start. To skip the mesh on touchscreen prints, modify START_PRINT to only run the mesh block when `params.MESH_MIN is defined` (slicer prints only), not on the fallback path.

## "BED_MESH_CALIBRATE_START_PRINT" still triggers a real mesh

Check that you replaced the macro body, not just the description. The body should be 4 lines (`BED_MESH_CLEAR`, two `M118`s, that's it). If your replacement still has `BED_MESH_CALIBRATE` inside it, that's the original Creality version still in the file.

## My print quality didn't improve

Adaptive mesh helps when:

- The bed has measurable variation across its surface (>0.05 mm range)
- Your prints are small/medium-sized so they only need a fraction of the bed
- Your first layer height is small enough that mesh compensation matters (≤0.2 mm)

If your bed is already perfectly flat (mesh range under 0.03 mm) and your prints fill the whole bed, adaptive mesh saves time but the quality difference is invisible.

If first layers are still bad, the issue isn't bed mesh — it's:

- Mechanical bed level (use `SCREWS_TILT_CALCULATE` and adjust the screws — see Klipper docs)
- Z offset (adjust with `SET_GCODE_OFFSET Z=...`)
- First layer extrusion settings (multiplier, height, speed)
- Build plate cleanliness

## I want to roll back

```sh
ssh root@192.168.x.x
cd /mnt/UDISK/printer_data/config
cp gcode_macro.cfg.bak.before-adaptive-mesh gcode_macro.cfg
cp printer.cfg.bak.before-adaptive-mesh printer.cfg
rm /usr/share/klipper/klippy/extras/restore_bed_mesh.py
/etc/init.d/klipper restart
```

You're back to stock Creality behavior.

## How do I know which Creality firmware version I'm on?

```sh
ssh root@192.168.x.x "uname -a; cat /usr/data/creality/factory_data 2>/dev/null | head; md5sum /usr/bin/master-server"
```

The `md5sum /usr/bin/master-server` is the most useful — if you compare against the README's "tested-against" md5 and they don't match, you're on a different build and there's a small chance the response handshake or command names have changed.
