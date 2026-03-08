from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pygame


@dataclass
class MenuItem:
    label: str
    action: str


class Menu:
    def __init__(self, speaker, audio, title: str, items: list[MenuItem]):
        self.speaker = speaker
        self.audio = audio
        self.title = title
        self.items = items
        self.index = 0
        self.opened = False

    def _menu_pan_for_index(self, index: int | None = None) -> float:
        if len(self.items) <= 1:
            return 0.0
        target_index = self.index if index is None else max(0, min(int(index), len(self.items) - 1))
        progress = target_index / (len(self.items) - 1)
        return (progress * 1.6) - 0.8

    def _play_menu_sound(self, key: str, index: int | None = None) -> None:
        if bool(self.audio.settings.get("menu_sound_hrtf", True)):
            self.audio.play(key, channel="ui", pan=self._menu_pan_for_index(index))
            return
        self.audio.play(key, channel="ui")

    def play_feedback(self, key: str, index: int | None = None) -> None:
        self._play_menu_sound(key, index=index)

    def open(self, start_index: int = 0, play_sound: bool = True) -> None:
        self.opened = True
        if self.items:
            self.index = max(0, min(int(start_index), len(self.items) - 1))
        else:
            self.index = 0
        if play_sound:
            self._play_menu_sound("menuopen")
        self.speaker.speak(self._opening_announcement(), interrupt=True)

    def _opening_announcement(self) -> str:
        if not self.items:
            return self.title
        return f"{self.title}. {self.items[self.index].label}"

    def _announce_current(self) -> None:
        if not self.items:
            return
        self.speaker.speak(self.items[self.index].label, interrupt=True)

    def _move_to_index(self, target_index: int) -> None:
        if not self.items:
            self._play_menu_sound("menuedge", index=0)
            return
        clamped_index = max(0, min(int(target_index), len(self.items) - 1))
        if clamped_index == self.index:
            self._play_menu_sound("menuedge")
            return
        self.index = clamped_index
        self._play_menu_sound("menumove")
        self._announce_current()

    def handle_key(self, key: int) -> Optional[str]:
        if key == pygame.K_ESCAPE:
            self._play_menu_sound("menuclose")
            return "close"
        if key in (pygame.K_UP, pygame.K_w):
            self._move_to_index(self.index - 1)
            return None
        if key in (pygame.K_DOWN, pygame.K_s):
            self._move_to_index(self.index + 1)
            return None
        if key == pygame.K_HOME:
            self._move_to_index(0)
            return None
        if key == pygame.K_END:
            self._move_to_index(len(self.items) - 1)
            return None
        if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._play_menu_sound("confirm")
            return self.items[self.index].action
        return None
