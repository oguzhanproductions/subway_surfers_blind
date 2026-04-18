from __future__ import annotations
from subway_blind.strings import sx as _sx
from dataclasses import dataclass
from typing import Optional
from subway_blind.models import Obstacle, lane_to_pan
HAZARD_KINDS = {_sx(643), _sx(644), _sx(97), _sx(645)}
TRAIN_FRONT_TRACKING_DISTANCE = 40.0
TRAIN_REAR_TRACKING_DISTANCE = 10.0
OBSTACLE_FRONT_TRACKING_DISTANCE = 26.0
LANE_ORDER = (-1, 0, 1)
PRIORITY = {_sx(643): 0, _sx(97): 1, _sx(644): 2, _sx(645): 3}
ANNOUNCER_PROMPT_SOUND_KEYS = {_sx(12): _sx(60), _sx(2125): _sx(60), _sx(14): _sx(63), _sx(2126): _sx(63), _sx(2127): _sx(61), _sx(2128): _sx(61), _sx(2129): _sx(62), _sx(2130): _sx(62)}
PROMPT_LEAD_TIMES = {_sx(643): 0.84, _sx(97): 0.62, _sx(644): 0.6, _sx(645): 0.58}
PROMPT_LEAD_TIME_SPEED_BONUS = {_sx(643): 0.22, _sx(97): 0.18, _sx(644): 0.16, _sx(645): 0.16}
PROMPT_LEAD_TIME_HIGH_SPEED_BONUS = {_sx(643): 0.18, _sx(97): 0.14, _sx(644): 0.13, _sx(645): 0.12}
PROMPT_DISTANCE_BUFFERS = {_sx(643): 5.5, _sx(97): 4.4, _sx(644): 4.0, _sx(645): 3.8}

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
                audio.stop(_sx(1555).format(lane))
        for cue in cues:
            if cue.kind == _sx(643):
                audio.update_spatial(channel=_sx(1555).format(cue.lane), x=cue.source_x, y=cue.source_y, z=cue.source_z, gain=cue.gain, pitch=cue.pitch, fallback_pan=cue.pan, velocity_x=cue.velocity_x, velocity_y=cue.velocity_y, velocity_z=cue.velocity_z)
            if cue.kind == _sx(643) and self._pulse_cooldowns[cue.lane] <= 0:
                audio.play_spatial(_sx(101), channel=_sx(1555).format(cue.lane), x=cue.source_x, y=cue.source_y, z=cue.source_z, gain=cue.gain, pitch=cue.pitch, fallback_pan=cue.pan, velocity_x=cue.velocity_x, velocity_y=cue.velocity_y, velocity_z=cue.velocity_z)
                self._pulse_cooldowns[cue.lane] = cue.interval
            if cue.announcer_key is not None:
                signature = cue.announcer_key
                if self._spoken_signatures.get(cue.lane) != signature:
                    play_announcer = getattr(audio, _sx(2138), None)
                    has_sound = getattr(audio, _sx(2139), None)
                    played = False
                    if callable(play_announcer):
                        if not callable(has_sound) or bool(has_sound(cue.announcer_key)):
                            play_announcer(cue.announcer_key, channel=_sx(2140))
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
        if obstacle.kind == _sx(643):
            return -TRAIN_REAR_TRACKING_DISTANCE <= obstacle.z <= TRAIN_FRONT_TRACKING_DISTANCE
        return 0.0 < obstacle.z <= OBSTACLE_FRONT_TRACKING_DISTANCE

    def _threat_metric(self, obstacle: Obstacle) -> tuple[int, float, int]:
        return (0 if obstacle.z > 0 else 1, abs(obstacle.z), PRIORITY.get(obstacle.kind, 99))

    def _build_cue(self, player_lane: int, speed: float, obstacle: Obstacle, lane_threats: dict[int, Obstacle]) -> ThreatCue:
        range_limit = TRAIN_FRONT_TRACKING_DISTANCE if obstacle.kind == _sx(643) else OBSTACLE_FRONT_TRACKING_DISTANCE
        signed_distance = obstacle.z
        distance = min(range_limit, abs(signed_distance))
        closeness = 1.0 - distance / range_limit
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
        if obstacle.kind == _sx(643):
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
        return ThreatCue(lane=obstacle.lane, kind=obstacle.kind, distance=distance, interval=max(0.12, interval), gain=max(0.12, min(1.0, gain)), pan=max(-1.0, min(1.0, pan)), source_x=source_x, source_y=source_y, source_z=source_z, velocity_x=velocity_x, velocity_y=velocity_y, velocity_z=velocity_z, pitch=max(0.75, min(1.3, pitch)), prompt=prompt, announcer_key=announcer_key)

    @staticmethod
    def _source_height_for_obstacle(kind: str, closeness: float) -> float:
        if kind == _sx(97):
            return 0.2 + closeness * 0.12
        if kind == _sx(644):
            return -0.42 + closeness * 0.08
        if kind == _sx(645):
            return -0.18
        if kind == _sx(643):
            return -0.02
        return -0.1

    def _prompt_for_obstacle(self, player_lane: int, obstacle: Obstacle, signed_distance: float, speed: float, speed_factor: float, lane_threats: dict[int, Obstacle]) -> Optional[str]:
        range_limit = TRAIN_FRONT_TRACKING_DISTANCE if obstacle.kind == _sx(643) else OBSTACLE_FRONT_TRACKING_DISTANCE
        high_speed_factor = speed_factor * speed_factor
        lead_time = PROMPT_LEAD_TIMES[obstacle.kind] + speed_factor * PROMPT_LEAD_TIME_SPEED_BONUS[obstacle.kind] + high_speed_factor * PROMPT_LEAD_TIME_HIGH_SPEED_BONUS[obstacle.kind]
        prompt_distance = PROMPT_DISTANCE_BUFFERS[obstacle.kind] + max(0.0, float(speed)) * lead_time
        prompt_distance = min(range_limit - 0.75, prompt_distance)
        if signed_distance <= 0 or signed_distance > prompt_distance:
            return None
        if obstacle.lane != player_lane:
            return None
        if obstacle.kind == _sx(643):
            direction = self._preferred_turn_direction(player_lane, lane_threats)
            return _sx(2133).format(direction) if speed_factor >= 0.72 else _sx(2134).format(direction)
        if speed_factor >= 0.72:
            return {_sx(644): _sx(12), _sx(97): _sx(14), _sx(645): _sx(12)}[obstacle.kind]
        return {_sx(644): _sx(2125), _sx(97): _sx(2126), _sx(645): _sx(2125)}[obstacle.kind]

    def _preferred_turn_direction(self, player_lane: int, lane_threats: dict[int, Obstacle]) -> str:
        if player_lane <= -1:
            return _sx(2131)
        if player_lane >= 1:
            return _sx(2132)
        left_score = self._escape_lane_score(lane_threats.get(-1))
        right_score = self._escape_lane_score(lane_threats.get(1))
        return _sx(2132) if left_score >= right_score else _sx(2131)

    def _escape_lane_score(self, obstacle: Optional[Obstacle]) -> tuple[int, float, int]:
        if obstacle is None:
            return (2, float(_sx(2137)), 0)
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
