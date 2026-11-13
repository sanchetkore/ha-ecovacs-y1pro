"""DEEBOT Y1 Pro (cqyi87) Runtime Capability Patch for Home Assistant.

This module patches deebot-client in memory when the ecovacs custom component loads:
1. Adds cqyi87 to deebot_client.hardware registry.
2. Injects numeric commands (10001, 10002, 40001, 40013, 40009).
3. Injects numeric telemetry message handlers (10000, 10001).
4. Updates appVersion to 3.17.0 to prevent server 1013 authentication rejections.
"""

from __future__ import annotations

import logging
import time
from abc import ABC
from dataclasses import dataclass
from typing import Any

_LOGGER = logging.getLogger(__name__)

_PATCHED = False


def apply_patch() -> None:
    global _PATCHED
    if _PATCHED:
        return

    _LOGGER.info("Applying DEEBOT Y1 Pro (cqyi87) capability patch to deebot_client...")

    try:
        import deebot_client.authentication as auth_mod
        auth_mod._META["appVersion"] = "3.17.0"

        from deebot_client.capabilities import (
            Capabilities,
            CapabilityClean,
            CapabilityCleanAction,
            CapabilityCustomCommand,
            CapabilityEvent,
            CapabilityExecute,
            CapabilityLifeSpan,
            CapabilitySet,
            CapabilitySetEnable,
            CapabilitySettings,
            CapabilitySetTypes,
            CapabilityStats,
            CapabilityWater,
            DeviceType,
        )
        from deebot_client.const import DataType
        from deebot_client.events import (
            AvailabilityEvent,
            BatteryEvent,
            ChildLockEvent,
            ContinuousCleaningEvent,
            CustomCommandEvent,
            EnableEvent,
            ErrorEvent,
            FanSpeedEvent,
            FanSpeedLevel,
            LifeSpan,
            LifeSpanEvent,
            NetworkInfoEvent,
            ReportStatsEvent,
            StateEvent,
            StatsEvent,
            TotalStatsEvent,
            VolumeEvent,
            water_info,
        )
        from deebot_client.events.base import Event
        import deebot_client.events as events_mod
        from deebot_client.message import HandlingResult, MessageBodyDataDict
        from deebot_client.models import StaticDeviceInfo, State
        from deebot_client.commands.json.common import ExecuteCommand, JsonCommand, JsonGetCommand, JsonSetCommand
        import deebot_client.commands.json as json_cmds
        import deebot_client.messages.json as json_msgs
        import deebot_client.hardware as hw

        # 1. Event definitions
        if not hasattr(events_mod, "DoNotDisturbEvent"):
            @dataclass(frozen=True)
            class DoNotDisturbEvent(EnableEvent):
                """Do not disturb event."""
            setattr(events_mod, "DoNotDisturbEvent", DoNotDisturbEvent)
        else:
            DoNotDisturbEvent = getattr(events_mod, "DoNotDisturbEvent")

        # 2. Native numeric JSON command base
        def native_header() -> dict[str, Any]:
            return {
                "pri": 3,
                "m": "cloudctl",
                "channel": "rop",
                "ver": "0.0.1",
                "tzm": 480,
                "ts": str(int(time.time() * 1000)),
            }

        class NativeJsonCommand(JsonCommand, ABC):
            def _get_payload(self) -> dict[str, Any] | list[Any]:
                return {"header": native_header(), "body": {"data": self._args}}

        class NativeExecuteCommand(NativeJsonCommand, ExecuteCommand, ABC):
            pass

        class NativeGetCommand(NativeJsonCommand, JsonGetCommand, ABC):
            pass

        class NativeSetCommand(NativeExecuteCommand, JsonSetCommand, ABC):
            pass

        # 3. Message handler (10000 / 10001)
        _FAN_MODE_MAP = {
            "quiet": FanSpeedLevel.QUIET,
            "auto": FanSpeedLevel.NORMAL,
            "strong": FanSpeedLevel.MAX,
            "max": FanSpeedLevel.MAX_PLUS,
        }
        _FAN_MODE_REV = {v: k for k, v in _FAN_MODE_MAP.items()}

        _WATER_MODE_MAP = {
            "low": water_info.WaterAmount.LOW,
            "mid": water_info.WaterAmount.MEDIUM,
            "high": water_info.WaterAmount.HIGH,
        }
        _WATER_MODE_REV = {v: k for k, v in _WATER_MODE_MAP.items()}

        class OnNativeInfo(MessageBodyDataDict):
            NAME = "10000"

            @classmethod
            def _handle_body_data_dict(cls, event_bus: Any, data: dict[str, Any]) -> HandlingResult:
                if not isinstance(data, dict):
                    return HandlingResult.success()

                # Status / State
                status = data.get("status")
                charge = data.get("chargeStatus")
                pause = data.get("pauseSwitch")

                if status is not None or charge is not None:
                    s_str = str(status).lower() if status else ""
                    if s_str in ("smartclean", "areaclean", "zoneclean"):
                        if pause is True:
                            state = State.PAUSED
                        else:
                            state = State.CLEANING
                    elif s_str == "gocharge":
                        state = State.RETURNING
                    elif s_str == "idle":
                        state = State.DOCKED if (charge is True) else State.IDLE
                    else:
                        state = State.DOCKED if (charge is True) else State.IDLE

                    event_bus.notify(StateEvent(state))

                # Battery
                if "battery" in data and isinstance(data["battery"], (int, float)):
                    event_bus.notify(BatteryEvent(int(data["battery"])))

                # Fan mode
                if "fanMode" in data and data["fanMode"] in _FAN_MODE_MAP:
                    event_bus.notify(FanSpeedEvent(_FAN_MODE_MAP[data["fanMode"]]))

                # Water mode
                if "waterMode" in data and data["waterMode"] in _WATER_MODE_MAP:
                    event_bus.notify(water_info.WaterAmountEvent(_WATER_MODE_MAP[data["waterMode"]]))

                # Mop state
                if "mopState" in data:
                    event_bus.notify(water_info.MopAttachedEvent(data["mopState"] == "installed"))

                # Consumables
                if "consumables" in data and isinstance(data["consumables"], list):
                    type_map = {
                        "sideBrush": LifeSpan.SIDE_BRUSH,
                        "rollBrush": LifeSpan.BRUSH,
                        "filter": LifeSpan.FILTER,
                        "unitCare": LifeSpan.UNIT_CARE,
                    }
                    for item in data["consumables"]:
                        c_type = item.get("type")
                        if c_type in type_map and "left" in item and "total" in item:
                            left = item["left"]
                            total = item["total"]
                            pct = round((left / total) * 100) if total > 0 else 0
                            event_bus.notify(LifeSpanEvent(type_map[c_type], pct, left))

                # Settings
                if "childLock" in data:
                    event_bus.notify(ChildLockEvent(bool(data["childLock"])))
                if "disturbSwitch" in data:
                    event_bus.notify(DoNotDisturbEvent(bool(data["disturbSwitch"])))
                if "breakCleanSwitch" in data:
                    event_bus.notify(ContinuousCleaningEvent(bool(data["breakCleanSwitch"])))
                if "volume" in data:
                    event_bus.notify(VolumeEvent(int(data["volume"])))

                # Error
                if "error" in data:
                    err_list = data["error"]
                    err_code = err_list[0] if isinstance(err_list, list) and err_list else 0
                    event_bus.notify(ErrorEvent(err_code, f"Error {err_code}"))

                # Network / Device Info
                if "deviceInfo" in data and isinstance(data["deviceInfo"], dict):
                    dev = data["deviceInfo"]
                    event_bus.notify(NetworkInfoEvent(
                        ip=dev.get("ip"),
                        mac=dev.get("mac"),
                        ssid=dev.get("ssid"),
                        rssi=dev.get("rssi"),
                    ))

                return HandlingResult.success()

        # 4. Commands
        class GetNativeInfo(NativeGetCommand, OnNativeInfo):
            NAME = "10001"

            def __init__(self, fields: list[str] | None = None, *, is_available_check: bool = False) -> None:
                if fields is None:
                    fields = [
                        "status", "pauseSwitch", "chargeStatus", "battery",
                        "fanMode", "waterMode", "mopState", "consumables",
                        "deviceInfo", "error", "childLock", "autoBoost",
                        "breakCleanSwitch", "disturbSwitch", "volume",
                    ]
                super().__init__({"fields": list(fields)})
                self._is_available_check = is_available_check

        class NativeStartClean(NativeExecuteCommand):
            NAME = "40001"
            def __init__(self) -> None:
                super().__init__({"act": "start", "mode": "smartClean"})

        class NativePauseClean(NativeExecuteCommand):
            NAME = "40009"
            def __init__(self) -> None:
                super().__init__({"act": "pause"})

        class NativeResumeClean(NativeExecuteCommand):
            NAME = "40001"
            def __init__(self) -> None:
                super().__init__({"act": "resume"})

        class NativeReturnToDock(NativeExecuteCommand):
            NAME = "40013"
            def __init__(self) -> None:
                super().__init__({"act": "goCharge"})

        class NativeLocate(NativeExecuteCommand):
            NAME = "10002"
            def __init__(self) -> None:
                super().__init__({"voiceFind": "start"})

        class NativeSetFanSpeed(NativeSetCommand):
            NAME = "10002"
            def __init__(self, speed: FanSpeedLevel | str) -> None:
                val = _FAN_MODE_REV.get(speed, str(speed))
                super().__init__(GetNativeInfo(["fanMode"]), {"fanMode": val})

        class NativeSetWaterAmount(NativeSetCommand):
            NAME = "10002"
            def __init__(self, amount: water_info.WaterAmount | str) -> None:
                val = _WATER_MODE_REV.get(amount, str(amount))
                super().__init__(GetNativeInfo(["waterMode"]), {"waterMode": val})

        class NativeSetChildLock(NativeSetCommand):
            NAME = "10002"
            def __init__(self, enable: bool) -> None:
                super().__init__(GetNativeInfo(["childLock"]), {"childLock": enable})

        class NativeSetDoNotDisturb(NativeSetCommand):
            NAME = "10002"
            def __init__(self, enable: bool) -> None:
                super().__init__(GetNativeInfo(["disturbSwitch"]), {"disturbSwitch": enable})

        class NativeSetContinuousCleaning(NativeSetCommand):
            NAME = "10002"
            def __init__(self, enable: bool) -> None:
                super().__init__(GetNativeInfo(["breakCleanSwitch"]), {"breakCleanSwitch": enable})

        class NativeSetVolume(NativeSetCommand):
            NAME = "10002"
            def __init__(self, volume: int) -> None:
                super().__init__(GetNativeInfo(["volume"]), {"volume": volume})

        class NativeResetLifeSpan(NativeExecuteCommand):
            NAME = "10002"
            def __init__(self, type_: LifeSpan) -> None:
                rev_types = {
                    LifeSpan.SIDE_BRUSH: "sideBrush",
                    LifeSpan.BRUSH: "rollBrush",
                    LifeSpan.FILTER: "filter",
                    LifeSpan.UNIT_CARE: "unitCare",
                }
                super().__init__({"resetConsumable": rev_types.get(type_, "unitCare")})

        class NativeCustomCommand(NativeExecuteCommand):
            NAME = "10002"
            def __init__(self, command: str, params: dict[str, Any] | None = None) -> None:
                args = {"cmd": command}
                if params:
                    args.update(params)
                super().__init__(args)

        def native_clean(action: Any) -> Any:
            from deebot_client.models import CleanAction
            if action == CleanAction.START:
                return NativeStartClean()
            if action == CleanAction.PAUSE:
                return NativePauseClean()
            if action == CleanAction.RESUME:
                return NativeResumeClean()
            if action == CleanAction.STOP:
                return NativeReturnToDock()
            return NativeStartClean()

        # 5. Register in commands and messages tables
        json_cmds.COMMANDS["10001"] = GetNativeInfo
        json_cmds.COMMANDS["40001"] = NativeStartClean
        json_cmds.COMMANDS["40009"] = NativePauseClean
        json_cmds.COMMANDS["40013"] = NativeReturnToDock
        json_cmds.COMMANDS["10002"] = NativeCustomCommand

        json_msgs.MESSAGES["10000"] = OnNativeInfo
        json_msgs.MESSAGES["10001"] = GetNativeInfo

        # 6. Capabilities definition
        life_span_types = (
            LifeSpan.BRUSH,
            LifeSpan.FILTER,
            LifeSpan.SIDE_BRUSH,
            LifeSpan.UNIT_CARE,
        )

        capabilities = Capabilities(
            device_type=DeviceType.VACUUM,
            availability=CapabilityEvent(
                AvailabilityEvent, [GetNativeInfo(["battery"], is_available_check=True)]
            ),
            battery=CapabilityEvent(BatteryEvent, [GetNativeInfo(["battery"])]),
            charge=CapabilityExecute(NativeReturnToDock),
            clean=CapabilityClean(
                action=CapabilityCleanAction(command=native_clean),
                continuous=CapabilitySetEnable(
                    ContinuousCleaningEvent,
                    [GetNativeInfo(["breakCleanSwitch"])],
                    NativeSetContinuousCleaning,
                ),
            ),
            custom=CapabilityCustomCommand(
                event=CustomCommandEvent, get=[], set=NativeCustomCommand
            ),
            error=CapabilityEvent(ErrorEvent, [GetNativeInfo(["error"])]),
            fan_speed=CapabilitySetTypes(
                event=FanSpeedEvent,
                get=[GetNativeInfo(["fanMode"])],
                set=NativeSetFanSpeed,
                types=(
                    FanSpeedLevel.QUIET,
                    FanSpeedLevel.NORMAL,
                    FanSpeedLevel.MAX,
                    FanSpeedLevel.MAX_PLUS,
                ),
            ),
            life_span=CapabilityLifeSpan(
                types=life_span_types,
                event=LifeSpanEvent,
                get=[GetNativeInfo(["consumables"])],
                reset=NativeResetLifeSpan,
            ),
            network=CapabilityEvent(NetworkInfoEvent, [GetNativeInfo(["deviceInfo"])]),
            play_sound=CapabilityExecute(NativeLocate),
            settings=CapabilitySettings(
                child_lock=CapabilitySetEnable(
                    ChildLockEvent,
                    [GetNativeInfo(["childLock"])],
                    NativeSetChildLock,
                ),
                do_not_disturb=CapabilitySetEnable(
                    DoNotDisturbEvent,
                    [GetNativeInfo(["disturbSwitch"])],
                    NativeSetDoNotDisturb,
                ),
                volume=CapabilitySet(
                    VolumeEvent,
                    [GetNativeInfo(["volume"])],
                    NativeSetVolume,
                ),
            ),
            state=CapabilityEvent(StateEvent, [GetNativeInfo()]),
            stats=CapabilityStats(
                clean=CapabilityEvent(StatsEvent, [GetNativeInfo(["cleanArea", "cleanTime"])]),
                report=CapabilityEvent(ReportStatsEvent, []),
                total=CapabilityEvent(TotalStatsEvent, []),
            ),
            water=CapabilityWater(
                amount=CapabilitySetTypes(
                    event=water_info.WaterAmountEvent,
                    get=[GetNativeInfo(["waterMode"])],
                    set=NativeSetWaterAmount,
                    types=(
                        water_info.WaterAmount.LOW,
                        water_info.WaterAmount.MEDIUM,
                        water_info.WaterAmount.HIGH,
                    ),
                ),
                mop_attached=CapabilityEvent(
                    water_info.MopAttachedEvent, [GetNativeInfo(["mopState"])]
                ),
            ),
        )

        cqyi87_device = StaticDeviceInfo(DataType.JSON, capabilities)
        hw._DEVICES["cqyi87"] = cqyi87_device

        _PATCHED = True
        _LOGGER.info("DEEBOT Y1 Pro (cqyi87) patch applied successfully!")

    except Exception as ex:
        _LOGGER.error("Failed applying cqyi87 patch: %s", ex, exc_info=True)
