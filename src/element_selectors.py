import re

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException
from selenium import webdriver


# The tier independent half of the level badge's own class, as in
# "text-rewardsLevelBadgeFg". A markup hook rather than a visible label, so it is
# not in Labels: unlike the text beside it, it needs no translating.
LEVEL_BADGE_CLASS = "rewardsLevelBadge"

# XPath 1.0 has no case insensitive compare, so translate() is how a text match
# is made case insensitive. Spelled out once rather than per selector.
_UPPERCASE = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_LOWERCASE = "abcdefghijklmnopqrstuvwxyz"


class ElementNotReady(NoSuchElementException):
	"""The element is in the page but not usable yet.

	A section this market does not ship and a section that has not finished
	hydrating both reach the caller as NoSuchElementException, which is why a
	run could report "not available in this UI variant" for something that was
	on screen. They need different messages and different next steps, so the
	second case gets its own type.

	Subclassed rather than separate, so every existing `except
	NoSuchElementException` keeps catching it.
	"""


class Labels:
	"""Visible labels the selectors match on.

	The Rewards markup carries no stable hooks for these controls, so they have
	to be found by their text. That makes the lookups language dependent even
	though they are market independent: a Rewards UI rendered in another
	language needs these translated, and there is exactly one place to do it.

	Matching is case insensitive and by substring unless noted.
	"""

	POINTS_BREAKDOWN = "points breakdown"
	READY_TO_CLAIM = "ready to claim"
	CLAIM = "claim"                      # exact label preferred, substring as fallback
	DAILY_SET_STREAK = "daily set streak"
	# Only safe scoped to the streaks section. Unscoped it also matches the
	# level up entry, "Complete the Daily Set for 7 days in a row", which is
	# why DAILY_SET_STREAK is tried against the whole page first.
	DAILY_SET = "daily set"
	# The badge words every tier as "<tier> Member", so this finds it whatever level
	# the account is on. Only reached when the badge class cannot be found: the tier
	# names on their own are not safe to match, since "Gold" names redemption offers
	# on the same page.
	MEMBERSHIP_LEVEL = "member"
	CARD_COMPLETED = "completed"
	# The full streak label on purpose: plain "visual search" also matches an
	# element on the dashboard, which can go stale mid-interaction.
	VISUAL_SEARCH_STREAK = "visual search streak"
	# The link out to Bing in the visual search panel. On an account that has
	# never done a visual search the same link reads "Activate streak" (#80).
	VISUAL_SEARCH_NOW = "search now"
	VISUAL_SEARCH_ACTIVATE = "activate streak"


