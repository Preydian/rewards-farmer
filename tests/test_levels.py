"""Tests for the Rewards levels table and what a run does with it.

The table decides how many points a day of searching is allowed to earn, so a
wrong figure here quietly changes the length of every run. The first class pins
the numbers to the published table; the rest cover reading a level off the
dashboard badge and the one place the table changes behaviour.

None of them need a browser.

	python -m unittest discover -s tests
"""

import contextlib
import logging
import os
import sys
import types
import unittest
from dataclasses import FrozenInstanceError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from selenium.common.exceptions import NoSuchElementException

import levels
import rewards_tasks

# The level badge exactly as the dashboard renders it. Every parsing case below
# is measured against this rather than against something invented.
BADGE_CLASS = (
	"rounded-ctrlBadgeCorner px-2 py-1 text-globalCaption1Strong "
	"text-rewardsLevelBadgeFg bg-rewardsGoldBadgeBg"
)
BADGE_TEXT = "Gold Member"


@contextlib.contextmanager
def env_level(value):
	"""Set REWARDS_LEVEL for the block, or remove it when value is None."""
	original = os.environ.get(levels.ENV_VAR)

	if value is None:
		os.environ.pop(levels.ENV_VAR, None)
	else:
		os.environ[levels.ENV_VAR] = value

	try:
		yield
	finally:
		if original is None:
			os.environ.pop(levels.ENV_VAR, None)
		else:
			os.environ[levels.ENV_VAR] = original


def tasks_at(level, badges=None):
	"""A RewardsTaskUtils without the browser its __init__ opens.

	`badges` is the (class, text) list the dashboard selector hands back, or
	None to make it raise the way an unreadable page does.
	"""
	tasks = rewards_tasks.RewardsTaskUtils.__new__(rewards_tasks.RewardsTaskUtils)
	tasks.level = level

	def membership_level_badges():
		if badges is None:
			raise NoSuchElementException("no membership level badge on the dashboard")

		return badges

	tasks.elements = types.SimpleNamespace(
		get_membership_level_badges=membership_level_badges
	)

	return tasks


class LevelsTable(unittest.TestCase):
	"""The published figures. A typo here changes how long every run takes."""

	def test_the_three_levels_in_ladder_order(self):
		self.assertEqual(
			[level.name for level in levels.LEVELS], ["Member", "Silver", "Gold"]
		)

	def test_daily_search_points_total(self):
		# A total across every surface Rewards counts, not a desktop ceiling. A
		# Gold account was measured at 90 desktop points against this 150.
		self.assertEqual(
			[level.daily_search_points_total for level in levels.LEVELS], [30, 150, 150]
		)

	def test_every_level_pays_the_same_rate(self):
		# The table states the rate once, in the heading of the cap row.
		self.assertEqual(levels.POINTS_PER_SEARCH, 3)

	def test_monthly_points_required(self):
		self.assertIsNone(levels.MEMBER.monthly_points_required)
		self.assertEqual(levels.SILVER.monthly_points_required, 500)
		self.assertEqual(levels.GOLD.monthly_points_required, 750)

	def test_only_gold_requires_level_up_activities(self):
		self.assertIsNone(levels.MEMBER.monthly_level_up_activities)
		self.assertIsNone(levels.SILVER.monthly_level_up_activities)
		self.assertEqual(levels.GOLD.monthly_level_up_activities, 2)

	def test_monthly_bonuses(self):
		self.assertEqual(
			[level.monthly_level_bonus for level in levels.LEVELS], [60, 180, 420]
		)
		self.assertEqual(
			[level.monthly_default_search_bonus for level in levels.LEVELS], [30, 90, 210]
		)
		self.assertEqual(
			[level.monthly_bing_star_bonus for level in levels.LEVELS], [300, 900, 2100]
		)

	def test_purchase_multipliers(self):
		# Recorded, never acted on: a search bot cannot spend money.
		self.assertEqual(
			[level.store_points_per_dollar for level in levels.LEVELS], [1, 10, 10]
		)
		self.assertEqual(
			[level.xbox_points_per_dollar for level in levels.LEVELS], [4, 4, 4]
		)

	def test_redemption_and_exclusive_offers(self):
		self.assertEqual(
			[level.redemption_coupon_points for level in levels.LEVELS], [None, 100, 200]
		)
		self.assertEqual(
			[level.exclusive_earning_offers for level in levels.LEVELS],
			[False, True, True],
		)

	def test_a_level_cannot_be_edited_in_place(self):
		# Module level shared state: one task mutating it would change every
		# later read, including the next account in a batched run.
		with self.assertRaises(FrozenInstanceError):
			levels.SILVER.daily_search_points_total = 9999


