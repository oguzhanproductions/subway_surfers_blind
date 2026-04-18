from __future__ import annotations
from subway_blind.strings import sx as _sx
import pygame
from subway_blind.audio import initialize_mixer_output
from subway_blind.config import load_settings
from subway_blind.game import SubwayBlindGame
from subway_blind.version import APP_VERSION, APP_WINDOW_TITLE

def main() -> None:
    settings = load_settings()
    pygame.init()
    settings[_sx(1)] = initialize_mixer_output(settings.get(_sx(1))) or _sx(2)
    pygame.display.set_caption(_sx(3).format(APP_WINDOW_TITLE, APP_VERSION))
    screen = pygame.display.set_mode((900, 600), pygame.RESIZABLE)
    clock = pygame.time.Clock()
    game = SubwayBlindGame(screen, clock, settings)
    try:
        game.run()
    finally:
        pygame.quit()
