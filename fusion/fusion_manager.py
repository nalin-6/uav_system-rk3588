from __future__ import annotations

from telemetry_link.models import DroneState, GimbalState

from .models import FusedState, FusionConfig
from .rules import build_fused_state, normalize_perception_target


class FusionManager:
    def __init__(self, config: FusionConfig | None = None) -> None:
        self.config = config or FusionConfig()
        self._consecutive_lost: int = 0

    def update(self, perception_target, drone_state: DroneState, gimbal_state: GimbalState) -> FusedState:
        normalized_target = normalize_perception_target(perception_target)

        # Hysteresis: once locked, tolerate brief perception dropouts.
        raw_locked = bool(
            normalized_target.target_valid
            and normalized_target.tracking_state == "locked"
        )
        if raw_locked:
            self._consecutive_lost = 0
        else:
            self._consecutive_lost += 1

        tolerance = max(0, self.config.lock_lost_tolerance)
        if not raw_locked and self._consecutive_lost <= tolerance:
            normalized_target.target_valid = True
            normalized_target.tracking_state = "locked"

        return build_fused_state(
            perception_target=normalized_target,
            drone_state=drone_state,
            gimbal_state=gimbal_state,
            require_gimbal_feedback=self.config.require_gimbal_feedback,
        )
