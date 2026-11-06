"""Characters can't depict real people, other brands or other people's characters.

A deterministic word list catches the obvious cases; the LLM (character suggestion and image QA) catches the
rest. References in captions are fine (a gamer cat may talk about Deadlock), so the list is applied to what
gets drawn: the name, the looks and image scenes."""

from __future__ import annotations

import re

BLOCKED = {
    # famous fictional cats and characters
    "garfield", "hello kitty", "puss in boots", "sylvester", "tom and jerry", "pusheen", "doraemon", "grumpy cat",
    "nyan cat", "cheshire cat", "felix the cat", "salem saberhagen", "luna sailor", "meowth", "pikachu", "pokemon",
    "pokémon", "simba", "mufasa", "the aristocats", "catbus", "totoro", "sonic", "mario", "mickey", "minnie",
    "spider-man", "spiderman", "batman", "superman", "shrek", "stitch", "kirby", "jiji",
    # brands and studios
    "disney", "pixar", "marvel", "dc comics", "nintendo", "valve", "steam logo", "riot games", "blizzard", "nike",
    "adidas", "gucci", "louis vuitton", "chanel", "prada", "supreme", "coca-cola", "pepsi", "red bull", "monster energy",
    "apple logo", "razer", "logitech", "hyperx", "rolex", "ferrari", "lamborghini", "starbucks", "mcdonald",
    # game heroes and marks that must not appear in images
    "deadlock hero", "dota", "counter-strike logo", "valorant agent",
    # real people
    "elon musk", "donald trump", "trump", "putin", "biden", "taylor swift", "kim kardashian", "beyonce", "obama",
    "zelensky", "xi jinping", "mr beast", "mrbeast", "pewdiepie", "s1mple", "faker",
}

_PATTERN = re.compile(r"(?<![a-z0-9])(" + "|".join(sorted((re.escape(w) for w in BLOCKED), key=len, reverse=True)) +
                      r")(?![a-z0-9])", re.I)


def find_blocked(*texts: str) -> list[str]:
    found: list[str] = []
    for t in texts:
        for m in _PATTERN.finditer(t or ""):
            w = m.group(1).lower()
            if w not in found:
                found.append(w)
    return found


def check_character(name: str, handle: str, appearance: dict) -> list[str]:
    return find_blocked(name, handle.replace(".", " ").replace("_", " "),
                        *(str(v) for v in (appearance or {}).values()))
