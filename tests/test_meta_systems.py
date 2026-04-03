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
    reset_daily_event_progress,
    word_hunt_target_word,
)
from subway_blind.progression import reset_daily_word_hunt_progress
from subway_blind.quests import (
    can_claim_meter_reward,
    claim_meter_reward,
    claim_quest,
    daily_quests,
    ensure_quest_state,
    next_meter_threshold,
    quest_sneakers,
    record_quest_metric,
    reset_daily_quest_progress,
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

    def test_daily_quests_include_practice_lane_training_quest(self):
        today = date(2026, 3, 29)

        quests = daily_quests(today)

        self.assertTrue(any(quest.metric == "practice_runs_completed" and quest.target == 1 for quest in quests))

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

    def test_reset_daily_quest_progress_clears_unclaimed_daily_quests_only(self):
        settings = copy.deepcopy(config_module.DEFAULT_SETTINGS)
        today = date(2026, 3, 29)
        ensure_quest_state(settings, today)
        regular_daily_quests = [quest for quest in daily_quests(today) if quest.metric != "practice_runs_completed"]
        first_quest, second_quest = regular_daily_quests[:2]
        settings["quest_state"]["daily_progress"][first_quest.key] = first_quest.target - 1
        settings["quest_state"]["daily_progress"][second_quest.key] = second_quest.target
        settings["quest_state"]["daily_claimed"] = [second_quest.key]

        reset_quests = reset_daily_quest_progress(settings, today)

        self.assertEqual({quest.key for quest in reset_quests}, {first_quest.key})
        self.assertEqual(settings["quest_state"]["daily_progress"][first_quest.key], 0)
        self.assertEqual(settings["quest_state"]["daily_progress"][second_quest.key], second_quest.target)

    def test_reset_daily_word_hunt_progress_preserves_completed_reward(self):
        settings = copy.deepcopy(config_module.DEFAULT_SETTINGS)
        today = date(2026, 3, 29)
        settings["word_hunt_active_word"] = "TRAIN"
        settings["word_hunt_day"] = today.isoformat()
        settings["word_hunt_letters"] = "TRAIN"
        settings["word_hunt_completed_on"] = today.isoformat()

        reset = reset_daily_word_hunt_progress(settings, today)

        self.assertFalse(reset)
        self.assertEqual(settings["word_hunt_letters"], "TRAIN")

    def test_reset_daily_event_progress_clears_counters_without_reopening_claimed_tiers(self):
        settings = copy.deepcopy(config_module.DEFAULT_SETTINGS)
        today = date(2026, 3, 29)
        ensure_event_state(settings, today)
        settings["event_state"]["daily_high_score_total"] = 4200
        settings["event_state"]["daily_high_score_claimed_tiers"] = 2
        settings["event_state"]["coin_meter_coins"] = 160
        settings["event_state"]["coin_meter_claimed_tiers"] = 1

        daily_high_score_reset, coin_meter_reset = reset_daily_event_progress(settings, today)

        self.assertTrue(daily_high_score_reset)
        self.assertTrue(coin_meter_reset)
        self.assertEqual(settings["event_state"]["daily_high_score_total"], 0)
        self.assertEqual(settings["event_state"]["coin_meter_coins"], 0)
        self.assertEqual(settings["event_state"]["daily_high_score_claimed_tiers"], 2)
        self.assertEqual(settings["event_state"]["coin_meter_claimed_tiers"], 1)


if __name__ == "__main__":
    unittest.main()