class LevelByName(unittest.TestCase):
	def test_matches_regardless_of_case_and_padding(self):
		self.assertIs(levels.by_name("  SILVER  "), levels.SILVER)

	def test_an_unknown_name_is_none(self):
		self.assertIsNone(levels.by_name("platinum"))

	def test_an_empty_name_is_none(self):
		self.assertIsNone(levels.by_name(""))


class LevelFromText(unittest.TestCase):
	"""Reading a tier out of the badge's text, and out of its class."""

	def test_reads_the_real_badge_text(self):
		# "<tier> Member" is how the badge words every level. Treating "member"
		# as an equal signal would make all three of these ambiguous.
		self.assertIs(levels.level_from_text("Gold Member"), levels.GOLD)
		self.assertIs(levels.level_from_text("Silver Member"), levels.SILVER)
		self.assertIs(levels.level_from_text("Member"), levels.MEMBER)

	def test_reads_the_tier_out_of_the_real_badge_class(self):
		# Language independent, unlike the text beside it.
		self.assertIs(levels.level_from_text(BADGE_CLASS), levels.GOLD)

	def test_the_tier_independent_part_of_the_class_names_no_tier(self):
		# "Level" is not a tier, so a badge whose background class is missing
		# does not resolve to one by accident.
		self.assertIsNone(levels.level_from_text("text-rewardsLevelBadgeFg"))

	def test_is_case_insensitive(self):
		self.assertIs(levels.level_from_text("SILVER MEMBER"), levels.SILVER)

	def test_does_not_match_a_tier_inside_another_word(self):
		# Substring matching finds "gold" in "goldfish".
		self.assertIsNone(levels.level_from_text("Level up: goldfish facts"))

	def test_does_not_match_a_tier_inside_a_camel_case_word(self):
		# The class tokenizer splits on case changes, so it has to not split
		# inside a word that merely starts with a tier name.
		self.assertIsNone(levels.level_from_text("bg-goldenrodBadgeBg"))

	def test_text_naming_both_silver_and_gold_is_not_an_answer(self):
		# The badge and a redemption offer caught by the same element. Guessing
		# here would raise the search target for an account that cannot reach it.
		self.assertIsNone(
			levels.level_from_text("Silver level. Redeem for Xbox Game Pass Gold.")
		)

	def test_text_naming_no_tier_is_none(self):
		self.assertIsNone(levels.level_from_text("Level up to earn more"))

	def test_empty_text_is_none(self):
		self.assertIsNone(levels.level_from_text(""))

	def test_member_is_the_weakest_signal(self):
		# It has to be, or "Gold Member" answers nothing. The price is that
		# ordinary prose reads as Member, which is the level a run already
		# assumes when it cannot tell, and which carries the lowest cap. So the
		# cost of being wrong here is an under-reach, not a wasted run.
		self.assertIs(levels.level_from_text("member since 2019"), levels.MEMBER)


class LevelFromBadge(unittest.TestCase):
	"""Class before text, because only one of the two survives translation."""

	def test_reads_the_real_badge(self):
		self.assertIs(levels.level_from_badge(BADGE_CLASS, BADGE_TEXT), levels.GOLD)

	def test_the_class_is_asked_before_the_text(self):
		# The two should never disagree, but the order is the whole reason the
		# class is read at all, so it gets pinned rather than left to chance.
		self.assertIs(
			levels.level_from_badge(BADGE_CLASS, "Silver Member"), levels.GOLD
		)

	def test_the_class_answers_when_the_text_is_translated(self):
		# A German dashboard renders "Goldmitglied" as one word, which names no
		# tier once split. The class still does, in every market.
		self.assertIsNone(levels.level_from_text("Goldmitglied"))
		self.assertIs(
			levels.level_from_badge(BADGE_CLASS, "Goldmitglied"), levels.GOLD
		)

	def test_the_text_answers_when_the_class_names_no_tier(self):
		# The fallback for a deploy that renames the background class.
		self.assertIs(
			levels.level_from_badge("text-rewardsLevelBadgeFg", "Silver Member"),
			levels.SILVER,
		)

	def test_neither_naming_a_tier_is_none(self):
		self.assertIsNone(levels.level_from_badge("px-2 py-1", "Rewards"))


class ConfiguredLevel(unittest.TestCase):
	def test_unset_is_none(self):
		with env_level(None):
			self.assertIsNone(levels.configured())

	def test_blank_is_none(self):
		with env_level("   "):
			self.assertIsNone(levels.configured())

	def test_a_named_level_is_returned(self):
		with env_level("gold"):
			self.assertIs(levels.configured(), levels.GOLD)

	def test_an_unknown_name_warns_and_is_ignored(self):
		# A typo in an environment variable must not end an unattended run, so
		# this reports it and lets the caller fall back.
		with env_level("platinum"):
			with self.assertLogs(levels.logger, level=logging.WARNING) as captured:
				self.assertIsNone(levels.configured())

		self.assertIn("platinum", "".join(captured.output))


