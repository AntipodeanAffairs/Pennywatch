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
METHODOLOGY_VERSION = "1.3.6"

HERE = Path(__file__).parent
TWEETS_PATH = HERE / "tweets.json"
SUMMARY_PATH = HERE / "summary.json"
SEED_PATH = HERE / "seed_tweets.json"
HTML_PATH = HERE / "index.html"
TEMPLATE_PATH = HERE / "index.template.html"
MANUAL_PATH = HERE / "manual_tweets.json"   # tweets the X API missed

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
    ]),
    ("Concern", [
        r"\bconcerned\b", r"\bdeeply concerned\b", r"\btroubled\b",
        r"\balarmed\b", r"\bdismayed\b", r"\bdisturbed\b", r"\bregret\b",
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
        sev, m_crit = _strongest_match(s, _TRIGGER_RX)
        warm, m_pos = _strongest_match(s, _POSITIVE_RX)
        all_matched.extend(m_crit + m_pos)

        if sev is None and warm is None:
            continue

        # Identify co-signatories: countries appearing in a "joins X in" /
        # "alongside X" / "together with X" construction. These are joining
        # Australia in the statement, not the statement's target. We strip
        # them from the target list for this sentence.
        cosigners: set[str] = set()
        for m in _COSIGNATORY_RX.finditer(s):
            cosig_text = m.group(2) or ""
            for name in _targets_in(cosig_text, _TARGET_RX):
                cosigners.add(name)

        # v1.3.1: Identify countries appearing in descriptive constructions
        # ("Indonesian-funded hospital", "Jordanian field hospital") —
        # these describe a noun, they are not the target of the statement.
        descriptive: set[str] = set()
        for m in _DESCRIPTIVE_RX.finditer(s):
            adj = m.group(1)
            for name, rxs in _TARGET_RX.items():
                if any(rx.search(adj) for rx in rxs):
                    descriptive.add(name)

        # v1.3.2: Identify victim countries — those appearing as the
        # object of a violence-word ("attacks on Israel", "killing of
        # Israeli staff"). These are victims of the violence the tweet
        # is criticising, not the targets of the criticism itself.
        victims: set[str] = set()
        for m in _VICTIM_RX.finditer(s):
            victim_span = m.group(3) or ""
            for name in _targets_in(victim_span, _TARGET_RX):
                victims.add(name)

        excluded = cosigners | descriptive | victims
        targets_here = [t for t in _targets_in(s, _TARGET_RX) if t not in excluded]
        ns_here = _targets_in(s, _NON_STATE_RX)

        if sev is not None:
            tweet_severity = _stronger(tweet_severity, sev, sev_rank)
            for c in targets_here:
                critical_targets[c] = _stronger(critical_targets.get(c), sev, sev_rank)
            critical_non_state.update(ns_here)

        if warm is not None:
            tweet_warmth = _stronger(tweet_warmth, warm, warm_rank)
            for c in targets_here:
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
    for t in ordered:
        result = classify(t["text"])
        if not result:
            continue
        record = {
            "id": t["id"],
            "url": f"https://x.com/{HANDLE}/status/{t['id']}",
            "created_at": t["created_at"],
            "text": t["text"],
            **result,
        }
        if t.get("_manual"):
            record["manually_added"] = True
            for k in ("added_by", "note"):
                if k in t:
                    record[k] = t[k]
            n_manual += 1
        classified.append(record)

    classified.sort(key=lambda c: c["created_at"], reverse=True)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "methodology_version": METHODOLOGY_VERSION,
        "source_handle": f"@{HANDLE}",
        "since": SINCE,
        "tweet_count_raw": len(ordered),
        "tweet_count_classified": len(classified),
        "tweet_count_manual": n_manual,
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true",
                    help="skip the API call, reclassify existing tweets.json")
    ap.add_argument("--seed", action="store_true",
                    help="use seed_tweets.json instead of calling the API")
    args = ap.parse_args()

    if args.seed:
        raw = json.loads(SEED_PATH.read_text())
        print(f"Using seed dataset: {len(raw)} tweets", file=sys.stderr)
    elif args.no_fetch:
        existing = json.loads(TWEETS_PATH.read_text())
        raw = [{"id": t["id"], "text": t["text"], "created_at": t["created_at"],
                "_manual": t.get("manually_added", False)}
               for t in existing["tweets"]]
        print(f"Reclassifying existing dataset: {len(raw)} tweets", file=sys.stderr)
    else:
        bearer = os.environ.get("X_BEARER_TOKEN")
        if not bearer:
            print("Set X_BEARER_TOKEN, or pass --seed / --no-fetch", file=sys.stderr)
            return 2
        print(f"Fetching @{HANDLE} via timeline since {SINCE}…", file=sys.stderr)
        raw = fetch_tweets(HANDLE, SINCE, bearer)
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

    # v1.3.3: merge in any manually-curated tweets that the X API missed.
    manual = load_manual_tweets()
    if manual:
        print(f"Adding {len(manual)} manually-curated tweets from manual_tweets.json", file=sys.stderr)
        raw = list(raw) + manual

    dataset = build_dataset(raw)
    summary = summarise(dataset)

    TWEETS_PATH.write_text(json.dumps(dataset, indent=2, ensure_ascii=False))
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    render_site(dataset, summary)

    print(f"Classified {summary['total_classified']} / {dataset['tweet_count_raw']} tweets "
          f"({summary['total_critical']} critical, {summary['total_positive']} positive, "
          f"{summary['total_mixed']} mixed, {dataset['tweet_count_manual']} manual)")
    print(f"Top critical targets: {list(summary['by_country'].items())[:5]}")
    print(f"Top positive targets: {list(summary['positive_by_country'].items())[:5]}")
    print(f"Wrote {TWEETS_PATH.name}, {SUMMARY_PATH.name}, {HTML_PATH.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
