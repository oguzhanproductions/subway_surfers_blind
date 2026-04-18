from __future__ import annotations
from subway_blind.strings import sx as _sx
from dataclasses import dataclass
from typing import Callable, Optional
import pygame

@dataclass
class MenuItem:
    label: str
    action: str
    description: str = _sx(2)

class Menu:

    def __init__(self, speaker, audio, title: str, items: list[MenuItem], description_enabled: Callable[[], bool] | None=None):
        self.speaker = speaker
        self.audio = audio
        self.title = title
        self.items = items
        self.description_enabled = description_enabled
        self.index = 0
        self.opened = False

    def _menu_pan_for_index(self, index: int | None=None) -> float:
        if len(self.items) <= 1:
            return 0.0
        target_index = self.index if index is None else max(0, min(int(index), len(self.items) - 1))
        progress = target_index / (len(self.items) - 1)
        return progress * 1.6 - 0.8

    def _play_menu_sound(self, key: str, index: int | None=None, channel: str=_sx(180)) -> None:
        if bool(self.audio.settings.get(_sx(195), True)):
            self.audio.play(key, channel=channel, pan=self._menu_pan_for_index(index))
            return
        self.audio.play(key, channel=channel)

    def play_feedback(self, key: str, index: int | None=None) -> None:
        self._play_menu_sound(key, index=index)

    def open(self, start_index: int=0, play_sound: bool=True) -> None:
        self.opened = True
        if self.items:
            self.index = max(0, min(int(start_index), len(self.items) - 1))
        else:
            self.index = 0
        if play_sound:
            self._play_menu_sound(_sx(54))
        self.speaker.speak(self._opening_announcement(), interrupt=True)

    def _opening_announcement(self) -> str:
        if not self.items:
            return self.title
        return _sx(988).format(self.title, self._current_announcement_text())

    def _descriptions_enabled(self) -> bool:
        if self.description_enabled is None:
            return False
        try:
            return bool(self.description_enabled())
        except Exception:
            return False

    def _item_announcement_text(self, item: MenuItem) -> str:
        description = item.description.strip()
        if description and self._descriptions_enabled():
            return _sx(988).format(item.label, description)
        return item.label

    def _current_announcement_text(self) -> str:
        if not self.items:
            return _sx(2)
        return self._item_announcement_text(self.items[self.index])

    def _announce_current(self) -> None:
        if not self.items:
            return
        self.speaker.speak(self._current_announcement_text(), interrupt=True)

    def _wrapping_enabled(self) -> bool:
        try:
            return bool(self.audio.settings.get(_sx(315), False))
        except Exception:
            return False

    def _move_to_index(self, target_index: int) -> None:
        if not self.items:
            self._play_menu_sound(_sx(52), index=0)
            return
        last_index = len(self.items) - 1
        requested_index = int(target_index)
        if requested_index < 0 or requested_index > last_index:
            if self._wrapping_enabled() and last_index > 0:
                self.index = last_index if requested_index < 0 else 0
                self._play_menu_sound(_sx(53))
                self._play_menu_sound(_sx(51), channel=_sx(1250))
                self._announce_current()
                return
            self._play_menu_sound(_sx(52))
            return
        if requested_index == self.index:
            self._play_menu_sound(_sx(52))
            return
        self.index = requested_index
        self._play_menu_sound(_sx(51))
        self._announce_current()

    def handle_key(self, key: int) -> Optional[str]:
        if key == pygame.K_ESCAPE:
            self._play_menu_sound(_sx(55))
            return _sx(1067)
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
            if not self.items:
                self._play_menu_sound(_sx(52))
                return None
            self._play_menu_sound(_sx(56))
            return self.items[self.index].action
        return None
