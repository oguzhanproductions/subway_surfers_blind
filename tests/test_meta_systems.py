import copy
import unittest
from datetime import date

from subway_blind import config as config_module
from subway_blind.boards import ensure_board_state, selected_board_definition
from subway_blind.events import (
    claim_daily_gift,
    claim_login_calendar_reward,
    daily_gift_available,
    ensure_event_state,
    login_calendar_available,
    word_hunt_target_word,
)
from subway_blind.quests import (
    can_claim_meter_reward,
    claim_meter_reward,
    claim_quest,
    daily_quests,
    ensure_quest_state,
    next_meter_threshold,
    quest_sneakers,
    record_quest_metric,
)


class MetaSystemTests(unittest.TestCase):
    def test_board_state_falls_back_to_unlocked_default(self):
        settings = copy.deepcopy(config_module.DEFAULT_SETTINGS)
        settings["selected_board"] = "zapper"
        settings["board_progress"] = {"zapper": {"unlocked": False}}

        ensure_board_state(settings)

        self.assertEqual(selected_board_definition(settings).key, "classic")
        self.assertTrue(settings["board_progress"]["classic"]["unlocked"])

    def test_daily_gift_is_only_claimable_once_per_day(self):
        settings = copy.deepcopy(config_module.DEFAULT_SETTINGS)
        today = date(2026, 3, 29)

        ensure_event_state(settings, today)
        first_reward = claim_daily_gift(settings, today)
        second_reward = claim_daily_gift(settings, today)

        self.assertIsNotNone(first_reward)
        self.assertIsNone(second_reward)
        self.assertFalse(daily_gift_available(settings, today))

    def test_login_calendar_is_only_claimable_once_per_day(self):
        settings = copy.deepcopy(config_module.DEFAULT_SETTINGS)
        today = date(2026, 3, 29)

        ensure_event_state(settings, today)
        first_reward = claim_login_calendar_reward(settings, today)
        second_reward = claim_login_calendar_reward(settings, today)

        self.assertIsNotNone(first_reward)
        self.assertIsNone(second_reward)
        self.assertFalse(login_calendar_available(settings, today))

    def test_wordy_weekend_uses_selected_character_name(self):
        settings = copy.deepcopy(config_module.DEFAULT_SETTINGS)
        settings["character_progress"]["tricky"]["unlocked"] = True
        settings["selected_character"] = "tricky"

        word = word_hunt_target_word(settings, date(2026, 3, 29))

        self.assertEqual(word, "TRICKY")

    def test_claiming_completed_quest_adds_sneakers(self):
        settings = copy.deepcopy(config_module.DEFAULT_SETTINGS)
        today = date(2026, 3, 29)
        ensure_quest_state(settings, today)
        quest = daily_quests(today)[0]

        record_quest_metric(settings, quest.metric, quest.target, today)
        claimed = claim_quest(settings, quest.key, today)

        self.assertIsNotNone(claimed)
        self.assertEqual(quest_sneakers(settings, today), quest.sneaker_reward)

    def test_quest_meter_reward_unlocks_at_threshold(self):
        settings = copy.deepcopy(config_module.DEFAULT_SETTINGS)
        today = date(2026, 3, 29)
        ensure_quest_state(settings, today)
        threshold = next_meter_threshold(settings, today)
        settings["quest_state"]["sneakers"] = threshold

        self.assertTrue(can_claim_meter_reward(settings, today))
        reward = claim_meter_reward(settings, today)

        self.assertIsNotNone(reward)
        self.assertEqual(settings["quest_state"]["meter_stage"], 1)


if __name__ == "__main__":
    unittest.main()
