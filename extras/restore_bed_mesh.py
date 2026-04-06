# Bed mesh override — restores upstream BED_MESH_CALIBRATE handler.
#
# Creality's prtouch_v3_wrapper.so registers its own cmd_BED_MESH_CALIBRATE
# which ignores MESH_MIN, MESH_MAX, PROBE_COUNT runtime parameters and
# crashes with IndexError when they are passed. This module re-registers
# the upstream bed_mesh.py BedMeshCalibrate.cmd_BED_MESH_CALIBRATE so that
# adaptive bed mesh works.
#
# Loaded via [bed_mesh_override] in printer.cfg, AFTER [bed_mesh] and
# [prtouch_v3] sections so it can override their registration.
#
# 2026-04-06
import logging

class BedMeshOverride:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.printer.register_event_handler(
            "klippy:connect", self._handle_connect)

    def _handle_connect(self):
        try:
            gcode = self.printer.lookup_object('gcode')
            bed_mesh = self.printer.lookup_object('bed_mesh')
            bmc = getattr(bed_mesh, 'bmc', None)
            if bmc is None:
                logging.error(
                    "bed_mesh_override: bed_mesh.bmc not found, abort")
                return
            cmd = getattr(bmc, 'cmd_BED_MESH_CALIBRATE', None)
            help_text = getattr(
                bmc, 'cmd_BED_MESH_CALIBRATE_help',
                "Perform Mesh Bed Leveling")
            if cmd is None:
                logging.error(
                    "bed_mesh_override: cmd_BED_MESH_CALIBRATE not found, "
                    "abort")
                return
            # Unregister whatever was registered (the wrapper's version),
            # then register the upstream handler.
            try:
                gcode.register_command('BED_MESH_CALIBRATE', None)
            except Exception:
                pass
            gcode.register_command(
                'BED_MESH_CALIBRATE', cmd, desc=help_text)
            logging.info(
                "bed_mesh_override: BED_MESH_CALIBRATE re-registered to "
                "upstream bed_mesh.BedMeshCalibrate.cmd_BED_MESH_CALIBRATE")
        except Exception:
            logging.exception("bed_mesh_override: failed to override")

def load_config(config):
    return BedMeshOverride(config)