class ElementSelectionUtils:
	"""Selectors for the Rewards UI.

	These are deliberately semantic rather than positional. The Rewards page is
	server-rendered React whose markup differs between markets and changes
	between deploys, so absolute XPaths like
	`/html/body/div[2]/div[2]/div/main/section[1]/...` resolve to nothing
	outside the exact variant they were written against.

	Two concrete cases this has to survive:

	1. Outside en-US the page can render an extra `exploreonbing` section, which
	   shifts every positional section index by one.
	2. Some sections are emitted twice for responsive layout. The first match in
	   document order can be the hidden, empty one, so container lookups must
	   pick the copy that is visible and actually has content.

	Anything the current variant does not ship raises NoSuchElementException so
	the caller can skip that task instead of aborting the whole run. Something
	that is present but not usable yet raises ElementNotReady instead, because
	skipping it is the wrong answer and so is the message that goes with it.
	"""

	def __init__(self, driver: webdriver.Edge):
		self.driver = driver

	# ------------------------------------------------------------------
	# helpers
	# ------------------------------------------------------------------

	def resolve(self, xpath: str):
		return self.driver.find_element(By.XPATH, xpath)

	def _container_by_id(self, element_id: str) -> WebElement:
		"""Return the usable copy of an id that may be present more than once.

		Only a copy that is both visible and has content is usable. A hidden copy
		still exposes its links to find_elements, but they cannot be clicked and
		their `.text` is empty, so returning one produces silent no-ops further
		up. Raising instead lets the caller's WebDriverWait retry while the page
		finishes hydrating.

		The two failures are not the same finding. No element with the id means
		this variant does not ship the section. An id that is there but has no
		usable copy means it is still rendering, so that one raises
		ElementNotReady.
		"""
		matches = self.driver.find_elements(By.ID, element_id)

		if not matches:
			raise NoSuchElementException(f"no element with id {element_id!r}")

		for match in matches:
			try:
				if match.is_displayed() and match.find_elements(By.TAG_NAME, "a"):
					return match
			except StaleElementReferenceException:
				continue

		raise ElementNotReady(
			f"{element_id!r} is present but no visible copy has content yet"
		)

	def _button_containing(self, needle: str, root: WebElement = None) -> WebElement:
		"""First button whose visible text contains `needle` (case-insensitive)."""
		scope = self.driver if root is None else root
		needle = needle.lower()

		for button in scope.find_elements(By.TAG_NAME, "button"):
			try:
				if needle in (button.text or "").lower():
					return button
			except StaleElementReferenceException:
				continue

		raise NoSuchElementException(f"no button containing {needle!r}")

	def _link_containing(self, needle: str, root: WebElement = None) -> WebElement:
		scope = self.driver if root is None else root
		needle = needle.lower()

		for link in scope.find_elements(By.TAG_NAME, "a"):
			try:
				if needle in (link.text or "").lower():
					return link
			except StaleElementReferenceException:
				continue

		raise NoSuchElementException(f"no link containing {needle!r}")

	# ------------------------------------------------------------------
	# navigation
	# ------------------------------------------------------------------

	def get_earn_tab(self):
		# The react-aria prefix is generated per build, so match on the suffix.
		return self.driver.find_element(By.CSS_SELECTOR, '[id$="-tab-/earn"]')

	def get_dashboard_tab(self):
		return self.driver.find_element(By.CSS_SELECTOR, '[id$="-tab-/dashboard"]')

	def get_sidebar_section(self):
		sections = self.driver.find_elements(By.TAG_NAME, "section")
		for section in sections:
			try:
				sec_id = section.get_dom_attribute("id") or ""
				if sec_id.startswith("react-aria") and section.is_displayed():
					if section.find_elements(By.TAG_NAME, "a") or section.find_elements(By.TAG_NAME, "button"):
						return section
			except StaleElementReferenceException:
				continue

		for section in sections:
			try:
				sec_id = section.get_dom_attribute("id") or ""
				if sec_id.startswith("react-aria"):
					return section
			except StaleElementReferenceException:
				continue

		raise NoSuchElementException("sidebar section not found")

	# ------------------------------------------------------------------
	# membership level
	# ------------------------------------------------------------------

	@staticmethod
	def _membership_level_xpath() -> str:
		"""The browser side filter for elements whose text mentions membership."""
		lowered = f"translate(., '{_UPPERCASE}', '{_LOWERCASE}')"

		return (
			"//*[self::p or self::span or self::div or self::h1 or self::h2 or self::h3]"
			f"[contains({lowered}, '{Labels.MEMBERSHIP_LEVEL.lower()}')]"
		)

	def _badges(self, by: str, selector: str) -> list[tuple[str, str]]:
		"""(class, text) for each match, shortest text first.

		Shortest first because a text search matches the badge's ancestors too, and
		the innermost match is the one that is only about the badge.
		"""
		found = []

		for element in self.driver.find_elements(by, selector):
			try:
				found.append((
					element.get_dom_attribute("class") or "",
					(element.text or "").strip(),
				))
			except StaleElementReferenceException:
				continue

		return sorted(found, key=lambda badge: len(badge[1]))

	def get_membership_level_badges(self) -> list[tuple[str, str]]:
		"""(class, text) for each element that looks like the level badge.

		The badge carries its tier twice over. The markup is

		    <p class="... text-rewardsLevelBadgeFg bg-rewardsGoldBadgeBg">Gold Member</p>

		so the tier is in the background class and again in the text. Both are handed
		back for levels.level_from_badge to decide between, which keeps the reading
		testable without a browser.

		The class is looked up first. LEVEL_BADGE_CLASS is the tier independent half
		of the badge's own class, so it finds the badge whatever tier the account is
		on, and it needs no translating. The text search is the fallback for a variant
		that renames the class; it is a far looser net, which is why it only runs when
		the class finds nothing.
		"""
		for by, selector in (
			(By.CSS_SELECTOR, f'[class*="{LEVEL_BADGE_CLASS}"]'),
			(By.XPATH, self._membership_level_xpath()),
		):
			badges = self._badges(by, selector)

			if badges:
				return badges

		raise NoSuchElementException("no membership level badge on the dashboard")

	# ------------------------------------------------------------------
	# daily set
	# ------------------------------------------------------------------

	def _streaks_button(self, index: int) -> WebElement:
		"""Positional fallback inside the streaks section.

		Same node the original absolute XPath pointed at, but anchored on the
		section id so an extra section earlier in the page cannot shift it.
		"""
		streaks = self.driver.find_element(By.ID, "streaks")

		return streaks.find_element(By.XPATH, f"./div/div[2]/div/div/button[{index}]")

	def get_open_daily_set_button(self):
		# Lives in the streaks section, not in a section of its own. Match on
		# "daily set streak" rather than "daily set", because the level up
		# section also has "Complete the Daily Set for 7 days in a row".
		try:
			return self._button_containing(Labels.DAILY_SET_STREAK)
		except NoSuchElementException:
			pass

		# Markets that word the streak label differently still carry "daily set"
		# on the opener, so fall back to matching that inside the streaks
		# section. Scoping is what makes the shorter needle safe: the level up
		# entry lives in a section of its own and stays out of reach.
		#
		# This replaces a fallback that took whatever sat third in the section.
		# On a partially rendered streaks section that was the mobile app entry,
		# and clicking it opens the app store instead of the panel, which is
		# what #45 and #46 describe. Matching on content finds the opener
		# wherever in the section it sits, and never returns a different streak.
		streaks = self.driver.find_element(By.ID, "streaks")

		try:
			return self._button_containing(Labels.DAILY_SET, root=streaks)
		except NoSuchElementException:
			# Absence rather than a wrong guess, so the wait above the caller
			# keeps retrying while the section fills, and reports a skip only
			# if it never does.
			raise NoSuchElementException(
				f"no button in the streaks section contains {Labels.DAILY_SET!r}"
			) from None

	def get_daily_set_elements(self):
		"""The daily set activities in the opened panel.

		Everything after the first link is not reliably an activity. The panel
		also carries promotional links, a referral card and a Bing app promo have
		both been observed sitting between the progress row and the activities.
		Handing one of those back gets it clicked, which navigates away from
		rewards.bing.com, and every element captured beforehand then goes stale.

		Matching on a Bing search alone was too narrow. "Turn referrals into
		rewards" is a real daily set activity that awards points, and it points
		at a rewards URL rather than a search. Three shapes have been observed:

		1. `bing.com/search?q=...`, the classic search activity,
		2. `bing.com/rewards/...`, seen on daily sets alongside the searches,
		3. `rewards.bing.com/...`, the same activity written against the
		   rewards host.

		The Bing app promo behind #45 is on `bingapp.microsoft.com`, so it stays
		out of all three, and so does anything else off those hosts. If nothing
		matches, return nothing: clicking a promo is worse than skipping the
		task, and the caller already reports the shortfall.
		"""
		activities = []

		for link in self.get_sidebar_section().find_elements(By.TAG_NAME, "a"):
			try:
				if self._is_daily_set_activity(link.get_dom_attribute("href") or ""):
					activities.append(link)
			except StaleElementReferenceException:
				continue

		return activities

	@staticmethod
	def _is_daily_set_activity(href: str) -> bool:
		"""Whether an href in the daily set panel is an activity rather than a promo."""
		return any(
			marker in href
			for marker in ("bing.com/search", "bing.com/rewards", "rewards.bing.com/")
		)

	def get_daily_set_element_by_index(self, index: int):
		elements = self.get_daily_set_elements()
		if index < len(elements):
			return elements[index]
		raise NoSuchElementException(f"daily set element at index {index} not found")

	# ------------------------------------------------------------------
	# explore on bing (absent in en-US, present in some other markets)
	# ------------------------------------------------------------------

	def get_explore_on_bing_elements(self):
		"""The cards of the Explore on Bing section, or [] when it is not there.

		A section that is on the page and still rendering raises ElementNotReady
		instead of coming back as [], so the task can wait for it rather than
		report a market that does not ship it.
		"""
		try:
			container = self._container_by_id("exploreonbing")
		except ElementNotReady:
			raise
		except NoSuchElementException:
			return []

		return container.find_elements(By.TAG_NAME, "a")

	# ------------------------------------------------------------------
	# visual search
	# ------------------------------------------------------------------

	def get_open_visual_search_sidebar(self):
		try:
			return self._button_containing(Labels.VISUAL_SEARCH_STREAK)
		except NoSuchElementException:
			# Not every layout ships this entry point. Where it does but the
			# label differs, fall back to the original position in streaks.
			return self._streaks_button(5)

	def get_search_now_link_from_visual_search_sidebar(self):
		sidebar = self.get_sidebar_section()

		for label in (Labels.VISUAL_SEARCH_NOW, Labels.VISUAL_SEARCH_ACTIVATE):
			try:
				return self._link_containing(label, sidebar)
			except NoSuchElementException:
				continue

		# Fall back to the original positional behaviour.
		links = sidebar.find_elements(By.TAG_NAME, "a")

		if len(links) < 2:
			raise NoSuchElementException("visual search sidebar has no usable link")

		return links[1]

	def visual_search_done_today(self) -> bool:
		"""Whether the panel shows today's visual search as done.

		Once it is, search now stops being a link. It is rendered as a span with
		role="link" and aria-disabled="true", and the panel has no <a> left at
		all, so waiting for the link runs out however long it waits.
		"""
		sidebar = self.get_sidebar_section()

		for control in sidebar.find_elements(By.CSS_SELECTOR, '[role="link"]'):
			try:
				if (
					control.get_dom_attribute("aria-disabled") == "true"
					and Labels.VISUAL_SEARCH_NOW in (control.text or "").lower()
				):
					return True
			except StaleElementReferenceException:
				continue

		return False

	def get_visual_search_button(self):
		return self.driver.find_element(By.CSS_SELECTOR, "#sb_form > div.camera.icon")

	def get_visual_search_file_input(self):
		return self.driver.find_element(By.CSS_SELECTOR, "#sb_fileinput")

	# ------------------------------------------------------------------
	# cards
	# ------------------------------------------------------------------

	def get_all_misc_cards(self):
		return self._container_by_id("moreactivities").find_elements(By.TAG_NAME, "a")

	def extract_card_descriptions(self, card: WebElement):
		try:
			return card.find_element(By.CSS_SELECTOR, "p:nth-child(2)").text
		except NoSuchElementException:
			paragraphs = card.find_elements(By.TAG_NAME, "p")

			return paragraphs[1].text if len(paragraphs) > 1 else (card.text or "")

	def _card_status_element(self, card: WebElement):
		return card.find_element(By.CSS_SELECTOR, "div.flex.w-full.items-center.gap-2")

	def card_is_complete(self, card: WebElement):
		try:
			status = self._card_status_element(card).text
		except NoSuchElementException:
			return False

		return Labels.CARD_COMPLETED in (status or "").lower()

	def get_card_point_value(self, card: WebElement):
		try:
			elem = self._card_status_element(card).find_element(By.TAG_NAME, "p")
		except NoSuchElementException:
			return 0

		# Rendered as "+10", and other variants add a unit, so pull the digits out
		# rather than relying on int() accepting the exact string.
		digits = re.search(r"\d+", elem.text or "")

		return int(digits.group()) if digits else 0

	def element_is_fully_in_viewport(self, elem: WebElement) -> bool:
		js_viewport_check = """
var elem = arguments[0];
var box = elem.getBoundingClientRect();

return (
	box.top >= 0 &&
	box.left >= 0 &&
	box.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
	box.right <= (window.innerWidth || document.documentElement.clientWidth)
);
"""

		return self.driver.execute_script(js_viewport_check, elem)

	# ------------------------------------------------------------------
	# points breakdown
	# ------------------------------------------------------------------

	def get_points_breakdown_button(self):
		return self._button_containing(Labels.POINTS_BREAKDOWN)

	def get_close_button_on_points_breakdown(self):
		return self.get_generic_sidebar_close_button()

	def get_points_earned_from_searches_on_points_breakdown(self):
		"""Return (earned, max) for the Bing search row of the breakdown panel.

		The value renders as two spans, "3" and "/15", so an XPath on text()
		matches only the second half. Read the panel's rendered text instead and
		anchor on the row label, because several rows share the same value class
		and a reordering would otherwise silently return the wrong number.
		"""
		sidebar = self.get_sidebar_section()
		text = sidebar.text or ""
		lines = [line.strip() for line in text.splitlines()]

		def parse(candidate: str):
			match = re.fullmatch(r"([\d,]+)\s*/\s*([\d,]+)", candidate)

			if not match:
				return None

			return int(match.group(1).replace(",", "")), int(match.group(2).replace(",", ""))

		for index, line in enumerate(lines):
			if "bing search" in line.lower():
				for candidate in lines[index + 1:index + 3]:
					parsed = parse(candidate)

					if parsed:
						return parsed

		# Fall back to the first fraction anywhere in the panel.
		match = re.search(r"([\d,]+)\s*/\s*([\d,]+)", text)

		if match:
			return int(match.group(1).replace(",", "")), int(match.group(2).replace(",", ""))

		raise NoSuchElementException("no points fraction found in the breakdown sidebar")

	# ------------------------------------------------------------------
	# bonus
	# ------------------------------------------------------------------

	def get_bonus_button_on_dashboard(self):
		return self._button_containing(Labels.READY_TO_CLAIM)

	def get_claim_bonus_points_button(self):
		sidebar = self.get_sidebar_section()
		buttons = sidebar.find_elements(By.TAG_NAME, "button")

		# Prefer the button whose whole label is the action. A substring match
		# would hit the "Ready to claim" heading before the actual Claim button.
		for button in buttons:
			try:
				if (button.text or "").strip().lower() == Labels.CLAIM:
					return button
			except StaleElementReferenceException:
				continue

		for button in buttons:
			try:
				if Labels.CLAIM in (button.text or "").lower():
					return button
			except StaleElementReferenceException:
				continue

		if len(buttons) < 3:
			raise NoSuchElementException("bonus sidebar has no claim button")

		return buttons[2]

	def get_generic_sidebar_close_button(self):
		sidebar = self.get_sidebar_section()

		try:
			return sidebar.find_element(By.CSS_SELECTOR, "button[aria-label*='lose']")
		except NoSuchElementException:
			buttons = sidebar.find_elements(By.TAG_NAME, "button")

			if not buttons:
				raise NoSuchElementException("sidebar has no buttons")

			return buttons[0]

	# ------------------------------------------------------------------
	# bing search page
	# ------------------------------------------------------------------

	def get_bing_search_bar(self):
		return self.driver.find_element(By.TAG_NAME, "textarea")

	def get_clear_bing_search_query_button(self):
		return self.driver.find_element(By.ID, "sw_clx")
