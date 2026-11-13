"""DEEBOT Y1 Pro (cqyi87) Runtime Capability Patch for Home Assistant.

This module patches deebot-client in memory when the ecovacs custom component loads:
1. Adds cqyi87 to deebot_client.hardware registry.
2. Injects native numeric commands (10001, 40001, 40009, 40011, 40013, 40019, 50011, 50013, 50017, 50019, 50023, 50025, 50036, 50038).
3. Injects numeric telemetry message handlers (10000, 10001).
4. Updates appVersion to 3.17.0 to prevent server 1013 authentication rejections.
"""

from __future__ import annotations

import logging
import time
from abc import ABC
from dataclasses import dataclass
from types import MappingProxyType
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
        from deebot_client.command import Command, InitParam
        from deebot_client.const import DataType
        from deebot_client.events import (
            AvailabilityEvent,
            BatteryEvent,
            CarpetAutoFanBoostEvent,
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
        from deebot_client.message import HandlingResult, HandlingState, MessageBodyDataDict
        from deebot_client.models import CleanAction, StaticDeviceInfo, State
        from deebot_client.commands.json.common import (
            ExecuteCommand,
            JsonCommand,
            JsonCommandMqttP2P,
            JsonGetCommand,
            JsonSetCommand,
        )
        import deebot_client.commands.json as json_cmds
        import deebot_client.messages.json as json_msgs
        import deebot_client.hardware as hw
        from deebot_client.util import get_enum

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

        # 3. Mappings
        _FAN_TO_NATIVE: dict[FanSpeedLevel, str] = {
            FanSpeedLevel.QUIET: "quiet",
            FanSpeedLevel.NORMAL: "auto",
            FanSpeedLevel.MAX: "strong",
            FanSpeedLevel.MAX_PLUS: "max",
        }
        _FAN_ALIASES: dict[str, FanSpeedLevel] = {
            "quiet": FanSpeedLevel.QUIET,
            "auto": FanSpeedLevel.NORMAL,
            "normal": FanSpeedLevel.NORMAL,
            "strong": FanSpeedLevel.MAX,
            "max": FanSpeedLevel.MAX,
            "max_plus": FanSpeedLevel.MAX_PLUS,
            "maxplus": FanSpeedLevel.MAX_PLUS,
        }
        _FAN_FROM_NATIVE: dict[str, FanSpeedLevel] = {
            "quiet": FanSpeedLevel.QUIET,
            "auto": FanSpeedLevel.NORMAL,
            "strong": FanSpeedLevel.MAX,
            "max": FanSpeedLevel.MAX_PLUS,
        }

        _WATER_TO_NATIVE: dict[water_info.WaterAmount, str] = {
            water_info.WaterAmount.LOW: "low",
            water_info.WaterAmount.MEDIUM: "mid",
            water_info.WaterAmount.HIGH: "high",
        }
        _WATER_ALIASES: dict[str, water_info.WaterAmount] = {
            "low": water_info.WaterAmount.LOW,
            "mid": water_info.WaterAmount.MEDIUM,
            "medium": water_info.WaterAmount.MEDIUM,
            "high": water_info.WaterAmount.HIGH,
        }
        _WATER_FROM_NATIVE: dict[str, water_info.WaterAmount] = {
            "low": water_info.WaterAmount.LOW,
            "mid": water_info.WaterAmount.MEDIUM,
            "high": water_info.WaterAmount.HIGH,
        }

        _RESET_TO_NATIVE: dict[LifeSpan, str] = {
            LifeSpan.BRUSH: "rollBrush",
            LifeSpan.FILTER: "filter",
            LifeSpan.SIDE_BRUSH: "sideBrush",
            LifeSpan.UNIT_CARE: "unitCare",
        }
        _RESET_FROM_NATIVE: dict[str, LifeSpan] = {
            v: k for k, v in _RESET_TO_NATIVE.items()
        }

        _CLEAN_STATUSES = frozenset({"smartclean", "areaclean", "zoneclean"})

        # 4. Message handler (10000 / 10001)
        class OnNativeInfo(MessageBodyDataDict):
            NAME = "10000"

            @classmethod
            def _handle_body_data_dict(cls, event_bus: Any, data: dict[str, Any]) -> HandlingResult:
                if not isinstance(data, dict) or not data:
                    return HandlingResult.success()

                try:
                    event_bus.notify(AvailabilityEvent(available=True))
                except Exception as ex:
                    _LOGGER.debug("AvailabilityEvent notify error: %s", ex)

                # Status / State
                try:
                    status = data.get("status")
                    charge = data.get("chargeStatus")
                    pause = data.get("pauseSwitch")

                    if status is not None or charge is not None:
                        s_str = str(status).lower() if status else ""
                        if s_str in _CLEAN_STATUSES:
                            state = State.PAUSED if pause is True else State.CLEANING
                        elif s_str == "gocharge":
                            state = State.RETURNING
                        elif s_str == "idle":
                            state = State.DOCKED if (charge is True) else State.IDLE
                        else:
                            state = State.DOCKED if (charge is True) else State.IDLE

                        event_bus.notify(StateEvent(state))
                except Exception as ex:
                    _LOGGER.warning("Error parsing status/state in 10001: %s", ex)

                # Battery
                try:
                    if "battery" in data and isinstance(data["battery"], (int, float)):
                        b = int(data["battery"])
                        if 0 <= b <= 100:
                            event_bus.notify(BatteryEvent(b))
                except Exception as ex:
                    _LOGGER.warning("Error parsing battery in 10001: %s", ex)

                # Fan mode
                try:
                    if "fanMode" in data and data["fanMode"] in _FAN_FROM_NATIVE:
                        event_bus.notify(FanSpeedEvent(_FAN_FROM_NATIVE[data["fanMode"]]))
                except Exception as ex:
                    _LOGGER.warning("Error parsing fanMode in 10001: %s", ex)

                # Water mode
                try:
                    if "waterMode" in data and data["waterMode"] in _WATER_FROM_NATIVE:
                        event_bus.notify(water_info.WaterAmountEvent(_WATER_FROM_NATIVE[data["waterMode"]]))
                except Exception as ex:
                    _LOGGER.warning("Error parsing waterMode in 10001: %s", ex)

                # Mop state
                try:
                    if "mopState" in data:
                        event_bus.notify(water_info.MopAttachedEvent(data["mopState"] == "installed"))
                except Exception as ex:
                    _LOGGER.warning("Error parsing mopState in 10001: %s", ex)

                # Consumables
                try:
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
                except Exception as ex:
                    _LOGGER.warning("Error parsing consumables in 10001: %s", ex)

                # Settings
                try:
                    if "childLock" in data and isinstance(data["childLock"], bool):
                        event_bus.notify(ChildLockEvent(data["childLock"]))
                except Exception as ex:
                    _LOGGER.warning("Error parsing childLock: %s", ex)

                try:
                    if "autoBoost" in data and isinstance(data["autoBoost"], bool):
                        event_bus.notify(CarpetAutoFanBoostEvent(data["autoBoost"]))
                except Exception as ex:
                    _LOGGER.warning("Error parsing autoBoost: %s", ex)

                try:
                    if "disturbSwitch" in data and isinstance(data["disturbSwitch"], bool):
                        event_bus.notify(DoNotDisturbEvent(data["disturbSwitch"]))
                except Exception as ex:
                    _LOGGER.warning("Error parsing disturbSwitch: %s", ex)

                try:
                    if "breakCleanSwitch" in data and isinstance(data["breakCleanSwitch"], bool):
                        event_bus.notify(ContinuousCleaningEvent(data["breakCleanSwitch"]))
                except Exception as ex:
                    _LOGGER.warning("Error parsing breakCleanSwitch: %s", ex)

                try:
                    if "volume" in data and not isinstance(data["volume"], bool) and isinstance(data["volume"], (int, float)):
                        vol = int(data["volume"])
                        if 0 <= vol <= 10:
                            event_bus.notify(VolumeEvent(vol, 10))
                except Exception as ex:
                    _LOGGER.warning("Error parsing volume: %s", ex)

                # Error
                try:
                    if "error" in data:
                        err_list = data["error"]
                        err_code = err_list[0] if isinstance(err_list, list) and err_list else 0
                        event_bus.notify(ErrorEvent(err_code, f"Error {err_code}"))
                except Exception as ex:
                    _LOGGER.warning("Error parsing error: %s", ex)

                # Stats (clean area, clean time)
                try:
                    clean_area = data.get("cleanArea")
                    clean_time = data.get("cleanTime")
                    if clean_area is not None or clean_time is not None:
                        a_val = int(clean_area) if clean_area is not None else None
                        t_val = (int(clean_time) * 60) if clean_time is not None else None
                        event_bus.notify(StatsEvent(area=a_val, time=t_val, type=None))
                    else:
                        last_stats = event_bus.get_last_event(StatsEvent)
                        if last_stats is None:
                            event_bus.notify(StatsEvent(area=0, time=0, type=None))
                except Exception as ex:
                    _LOGGER.warning("Error parsing clean stats: %s", ex)

                # Total stats (initialize so sensors aren't unknown)
                try:
                    last_total = event_bus.get_last_event(TotalStatsEvent)
                    if last_total is None:
                        event_bus.notify(TotalStatsEvent(area=0, time=0, cleanings=0))
                except Exception as ex:
                    _LOGGER.debug("Error initializing total stats: %s", ex)

                # Network / Device Info
                try:
                    if "deviceInfo" in data and isinstance(data["deviceInfo"], dict):
                        dev = data["deviceInfo"]
                        event_bus.notify(NetworkInfoEvent(
                            ip=dev.get("ip"),
                            mac=dev.get("mac"),
                            ssid=dev.get("ssid"),
                            rssi=dev.get("rssi"),
                        ))
                except Exception as ex:
                    _LOGGER.warning("Error parsing deviceInfo: %s", ex)

                return HandlingResult.success()

        # 5. Commands
        _DEFAULT_FIELDS = [
            "status", "pauseSwitch", "chargeStatus", "battery",
            "fanMode", "waterMode", "mopState", "consumables",
            "deviceInfo", "error", "childLock", "autoBoost",
            "breakCleanSwitch", "disturbSwitch", "volume",
            "cleanArea", "cleanTime",
        ]

        class GetNativeInfo(OnNativeInfo, NativeGetCommand):
            NAME = "10001"

            def __init__(self, fields: list[str] | None = None, *, is_available_check: bool = False) -> None:
                super().__init__({"fields": list(fields) if fields is not None else list(_DEFAULT_FIELDS)})
                self._is_available_check = is_available_check

        class NativeStartClean(NativeExecuteCommand):
            NAME = "40001"

            def __init__(self) -> None:
                super().__init__({"cleanSwitch": True, "cleanMode": "smart"})

            async def _execute(
                self,
                authenticator: Any,
                device_info: Any,
                event_bus: Any,
            ) -> tuple[HandlingResult, dict[str, Any]]:
                state = event_bus.get_last_event(StateEvent)
                if isinstance(state, StateEvent) and state.state == State.PAUSED:
                    return await NativeResumeClean()._execute(authenticator, device_info, event_bus)
                result, response = await super()._execute(authenticator, device_info, event_bus)
                if result.state == HandlingState.SUCCESS:
                    event_bus.notify(StateEvent(State.CLEANING))
                    result.requested_commands.append(GetNativeInfo())
                return result, response

        class NativePauseClean(NativeExecuteCommand):
            NAME = "40009"

            def __init__(self) -> None:
                super().__init__({"pauseSwitch": True})

            async def _execute(
                self,
                authenticator: Any,
                device_info: Any,
                event_bus: Any,
            ) -> tuple[HandlingResult, dict[str, Any]]:
                result, response = await super()._execute(authenticator, device_info, event_bus)
                if result.state == HandlingState.SUCCESS:
                    event_bus.notify(StateEvent(State.PAUSED))
                    result.requested_commands.append(GetNativeInfo())
                return result, response

        class NativeResumeClean(NativeExecuteCommand):
            NAME = "40011"

            def __init__(self) -> None:
                super().__init__({"pauseSwitch": False})

            async def _execute(
                self,
                authenticator: Any,
                device_info: Any,
                event_bus: Any,
            ) -> tuple[HandlingResult, dict[str, Any]]:
                state = event_bus.get_last_event(StateEvent)
                if isinstance(state, StateEvent) and state.state != State.PAUSED:
                    return await NativeStartClean()._execute(authenticator, device_info, event_bus)
                result, response = await super()._execute(authenticator, device_info, event_bus)
                if result.state == HandlingState.SUCCESS:
                    event_bus.notify(StateEvent(State.CLEANING))
                    result.requested_commands.append(GetNativeInfo())
                return result, response

        class NativeReturnToDock(NativeExecuteCommand):
            NAME = "40013"

            def __init__(self) -> None:
                super().__init__({"chargeSwitch": True})

            async def _execute(
                self,
                authenticator: Any,
                device_info: Any,
                event_bus: Any,
            ) -> tuple[HandlingResult, dict[str, Any]]:
                result, response = await super()._execute(authenticator, device_info, event_bus)
                if result.state == HandlingState.SUCCESS:
                    event_bus.notify(StateEvent(State.RETURNING))
                    result.requested_commands.append(GetNativeInfo())
                return result, response

        class NativeLocate(NativeExecuteCommand):
            NAME = "40019"

            def __init__(self) -> None:
                super().__init__({"seek": True})

        class NativeResetLifeSpan(NativeExecuteCommand, JsonCommandMqttP2P):
            NAME = "50017"
            _mqtt_params = MappingProxyType(
                {"resetConsumable": InitParam(LifeSpan, "life_span")}
            )

            def __init__(self, life_span: LifeSpan) -> None:
                if life_span not in _RESET_TO_NATIVE:
                    raise ValueError(f"Unsupported native reset component: {life_span}")
                super().__init__({"resetConsumable": _RESET_TO_NATIVE[life_span]})

        class NativeSetFanSpeed(NativeSetCommand):
            NAME = "50011"
            get_command = GetNativeInfo
            _mqtt_params = MappingProxyType({"fanMode": InitParam(FanSpeedLevel, "speed")})

            def __init__(self, speed: FanSpeedLevel | str) -> None:
                if isinstance(speed, str):
                    speed_lower = speed.lower()
                    if speed_lower in _FAN_ALIASES:
                        speed = _FAN_ALIASES[speed_lower]
                    else:
                        speed = get_enum(FanSpeedLevel, speed)
                super().__init__({"fanMode": _FAN_TO_NATIVE[speed]})

        class NativeSetWaterAmount(NativeSetCommand):
            NAME = "50013"
            get_command = GetNativeInfo
            _mqtt_params = MappingProxyType({"waterMode": InitParam(water_info.WaterAmount, "amount")})

            def __init__(self, amount: water_info.WaterAmount | str) -> None:
                if isinstance(amount, str):
                    amt_lower = amount.lower()
                    if amt_lower in _WATER_ALIASES:
                        amount = _WATER_ALIASES[amt_lower]
                    else:
                        amount = get_enum(water_info.WaterAmount, amount)
                if amount not in _WATER_TO_NATIVE:
                    raise ValueError(f"Unsupported native water amount: {amount}")
                super().__init__({"waterMode": _WATER_TO_NATIVE[amount]})

        class NativeSetChildLock(NativeSetCommand):
            NAME = "50038"
            get_command = GetNativeInfo
            _mqtt_params = MappingProxyType({"childLock": InitParam(bool, "enable")})

            def __init__(self, enable: bool) -> None:
                super().__init__({"childLock": bool(enable)})

        class NativeSetAutoBoost(NativeSetCommand):
            NAME = "50036"
            get_command = GetNativeInfo
            _mqtt_params = MappingProxyType({"autoBoost": InitParam(bool, "enable")})

            def __init__(self, enable: bool) -> None:
                super().__init__({"autoBoost": bool(enable)})

        class NativeSetContinuousCleaning(NativeSetCommand):
            NAME = "50025"
            get_command = GetNativeInfo
            _mqtt_params = MappingProxyType({"breakCleanSwitch": InitParam(bool, "enable")})

            def __init__(self, enable: bool) -> None:
                super().__init__({"breakCleanSwitch": bool(enable)})

        class NativeSetDoNotDisturb(NativeSetCommand):
            NAME = "50019"
            get_command = GetNativeInfo
            _mqtt_params = MappingProxyType({"disturbSwitch": InitParam(bool, "enable")})

            def __init__(self, enable: bool) -> None:
                super().__init__({"disturbSwitch": bool(enable)})

        class NativeSetVolume(NativeSetCommand):
            NAME = "50023"
            get_command = GetNativeInfo
            _mqtt_params = MappingProxyType({"volume": InitParam(int, "volume")})

            def __init__(self, volume: int) -> None:
                super().__init__({"volume": int(volume)})

        class NativeCustomCommand(NativeExecuteCommand):
            NAME = "10002"

            def __init__(self, command: str, params: dict[str, Any] | None = None) -> None:
                args = {"cmd": command}
                if params:
                    args.update(params)
                super().__init__(args)

        def native_clean(action: CleanAction) -> Command:
            if action == CleanAction.START:
                return NativeStartClean()
            if action == CleanAction.PAUSE:
                return NativePauseClean()
            if action == CleanAction.RESUME:
                return NativeResumeClean()
            if action == CleanAction.STOP:
                return NativeReturnToDock()
            return NativeStartClean()

        # 6. Register in commands and messages tables
        json_cmds.COMMANDS["10001"] = GetNativeInfo
        json_cmds.COMMANDS["40001"] = NativeStartClean
        json_cmds.COMMANDS["40009"] = NativePauseClean
        json_cmds.COMMANDS["40011"] = NativeResumeClean
        json_cmds.COMMANDS["40013"] = NativeReturnToDock
        json_cmds.COMMANDS["40019"] = NativeLocate
        json_cmds.COMMANDS["50011"] = NativeSetFanSpeed
        json_cmds.COMMANDS["50013"] = NativeSetWaterAmount
        json_cmds.COMMANDS["50017"] = NativeResetLifeSpan
        json_cmds.COMMANDS["50019"] = NativeSetDoNotDisturb
        json_cmds.COMMANDS["50023"] = NativeSetVolume
        json_cmds.COMMANDS["50025"] = NativeSetContinuousCleaning
        json_cmds.COMMANDS["50036"] = NativeSetAutoBoost
        json_cmds.COMMANDS["50038"] = NativeSetChildLock
        json_cmds.COMMANDS["10002"] = NativeCustomCommand

        json_msgs.MESSAGES["10000"] = OnNativeInfo
        json_msgs.MESSAGES["10001"] = GetNativeInfo

        # 7. Capabilities definition
        life_span_types = (
            LifeSpan.BRUSH,
            LifeSpan.FILTER,
            LifeSpan.SIDE_BRUSH,
            LifeSpan.UNIT_CARE,
        )

        capabilities = Capabilities(
            device_type=DeviceType.VACUUM,
            availability=CapabilityEvent(
                AvailabilityEvent, [GetNativeInfo(is_available_check=True)]
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
                carpet_auto_fan_boost=CapabilitySetEnable(
                    CarpetAutoFanBoostEvent,
                    [GetNativeInfo(["autoBoost"])],
                    NativeSetAutoBoost,
                ),
                child_lock=CapabilitySetEnable(
                    ChildLockEvent,
                    [GetNativeInfo(["childLock"])],
                    NativeSetChildLock,
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