class ResolveLevel(unittest.TestCase):
	"""Which source wins, and what happens when two of them disagree."""

	def test_the_dashboard_badge_is_used_when_nothing_is_configured(self):
		tasks = tasks_at(None, badges=[(BADGE_CLASS, BADGE_TEXT)])

		with env_level(None):
			self.assertIs(tasks.resolve_level(), levels.GOLD)

	def test_the_environment_overrides_the_dashboard(self):
		# The only way to correct a badge the selector reads wrongly, so it has
		# to win, and it has to say that it did.
		tasks = tasks_at(None, badges=[(BADGE_CLASS, BADGE_TEXT)])

		with env_level("silver"):
			with self.assertLogs(rewards_tasks.logger, level=logging.WARNING) as captured:
				self.assertIs(tasks.resolve_level(), levels.SILVER)

		self.assertIn("dashboard reads Gold", "".join(captured.output))

	def test_an_unreadable_dashboard_falls_back_to_the_environment(self):
		tasks = tasks_at(None, badges=None)

		with env_level("silver"):
			self.assertIs(tasks.resolve_level(), levels.SILVER)

	def test_nothing_readable_and_nothing_configured_assumes_member(self):
		tasks = tasks_at(None, badges=None)

		with env_level(None):
			self.assertIs(tasks.resolve_level(), levels.DEFAULT)

		# The lowest cap of the three, so an unrecognised dashboard under-reaches
		# rather than sending a run after points it cannot earn.
		self.assertIs(levels.DEFAULT, levels.MEMBER)

	def test_a_badge_naming_no_tier_is_skipped_for_one_that_does(self):
		# The selector hands back candidates, not an answer. A wrapper that
		# matched the class but carries no tier must not end the search.
		tasks = tasks_at(None, badges=[
			("text-rewardsLevelBadgeFg", "Rewards"),
			(BADGE_CLASS, BADGE_TEXT),
		])

		with env_level(None):
			self.assertIs(tasks.resolve_level(), levels.GOLD)


class SearchQuotaCeiling(unittest.TestCase):
	"""The panel is the ceiling, and the table never raises it.

	This was the other way round once. The table's figure is a total across
	every surface Rewards counts, so a Gold account reads 90 on the panel
	against a documented 150, the other 60 being earnable only from a mobile
	user agent. Treating 150 as a desktop target made a finished run keep
	searching for nothing, at five to seven seconds a search.
	"""

	def _tasks(self, level, readings):
		tasks = tasks_at(level)
		tasks.batches = []
		tasks.read_search_points = lambda: readings.pop(0)

		# Every search asked for goes out, and the count comes back the way
		# run_search_batch reports it.
		def run_search_batch(count, already_sent=0):
			tasks.batches.append(count)

			return count

		tasks.run_search_batch = run_search_batch

		return tasks

	def test_a_full_panel_quota_ends_the_task(self):
		# The reported case: 90/90 on a Gold account, and every search after
		# that earned nothing.
		tasks = self._tasks(levels.GOLD, [(90, 90)])

		with self.assertLogs(rewards_tasks.logger, level=logging.INFO):
			tasks.complete_required_searches()

		self.assertEqual(tasks.batches, [])

	def test_the_level_total_never_raises_the_panel_maximum(self):
		# 30 searches for the panel's 90, not 50 for the table's 150.
		tasks = self._tasks(levels.GOLD, [(0, 90), (90, 90)])

		with self.assertLogs(rewards_tasks.logger, level=logging.INFO):
			tasks.complete_required_searches(max_rounds=1)

		self.assertEqual(tasks.batches, [30])

	def test_the_unreachable_remainder_is_explained(self):
		# Without this a Gold run finishing at 90 looks 60 short of its own
		# level for no stated reason.
		tasks = self._tasks(levels.GOLD, [(90, 90)])

		with self.assertLogs(rewards_tasks.logger, level=logging.INFO) as captured:
			tasks.complete_required_searches()

		output = "".join(captured.output)

		self.assertIn("60", output)
		self.assertIn("mobile user agent", output)

	def test_nothing_is_said_when_the_panel_matches_the_level(self):
		# A Member account at 30/30 has nothing left anywhere, so the note
		# would only be noise.
		tasks = self._tasks(levels.MEMBER, [(30, 30)])

		with self.assertLogs(rewards_tasks.logger, level=logging.INFO) as captured:
			tasks.complete_required_searches()

		self.assertNotIn("mobile user agent", "".join(captured.output))


if __name__ == "__main__":
	unittest.main()
