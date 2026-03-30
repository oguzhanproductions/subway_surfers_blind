from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from subway_blind.models import Obstacle, lane_to_pan

HAZARD_KINDS = {"train", "low", "high", "bush"}
TRAIN_FRONT_TRACKING_DISTANCE = 40.0
TRAIN_REAR_TRACKING_DISTANCE = 10.0
OBSTACLE_FRONT_TRACKING_DISTANCE = 26.0
LANE_ORDER = (-1, 0, 1)
PRIORITY = {"train": 0, "high": 1, "low": 2, "bush": 3}
ANNOUNCER_PROMPT_SOUND_KEYS = {
    "jump": "announcer_jump_now",
    "jump now": "announcer_jump_now",
    "roll": "announcer_roll_now",
    "roll now": "announcer_roll_now",
    "turn left": "announcer_move_left_now",
    "turn left now": "announcer_move_left_now",
    "turn right": "announcer_move_right_now",
    "turn right now": "announcer_move_right_now",
}
PROMPT_LEAD_TIMES = {
    "train": 0.84,
    "high": 0.62,
    "low": 0.6,
    "bush": 0.58,
}
PROMPT_LEAD_TIME_SPEED_BONUS = {
    "train": 0.22,
    "high": 0.18,
    "low": 0.16,
    "bush": 0.16,
}
PROMPT_LEAD_TIME_HIGH_SPEED_BONUS = {
    "train": 0.18,
    "high": 0.14,
    "low": 0.13,
    "bush": 0.12,
}
PROMPT_DISTANCE_BUFFERS = {
    "train": 5.5,
    "high": 4.4,
    "low": 4.0,
    "bush": 3.8,
}


@dataclass(frozen=True)
class ThreatCue:
    lane: int
    kind: str
    distance: float
    interval: float
    gain: float
    pan: float
    source_x: float
    source_y: float
    source_z: float
    velocity_x: float
    velocity_y: float
    velocity_z: float
    pitch: float
    prompt: Optional[str]
    announcer_key: Optional[str]


