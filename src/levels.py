"""The Microsoft Rewards levels, and what each one is worth.

An account's level decides how much a day of searching can earn, so a run has to
know which one it is on. Two rows of the levels table matter to the bot: the
daily Bing search cap and the rate those searches pay. The rest is recorded
because it is what the table states and it explains why levelling matters, but a
search bot cannot act on a store multiplier or a redemption coupon, so nothing
reads those fields.

These are documented totals rather than live readings, and they span every
surface Rewards counts rather than the desktop searches this bot makes. What an
account can actually earn from a desktop run is whatever the points breakdown
panel reports, and that is the only number a run works towards. The table is
here to name the level and to explain the shortfall, never to override the
panel: a Gold account reading 90/90 is finished, not 60 short.

    REWARDS_LEVEL=silver python src/main.py

Unset, a run reads the level off the dashboard and assumes Member when it
cannot. Member has the lowest cap of the three, so a wrong guess can only ever
under-reach.
"""

import logging
import os
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

ENV_VAR = "REWARDS_LEVEL"

# Every level pays the same rate; only the daily ceiling moves.
POINTS_PER_SEARCH = 3

# Tier names are read out of prose and out of class attributes, so a value is
# split into words before matching. Substring matching would find "gold" inside
# "goldfish" and inside "bg-goldenrod"; word matching will not.
_WORDS = re.compile(r"[a-z]+")

# Class attributes are camelCase, so "bg-rewardsGoldBadgeBg" has to break at the
# case changes as well as at the punctuation before "gold" is a word of its own.
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


@dataclass(frozen=True)
class Level:
	"""One rung of the Rewards ladder, as the levels table states it.

	None is the table's "-": a requirement that does not apply to this level, or
	a benefit it does not carry.
	"""

	name: str

	# What reaching this level takes, per month.
	monthly_points_required: int | None
	monthly_level_up_activities: int | None

	# What holding it is worth.
	#
	# daily_search_points_total spans every surface Rewards counts, not just
	# the desktop searches this bot makes. A Gold account was measured at 90
	# desktop points against a documented 150: the remaining 60 needs searches
	# from a mobile user agent, which nothing here sends. Treating the total as
	# a desktop ceiling makes a run keep searching after the real quota is full,
	# earning nothing, so it is recorded for reference and never used as a target.
	daily_search_points_total: int
	store_points_per_dollar: int
	xbox_points_per_dollar: int
	monthly_level_bonus: int
	monthly_default_search_bonus: int
	monthly_bing_star_bonus: int
	exclusive_earning_offers: bool
	redemption_coupon_points: int | None


MEMBER = Level(
	name="Member",
	monthly_points_required=None,
	monthly_level_up_activities=None,
	daily_search_points_total=30,
	store_points_per_dollar=1,
	xbox_points_per_dollar=4,
	monthly_level_bonus=60,
	monthly_default_search_bonus=30,
	monthly_bing_star_bonus=300,
	exclusive_earning_offers=False,
	redemption_coupon_points=None,
)

SILVER = Level(
	name="Silver",
	monthly_points_required=500,
	monthly_level_up_activities=None,
	daily_search_points_total=150,
	store_points_per_dollar=10,
	xbox_points_per_dollar=4,
	monthly_level_bonus=180,
	monthly_default_search_bonus=90,
	monthly_bing_star_bonus=900,
	exclusive_earning_offers=True,
	redemption_coupon_points=100,
)

GOLD = Level(
	name="Gold",
	monthly_points_required=750,
	monthly_level_up_activities=2,
	daily_search_points_total=150,
	store_points_per_dollar=10,
	xbox_points_per_dollar=4,
	monthly_level_bonus=420,
	monthly_default_search_bonus=210,
	monthly_bing_star_bonus=2100,
	exclusive_earning_offers=True,
	redemption_coupon_points=200,
)

# Lowest first, so the order is the ladder itself.
LEVELS = (MEMBER, SILVER, GOLD)

# What a run assumes when it has not been told and cannot tell. The lowest cap
# of the three on purpose: under-reaching only forgoes points the panel already
# said were unavailable, while over-reaching spends searches on a ceiling that
# is not there.
DEFAULT = MEMBER


def by_name(name: str) -> Level | None:
	"""The level with this name, or None. Case and whitespace insensitive."""
	wanted = (name or "").strip().lower()

	for level in LEVELS:
		if level.name.lower() == wanted:
			return level

	return None


def level_from_text(value: str) -> Level | None:
	"""The level named in a piece of page text, or None where it is not clear.

	Works on a class attribute as readily as on visible text: both are split into
	words first, camelCase included, so "bg-rewardsGoldBadgeBg" and "Gold Member"
	each yield "gold".

	Member is deliberately the weakest signal. The badge words every tier as
	"<tier> Member", so reading "member" as an equal answer would make the real
	badge ambiguous and return nothing at all. It therefore only answers when no
	stronger name is present. The cost is that ordinary prose like "member since
	2019" reads as Member, which is the level a run already assumes when it
	cannot tell, and which carries the lowest cap.

	Silver and Gold name only themselves, so a value carrying both has not said
	which the account is on and gets no answer. Guessing there would raise the
	search target for an account that cannot reach it.
	"""
	spaced = _CAMEL_BOUNDARY.sub(" ", value or "")
	words = set(_WORDS.findall(spaced.lower()))
	named = [level for level in (SILVER, GOLD) if level.name.lower() in words]

	if named:
		return named[0] if len(named) == 1 else None

	return MEMBER if MEMBER.name.lower() in words else None


def level_from_badge(class_attribute: str, text: str) -> Level | None:
	"""The tier a level badge names, from its class first and its text second.

	The class is language independent, "bg-rewardsGoldBadgeBg" in every market,
	while the text beside it is translated. So the class is asked first, and the
	text is what answers when a variant renames the class.
	"""
	return level_from_text(class_attribute) or level_from_text(text)


def configured() -> Level | None:
	"""The level named by $REWARDS_LEVEL, or None when it is unset.

	An unusable value warns and returns None rather than raising. A typo in an
	environment variable must not be able to take down an unattended run, and the
	caller falls back to a level that cannot over-reach.
	"""
	raw = os.environ.get(ENV_VAR, "").strip()

	if not raw:
		return None

	chosen = by_name(raw)

	if chosen is None:
		logger.warning(
			"Unknown %s value %r, ignoring it. Known levels: %s.",
			ENV_VAR, raw, ", ".join(level.name for level in LEVELS)
		)

	return chosen
