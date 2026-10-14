"""Deterministic English prose for synthetic fixtures.

Sentences are built from fixed templates and a fixed vocabulary of ordinary English words,
driven by a seeded ``random.Random``, so the same seed always gives the same text. Every
word is a dictionary word (useful for de-hyphenation), and only sentence starts are
capitalised, so a sentence continued on a new line or page starts in lowercase.
"""

import random

ADJECTIVES = [
    "old",
    "quiet",
    "narrow",
    "bright",
    "cold",
    "distant",
    "familiar",
    "heavy",
    "gentle",
    "patient",
    "careful",
    "ordinary",
    "remarkable",
    "comfortable",
    "mysterious",
    "beautiful",
    "grey",
    "small",
    "wide",
    "silent",
    "weathered",
    "important",
    "particular",
    "wooden",
]
NOUNS = [
    "harbour",
    "lighthouse",
    "keeper",
    "village",
    "window",
    "letter",
    "morning",
    "evening",
    "afternoon",
    "boat",
    "garden",
    "kitchen",
    "staircase",
    "lantern",
    "shoreline",
    "neighbour",
    "photograph",
    "conversation",
    "difference",
    "experience",
    "information",
    "journey",
    "notebook",
    "weather",
    "question",
    "promise",
    "doorway",
    "fisherman",
    "schoolteacher",
    "household",
    "river",
    "station",
    "message",
    "telegram",
    "workshop",
    "landscape",
]
VERBS_PAST = [
    "remembered",
    "watched",
    "carried",
    "followed",
    "considered",
    "discovered",
    "repaired",
    "noticed",
    "described",
    "explained",
    "imagined",
    "recognised",
    "understood",
    "visited",
    "answered",
    "collected",
    "examined",
    "mentioned",
    "prepared",
    "returned to",
]
ADVERBS = [
    "slowly",
    "quietly",
    "carefully",
    "eventually",
    "occasionally",
    "immediately",
    "afterwards",
    "certainly",
    "suddenly",
    "patiently",
    "gradually",
    "particularly",
]
PREPOSITIONS = ["near", "behind", "beyond", "across", "beside", "towards", "under", "above"]
SUBJECTS = ["She", "He", "The keeper", "Her brother", "The schoolteacher", "Nobody", "Everyone"]
CLAUSES = [
    "because the weather had changed",
    "although nobody had asked",
    "while the tide was turning",
    "before the lamps were lit",
    "as the boats came home",
    "when the letter finally arrived",
    "since the harbour was closed",
]


def sentence(rng: random.Random) -> str:
    """One sentence, capitalised and ending in a full stop."""
    adj, adj2 = rng.choice(ADJECTIVES), rng.choice(ADJECTIVES)
    noun, noun2 = rng.choice(NOUNS), rng.choice(NOUNS)
    verb, adverb = rng.choice(VERBS_PAST), rng.choice(ADVERBS)
    prep, subject, clause = rng.choice(PREPOSITIONS), rng.choice(SUBJECTS), rng.choice(CLAUSES)
    templates = [
        f"The {adj} {noun} {verb} the {noun2} {prep} the {adj2} village",
        f"{subject} {adverb} {verb} the {adj} {noun} {clause}",
        f"{subject} {verb} the {noun} {prep} the {adj2} {noun2}, and then {adverb} went home",
        f"In the {adj} {noun}, {subject.lower()} {verb} a {adj2} {noun2} {clause}",
        f"It was a {adj} {noun}, and the {noun2} {prep} the harbour was {adj2}",
        f"{subject} {verb} that the {noun} was {adj} {clause}, {adverb}",
    ]
    text = rng.choice(templates)
    return text[0].upper() + text[1:] + "."


def paragraph(rng: random.Random, min_sentences: int = 3, max_sentences: int = 6) -> str:
    """One paragraph of several sentences."""
    return " ".join(sentence(rng) for _ in range(rng.randint(min_sentences, max_sentences)))
