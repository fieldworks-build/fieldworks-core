"""
Static MQTT + OPC-UA snapshot for a legacy WTP installation.

Messiness types present:
  - Abbreviated attributes: RawWater_02 uses FLW/PRS/PWR/RUN instead of Flow/Pressure/Power/Running
  - Ghost tag: OldPump_03 — decommissioned pump, stale zero-value publish, absent from OPC-UA
  - Duplicate sensors: RawWater_01 has Flow + FlowPrimary + FlowBackup
  - Deprecated alias: Clarifier_01/TRBD alongside Clarifier_01/Turbidity
  - Non-standard depth: HS_Pump_1 published at 3 levels (WTP/HS_Pump_1/attr) instead of 5
  - Ambiguous equipment: ABB_Drive_01 has no equipment type in the template
  - Retired UV bank: UV_03 publishes constant 0.0 / false, not in OPC-UA
  - Vendor-prefixed namespace: HS_Pump_2 under Siemens/S7/Pump/
  - Missing required attr: pH absent from FinishedWater_01 MQTT stream (pH_raw/pH_units are non-standard)
  - Flat tags: wtp_rawpump_* — single-level, match no equipment pattern

OPC-UA covers only the well-maintained, still-active equipment. Decommissioned and
legacy-namespace instances are MQTT-only, which is the real-world pattern: OPC-UA servers
get cleaned up before MQTT bridges do.
"""

# Topic strings only — inference.py never reads MQTT payload values, so this is
# a plain list (unlike the waterworks-ai original, which carried string values
# for a dict-shaped mqtt_topics param that's since been simplified to list[str]).
LEGACY_TOPICS: list[str] = [
    # ── Clean pump — all standard attrs + duplicate flow sensors ────────────────
    "Plant/WTP/Pump/RawWater_01/Flow",
    "Plant/WTP/Pump/RawWater_01/Pressure",
    "Plant/WTP/Pump/RawWater_01/Power",
    "Plant/WTP/Pump/RawWater_01/Running",
    "Plant/WTP/Pump/RawWater_01/FlowPrimary",
    "Plant/WTP/Pump/RawWater_01/FlowBackup",
    # ── Abbreviated attribute names ──────────────────────────────────────────────
    "Plant/WTP/Pump/RawWater_02/FLW",
    "Plant/WTP/Pump/RawWater_02/PRS",
    "Plant/WTP/Pump/RawWater_02/PWR",
    "Plant/WTP/Pump/RawWater_02/RUN",
    # ── Ghost tag — decommissioned pump, stale zeros, no OPC-UA ─────────────────
    "Plant/WTP/Pump/OldPump_03/Flow",
    "Plant/WTP/Pump/OldPump_03/Pressure",
    # ── Non-standard depth (3 levels) — matches only via legacy_patterns ─────────
    "WTP/HS_Pump_1/Flow",
    "WTP/HS_Pump_1/Pressure",
    "WTP/HS_Pump_1/Running",
    # ── Ambiguous equipment — no matching type in template ───────────────────────
    "Plant/WTP/Drive/ABB_Drive_01/ActualSpeed",
    "Plant/WTP/Drive/ABB_Drive_01/Torque",
    "Plant/WTP/Drive/ABB_Drive_01/Running",
    # ── Clarifier — clean + deprecated alias still publishing ────────────────────
    "Plant/WTP/Clarifier/Clarifier_01/Level",
    "Plant/WTP/Clarifier/Clarifier_01/Turbidity",
    "Plant/WTP/Clarifier/Clarifier_01/TRBD",
    # ── Storage tank — pH absent (sensor offline); non-standard pH attrs present ─
    "Plant/WTP/StorageTank/FinishedWater_01/Level",
    "Plant/WTP/StorageTank/FinishedWater_01/Turbidity",
    "Plant/WTP/StorageTank/FinishedWater_01/pH_raw",
    "Plant/WTP/StorageTank/FinishedWater_01/pH_units",
    # ── Dosing — clean ────────────────────────────────────────────────────────────
    "Plant/WTP/Dosing/Chlorine_01/FlowRate",
    "Plant/WTP/Dosing/Chlorine_01/TankLevel",
    "Plant/WTP/Dosing/Chlorine_01/Running",
    # ── UV — active bank (clean) + retired bank (constant zero, no OPC-UA) ──────
    "Plant/WTP/UV/UV_01/Intensity",
    "Plant/WTP/UV/UV_01/LampHours",
    "Plant/WTP/UV/UV_01/Running",
    "Plant/WTP/UV/UV_03/Intensity",
    "Plant/WTP/UV/UV_03/LampHours",
    "Plant/WTP/UV/UV_03/Running",
    # ── Vendor-prefixed namespace — Siemens S7 OPC-UA bridge, wrong root ─────────
    "Siemens/S7/Pump/HS_Pump_2/Speed_rpm",
    "Siemens/S7/Pump/HS_Pump_2/Current_mA",
    # ── Flat single-level legacy tags — match no equipment pattern ────────────────
    "wtp_rawpump_flow",
    "wtp_rawpump_pressure",
]

# OPC-UA covers modern, actively maintained equipment only.
# Absent: OldPump_03, HS_Pump_1, RawWater_02, UV_03, HS_Pump_2 (Siemens).
# This asymmetry (MQTT-present + OPC-UA-absent) is the real-world signal for
# decommissioned or legacy-namespace equipment.
LEGACY_OPCUA_NODES: list[str] = [
    "Objects/Plant/WTP/Pump/RawWater_01/Flow",
    "Objects/Plant/WTP/Pump/RawWater_01/Pressure",
    "Objects/Plant/WTP/Pump/RawWater_01/Running",
    "Objects/Plant/WTP/Clarifier/Clarifier_01/Level",
    "Objects/Plant/WTP/Clarifier/Clarifier_01/Turbidity",
    "Objects/Plant/WTP/Dosing/Chlorine_01/FlowRate",
    "Objects/Plant/WTP/Dosing/Chlorine_01/Running",
    "Objects/Plant/WTP/UV/UV_01/Intensity",
    "Objects/Plant/WTP/UV/UV_01/Running",
    "Objects/Plant/WTP/StorageTank/FinishedWater_01/Level",
]
