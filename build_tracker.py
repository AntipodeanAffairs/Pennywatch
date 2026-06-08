#!/usr/bin/env python3
"""
Wong Condemnations Tracker — fetch + classify pipeline.

Pulls @SenatorWong's tweets via the X API v2, classifies each one against the
methodology in METHODOLOGY.md, and writes:

  - tweets.json      : full classified dataset
  - summary.json     : precomputed counts (by country, severity, month)
  - index.html       : static site with the dataset embedded inline

Usage:
    export X_BEARER_TOKEN="..."          # from developer.x.com
    python build_tracker.py              # fetch + classify + rebuild site
    python build_tracker.py --no-fetch   # reclassify existing tweets.json only
    python build_tracker.py --seed       # use seed_tweets.json (no API call)

The classifier is intentionally simple and transparent. Edit TRIGGERS and
TARGETS below — every change should be reflected in METHODOLOGY.md and the
version bumped.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HANDLE = "SenatorWong"
SINCE = "2022-06-01T00:00:00Z"   # Wong sworn in as Foreign Minister
METHODOLOGY_VERSION = "1.5.2"

# v1.4.0: incremental fetching. Each daily run fetches only tweets newer
# than the most recent tweet in the existing dataset, minus this overlap
# window in days (to catch any tweets the previous run missed near the
# boundary due to X API filtering or rate limits).
INCREMENTAL_OVERLAP_DAYS = 5

HERE = Path(__file__).parent
TWEETS_PATH = HERE / "tweets.json"
SUMMARY_PATH = HERE / "summary.json"
SEED_PATH = HERE / "seed_tweets.json"
HTML_PATH = HERE / "index.html"
TEMPLATE_PATH = HERE / "index.template.html"
MANUAL_PATH = HERE / "manual_tweets.json"   # tweets the X API missed
MISSED_IDS_PATH = HERE / "missed_ids.json"  # tweet IDs to fetch directly by /2/tweets/?ids=...

# Critical severity tiers, ordered strongest → weakest. The classifier assigns
# the strongest tier any trigger from the tweet matches.
TRIGGERS: list[tuple[str, list[str]]] = [
    ("Condemn", [
        r"\bcondemn\b", r"\bcondemns\b", r"\bcondemned\b", r"\bcondemning\b",
        r"\bcondemnation\b", r"\bdenounce\b", r"\bdenounces\b",
    ]),
    ("Criticise", [
        r"\bdeplore\b", r"\bdeplores\b", r"\bdeplored\b", r"\bdeplorable\b",
        r"\bunacceptable\b", r"\bappalling\b", r"\bappalled\b",
        r"\babhorrent\b", r"\boutrageous\b", r"\batrocity\b", r"\batrocities\b",
        r"\breject(s|ed)?\b", r"\bsanction(s|ed|ing)?\b",
        # v1.3.8: severe diplomatic-protest actions — expelling or recalling
        # ambassadors. Recall (of one's own) is the stronger; expel (of theirs)
        # is also strong. Both at Criticise tier. Requires proximity to
        # "ambassador" to avoid false positives on "recall" / "expel" in
        # unrelated contexts.
        r"\bexpel(s|led|ling)?\b.{0,40}\b(ambassador|envoy|diplomat|high commissioner)\b",
        r"\brecall(s|ed|ing)? (our|the|its)\b.{0,40}\b(ambassador|envoy|diplomat|high commissioner)\b",
    ]),
    ("Concern", [
        r"\bconcerned\b", r"\bdeeply concerned\b", r"\btroubled\b",
        r"\balarmed\b", r"\bdismayed\b", r"\bdisturbed\b", r"\bregret\b",
        # v1.3.8: diplomatic protest — calling in or summoning a foreign
        # ambassador is a formal critical action that signals serious
        # displeasure short of recall/expulsion. Recorded at Concern tier.
        # Requires proximity to "ambassador" / "envoy" / "diplomat" /
        # "high commissioner" to avoid false positives on common phrases
        # like "call in sick" or "summon courage".
        r"\b(call(s|ed|ing)? in|summon(s|ed|ing)?|haul(s|ed|ing)? in)\b.{0,40}\b(ambassador|envoy|diplomat|high commissioner|chargé d'affaires)\b",
        # v1.3.1: "restraint" is a diplomatic soft-criticism — recorded at
        # Concern tier. Patterns require the trigger to be near restraint
        # to avoid bare "restraint" false positives.
        r"\bexercise of restraint\b",
        r"\b(show|exercise|practise|practice|exercising) (maximum |utmost |the greatest )?restraint\b",
        r"\bmaximum restraint\b", r"\butmost restraint\b",
        r"\b(call(s|ing|ed)? (for|on)|urges? .{0,40})\brestraint\b",
        # v1.3.1: "how X defends itself matters" / "the manner in which X
        # defends" — diplomatic soft-criticism that grants the right to
        # defend while flagging conduct as a concern. Same register as
        # restraint. Content-neutral pattern, though in current diplomatic
        # usage it fires mostly on Israel-related statements — a fact about
        # the phrase's usage, not about the rule.
        r"\bhow (\w+\s?){0,3}(defends?|defending|responds?|responding|conducts?|conducting).{0,40}\bmatters?\b",
        r"\bmanner in which\b.{0,60}\b(defends?|defending|responds?|responding|conducts?|conducting)\b",
        r"\bthe way (\w+\s?){1,3}(defends?|defending|responds?|responding|conducts?|conducting).{0,40}\bmatters?\b",
    ]),
    ("Call for action", [
        # explicit imperatives
        r"\bmust end\b", r"\bmust stop\b", r"\bmust cease\b", r"\bmust release\b",
        r"\bmust (be allowed|be protected|be guaranteed|be ensured|be respected)\b",
        r"\bmust (allow|protect|guarantee|ensure|respect|halt|withdraw)\b",
        r"\bdemand(s|ed)?\b",
        # call-on variants — v1.3 broadened from just "call/calls on" to include
        # the "calling on" gerund form and "called on" past tense, plus
        # "calling for" which appears in ceasefire-type statements.
        # v1.3.4: added bare "call for" / "calls for" — these catch "our
        # call for the release of detained Australians" patterns that the
        # gerund/past forms alone missed.
        r"\bcalls? on\b", r"\bcalled on\b", r"\bcalling on\b",
        r"\bcalling for\b", r"\bcalled for\b", r"\bcalls? for\b",
        r"\b(our|the|a) call for\b",
        # urge variants — v1.3 relaxed to allow 1–2 intermediate words
        # ("urge all parties to", "urge the regime to") and added "urging".
        r"\burges? (\w+ ){0,2}\w+ to\b",
        r"\burging (\w+ ){0,2}\w+ to\b",
        r"\burges? (an?|the) (immediate|urgent)\b",
        # passive constructions diplomatic language often uses
        r"\baid must flow\b",
        r"\b(immediate|urgent|unimpeded) (ceasefire|access|withdrawal|release)\b",
    ]),
]

# Positive warmth tiers, ordered strongest → weakest. Same matching rule:
# the strongest tier any trigger fires wins.
POSITIVE_TRIGGERS: list[tuple[str, list[str]]] = [
    ("Endorse", [
        # explicit positive commitment / praise
        r"\bcongratulat(e|es|ed|ing|ions)\b", r"\bcommend(s|ed|ing)?\b",
        r"\bapplaud(s|ed|ing)?\b", r"\bsalute(s|d)?\b", r"\bhonou?r(s|ed)? the\b",
        r"\bwarmly welcome(s|d)?\b", r"\bcelebrate(s|d)?\b",
    ]),
    ("Commend", [
        r"\bwelcome(s|d)?\b", r"\bproud (to|of)\b", r"\bpleased to (welcome|meet|host|see)\b",
        r"\bstrong(ly)? support(s|ed)?\b", r"\bdelighted\b",
    ]),
    ("Appreciate", [
        r"\bthank(s|ed|ing)?\b", r"\bgrateful\b", r"\bappreciate(s|d)?\b",
        r"\bvalue(s|d)?\b", r"\brecognis(e|es|ed|ing)\b",
        r"\bclose (partner|partnership|friend|friendship)\b",
        r"\bdeep partnership\b", r"\benduring (partnership|friendship)\b",
    ]),
    ("Solidarity", [
        # sympathy, condolences, standing-with — these were excluded under v1.0,
        # now counted as positive-toward statements per v1.2.
        r"\bthoughts (are )?with\b", r"\bthoughts (go|are going) out\b",
        r"\bhearts go out\b", r"\bcondolences\b",
        r"\bmourn(s|ed|ing)?\b", r"\bstand with the people of\b",
        r"\bstands? with\b", r"\bin solidarity with\b",
        r"\boffer(s|ed)? (our )?support to\b",
        # v1.3.2: "shared condolences with" / "shared my condolences with" /
        # "expressed condolences to" — explicit condolence-sharing constructions.
        r"\b(shared|share|expressed|extended|offered) (my |our |deepest |sincere )*condolences\b",
    ]),
]

# State actors. Each entry: canonical_name -> list of patterns that mean it.
# Patterns are matched case-insensitively against the tweet text.
#
# Per methodology v1.1: any named head of state, head of government, cabinet
# minister, or senior official attributes to their country. Add names below
# under the country they serve.
TARGETS: dict[str, list[str]] = {
    "Russia": [
        r"\bRussia\b", r"\bRussian (regime|government|authorities|forces|military|federation)\b", r"\bKremlin\b",
        # named officials
        r"\bPutin\b", r"\bLavrov\b", r"\bMedvedev\b", r"\bShoigu\b", r"\bPeskov\b", r"\bMishustin\b",
    ],
    "Iran": [
        r"\bIran\b", r"\bIranian (regime|government|authorities|forces)\b", r"\bIRGC\b", r"\bRevolutionary Guard\b",
        # named officials
        r"\bKhamenei\b", r"\bPezeshkian\b", r"\bAraghchi\b", r"\bRaisi\b",
    ],
    "China": [
        r"\bChina\b", r"\bChinese (government|authorities|Communist Party|Coast Guard)\b", r"\bPRC\b", r"\bBeijing\b",
        # named officials
        r"\bXi Jinping\b", r"\bWang Yi\b", r"\bLi Qiang\b", r"\bQin Gang\b",
    ],
    "North Korea": [
        r"\bNorth Korea(n)?\b", r"\bDPRK\b", r"\bPyongyang\b",
        # named officials
        r"\bKim Jong[- ]?Un\b", r"\bKim Yo[- ]?Jong\b",
    ],
    "Myanmar": [
        r"\bMyanmar\b", r"\bBurm(a|ese)\b", r"\bTatmadaw\b", r"\bMyanmar (junta|regime|military)\b",
        # named officials
        r"\bMin Aung Hlaing\b",
    ],
    "Israel": [
        r"\bIsrael(i)?\b", r"\bIDF\b", r"\bIsraeli (government|forces|cabinet)\b", r"\bKnesset\b",
        # named ministers and senior officials
        r"\bNetanyahu\b", r"\bBen[- ]Gvir\b", r"\bSmotrich\b", r"\bGallant\b", r"\bIsrael Katz\b",
        r"\bSa'ar\b", r"\bDermer\b",
    ],
    "Syria": [
        r"\bSyria(n)?\b",
        # named officials (Assad regime through Dec 2024; al-Sharaa thereafter)
        r"\bAssad\b", r"\bal[- ]?Sharaa\b",
    ],
    "Venezuela": [
        r"\bVenezuela(n)?\b",
        r"\bMaduro\b", r"\bCabello\b",
    ],
    "Belarus": [
        r"\bBelarus(ian)?\b",
        r"\bLukashenko\b",
    ],
    "Afghanistan": [
        r"\bAfghan(istan)?\b", r"\bTaliban\b",
        r"\bAkhundzada\b", r"\bHaqqani\b",
    ],
    "Sudan": [
        r"\bSudan(ese)?\b", r"\bRSF\b", r"\bRapid Support Forces\b", r"\bSAF\b",
        r"\bBurhan\b", r"\bHemedti\b", r"\bDagalo\b",
    ],
    "United States": [
        r"\bUnited States (administration|government)\b", r"\bTrump administration\b",
        r"\bU\.S\. (government|administration|tariffs)\b",
    ],
    "Saudi Arabia": [r"\bSaudi Arabia(n)?\b", r"\bKSA\b", r"\bMBS\b", r"\bMohammed bin Salman\b"],
    "Türkiye": [
        r"\bTürkiye\b", r"\bTurkey\b", r"\bTurkish (government|authorities)\b",
        r"\bErdoğan\b", r"\bErdogan\b", r"\bFidan\b",
    ],
    "Ethiopia": [r"\bEthiopia(n)?\b", r"\bTPLF\b", r"\bAbiy Ahmed\b"],
    "Eritrea": [r"\bEritrea(n)?\b", r"\bIsaias Afwerki\b"],
    "Cuba": [r"\bCuba(n)?\b", r"\bDíaz[- ]Canel\b", r"\bDiaz[- ]Canel\b"],
    "Nicaragua": [r"\bNicaragua(n)?\b", r"\bOrtega\b", r"\bMurillo\b"],
    "Hungary": [r"\bHungar(y|ian government)\b", r"\bOrbán\b", r"\bOrban\b"],
    # --- Allies and partners (most often appearing in positive statements) ---
    "Ukraine": [r"\bUkrain(e|ian)\b", r"\bZelensky\b", r"\bZelenskyy\b", r"\bKyiv\b"],
    "Japan": [r"\bJapan(ese)?\b", r"\bTokyo\b", r"\bIshiba\b", r"\bKishida\b", r"\bIwaya\b"],
    "South Korea": [r"\b(South Korea|Republic of Korea|ROK)\b", r"\bSeoul\b", r"\bYoon Suk[- ]Yeol\b", r"\bLee Jae[- ]?myung\b"],
    "India": [r"\bIndia(n)?\b", r"\bNew Delhi\b", r"\bModi\b", r"\bJaishankar\b"],
    "Indonesia": [r"\bIndonesia(n)?\b", r"\bJakarta\b", r"\bPrabowo\b", r"\bJokowi\b", r"\bSugiono\b", r"\bRetno\b"],
    "Philippines": [r"\bPhilippine(s)?\b", r"\bManila\b", r"\bMarcos\b", r"\bManalo\b"],
    "Vietnam": [r"\bVietnam(ese)?\b", r"\bHanoi\b"],
    "Singapore": [r"\bSingapore(an)?\b", r"\bLawrence Wong\b", r"\bBalakrishnan\b"],
    "Malaysia": [r"\bMalaysia(n)?\b", r"\bAnwar\b"],
    "Thailand": [r"\bThai(land)?\b", r"\bBangkok\b"],
    "New Zealand": [r"\bNew Zealand\b", r"\bAotearoa\b", r"\bLuxon\b", r"\bPeters\b"],
    "United Kingdom": [r"\bUnited Kingdom\b", r"\bU\.?K\.?\b", r"\bBritain\b", r"\bBritish\b", r"\bLondon\b", r"\bStarmer\b", r"\bLammy\b"],
    "France": [r"\bFrance\b", r"\bFrench (government|Republic|Foreign Minister)\b", r"\bMacron\b", r"\bBarrot\b"],
    "Germany": [r"\bGerman(y|ies)?\b", r"\bBerlin\b", r"\bScholz\b", r"\bMerz\b", r"\bBaerbock\b"],
    "Canada": [r"\bCanad(a|ian)\b", r"\bOttawa\b", r"\bTrudeau\b", r"\bCarney\b", r"\bJoly\b"],
    "European Union": [r"\bEuropean Union\b", r"\bthe EU\b", r"\bvon der Leyen\b", r"\bKallas\b", r"\bBorrell\b"],
    "Papua New Guinea": [r"\bPapua New Guinea\b", r"\bPNG\b", r"\bMarape\b", r"\bTkatchenko\b"],
    "Fiji": [r"\bFiji(an)?\b", r"\bRabuka\b"],
    "Solomon Islands": [r"\bSolomon Islands\b", r"\bManele\b"],
    "Vanuatu": [r"\bVanuatu\b"],
    "Tonga": [r"\bTonga(n)?\b"],
    "Samoa": [r"\bSamoa(n)?\b"],
    "Tuvalu": [r"\bTuvalu(an)?\b"],
    "Kiribati": [r"\bKiribati\b"],
    "Cook Islands": [r"\bCook Islands\b"],
    "Timor-Leste": [r"\bTimor[- ]Leste\b", r"\bEast Timor\b"],
    "Palestine": [r"\bPalestin(e|ian)\b", r"\bPalestinian Authority\b", r"\bAbbas\b"],
    "Lebanon": [r"\bLebanon\b", r"\bLebanese (government|authorities|Armed Forces|cabinet)\b", r"\bBeirut\b", r"\bLAF\b", r"\bMikati\b", r"\bAoun\b", r"\bBerri\b", r"\bSalam\b"],
    "Jordan": [r"\bJordan(ian)?\b", r"\bAmman\b", r"\bAbdullah II\b", r"\bSafadi\b"],
    "Egypt": [r"\bEgypt(ian)?\b", r"\bCairo\b", r"\bSisi\b", r"\bel[- ]Sisi\b", r"\bShoukry\b", r"\bAbdelatty\b"],
    "United Arab Emirates": [r"\bUnited Arab Emirates\b", r"\bUAE\b", r"\bAbu Dhabi\b", r"\bDubai\b", r"\bMohamed bin Zayed\b", r"\bMBZ\b"],
    "Qatar": [r"\bQatar(i)?\b", r"\bDoha\b", r"\bTamim\b"],
    "Iraq": [r"\bIraq(i)?\b", r"\bBaghdad\b"],
    "Yemen": [r"\bYemen(i)?\b", r"\bSanaa\b"],
    "Libya": [r"\bLibya(n)?\b", r"\bTripoli\b"],
}

# Non-state actors — recorded separately, do NOT contribute to country counts.
NON_STATE: dict[str, list[str]] = {
    "Hamas": [r"\bHamas\b"],
    "Hezbollah": [r"\bHezbollah\b", r"\bHizbullah\b", r"\bHizballah\b", r"\bHizb[- ]?Allah\b"],
    "Houthis": [r"\bHouthi(s)?\b", r"\bAnsar Allah\b"],
    "ISIS": [r"\bISIS\b", r"\bISIL\b", r"\bDa'?esh\b", r"\bIslamic State\b"],
    "Wagner": [r"\bWagner( Group)?\b"],
}

# Tweets containing these phrases are excluded — sympathy / condolence /
# quoting someone else.
EXCLUSION_PATTERNS = [
    r"thoughts (and prayers )?(are )?with",
    r"condolences to",
    r"join(s|ed)? .* in condemning",   # "PM joined X in condemning Y" tends to
                                        # be a report, not an original criticism;
                                        # flag for review rather than auto-exclude
]

# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

def _compile(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]

_TRIGGER_RX = [(tier, _compile(pats)) for tier, pats in TRIGGERS]
_POSITIVE_RX = [(tier, _compile(pats)) for tier, pats in POSITIVE_TRIGGERS]
_TARGET_RX = {name: _compile(pats) for name, pats in TARGETS.items()}
_NON_STATE_RX = {name: _compile(pats) for name, pats in NON_STATE.items()}
_EXCLUDE_RX = _compile(EXCLUSION_PATTERNS)


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")

# Co-signatory pattern: in diplomatic language, "Australia joins X in
# calling on Y" lists co-signatories (X) before the actual target (Y).
# Countries named inside this construction are joining Australia in the
# statement, NOT the target of the statement. v1.3 strips them.
_COSIGNATORY_RX = re.compile(
    r"\b(joins?|joined|joining|alongside|together with|with our partners?)\s+(.{0,120}?)\s+in\b",
    re.IGNORECASE | re.DOTALL,
)

# Descriptive-attribution pattern: v1.3.1. Catches constructions like
# "an Indonesian-funded hospital", "the Jordanian field hospital", "an
# Iranian-backed militia", "a Japanese-built bridge" — where the country
# adjective describes WHO FUNDED/BUILT/SUPPORTED something, not who the
# statement is targeting. Countries appearing only in this construction
# in a sentence are stripped from the target list for that sentence.
_DESCRIPTIVE_RX = re.compile(
    r"\b(\w+(?:n|ese|i|ish|an))[- ]"
    r"(funded|backed|built|supported|operated|run|sponsored|donated|aided|administered|owned|managed|trained|equipped|made|field|aid)\b",
    re.IGNORECASE,
)

# Victim pattern: v1.3.2. When a sentence describes violence done TO a
# country ("attacks on Israel", "killing of two Israeli embassy staff",
# "rocket fire on Israeli cities", "bombing of Russian diplomats"), the
# country named is the VICTIM, not the target of the criticism. We
# capture the text between the violence-word and either "by ..." (which
# would name the perpetrator) or the sentence end, and exclude any
# countries found in that span. Content-neutral: applies symmetrically
# to any country in the same construction.
_VICTIM_RX = re.compile(
    r"\b(killing|killings|attack|attacks|murder|murdered|bombing|bombings|massacre|"
    r"shooting|stabbing|terror|terrorist|rocket|missile|missiles|strike|strikes|"
    r"raid|raids|violence|assault|abduction|kidnap|kidnapping|atrocity|atrocities)\w*"
    r"\s+(of|on|against|targeting|towards?|aimed at|inflicted on|directed at)\s+"
    r"([^.!?]{0,80}?)(?=\s+by\b|[.!?]|$)",
    re.IGNORECASE,
)

# Perpetrator pattern: v1.4.1. Mirror of the victim pattern. When a country
# appears in clearly oppositional framing — "X's invasion", "X's oppressive
# regime", "against X", "hold X accountable" — it is the PERPETRATOR of the
# action being criticised, not a recipient of positive sentiment. Countries
# detected by these patterns are:
#   - Excluded from positive_targets for the sentence (a "stand with Ukraine
#     against Russia's invasion" sentence should not credit Russia with
#     Solidarity).
#   - Tagged with Condemn severity in critical_targets (because the
#     construction itself is a critical signal — even if no explicit
#     "condemn"/"deplore" trigger is in the sentence).
# Symmetric across all countries.

_PERPETRATOR_AGGRESSION_RX = re.compile(
    # "X's [aggression-noun]": Russia's invasion, Iran's atrocities, etc.
    r"\b(\w+)['’]s\s+"
    r"(invasion|invasions|aggression|aggressions|"
    r"atrocity|atrocities|war\s+crimes?|crimes?\s+against\s+humanity|"
    r"occupation|annexation|bombardment|shelling|"
    r"interference|disinformation|threats?|incursions?|provocations?|"
    r"hostilities|reckless\s+behaviou?r|illegal\s+actions?)\b",
    re.IGNORECASE,
)

_PERPETRATOR_DESCRIPT_RX = re.compile(
    # "X's [critical-adj] [regime/government/...]": Putin's oppressive regime
    r"\b(\w+)['’]s\s+"
    r"(oppressive|brutal|illegal|reckless|repressive|authoritarian|"
    r"criminal|murderous|warlike|hostile)\s+"
    r"(regime|government|authorities|actions|behaviou?r|leadership|"
    r"cabinet|forces|military|administration)\b",
    re.IGNORECASE,
)

_AGAINST_RX = re.compile(
    # "against X" — opposition. Captures up to 80 chars after "against",
    # stopping at sentence/clause boundaries.
    r"\bagainst\s+(.{0,80}?)(?=[.!?,;]|\s+in\s|\s+despite\b|$)",
    re.IGNORECASE | re.DOTALL,
)

_ACCOUNTABILITY_RX = re.compile(
    # "hold X accountable" / "holding X accountable" / etc.
    r"\b(?:holds?|holding|held)\s+(.{0,80}?)\s+accountable\b",
    re.IGNORECASE | re.DOTALL,
)

# Location-context patterns: v1.4.2. When a country is mentioned as a
# place people are departing from, leaving, evacuating, or stranded in,
# it is a CONTEXTUAL LOCATION, not a recipient of any positive sentiment
# the sentence may express. E.g., "Australia thanks Jordan for assisting
# Australians depart Israel & the Occupied Palestinian Territories" —
# Jordan is the positive target; Israel and Palestine are locations.
# Countries detected here are excluded from positive_targets only. They
# remain available for critical_targets if a separate critical signal
# applies in the same sentence.

_LOC_DEPARTURE_RX = re.compile(
    # "depart Israel", "leaving Israel", "evacuate (from) X", "flee X".
    # Captures up to 80 chars after the verb, including coordinated phrases
    # like "Israel & the Occupied Palestinian Territories" (don't stop on
    # & / and — we WANT to catch both countries in such constructions).
    r"\b(depart(?:ing|ed|s)?|leav(?:e|ing|es)|exit(?:ing|ed|s)?|"
    r"evacuat(?:e|ing|ed|es)|escape(?:d|ing|s)?|flee(?:ing)?|fled)\s+"
    r"(?:from\s+)?(.{0,80}?)(?=[.!?;]|$)",
    re.IGNORECASE | re.DOTALL,
)

_LOC_TRAPPED_RX = re.compile(
    # "stranded in X", "trapped in X", "stuck in X", "caught in X"
    r"\b(strand(?:ed|ing)?|trapp(?:ed|ing)?|stuck|caught)\s+in\s+"
    r"(.{0,80}?)(?=[.!?;]|$)",
    re.IGNORECASE | re.DOTALL,
)


def _strongest_match(text: str, tiered: list) -> tuple[str | None, list[str]]:
    """Return (strongest_tier, all_matched_patterns)."""
    strongest = None
    matched: list[str] = []
    for tier, rxs in tiered:
        hits = [rx.pattern for rx in rxs if rx.search(text)]
        if hits:
            if strongest is None:
                strongest = tier
            matched.extend(hits)
    return strongest, matched


def _targets_in(text: str, target_rx: dict) -> list[str]:
    return [name for name, rxs in target_rx.items() if any(rx.search(text) for rx in rxs)]


def classify(text: str) -> dict | None:
    """Return classification dict, or None if the tweet doesn't qualify.

    Per methodology v1.2, tone attribution is **sentence-scoped**: a target
    only gets a critical tier if it appears in a sentence that contains a
    critical trigger, and only gets a positive tier if it appears in a
    sentence with a positive trigger. This prevents tweets like
    "Australia condemns Russia's invasion. We stand with Ukraine." from
    mis-attributing the Solidarity tag to Russia.
    """
    needs_review = any(rx.search(text) for rx in _EXCLUDE_RX)

    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]

    critical_targets: dict[str, str] = {}   # country -> strongest critical tier seen
    positive_targets: dict[str, str] = {}   # country -> strongest positive tier seen
    critical_non_state: set[str] = set()
    positive_non_state: set[str] = set()
    all_matched: list[str] = []
    tweet_severity: str | None = None
    tweet_warmth: str | None = None

    # ordered list of severity / warmth tiers, strongest first
    sev_rank = {t: i for i, (t, _) in enumerate(TRIGGERS)}
    warm_rank = {t: i for i, (t, _) in enumerate(POSITIVE_TRIGGERS)}

    def _stronger(a: str | None, b: str, rank: dict) -> str:
        if a is None:
            return b
        return a if rank[a] <= rank[b] else b

    for s in sentences:
        sev_from_trigger, m_crit = _strongest_match(s, _TRIGGER_RX)
        warm, m_pos = _strongest_match(s, _POSITIVE_RX)
        all_matched.extend(m_crit + m_pos)

        # v1.4.1: Identify perpetrator countries FIRST so that sentences
        # with no explicit trigger but with oppositional framing still
        # process (e.g., "we honour resistance against X's regime").
        perpetrators: set[str] = set()
        for m in _PERPETRATOR_AGGRESSION_RX.finditer(s):
            for name, rxs in _TARGET_RX.items():
                if any(rx.search(m.group(1)) for rx in rxs):
                    perpetrators.add(name)
        for m in _PERPETRATOR_DESCRIPT_RX.finditer(s):
            for name, rxs in _TARGET_RX.items():
                if any(rx.search(m.group(1)) for rx in rxs):
                    perpetrators.add(name)
        for m in _AGAINST_RX.finditer(s):
            for name in _targets_in(m.group(1), _TARGET_RX):
                perpetrators.add(name)
        for m in _ACCOUNTABILITY_RX.finditer(s):
            for name in _targets_in(m.group(1), _TARGET_RX):
                perpetrators.add(name)

        if perpetrators:
            all_matched.append("\\bperpetrator-context\\b")

        # v1.4.2: location-context detection — countries mentioned as the
        # place from which Australians are departing / leaving / evacuating
        # / trapped in. These are excluded from POSITIVE attribution only
        # (the country can still be tagged critical if a separate critical
        # signal applies).
        locations: set[str] = set()
        for m in _LOC_DEPARTURE_RX.finditer(s):
            for name in _targets_in(m.group(2) or "", _TARGET_RX):
                locations.add(name)
        for m in _LOC_TRAPPED_RX.finditer(s):
            for name in _targets_in(m.group(2) or "", _TARGET_RX):
                locations.add(name)

        # Skip sentence if nothing at all fired
        if sev_from_trigger is None and warm is None and not perpetrators:
            continue

        # Identify co-signatories (v1.3): "joins X in", "alongside X", etc.
        cosigners: set[str] = set()
        for m in _COSIGNATORY_RX.finditer(s):
            for name in _targets_in(m.group(2) or "", _TARGET_RX):
                cosigners.add(name)

        # Descriptive (v1.3.1): "Indonesian-funded hospital", etc.
        descriptive: set[str] = set()
        for m in _DESCRIPTIVE_RX.finditer(s):
            for name, rxs in _TARGET_RX.items():
                if any(rx.search(m.group(1)) for rx in rxs):
                    descriptive.add(name)

        # Victims (v1.3.2): countries on the receiving end of violence.
        victims: set[str] = set()
        for m in _VICTIM_RX.finditer(s):
            for name in _targets_in(m.group(3) or "", _TARGET_RX):
                victims.add(name)

        excluded_from_crit = cosigners | descriptive | victims
        targets_here = [t for t in _targets_in(s, _TARGET_RX) if t not in excluded_from_crit]
        ns_here = _targets_in(s, _NON_STATE_RX)

        # CRITICAL attribution
        # v1.4.1 fix: only apply the explicit trigger's severity to non-
        # perpetrator targets. Perpetrators get Condemn independently.
        if sev_from_trigger is not None:
            tweet_severity = _stronger(tweet_severity, sev_from_trigger, sev_rank)
            for c in targets_here:
                if c in perpetrators:
                    continue   # perpetrators handled below
                critical_targets[c] = _stronger(critical_targets.get(c), sev_from_trigger, sev_rank)
            critical_non_state.update(ns_here)
        if perpetrators:
            # Perpetrators always get Condemn, and the tweet's overall
            # severity is bumped to at least Condemn.
            tweet_severity = _stronger(tweet_severity, "Condemn", sev_rank)
            for c in perpetrators:
                critical_targets[c] = _stronger(critical_targets.get(c), "Condemn", sev_rank)

        # POSITIVE attribution — perpetrators AND location-context excluded
        if warm is not None:
            tweet_warmth = _stronger(tweet_warmth, warm, warm_rank)
            for c in targets_here:
                if c in perpetrators or c in locations:
                    continue
                positive_targets[c] = _stronger(positive_targets.get(c), warm, warm_rank)
            positive_non_state.update(ns_here)

    if tweet_severity is None and tweet_warmth is None:
        return None
    if not critical_targets and not positive_targets and not critical_non_state and not positive_non_state:
        return None  # no target → exclude

    all_targets = sorted(set(list(critical_targets.keys()) + list(positive_targets.keys())))
    all_non_state = sorted(critical_non_state | positive_non_state)

    has_crit = bool(critical_targets) or bool(critical_non_state)
    has_pos = bool(positive_targets) or bool(positive_non_state)
    tone = "mixed" if (has_crit and has_pos) else ("critical" if has_crit else "positive")

    return {
        "tone": tone,
        "severity": tweet_severity,
        "warmth": tweet_warmth,
        "targets": all_targets,                       # union, for display
        "critical_targets": sorted(critical_targets.keys()),
        "positive_targets": sorted(positive_targets.keys()),
        "non_state_targets": all_non_state,
        "critical_non_state": sorted(critical_non_state),
        "positive_non_state": sorted(positive_non_state),
        "matched_triggers": all_matched,
        "needs_review": needs_review,
    }


# ---------------------------------------------------------------------------
# X API client
# ---------------------------------------------------------------------------

X_API = "https://api.x.com/2"


def _x_get(path: str, params: dict, bearer: str) -> dict:
    url = f"{X_API}{path}?{urlencode(params)}"
    req = Request(url, headers={"Authorization": f"Bearer {bearer}"})
    for attempt in range(5):
        try:
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except HTTPError as e:
            if e.code == 429:                               # rate limited
                reset = int(e.headers.get("x-rate-limit-reset", time.time() + 60))
                wait = max(5, reset - int(time.time()))
                print(f"  rate limited; sleeping {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(f"Gave up after retries: {url}")


def fetch_user_id(handle: str, bearer: str) -> str:
    data = _x_get(f"/users/by/username/{handle}", {}, bearer)
    return data["data"]["id"]


def _is_retweet(tweet: dict) -> bool:
    """A pure retweet has a referenced_tweets entry of type=retweeted.
    Replies have type=replied_to; quote tweets have type=quoted. We keep
    those — only retweets are excluded per methodology."""
    return any(r.get("type") == "retweeted" for r in tweet.get("referenced_tweets") or [])


def fetch_tweets(handle: str, since: str, bearer: str) -> list[dict]:
    """Fetch Senator Wong's tweets via /2/users/:id/tweets (the timeline).

    v1.3.4: dropped the server-side `exclude=retweets` parameter — empirical
    testing showed X's exclude filter aggressively dropped replies and thread
    continuations alongside retweets, contrary to documentation. We now fetch
    everything and filter retweets client-side by inspecting
    referenced_tweets[].type. This restores replies and conversation
    continuations to the dataset, which the methodology has always intended
    to include (a foreign minister's thread leads and follow-ups are part of
    the public record by the same logic as standalone tweets).
    """
    user_id = fetch_user_id(handle, bearer)
    out: list[dict] = []
    pagination_token: str | None = None
    page = 0
    dropped_rt = 0
    while True:
        page += 1
        params = {
            "max_results": "100",
            "start_time": since,
            "tweet.fields": (
                "created_at,text,public_metrics,referenced_tweets,"
                "in_reply_to_user_id,conversation_id,author_id"
            ),
            "expansions": "in_reply_to_user_id,referenced_tweets.id,author_id",
            # Note: NO `exclude=retweets`. Filter client-side instead.
        }
        if pagination_token:
            params["pagination_token"] = pagination_token
        data = _x_get(f"/users/{user_id}/tweets", params, bearer)
        batch = data.get("data", [])
        kept = [t for t in batch if not _is_retweet(t)]
        dropped_rt += len(batch) - len(kept)
        out.extend(kept)
        print(f"  timeline page {page}: kept {len(kept)} of {len(batch)} (total {len(out)})", file=sys.stderr)
        pagination_token = data.get("meta", {}).get("next_token")
        if not pagination_token:
            break
    print(f"  timeline: {len(out)} kept, {dropped_rt} retweets filtered client-side", file=sys.stderr)
    return out


def fetch_conversation_continuations(handle: str, bearer: str,
                                     conversation_ids: list[str]) -> list[dict]:
    """v1.3.6: For each conversation Wong started, query X for every tweet
    she made in that conversation. This is the most specific query we can
    make — and the most reliable way to surface thread continuations that
    the broader `from:X` and `from:X is:reply` queries are still filtering.

    Conversation IDs are batched into queries (up to ~25 per query) to stay
    under X's 1024-character query length limit on Basic tier.
    """
    out: list[dict] = []
    if not conversation_ids:
        return out

    BATCH_SIZE = 25
    ids = sorted(set(conversation_ids))
    n_batches = (len(ids) + BATCH_SIZE - 1) // BATCH_SIZE

    for b, i in enumerate(range(0, len(ids), BATCH_SIZE), 1):
        batch = ids[i:i + BATCH_SIZE]
        # Build query: from:HANDLE (conversation_id:A OR conversation_id:B OR ...)
        clauses = " OR ".join(f"conversation_id:{cid}" for cid in batch)
        query = f"from:{handle} ({clauses})"

        next_token: str | None = None
        page = 0
        while True:
            page += 1
            params = {
                "query": query,
                "max_results": "100",
                "tweet.fields": (
                    "created_at,text,public_metrics,referenced_tweets,"
                    "in_reply_to_user_id,conversation_id,author_id"
                ),
            }
            if next_token:
                params["next_token"] = next_token
            try:
                data = _x_get("/tweets/search/recent", params, bearer)
            except HTTPError as e:
                print(f"  conv-chase batch {b}/{n_batches} failed ({e})", file=sys.stderr)
                break
            page_batch = data.get("data", []) or []
            page_batch = [t for t in page_batch if not _is_retweet(t)]
            out.extend(page_batch)
            print(f"  conv-chase batch {b}/{n_batches} page {page}: +{len(page_batch)}",
                  file=sys.stderr)
            next_token = data.get("meta", {}).get("next_token")
            if not next_token:
                break

    return out


def fetch_recent_via_search(handle: str, bearer: str) -> list[dict]:
    """Supplementary fetch via /2/tweets/search/recent.

    v1.3.5: runs TWO queries in parallel and merges results:
      (a) `from:HANDLE`            — originals + replies to others
      (b) `from:HANDLE is:reply`   — explicitly requests replies, which
                                     includes thread continuations
                                     (self-replies) that query (a) appears
                                     to silently filter despite X docs
                                     saying it shouldn't.
    Limited to the last 7 days on Basic tier. The deep history still comes
    from the timeline endpoint.
    """
    queries = [
        f"from:{handle}",
        f"from:{handle} is:reply",
    ]
    out: list[dict] = []
    seen_ids: set[str] = set()
    for q_idx, q in enumerate(queries, 1):
        next_token: str | None = None
        page = 0
        while True:
            page += 1
            params = {
                "query": q,
                "max_results": "100",
                "tweet.fields": (
                    "created_at,text,public_metrics,referenced_tweets,"
                    "in_reply_to_user_id,conversation_id,author_id"
                ),
            }
            if next_token:
                params["next_token"] = next_token
            try:
                data = _x_get("/tweets/search/recent", params, bearer)
            except HTTPError as e:
                print(f"  search/recent ({q!r}) failed ({e}); continuing", file=sys.stderr)
                break
            batch = data.get("data", []) or []
            new = [t for t in batch if t["id"] not in seen_ids]
            for t in new:
                seen_ids.add(t["id"])
            # Client-side filter: drop pure retweets (search is already
            # filtered, but be defensive).
            new = [t for t in new if not _is_retweet(t)]
            out.extend(new)
            print(f"  search q{q_idx} page {page}: +{len(new)} new of {len(batch)} "
                  f"(seen total {len(seen_ids)})", file=sys.stderr)
            next_token = data.get("meta", {}).get("next_token")
            if not next_token:
                break
    return out


def load_missed_ids() -> list[str]:
    """Load tweet IDs to fetch via direct ID lookup. v1.3.7.

    Schema (missed_ids.json):
        { "ids": ["2057237192603570389", "..."] }

    Each ID is fetched via /2/tweets/?ids=... and added to the raw set if
    the API returns it. Lighter than manual_tweets.json (no text-typing
    required) — useful when you spot a missing tweet and just want to
    paste its ID.
    """
    if not MISSED_IDS_PATH.exists():
        return []
    try:
        data = json.loads(MISSED_IDS_PATH.read_text())
    except json.JSONDecodeError as e:
        print(f"WARN: missed_ids.json invalid JSON: {e}", file=sys.stderr)
        return []
    return [str(i) for i in data.get("ids", []) if i]


def fetch_tweets_by_ids(ids: list[str], bearer: str) -> list[dict]:
    """Direct-fetch tweets by ID via /2/tweets?ids=A,B,C.

    Returns each tweet the API recognises, marked with _via_id_lookup=True
    so downstream classification can flag them. Up to 100 IDs per request.
    Tweets the API does NOT recognise (deleted / private / hard-filtered)
    are reported but not added.
    """
    out: list[dict] = []
    if not ids:
        return out

    # Dedupe and chunk
    unique = sorted(set(ids))
    BATCH = 100
    for i in range(0, len(unique), BATCH):
        batch = unique[i:i + BATCH]
        params = {
            "ids": ",".join(batch),
            "tweet.fields": (
                "created_at,text,public_metrics,referenced_tweets,"
                "in_reply_to_user_id,conversation_id,author_id"
            ),
        }
        try:
            data = _x_get("/tweets", params, bearer)
        except HTTPError as e:
            print(f"  /tweets?ids=… batch {i//BATCH + 1} failed ({e})", file=sys.stderr)
            continue
        got = data.get("data", []) or []
        errors = data.get("errors", []) or []
        for t in got:
            t["_via_id_lookup"] = True
            out.append(t)
        if errors:
            for err in errors:
                # X returns per-ID errors: not found, suspended, etc.
                rid = err.get("resource_id") or err.get("value") or "?"
                detail = err.get("title") or err.get("detail") or "unknown"
                print(f"  id={rid} not returned: {detail}", file=sys.stderr)
        print(f"  /tweets?ids=… batch {i//BATCH + 1}: requested {len(batch)}, "
              f"returned {len(got)}, errors {len(errors)}", file=sys.stderr)
    return out


def load_manual_tweets() -> list[dict]:
    """Load manually-curated tweets (those the X API didn't return).

    Schema (manual_tweets.json):
        {
          "tweets": [
            {
              "id": "2057237000168808476",
              "created_at": "2026-05-20T23:08:17Z",
              "text": "the full tweet text",
              "added_by": "antipodean-affairs",  // optional
              "note": "missed by X API"           // optional
            },
            ...
          ]
        }
    """
    if not MANUAL_PATH.exists():
        return []
    try:
        data = json.loads(MANUAL_PATH.read_text())
    except json.JSONDecodeError as e:
        print(f"WARN: manual_tweets.json invalid JSON: {e}", file=sys.stderr)
        return []
    tweets = data.get("tweets", [])
    # Mark each so build_dataset knows which entries came from this file
    for t in tweets:
        t["_manual"] = True
    return tweets


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def build_dataset(raw_tweets: list[dict]) -> dict:
    # Deduplicate by id — if a manual tweet has the same id as one already
    # returned by the API, keep the API version (so the API stays canonical).
    seen: set[str] = set()
    ordered: list[dict] = []
    for t in raw_tweets:
        if t["id"] in seen:
            continue
        seen.add(t["id"])
        ordered.append(t)

    classified = []
    n_manual = 0
    n_by_source: Counter = Counter()
    for t in ordered:
        result = classify(t["text"])
        if not result:
            continue
        source = t.get("source", "x")
        # URL: use the source's own URL if it provides one (DFAT does),
        # otherwise build the X URL from the tweet ID.
        url = t.get("url") or f"https://x.com/{HANDLE}/status/{t['id']}"
        record = {
            "id": t["id"],
            "url": url,
            "source": source,
            "created_at": t["created_at"],
            "text": t["text"],
            **result,
        }
        if "title" in t:
            record["title"] = t["title"]
        if t.get("joint_with"):
            record["joint_with"] = t["joint_with"]
        if t.get("_manual"):
            record["manually_added"] = True
            for k in ("added_by", "note"):
                if k in t:
                    record[k] = t[k]
            n_manual += 1
        if t.get("_via_id_lookup"):
            record["fetched_by_id"] = True
        classified.append(record)
        n_by_source[source] += 1

    classified.sort(key=lambda c: c["created_at"], reverse=True)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "methodology_version": METHODOLOGY_VERSION,
        "source_handle": f"@{HANDLE}",
        "since": SINCE,
        "tweet_count_raw": len(ordered),
        "tweet_count_classified": len(classified),
        "tweet_count_manual": n_manual,
        "count_by_source": dict(n_by_source),
        "tweets": classified,
    }


def summarise(dataset: dict) -> dict:
    crit_by_country: Counter = Counter()
    crit_by_severity: Counter = Counter()
    crit_by_month: Counter = Counter()
    crit_by_country_sev: dict = defaultdict(lambda: Counter())

    pos_by_country: Counter = Counter()
    pos_by_warmth: Counter = Counter()
    pos_by_month: Counter = Counter()
    pos_by_country_warmth: dict = defaultdict(lambda: Counter())

    n_critical = 0
    n_positive = 0
    n_mixed = 0

    for t in dataset["tweets"]:
        month = t["created_at"][:7]
        if t["tone"] in ("critical", "mixed"):
            n_critical += 1
            crit_by_severity[t["severity"]] += 1
            crit_by_month[month] += 1
            for c in t["critical_targets"]:
                crit_by_country[c] += 1
                crit_by_country_sev[c][t["severity"]] += 1
        if t["tone"] in ("positive", "mixed"):
            n_positive += 1
            pos_by_warmth[t["warmth"]] += 1
            pos_by_month[month] += 1
            for c in t["positive_targets"]:
                pos_by_country[c] += 1
                pos_by_country_warmth[c][t["warmth"]] += 1
        if t["tone"] == "mixed":
            n_mixed += 1

    # Net sentiment: (positive - critical) per country, only for countries
    # with at least one statement of either tone.
    net = {}
    for c in set(list(crit_by_country.keys()) + list(pos_by_country.keys())):
        net[c] = pos_by_country.get(c, 0) - crit_by_country.get(c, 0)
    net_sorted = dict(sorted(net.items(), key=lambda kv: kv[1]))

    return {
        "total_classified": len(dataset["tweets"]),
        "total_critical": n_critical,
        "total_positive": n_positive,
        "total_mixed": n_mixed,
        # critical side
        "by_country": dict(crit_by_country.most_common()),
        "by_severity": dict(crit_by_severity),
        "by_month": dict(sorted(crit_by_month.items())),
        "by_country_severity": {c: dict(s) for c, s in crit_by_country_sev.items()},
        # positive side
        "positive_by_country": dict(pos_by_country.most_common()),
        "positive_by_warmth": dict(pos_by_warmth),
        "positive_by_month": dict(sorted(pos_by_month.items())),
        "positive_by_country_warmth": {c: dict(s) for c, s in pos_by_country_warmth.items()},
        # combined view
        "net_by_country": net_sorted,
        "needs_review": sum(1 for t in dataset["tweets"] if t["needs_review"]),
    }


def render_site(dataset: dict, summary: dict) -> None:
    template = TEMPLATE_PATH.read_text()
    payload = json.dumps({"dataset": dataset, "summary": summary}, ensure_ascii=False)
    html = template.replace("/*__DATA__*/", payload)
    HTML_PATH.write_text(html)


def _existing_raw_from_dataset(existing: dict) -> list[dict]:
    """Extract raw fields from an already-classified tweets.json, preserving
    the manually_added / fetched_by_id / source / title / joint_with flags
    so a re-classification run keeps them intact."""
    out = []
    for t in existing.get("tweets", []):
        rec = {
            "id": t["id"],
            "text": t["text"],
            "created_at": t["created_at"],
            "_manual": t.get("manually_added", False),
            "_via_id_lookup": t.get("fetched_by_id", False),
            "source": t.get("source", "x"),
        }
        if "title" in t:
            rec["title"] = t["title"]
        if "joint_with" in t:
            rec["joint_with"] = t["joint_with"]
        if "url" in t:
            rec["url"] = t["url"]
        out.append(rec)
    return out


def _incremental_start_time(existing_raw: list[dict]) -> str:
    """v1.4.0: derive a 'fetch since' timestamp from the most-recent tweet
    in the existing dataset, with an overlap window to catch boundary
    misses. Falls back to SINCE if no existing data."""
    if not existing_raw:
        return SINCE
    latest = max(t["created_at"] for t in existing_raw)
    try:
        when = datetime.fromisoformat(latest.replace("Z", "+00:00"))
    except ValueError:
        return SINCE
    overlap_dt = when - timedelta(days=INCREMENTAL_OVERLAP_DAYS)
    since_dt = datetime.fromisoformat(SINCE.replace("Z", "+00:00"))
    if overlap_dt < since_dt:
        return SINCE
    return overlap_dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true",
                    help="skip the API call, reclassify existing tweets.json")
    ap.add_argument("--seed", action="store_true",
                    help="use seed_tweets.json instead of calling the API")
    ap.add_argument("--full-fetch", action="store_true",
                    help="force a full backfill from SINCE instead of incremental")
    args = ap.parse_args()

    # Load existing dataset (if any) so we can carry forward across runs.
    existing_raw: list[dict] = []
    if TWEETS_PATH.exists() and not args.seed:
        try:
            existing = json.loads(TWEETS_PATH.read_text())
            existing_raw = _existing_raw_from_dataset(existing)
        except json.JSONDecodeError:
            existing_raw = []

    if args.seed:
        raw = json.loads(SEED_PATH.read_text())
        print(f"Using seed dataset: {len(raw)} tweets", file=sys.stderr)
    elif args.no_fetch:
        raw = existing_raw
        print(f"Reclassifying existing dataset: {len(raw)} tweets", file=sys.stderr)
    else:
        bearer = os.environ.get("X_BEARER_TOKEN")
        if not bearer:
            print("Set X_BEARER_TOKEN, or pass --seed / --no-fetch", file=sys.stderr)
            return 2

        # v1.4.0: incremental fetch. Start from the latest existing tweet
        # minus an overlap window, or from SINCE if forced / no existing data.
        if args.full_fetch or not existing_raw:
            start_time = SINCE
            print(f"Full backfill from {start_time} (--full-fetch={args.full_fetch}, "
                  f"existing={len(existing_raw)})", file=sys.stderr)
        else:
            start_time = _incremental_start_time(existing_raw)
            print(f"Incremental fetch from {start_time} "
                  f"({len(existing_raw)} existing tweets, {INCREMENTAL_OVERLAP_DAYS}d overlap)",
                  file=sys.stderr)

        print(f"Fetching @{HANDLE} via timeline…", file=sys.stderr)
        raw = fetch_tweets(HANDLE, start_time, bearer)
        print(f"Fetching @{HANDLE} via search/recent (supplementary, last 7d)…", file=sys.stderr)
        recent = fetch_recent_via_search(HANDLE, bearer)
        # v1.3.4: merge by tweet id, keep timeline entry on conflict
        existing_ids = {t["id"] for t in raw}
        added = [t for t in recent if t["id"] not in existing_ids]
        raw = list(raw) + added
        print(f"Merge: timeline {len(existing_ids)}, search added {len(added)} new, total {len(raw)}", file=sys.stderr)

        # v1.3.6: conversation chase — for each thread Wong started in the
        # last 7 days, explicitly query for every tweet she made in that
        # conversation. This surfaces self-replies that the broader
        # from:HANDLE queries still filter despite documentation.
        cutoff_ms = int((datetime.now(timezone.utc) - timedelta(days=7)).timestamp() * 1000)
        recent_conv_ids: set[str] = set()
        for t in raw:
            cid = t.get("conversation_id") or t["id"]
            try:
                # Decode tweet snowflake to ms timestamp
                ts_ms = (int(cid) >> 22) + 1288834974657
                if ts_ms >= cutoff_ms:
                    recent_conv_ids.add(cid)
            except (ValueError, TypeError):
                continue
        if recent_conv_ids:
            print(f"Conversation-chasing {len(recent_conv_ids)} recent threads…", file=sys.stderr)
            extra = fetch_conversation_continuations(HANDLE, bearer, list(recent_conv_ids))
            existing_ids = {t["id"] for t in raw}
            added2 = [t for t in extra if t["id"] not in existing_ids]
            raw = list(raw) + added2
            print(f"Conversation chase added {len(added2)} new tweets, total {len(raw)}", file=sys.stderr)

        # v1.3.7: direct ID lookup for tweets the timeline/search filters miss.
        # Reads missed_ids.json (just a list of IDs) and fetches each via
        # /2/tweets?ids=… — this endpoint bypasses the filtering applied to
        # timeline and search queries.
        missed = load_missed_ids()
        if missed:
            print(f"Direct-fetching {len(missed)} missed IDs via /2/tweets…", file=sys.stderr)
            by_id = fetch_tweets_by_ids(missed, bearer)
            existing_ids = {t["id"] for t in raw}
            added3 = [t for t in by_id if t["id"] not in existing_ids]
            raw = list(raw) + added3
            print(f"Direct ID lookup added {len(added3)} new tweets "
                  f"({len(by_id) - len(added3)} were already in dataset), "
                  f"total {len(raw)}", file=sys.stderr)

    # v1.3.3: merge in any manually-curated tweets that the X API missed.
    manual = load_manual_tweets()
    if manual:
        for m in manual:
            m.setdefault("source", "x")
        print(f"Adding {len(manual)} manually-curated tweets from manual_tweets.json", file=sys.stderr)
        raw = list(raw) + manual

    # v1.5.0: also fetch from DFAT/foreignminister.gov.au (second source).
    # Skipped for --seed and --no-fetch modes (those are X-only paths).
    if not args.seed and not args.no_fetch:
        try:
            from fetch_dfat import fetch_dfat_releases
        except ImportError as e:
            print(f"WARN: fetch_dfat not importable ({e}); skipping DFAT source",
                  file=sys.stderr)
        else:
            # v1.5.1: DFAT has its own incremental clock — if there are no
            # DFAT records in the existing dataset yet, force a full backfill
            # regardless of how many X records are present. Otherwise the
            # first DFAT run would only fetch the last few days (because the
            # latest X tweet's date would be the reference point).
            existing_dfat = [r for r in existing_raw if r.get("source") == "dfat"]
            if args.full_fetch or not existing_dfat:
                dfat_since = SINCE
                reason = "no existing DFAT records" if not existing_dfat else "--full-fetch"
                print(f"Full DFAT backfill from {dfat_since} ({reason})", file=sys.stderr)
            else:
                dfat_since = _incremental_start_time(existing_dfat)
                print(f"Incremental DFAT fetch from {dfat_since} "
                      f"({len(existing_dfat)} existing DFAT records)", file=sys.stderr)
            try:
                dfat = fetch_dfat_releases(dfat_since)
            except Exception as e:
                print(f"WARN: DFAT fetch failed ({type(e).__name__}: {e}); continuing with X only",
                      file=sys.stderr)
                dfat = []
            print(f"DFAT: {len(dfat)} releases fetched", file=sys.stderr)
            raw = list(raw) + dfat

    # v1.4.0: if this was an incremental fetch, merge with the existing
    # dataset. Newly-fetched tweets take precedence on ID collision so
    # any updated fields (e.g., new flags) win, but existing tweets that
    # weren't refetched (because they're older than the start_time) are
    # preserved. Skip merge for --seed (seed mode rebuilds from scratch).
    if existing_raw and not args.seed:
        new_ids = {t["id"] for t in raw}
        kept_from_existing = [t for t in existing_raw if t["id"] not in new_ids]
        print(f"v1.4.0 merge: existing {len(existing_raw)} + newly-fetched {len(raw)} "
              f"= {len(kept_from_existing) + len(raw)} after dedupe",
              file=sys.stderr)
        raw = list(raw) + kept_from_existing

    dataset = build_dataset(raw)
    summary = summarise(dataset)

    TWEETS_PATH.write_text(json.dumps(dataset, indent=2, ensure_ascii=False))
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    render_site(dataset, summary)

    print(f"Classified {summary['total_classified']} / {dataset['tweet_count_raw']} statements "
          f"({summary['total_critical']} critical, {summary['total_positive']} positive, "
          f"{summary['total_mixed']} mixed, {dataset['tweet_count_manual']} manual)")
    print(f"By source: {dataset.get('count_by_source', {})}")
    print(f"Top critical targets: {list(summary['by_country'].items())[:5]}")
    print(f"Top positive targets: {list(summary['positive_by_country'].items())[:5]}")
    print(f"Wrote {TWEETS_PATH.name}, {SUMMARY_PATH.name}, {HTML_PATH.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
