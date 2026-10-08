"""The two research prompts Claude follows at run time (`.claude/skills/briefing/SKILL.md`, read by the briefing and
Sunday routines, and `.claude/skills/trade-offer/SKILL.md`) quote numbers the code owns and name the overrides.json
keys the code reads. A number in the prose that drifts from the constant (the Friday Questionable sat at 0.25 while
`P_ZERO` said 0.30) sends Claude's `p_zero` override the wrong way, and an override key the prompt never names is
research that cannot reach the math."""
import re
from pathlib import Path

from ff.model.projections import P_ZERO, QUESTIONABLE_BY_WEEKDAY, WIND_MPH_START

ROOT = Path(__file__).resolve().parents[1]
BRIEFING = (ROOT / ".claude" / "skills" / "briefing" / "SKILL.md").read_text()
TRADE_OFFER = (ROOT / ".claude" / "skills" / "trade-offer" / "SKILL.md").read_text()
OVERRIDE_KEYS = ("p_zero", "mu_mult", "weeks_out", "ros_mult", "note")
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def questionable_groups() -> list[tuple[str, int]]:
    """The code's Questionable sit risk by weekday as the prompt should quote it: consecutive days at one value
    collapse to a range ("Mon–Wed 15%"), a lone day stands alone ("Thu 20%"), and the days `QUESTIONABLE_BY_WEEKDAY`
    does not list take `P_ZERO["QUESTIONABLE"]` (the Friday number)."""
    by_day = [QUESTIONABLE_BY_WEEKDAY.get(d, P_ZERO["QUESTIONABLE"]) for d in range(7)]
    groups, start = [], 0
    for d in range(1, 8):
        if d == 7 or by_day[d] != by_day[start]:
            label = DAYS[start] if d - 1 == start else f"{DAYS[start]}–{DAYS[d - 1]}"
            groups.append((label, round(by_day[start] * 100)))
            start = d
    return groups


def test_briefing_quotes_the_codes_questionable_sit_risk_by_weekday():
    quoted = dict(re.findall(r"((?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)(?:–(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun))?) (\d+)%", BRIEFING))
    for label, pct in questionable_groups():
        assert quoted.get(label) == str(pct), f"briefing skill should say '{label} {pct}%' for a Questionable; it quotes {quoted}"
    # the p_zero guide's Friday line is the code's Friday default, not a number of its own
    m = re.search(r"Q \+ limited(?: practice)? Fri[^;\n]*?(\d\.\d+)", BRIEFING)
    assert m, "briefing skill should give a p_zero for 'Q + limited Fri'"
    assert float(m.group(1)) == P_ZERO["QUESTIONABLE"]
    # the constant is named, so the next change to it has a grep hit in the prompt
    assert "QUESTIONABLE_BY_WEEKDAY" in BRIEFING


def test_trade_offer_names_every_override_key():
    for key in OVERRIDE_KEYS:
        assert f"`{key}`" in TRADE_OFFER or f'"{key}"' in TRADE_OFFER, f"trade-offer skill never names overrides.json key {key}"


def test_briefing_asks_for_usage_depth_chart_and_weather():
    low = BRIEFING.lower()
    assert "`mu_mult`" in BRIEFING and "p_zero" in BRIEFING
    for ask in ("snap share", "route share", "depth chart", "weather"):
        assert ask in low, f"briefing skill research step never asks for {ask}"
    # the code discounts wind already (D5); research adds only what the forecast does not capture
    assert "wind" in low and f"{WIND_MPH_START:.0f} mph" in BRIEFING


def test_trade_offer_read_rules_on_the_row():
    assert "items" in TRADE_OFFER and "rule" in TRADE_OFFER.lower()
    assert "offer:" in TRADE_OFFER, "the trade-offer skill should name the offer row id Claude rules on"


def test_prompts_never_hand_claude_a_projection_number():
    for text in (BRIEFING, TRADE_OFFER):
        assert "`mu`" not in text and "mu_ros" not in text.replace("mu_ros_active", "")