class SpatialThreatAudio:
    def __init__(self) -> None:
        self._pulse_cooldowns = {lane: 0.0 for lane in LANE_ORDER}
        self._spoken_signatures: dict[int, str] = {}

    def reset(self) -> None:
        self._pulse_cooldowns = {lane: 0.0 for lane in LANE_ORDER}
        self._spoken_signatures.clear()

    def update(self, delta_time: float, player_lane: int, speed: float, obstacles: list[Obstacle], audio, speaker) -> None:
        for lane in LANE_ORDER:
            self._pulse_cooldowns[lane] = max(0.0, self._pulse_cooldowns[lane] - delta_time)

        cues = self.build_threat_cues(player_lane, speed, obstacles)
        active_lanes = {cue.lane for cue in cues}
        for lane in LANE_ORDER:
            if lane not in active_lanes:
                self._spoken_signatures.pop(lane, None)
                audio.stop(f"spatial_{lane}")

        for cue in cues:
            if cue.kind == "train":
                audio.update_spatial(
                    channel=f"spatial_{cue.lane}",
                    x=cue.source_x,
                    y=cue.source_y,
                    z=cue.source_z,
                    gain=cue.gain,
                    pitch=cue.pitch,
                    fallback_pan=cue.pan,
                    velocity_x=cue.velocity_x,
                    velocity_y=cue.velocity_y,
                    velocity_z=cue.velocity_z,
                )
            if cue.kind == "train" and self._pulse_cooldowns[cue.lane] <= 0:
                audio.play_spatial(
                    "train_pass",
                    channel=f"spatial_{cue.lane}",
                    x=cue.source_x,
                    y=cue.source_y,
                    z=cue.source_z,
                    gain=cue.gain,
                    pitch=cue.pitch,
                    fallback_pan=cue.pan,
                    velocity_x=cue.velocity_x,
                    velocity_y=cue.velocity_y,
                    velocity_z=cue.velocity_z,
                )
                self._pulse_cooldowns[cue.lane] = cue.interval
            if cue.announcer_key is not None:
                signature = cue.announcer_key
                if self._spoken_signatures.get(cue.lane) != signature:
                    play_announcer = getattr(audio, "play", None)
                    has_sound = getattr(audio, "has_sound", None)
                    played = False
                    if callable(play_announcer):
                        if not callable(has_sound) or bool(has_sound(cue.announcer_key)):
                            play_announcer(cue.announcer_key, channel="announcer_prompt")
                            played = True
                    if not played and cue.prompt is not None:
                        speaker.speak(cue.prompt, interrupt=True)
                    self._spoken_signatures[cue.lane] = signature

    def build_threat_cues(self, player_lane: int, speed: float, obstacles: list[Obstacle]) -> list[ThreatCue]:
        lane_threats = self._nearest_hazard_per_lane(obstacles)
        cues: list[ThreatCue] = []
        for lane in LANE_ORDER:
            threat = lane_threats.get(lane)
            if threat is None:
                continue
            cues.append(self._build_cue(player_lane, speed, threat, lane_threats))
        return cues

    def _nearest_hazard_per_lane(self, obstacles: list[Obstacle]) -> dict[int, Obstacle]:
        lane_threats: dict[int, Obstacle] = {}
        for obstacle in obstacles:
            if obstacle.kind not in HAZARD_KINDS:
                continue
            if not self._is_within_tracking_window(obstacle):
                continue
            current = lane_threats.get(obstacle.lane)
            if current is None:
                lane_threats[obstacle.lane] = obstacle
                continue
            obstacle_metric = self._threat_metric(obstacle)
            current_metric = self._threat_metric(current)
            if obstacle_metric < current_metric:
                lane_threats[obstacle.lane] = obstacle
        return lane_threats

    def _is_within_tracking_window(self, obstacle: Obstacle) -> bool:
        if obstacle.kind == "train":
            return -TRAIN_REAR_TRACKING_DISTANCE <= obstacle.z <= TRAIN_FRONT_TRACKING_DISTANCE
        return 0.0 < obstacle.z <= OBSTACLE_FRONT_TRACKING_DISTANCE

    def _threat_metric(self, obstacle: Obstacle) -> tuple[int, float, int]:
        return (0 if obstacle.z > 0 else 1, abs(obstacle.z), PRIORITY.get(obstacle.kind, 99))

    def _build_cue(
        self,
        player_lane: int,
        speed: float,
        obstacle: Obstacle,
        lane_threats: dict[int, Obstacle],
    ) -> ThreatCue:
        range_limit = TRAIN_FRONT_TRACKING_DISTANCE if obstacle.kind == "train" else OBSTACLE_FRONT_TRACKING_DISTANCE
        signed_distance = obstacle.z
        distance = min(range_limit, abs(signed_distance))
        closeness = 1.0 - (distance / range_limit)
        speed_factor = self._speed_factor(speed)
        interval = 1.05 - closeness * 0.88
        gain = 0.22 + closeness * 0.86
        interval *= 1.0 - speed_factor * 0.14
        gain = min(1.0, gain + speed_factor * 0.06)
        if signed_distance < 0:
            gain *= 0.82
            interval *= 1.08
        lateral_bias = 0.18 * closeness if obstacle.lane != player_lane else 0.0
        if obstacle.lane < player_lane:
            pan = lane_to_pan(obstacle.lane) - lateral_bias
        elif obstacle.lane > player_lane:
            pan = lane_to_pan(obstacle.lane) + lateral_bias
        else:
            pan = lane_to_pan(obstacle.lane)
        relative_lane = obstacle.lane - player_lane
        width_scale = 1.55 + closeness * 0.85
        if obstacle.kind == "train":
            width_scale += 0.3
        source_x = relative_lane * width_scale
        source_y = self._source_height_for_obstacle(obstacle.kind, closeness)
        source_z = max(-TRAIN_FRONT_TRACKING_DISTANCE, min(TRAIN_REAR_TRACKING_DISTANCE, -signed_distance))
        velocity_x = 0.0
        velocity_y = 0.0
        if signed_distance >= 0:
            velocity_z = -max(4.0, speed * (0.92 + closeness * 0.18))
        else:
            velocity_z = max(3.0, speed * 0.55)
        pitch = 0.92 + closeness * 0.24
        if signed_distance < 0:
            pitch = max(0.82, pitch - 0.08)
            gain *= 0.88
        prompt = self._prompt_for_obstacle(player_lane, obstacle, signed_distance, speed, speed_factor, lane_threats)
        announcer_key = self._announcer_key_for_prompt(prompt)
        return ThreatCue(
            lane=obstacle.lane,
            kind=obstacle.kind,
            distance=distance,
            interval=max(0.12, interval),
            gain=max(0.12, min(1.0, gain)),
            pan=max(-1.0, min(1.0, pan)),
            source_x=source_x,
            source_y=source_y,
            source_z=source_z,
            velocity_x=velocity_x,
            velocity_y=velocity_y,
            velocity_z=velocity_z,
            pitch=max(0.75, min(1.3, pitch)),
            prompt=prompt,
            announcer_key=announcer_key,
        )

    @staticmethod
    def _source_height_for_obstacle(kind: str, closeness: float) -> float:
        if kind == "high":
            return 0.2 + closeness * 0.12
        if kind == "low":
            return -0.42 + closeness * 0.08
        if kind == "bush":
            return -0.18
        if kind == "train":
            return -0.02
        return -0.1

    def _prompt_for_obstacle(
        self,
        player_lane: int,
        obstacle: Obstacle,
        signed_distance: float,
        speed: float,
        speed_factor: float,
        lane_threats: dict[int, Obstacle],
    ) -> Optional[str]:
        range_limit = TRAIN_FRONT_TRACKING_DISTANCE if obstacle.kind == "train" else OBSTACLE_FRONT_TRACKING_DISTANCE
        high_speed_factor = speed_factor * speed_factor
        lead_time = (
            PROMPT_LEAD_TIMES[obstacle.kind]
            + (speed_factor * PROMPT_LEAD_TIME_SPEED_BONUS[obstacle.kind])
            + (high_speed_factor * PROMPT_LEAD_TIME_HIGH_SPEED_BONUS[obstacle.kind])
        )
        prompt_distance = PROMPT_DISTANCE_BUFFERS[obstacle.kind] + (max(0.0, float(speed)) * lead_time)
        prompt_distance = min(range_limit - 0.75, prompt_distance)
        if signed_distance <= 0 or signed_distance > prompt_distance:
            return None
        if obstacle.lane != player_lane:
            return None
        if obstacle.kind == "train":
            direction = self._preferred_turn_direction(player_lane, lane_threats)
            return f"turn {direction}" if speed_factor >= 0.72 else f"turn {direction} now"
        if speed_factor >= 0.72:
            return {"low": "jump", "high": "roll", "bush": "jump"}[obstacle.kind]
        return {"low": "jump now", "high": "roll now", "bush": "jump now"}[obstacle.kind]

    def _preferred_turn_direction(self, player_lane: int, lane_threats: dict[int, Obstacle]) -> str:
        if player_lane <= -1:
            return "right"
        if player_lane >= 1:
            return "left"
        left_score = self._escape_lane_score(lane_threats.get(-1))
        right_score = self._escape_lane_score(lane_threats.get(1))
        return "left" if left_score >= right_score else "right"

    def _escape_lane_score(self, obstacle: Optional[Obstacle]) -> tuple[int, float, int]:
        if obstacle is None:
            return (2, float("inf"), 0)
        if obstacle.z <= 0:
            return (1, abs(obstacle.z), -PRIORITY.get(obstacle.kind, 99))
        return (0, float(obstacle.z), -PRIORITY.get(obstacle.kind, 99))

    @staticmethod
    def _speed_factor(speed: float) -> float:
        return max(0.0, min(1.0, (float(speed) - 18.0) / 16.0))

    @staticmethod
    def _announcer_key_for_prompt(prompt: Optional[str]) -> Optional[str]:
        if prompt is None:
            return None
        return ANNOUNCER_PROMPT_SOUND_KEYS.get(str(prompt).strip().lower())
