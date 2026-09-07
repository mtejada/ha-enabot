#!/usr/bin/env python3
"""
gen_sprites.py - procedural pixel-art NPC sprites for the EBO AR game.

Style: GBA overworld townsfolk (Pokemon Ruby/Sapphire flavour) but FRONT-FACING,
chunky pixels, 1px dark outline, tiny palette. Every NPC is assembled from small
hand-drawn PART GRIDS (head, hair, hat, torso, arms, legs, accessories). Grids use
PALETTE LETTERS instead of colours, so the same part can be recoloured for every
archetype. Everything is drawn 1:1 on a 32x32 tile - scale it up on the canvas
with NEAREST (ctx.imageSmoothingEnabled = false) to keep the pixels crisp.

Output (all written next to this file):
  <archetype>.png   horizontal sprite sheet, FRAMES tiles of TILE x TILE, RGBA
  manifest.json     tile size, fps, archetype -> sheet, detected label -> archetype
  preview.png       contact sheet of every archetype, scaled up (for humans)

Run:  python3 gen_sprites.py        (needs Pillow)

Idle animation (3 frames, uniform timing):
  frame 0  idle
  frame 1  "breath" bob: head + torso + arms + held items 1px lower, legs fixed
  frame 2  idle pose with a blink (2px eyes collapse to a 1px line)

Grid letter legend ('.' = transparent):
  k outline        s/S skin base/shade    h/H hair       b/B body (shirt, robe, fur)
  p/P pants        f shoes                a/A accent     x/X accent2
  m/M metal        w/W white/white-shade  e eye
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Sequence, Tuple

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))

TILE = 32          # frame size in px (square)
FRAMES = 3         # idle, bob, blink
FPS = 3            # suggested playback rate
BASELINE = 30      # tile row of the bottom-most outline pixel of the feet
PREVIEW_SCALE = 3  # preview.png zoom

# --------------------------------------------------------------------------- colours
# Each named colour is (base, shade). Outline / white / shoes are shared.
OUTLINE = "#1a1626"
WHITE = ("#f8f8fc", "#c4c4d6")
SHOES = "#3d2a1f"

COLORS: Dict[str, Tuple[str, str]] = {
    # skin / fur
    "skin_light": ("#f7d4a8", "#d9a271"),
    "skin_tan":   ("#e0aa78", "#b97c50"),
    "skin_brown": ("#9e6a44", "#74472c"),
    "skin_dark":  ("#6f4530", "#4b2c1c"),
    "fur_orange": ("#f2a445", "#c47425"),
    "fur_bear":   ("#a5703f", "#7a4f2a"),
    "steel":      ("#c4c8d4", "#8e94a6"),
    # hair
    "hair_brown":  ("#7d4b2a", "#55321a"),
    "hair_black":  ("#3b3552", "#27233a"),
    "hair_blonde": ("#f3d15e", "#c9a338"),
    "hair_red":    ("#d8552b", "#9e3a1b"),
    "hair_grey":   ("#cfd0da", "#9b9cae"),
    "hair_white":  ("#f2f2f6", "#c7c7d2"),
    "hair_blue":   ("#4c72d8", "#34509e"),
    "hair_purple": ("#9a5fd0", "#6c3e9a"),
    "hair_pink":   ("#f293c4", "#c25d95"),
    # cloth / accents
    "red":       ("#e34c4c", "#a83232"),
    "blue":      ("#4a7ce0", "#3153a8"),
    "green":     ("#4fb35b", "#338040"),
    "yellow":    ("#f2c94c", "#c19a2f"),
    "purple":    ("#9263cc", "#69429a"),
    "orange":    ("#f08a3a", "#b95f28"),
    "teal":      ("#43b3b3", "#2b8282"),
    "pink":      ("#f285ad", "#c2527c"),
    "white":     ("#f5f5f9", "#c9c9db"),
    "brown":     ("#936243", "#62412b"),
    "grey":      ("#a3a3b4", "#72728a"),
    "darkgrey":  ("#5a5a6e", "#3d3d4c"),
    "navy":      ("#3a4a84", "#28325a"),
    "lightblue": ("#9ccdf0", "#6a9ac4"),
    "denim":     ("#4159a2", "#2d3d72"),
    "black":     ("#3c3849", "#262331"),
    "cream":     ("#efe3c9", "#c3b391"),
    "straw":     ("#e8c86a", "#b99a40"),
    "amber":     ("#d9902e", "#a3661c"),
    "cyan":      ("#5ee6f0", "#2fa9b8"),
    "lilac":     ("#c9a6f0", "#9a74c8"),
}

# Which palette slot each letter reads from.
SLOT_OF = {"s": "skin", "h": "hair", "b": "body", "p": "pants",
           "a": "accent", "x": "accent2", "m": "metal"}


def hex2rgba(h: str) -> Tuple[int, int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)


def build_palette(p: Dict[str, str]) -> Dict[str, Tuple[int, int, int, int]]:
    """Palette spec (slot -> COLORS key, plus optional eye/shoes hex) -> letter -> RGBA."""
    pal = {
        "k": hex2rgba(OUTLINE),
        "e": hex2rgba(p.get("eye", OUTLINE)),
        "f": hex2rgba(p.get("shoes", SHOES)),
        "w": hex2rgba(WHITE[0]),
        "W": hex2rgba(WHITE[1]),
    }
    for letter, slot in SLOT_OF.items():
        base, shade = COLORS[p.get(slot, "grey")]
        pal[letter] = hex2rgba(base)
        pal[letter.upper()] = hex2rgba(shade)
    return pal


# --------------------------------------------------------------------------- grids
Grid = List[str]


def G(*rows: str) -> Grid:
    """Validate that every row of a grid has the same width."""
    w = len(rows[0])
    for r in rows:
        if len(r) != w:
            raise ValueError(f"ragged grid row {r!r} (want width {w})\n" + "\n".join(rows))
    return list(rows)


def mirror(grid: Grid) -> Grid:
    return [r[::-1] for r in grid]


# ---- heads: 12x11. Eyes live at (3,5) and (7,5), each 2x2. Chin outline is row 10.
HEADS: Dict[str, Grid] = {
    "round": G(
        "...kkkkkk...",
        "..kssssssk..",
        ".kssssssssk.",
        "kssssssssssk",
        "kssssssssssk",
        "kssssssssssk",
        "kssssssssssk",
        "kssssssssssk",
        ".kssssssssk.",
        "..kSSSSSSk..",
        "...kkkkkk...",
    ),
    # robot: square head with a dark visor; eyes are lit pixels on the visor
    "box": G(
        "kkkkkkkkkkkk",
        "kmmmmmmmmmmk",
        "kmmmmmmmmmmk",
        "kmkkkkkkkkmk",
        "kmkMMMMMMkmk",
        "kmkMMMMMMkmk",
        "kmkMMMMMMkmk",
        "kmkkkkkkkkmk",
        "kmmmmmmmmmmk",
        "kMMMMMMMMMMk",
        "kkkkkkkkkkkk",
    ),
}
EYE_POS = ((3, 5), (7, 5))
EYES: Dict[str, Grid] = {
    "open": G("ee", "ee"),
    "shut": G("..", "ee"),
}
MOUTH = (5, 8, G("SS"))  # dx, dy, grid (head-relative)

# ---- hair: head-relative overlays, (dx, dy, grid). Drawn after the head.
HAIR: Dict[str, Tuple[int, int, Grid]] = {
    "short": (0, 0, G(
        "...kkkkkk...",
        "..khhhhhhk..",
        ".khhhhhhhhk.",
        "khhhhhhhhhhk",
        "khhhHhhhHhhk",
        "kH........Hk",
        "kH........Hk",
    )),
    "spiky": (0, -2, G(
        ".kk..kk..kk.",
        "khhkkhhkkhhk",
        "khhhhhhhhhhk",
        "khhhhhhhhhhk",
        "khhhhhhhhhhk",
        "khhhhhhhhhhk",
        "khhHhhhhHhhk",
        "kH........Hk",
    )),
    "long": (0, 0, G(
        "...kkkkkk...",
        "..khhhhhhk..",
        ".khhhhhhhhk.",
        "khhhhhhhhhhk",
        "khhhhHhhhhhk",
        "kh........hk",
        "kh........hk",
        "kh........hk",
        "khh......hhk",
        "khh......hhk",
        "khh......hhk",
        "kHh......hHk",
        ".kk......kk.",
    )),
    "bob": (0, 0, G(
        "...kkkkkk...",
        "..khhhhhhk..",
        ".khhhhhhhhk.",
        "khhhhhhhhhhk",
        "khhhhHhhhhhk",
        "kh........hk",
        "kh........hk",
        "kh........hk",
        "khh......hhk",
        "kHH......HHk",
        ".kk......kk.",
    )),
    "bun": (0, -3, G(
        "....kkkk....",
        "...khhhhk...",
        "..khhhhhhk..",
        ".khhhhhhhhk.",
        "khhhhhhhhhhk",
        "khhhhhhhhhhk",
        "kHhhhhhhhhHk",
        "kH........Hk",
    )),
    "bald": (0, 3, G(
        "kh........hk",
        "kh........hk",
    )),
    "pigtails": (-3, 0, G(
        "......kkkkkk......",
        ".....khhhhhhk.....",
        "....khhhhhhhhk....",
        "...khhhhhhhhhhk...",
        "...khhhhHhhhhhk...",
        ".kkkH........Hkkk.",
        "khhk..........khhk",
        "khhk..........khhk",
        "kHhk..........khHk",
        ".kk............kk.",
    )),
    # facial hair (uses the hair colour too)
    "beard": (0, 7, G(
        "kh........hk",
        "khh......hhk",
        "khhhhhhhhhhk",
        "khhhhhhhhhhk",
        ".khhhhhhhhk.",
        ".khhHhhhHhk.",
        "..khhhhhhk..",
        "...kkkkkk...",
    )),
    "mustache": (0, 7, G(
        "..khhkkhhk..",
        "...kk..kk...",
    )),
}

# ---- hats: head-relative overlays, (dx, dy, grid). Drawn after hair.
HATS: Dict[str, Tuple[int, int, Grid]] = {
    "cap": (-1, -2, G(
        "....kkkkkk....",
        "...kaaaaaak...",
        "..kaaaaaaaak..",
        ".kaaaaaaaaaak.",
        ".kaaaaaaaaaak.",
        "kkAAAAAAAAAAkk",
        ".kkkkkkkkkkkk.",
    )),
    "chef": (0, -6, G(
        "..kkkkkkkk..",
        ".kwwwwwwwwk.",
        "kwwwwwwwwwwk",
        "kwwwwwwwwwwk",
        "kwwwwwwwwwwk",
        "kwwwwwwwwwwk",
        ".kwwwwwwwwk.",
        ".kkkkkkkkkk.",
        "kwwwwwwwwwwk",
        "kWWWWWWWWWWk",
    )),
    "beanie": (0, -3, G(
        "....kkkk....",
        "..kkaaaakk..",
        ".kaaaaaaaak.",
        "kaaaaaaaaaak",
        "kaaaaaaaaaak",
        "kAAAAAAAAAAk",
        "kAAAAAAAAAAk",
        "kkkkkkkkkkkk",
    )),
    "nightcap": (-1, -5, G(
        "....kkkk......",
        "...kaaaak.....",
        "..kaaaaaak....",
        "..kaaaaaaakkk.",
        ".kaaaaaaaaaawk",
        ".kaaaaaaaaakwk",
        "kaaaaaaaaaaakk",
        "kAAAAAAAAAAAAk",
        ".kkkkkkkkkkkk.",
    )),
    "wizard": (-2, -8, G(
        ".......kk.......",
        "......kaak......",
        "......kaak......",
        ".....kaaaak.....",
        ".....kaaaak.....",
        "....kaaaaaak....",
        "....kaaaaaak....",
        "...kaaaaaaaak...",
        "..kaaaaaaaaaak..",
        "kkkaaaaaaaaaakkk",
        "kAAAAAAAAAAAAAAk",
        ".kkkkkkkkkkkkkk.",
    )),
    "headphones": (-1, -1, G(
        "...kkkkkkkk...",
        "..kaaaaaaaak..",
        ".kak......kak.",
        ".kak......kak.",
        "kkak......kakk",
        "kaak......kaak",
        "kaak......kaak",
        "kaak......kaak",
        "kkkk......kkkk",
    )),
    "straw": (-3, -3, G(
        "......kkkkkk......",
        ".....kaaaaaak.....",
        ".....kaaaaaak.....",
        ".....kAAAAAAk.....",
        "kkkkkkaaaaaakkkkkk",
        "kaaaaaaaaaaaaaaaak",
        ".kkkkkkkkkkkkkkkk.",
    )),
    "tophat": (-1, -6, G(
        "..kkkkkkkkkk..",
        "..kaaaaaaaak..",
        "..kaaaaaaaak..",
        "..kaaaaaaaak..",
        "..kaaaaaaaak..",
        "..kxxxxxxxxk..",
        "kkkaaaaaaaakkk",
        "kAAAAAAAAAAAAk",
        ".kkkkkkkkkkkk.",
    )),
    "cat_ears": (0, -4, G(
        "..k......k..",
        ".kak....kak.",
        ".kxak..kaxk.",
        "kaaak..kaaak",
        ".kkkkkkkkkk.",
    )),
    "bear_ears": (0, -3, G(
        ".kkk....kkk.",
        "khhhk..khhhk",
        "kHhhk..khhHk",
        ".kkkkkkkkkk.",
    )),
    "antenna": (0, -4, G(
        "....kkkk....",
        "....kxxk....",
        "....kkkk....",
        ".....kk.....",
    )),
    "crown": (0, -3, G(
        "..k..kk..k..",
        "..kakaakak..",
        "..kaaaaaak..",
        "..kkkkkkkk..",
    )),
    "towel": (0, -4, G(
        "....kkkk....",
        "..kkwwwwkk..",
        ".kwwwwwwwwk.",
        "kwwwwwwwwwwk",
        "kwwwwwwwwwwk",
        "kwWwwwwwwWwk",
        "kWWWWWWWWWWk",
        ".kkkkkkkkkk.",
    )),
}

# ---- bodies (silhouettes). torso + legs + one arm grid (mirrored for the other side).
#   inset  = torso column of the shoulder outline where the arm's inner column overlaps
#   arm_dy = arm offset from torso row 0 (lets round shoulders slope)
# The head (12 wide) is centred over the torso and overlaps its top row by 1px.
BODIES: Dict[str, dict] = {
    "normal": dict(
        torso=G(
            "kkkkkkkkkkkk",
            "kbbbbbbbbbbk",
            "kbbbbbbbbbbk",
            "kbbbbbbbbbbk",
            "kbbbbbbbbbbk",
            "kBbbbbbbbbBk",
            "kBBBBBBBBBBk",
        ),
        legs=G(
            "kppppppppppk",
            "kppppkkppppk",
            "kppppkkppppk",
            "kffffkkffffk",
            ".kkkk..kkkk.",
        ),
        arm=G(".kk.", "kbbk", "kbbk", "kbbk", "kBBk", "kssk", ".kk."),
        inset=0, arm_dy=0,
    ),
    "round": dict(
        torso=G(
            "..kkkkkkkkkk..",
            ".kbbbbbbbbbbk.",
            "kbbbbbbbbbbbbk",
            "kbbbbbbbbbbbbk",
            "kbbbbbbbbbbbbk",
            "kbbbbbbbbbbbbk",
            "kBbbbbbbbbbbBk",
            ".kBBBBBBBBBBk.",
        ),
        legs=G(
            "kppppppppk",
            "kpppkkpppk",
            "kfffkkfffk",
            ".kkk..kkk.",
        ),
        arm=G(".kk.", "kbbk", "kbbk", "kBBk", "kssk", ".kk."),
        inset=0, arm_dy=2,
    ),
    "kid": dict(
        torso=G(
            "kkkkkkkkkk",
            "kbbbbbbbbk",
            "kbbbbbbbbk",
            "kbbbbbbbbk",
            "kBBBBBBBBk",
        ),
        legs=G(
            "kppppppppk",
            "kpppkkpppk",
            "kfffkkfffk",
            ".kkk..kkk.",
        ),
        arm=G(".kk.", "kbbk", "kbbk", "kssk", ".kk."),
        inset=0, arm_dy=0,
    ),
    "dress": dict(
        torso=G(
            ".kkkkkkkkkkkk.",
            ".kbbbbbbbbbbk.",
            ".kbbbbbbbbbbk.",
            ".kbbbbbbbbbbk.",
            ".kbbbbbbbbbbk.",
            ".kBbbbbbbbbBk.",
            "kbbbbbbbbbbbbk",
            "kbbbbbbbbbbbbk",
            "kbbbbbbbbbbbbk",
            "kBBBBBBBBBBBBk",
            ".kkkkkkkkkkkk.",
        ),
        legs=G(
            "..kffk..kffk..",
            "..kkkk..kkkk..",
        ),
        arm=G(".kk.", "kbbk", "kbbk", "kbbk", "kBBk", "kssk", ".kk."),
        inset=1, arm_dy=0,
    ),
    "robot": dict(
        torso=G(
            "kkkkkkkkkkkk",
            "kmmmmmmmmmmk",
            "kmmxxmmxxmmk",
            "kmmxxmmxxmmk",
            "kmmmmmmmmmmk",
            "kMmmmmmmmmMk",
            "kMMMMMMMMMMk",
        ),
        legs=G(
            "kmmmmkkmmmmk",
            "kmmmmkkmmmmk",
            "kMMMMkkMMMMk",
            ".kkkk..kkkk.",
        ),
        arm=G(".kk.", "kmmk", "kmmk", "kmmk", "kMMk", "kssk", ".kk."),
        inset=0, arm_dy=0,
    ),
}

# ---- accessories. anchor: "head" | "torso" | "torso_center" | "right" | "left"
#   head/torso      : dx,dy from that part's origin
#   torso_center    : horizontally centred on the torso, dy from torso row 0
#   right / left    : dx from the torso's right edge / from the item's right edge at torso col 0
# layer: "back" (behind everything), "torso" (over torso, under head), "front" (over all)
ACCESSORIES: Dict[str, dict] = {
    # frame + a white glint on the outer edge of each lens; the 2x2 eyes show through the '.'
    "glasses": dict(anchor="head", dx=0, dy=4, layer="front", grid=G(
        ".kkkkkkkkkk.",
        "kkw..kkw..kk",
        ".kw..kkw..k.",
        ".kkkkkkkkkk.",
    )),
    "book": dict(anchor="torso_center", dy=2, layer="torso", grid=G(
        "kkkkkk",
        "kawwak",
        "kawwak",
        "kkkkkk",
    )),
    "mug": dict(anchor="right", dx=0, dy=3, layer="front", grid=G(
        "kkkk",
        "kaak",
        "kaak",
        "kkkk",
    )),
    "ball": dict(anchor="right", dx=-1, dy=2, layer="front", grid=G(
        ".kkk.",
        "kxwxk",
        "kxxxk",
        "kXxXk",
        ".kkk.",
    )),
    "broom": dict(anchor="torso", dx=-4, dy=-7, layer="back", grid=G(
        *([".kxk.."] * 15),
        "kkkkkk",
        "kxxxxk",
        "kxxxxk",
        "kXXXXk",
        ".kkkk.",
    )),
    "guitar": dict(anchor="torso", dx=1, dy=0, layer="torso", grid=G(
        "kk........",
        "kxk.......",
        ".kxk......",
        "..kaaaak..",
        ".kaaaaaak.",
        ".kaakkaak.",
        ".kaaaaaak.",
        "..kkkkkk..",
    )),
    "straps": dict(anchor="torso", dx=0, dy=1, layer="torso", grid=G(
        ".kxk....kxk.",
        ".kxk....kxk.",
        ".kxk....kxk.",
        ".kxk....kxk.",
    )),
    "tie": dict(anchor="torso_center", dy=1, layer="torso", grid=G(
        "kxxk",
        "kxxk",
        "kxxk",
        ".kk.",
    )),
    "apron": dict(anchor="torso_center", dy=2, layer="torso", grid=G(
        "kkkkkkkk",
        "kxxxxxxk",
        "kxxxxxxk",
        "kxxxxxxk",
        "kXXXXXXk",
    )),
    "scarf": dict(anchor="torso_center", dy=1, layer="torso", grid=G(
        "kxxxxxxxxxxk",
        ".kxxxkkxxxk.",
        "....kxxk....",
        ".....kk.....",
    )),
    "bow": dict(anchor="head", dx=6, dy=-1, layer="front", grid=G(
        ".kk.kk.",
        "kxxkxxk",
        "kxxkxxk",
        ".kk.kk.",
    )),
    "belly": dict(anchor="torso_center", dy=1, layer="torso", grid=G(
        ".xxxx.",
        "xxxxxx",
        "xxxxxx",
        ".xxxx.",
    )),
    "belly_round": dict(anchor="torso_center", dy=3, layer="torso", grid=G(
        ".xxxx.",
        "xxxxxx",
        "xxxxxx",
        ".xxxx.",
    )),
    "snout": dict(anchor="head", dx=0, dy=7, layer="front", grid=G(
        "....xkkx....",
        "...xxxxxx...",
        "....xxxx....",
    )),
    "cat_face": dict(anchor="head", dx=-2, dy=7, layer="front", grid=G(
        "kk.....xx.....kk",
        "......S..S......",
    )),
    "blush": dict(anchor="head", dx=0, dy=7, layer="front", grid=G(
        "..x......x..",
    )),
}

# --------------------------------------------------------------------------- archetypes
# body/head/hair/hat pick parts; acc lists accessory names; eyes is the resting eye
# state ("open" blinks shut on frame 2, "shut" blinks open); palette maps slots to
# COLORS keys (accent = hat / held item, accent2 = apron, straps, bow, ...).
def A(body="normal", head="round", hair=None, hat=None, acc=(), eyes="open",
      mouth=True, **palette) -> dict:
    hairs = [] if hair is None else ([hair] if isinstance(hair, str) else list(hair))
    return dict(body=body, head=head, hair=hairs, hat=hat, acc=list(acc),
                eyes=eyes, mouth=mouth, palette=palette)


ARCHETYPES: Dict[str, dict] = {
    # --- plain villagers: same parts, three palettes / hair styles
    "villager_a": A(hair="short", skin="skin_light", hair_c="hair_brown",
                    body="normal", body_c="blue", pants="denim"),
    "villager_b": A(hair="spiky", skin="skin_tan", hair_c="hair_blonde",
                    body_c="red", pants="brown"),
    "villager_c": A(hair="bob", skin="skin_brown", hair_c="hair_black",
                    body_c="green", pants="black"),
    # --- home
    "sleepy":  A(hair="short", hat="nightcap", eyes="shut", mouth=False,
                 skin="skin_light", hair_c="hair_brown", body_c="lightblue",
                 pants="lightblue", accent="lightblue", shoes="#c2527c"),
    "lass":    A(body="dress", hair="long", acc=("bow", "blush"),
                 skin="skin_light", hair_c="hair_red", body_c="pink",
                 accent2="white"),
    "granny":  A(body="dress", hair="bun", acc=("glasses",), mouth=False,
                 skin="skin_light", hair_c="hair_grey", body_c="purple"),
    # --- kitchen
    "chef":    A(body="round", hair="short", hat="chef", acc=("scarf",),
                 skin="skin_tan", hair_c="hair_black", body_c="white",
                 accent2="red"),
    "barkeep": A(body="round", hair=("bald", "mustache"), acc=("apron", "mug"),
                 skin="skin_light", hair_c="hair_brown", body_c="purple",
                 accent="amber", accent2="white"),
    # --- tech
    "gamer":   A(body="kid", hair="short", hat="headphones",
                 skin="skin_light", hair_c="hair_black", body_c="green",
                 pants="black", accent="darkgrey"),
    "robot":   A(body="robot", head="box", hat="antenna", mouth=False,
                 skin="steel", metal="grey", accent2="cyan", eye="#5ee6f0"),
    # --- study / shop
    "scholar": A(hair="short", acc=("glasses", "book"),
                 skin="skin_tan", hair_c="hair_black", body_c="brown",
                 pants="grey", accent="red"),
    "merchant": A(hair="short", hat="tophat", acc=("tie", "glasses"), mouth=False,
                  skin="skin_light", hair_c="hair_brown", body_c="navy",
                  pants="black", accent="black", accent2="red"),
    # --- outdoors / chores
    "hiker":   A(hair="short", hat="cap", acc=("straps",),
                 skin="skin_brown", hair_c="hair_black", body_c="green",
                 pants="brown", accent="orange", accent2="brown"),
    "janitor": A(hair="short", hat="cap", acc=("broom",),
                 skin="skin_tan", hair_c="hair_brown", body_c="teal",
                 pants="teal", accent="grey", accent2="straw"),
    "gardener": A(body="round", hair="short", hat="straw",
                  skin="skin_tan", hair_c="hair_brown", body_c="green",
                  pants="brown", accent="straw"),
    "bather":  A(body="dress", hat="towel", acc=("blush",), mouth=False,
                 skin="skin_light", body_c="pink", accent2="pink",
                 shoes="#f285ad"),
    # --- fantasy / music
    "wizard":  A(body="dress", hair="beard", hat="wizard", mouth=False,
                 skin="skin_light", hair_c="hair_white", body_c="navy",
                 accent="purple"),
    "musician": A(hair="spiky", acc=("guitar",),
                  skin="skin_dark", hair_c="hair_purple", body_c="pink",
                  pants="black", accent="amber", accent2="brown"),
    # --- kids & critters
    "kid_a":   A(body="kid", hair="spiky", acc=("ball",),
                 skin="skin_light", hair_c="hair_red", body_c="yellow",
                 pants="denim", accent2="red"),
    "kid_b":   A(body="kid", hair="pigtails",
                 skin="skin_brown", hair_c="hair_blonde", body_c="lilac",
                 pants="purple"),
    "teddy":   A(body="round", hat="bear_ears", acc=("belly_round", "snout"),
                 mouth=False, skin="fur_bear", hair_c="fur_bear", body_c="brown",
                 pants="brown", accent2="cream", shoes="#7a4f2a"),
    "cat":     A(body="kid", hat="cat_ears", acc=("belly", "cat_face"),
                 mouth=False, skin="fur_orange", body_c="orange", pants="orange",
                 accent="orange", accent2="cream", shoes="#c47425"),
}

# Detected-object label -> archetype. Every label the game can emit must be here.
LABELS: Dict[str, str] = {
    "_default": "villager_a",
    # furniture / rooms
    "chair": "villager_a", "door": "villager_a", "window": "villager_a",
    "couch": "villager_c", "rug": "villager_b",
    "bed": "sleepy", "pillow": "sleepy", "blanket": "sleepy", "slipper": "sleepy",
    "curtain": "lass", "mirror": "lass", "vase": "lass", "doll": "lass",
    "dining table": "granny", "plate": "granny", "bowl": "granny", "jar": "granny",
    "scissors": "granny",
    # kitchen
    "pan": "chef", "oven": "chef", "microwave": "chef", "toaster": "chef",
    "refrigerator": "chef",
    "bottle": "barkeep", "wine glass": "barkeep", "cup": "barkeep", "can": "barkeep",
    # tech
    "tv": "gamer", "remote": "gamer", "laptop": "gamer", "keyboard": "gamer",
    "monitor": "gamer", "tablet": "gamer", "cell phone": "gamer",
    "charger": "robot", "cable": "robot", "fan": "robot",
    # study / valuables
    "book": "scholar", "lamp": "scholar", "clock": "scholar", "glasses": "scholar",
    "wallet": "merchant", "watch": "merchant",
    # outdoors / chores / bath
    "backpack": "hiker", "suitcase": "hiker", "handbag": "hiker", "umbrella": "hiker",
    "hat": "hiker", "shoe": "hiker", "sock": "hiker",
    "broom": "janitor", "bucket": "janitor", "trash can": "janitor", "basket": "janitor",
    "potted plant": "gardener", "plant": "gardener",
    "toothbrush": "bather", "towel": "bather", "sink": "bather", "toilet": "bather",
    # fantasy / music
    "candle": "wizard", "key": "wizard",
    "guitar": "musician", "speaker": "musician", "headphones": "musician",
    # kids & critters
    "ball": "kid_a", "box": "kid_a", "toy": "kid_b",
    "teddy bear": "teddy",
    "food bowl": "cat", "litter box": "cat", "leash": "cat", "cat tree": "cat",
}


# --------------------------------------------------------------------------- renderer
def blit(img: Image.Image, grid: Sequence[str], x0: int, y0: int, pal: dict) -> None:
    """Paint a letter grid onto img at (x0, y0); '.' is transparent, off-tile pixels are clipped."""
    px = img.load()
    w, h = img.size
    for j, row in enumerate(grid):
        y = y0 + j
        if not 0 <= y < h:
            continue
        for i, ch in enumerate(row):
            if ch == ".":
                continue
            x = x0 + i
            if 0 <= x < w:
                px[x, y] = pal[ch]


def palette_for(arch: dict) -> dict:
    p = arch["palette"]
    # A() takes body= as the silhouette, so the shirt colour arrives as body_c / hair as hair_c.
    spec = {
        "skin": p.get("skin", "skin_light"),
        "hair": p.get("hair_c", "hair_brown"),
        "body": p.get("body_c", "blue"),
        "pants": p.get("pants", "denim"),
        "accent": p.get("accent", "red"),
        "accent2": p.get("accent2", "white"),
        "metal": p.get("metal", "grey"),
    }
    for k in ("eye", "shoes"):
        if k in p:
            spec[k] = p[k]
    return build_palette(spec)


def render_frame(arch: dict, frame: int) -> Image.Image:
    img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    pal = palette_for(arch)
    body = BODIES[arch["body"]]
    torso, legs, arm = body["torso"], body["legs"], body["arm"]
    tw, th, lw, lh = len(torso[0]), len(torso), len(legs[0]), len(legs)

    bob = 1 if frame == 1 else 0            # upper body sinks 1px on the "breath" frame
    blink = frame == 2

    # anchors: feet sit on BASELINE, torso above the legs, head overlaps torso row 0
    ly = BASELINE + 1 - lh
    lx = TILE // 2 - lw // 2
    tx = TILE // 2 - tw // 2
    ty = ly - th + bob
    hx = tx + (tw - 12) // 2
    hy = ty - 10

    def place(acc: dict) -> Tuple[int, int]:
        g = acc["grid"]
        a = acc["anchor"]
        if a == "head":
            return hx + acc["dx"], hy + acc["dy"]
        if a == "torso":
            return tx + acc["dx"], ty + acc["dy"]
        if a == "torso_center":
            return tx + (tw - len(g[0])) // 2, ty + acc["dy"]
        if a == "right":
            return tx + tw + acc["dx"], ty + acc["dy"]
        if a == "left":
            return tx - len(g[0]) + acc["dx"], ty + acc["dy"]
        raise ValueError(a)

    accs = [ACCESSORIES[n] for n in arch["acc"]]

    for acc in (a for a in accs if a["layer"] == "back"):
        blit(img, acc["grid"], *place(acc), pal)

    blit(img, legs, lx, ly, pal)

    inset, ady = body["inset"], body["arm_dy"]
    blit(img, arm, tx + inset - 3, ty + ady, pal)                    # viewer-left arm
    blit(img, mirror(arm), tx + tw - inset - 1, ty + ady, pal)       # viewer-right arm
    blit(img, torso, tx, ty, pal)

    for acc in (a for a in accs if a["layer"] == "torso"):
        blit(img, acc["grid"], *place(acc), pal)

    blit(img, HEADS[arch["head"]], hx, hy, pal)
    eye_state = arch["eyes"]
    if blink:
        eye_state = "shut" if eye_state == "open" else "open"
    for ex, ey in EYE_POS:
        blit(img, EYES[eye_state], hx + ex, hy + ey, pal)
    if arch["mouth"]:
        blit(img, MOUTH[2], hx + MOUTH[0], hy + MOUTH[1], pal)

    for style in arch["hair"]:                 # hair styles + facial hair, in order
        dx, dy, g = HAIR[style]
        blit(img, g, hx + dx, hy + dy, pal)
    if arch["hat"]:
        dx, dy, g = HATS[arch["hat"]]
        blit(img, g, hx + dx, hy + dy, pal)

    for acc in (a for a in accs if a["layer"] == "front"):
        blit(img, acc["grid"], *place(acc), pal)
    return img


def render_sheet(arch: dict) -> Image.Image:
    sheet = Image.new("RGBA", (TILE * FRAMES, TILE), (0, 0, 0, 0))
    for f in range(FRAMES):
        sheet.paste(render_frame(arch, f), (f * TILE, 0))
    return sheet


# --------------------------------------------------------------------------- outputs
def write_manifest(names: List[str]) -> str:
    missing = sorted(set(LABELS.values()) - set(ARCHETYPES))
    if missing:
        raise SystemExit(f"labels point at unknown archetypes: {missing}")
    manifest = {
        "tile": TILE,
        "frames": FRAMES,
        "fps": FPS,
        "baseline": BASELINE + 1,
        "layout": ("horizontal strip per archetype: frame i is the tile at "
                   "sx = i*tile, sy = 0, tile x tile px. Draw with "
                   "ctx.imageSmoothingEnabled = false; feet touch y = baseline."),
        "frame_notes": ["idle", "bob (upper body 1px lower)", "idle + blink"],
        "archetypes": {
            n: {"sheet": f"{n}.png", "frames": FRAMES, "width": TILE * FRAMES,
                "height": TILE, "body": ARCHETYPES[n]["body"]}
            for n in names
        },
        "labels": dict(sorted(LABELS.items())),
    }
    path = os.path.join(HERE, "manifest.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
        fh.write("\n")
    return path


def write_preview(sheets: Dict[str, Image.Image]) -> str:
    """Contact sheet: every archetype's 3 frames, zoomed, on a neutral ground."""
    s = PREVIEW_SCALE
    cols = 4
    cw, ch = TILE * FRAMES * s + 12, TILE * s + 24
    rows = (len(sheets) + cols - 1) // cols
    out = Image.new("RGBA", (cols * cw, rows * ch), (70, 74, 88, 255))
    d = ImageDraw.Draw(out)
    for i, (name, sheet) in enumerate(sheets.items()):
        x, y = (i % cols) * cw + 6, (i // cols) * ch + 6
        big = sheet.resize((sheet.width * s, sheet.height * s), Image.NEAREST)
        out.alpha_composite(big, (x, y))
        d.text((x, y + TILE * s + 4), name, fill=(230, 230, 240, 255))
    path = os.path.join(HERE, "preview.png")
    out.save(path, optimize=True)
    return path


def main() -> None:
    sheets: Dict[str, Image.Image] = {}
    for name, arch in ARCHETYPES.items():
        sheet = render_sheet(arch)
        sheet.save(os.path.join(HERE, f"{name}.png"), optimize=True)
        sheets[name] = sheet
    manifest = write_manifest(list(ARCHETYPES))
    preview = write_preview(sheets)
    print(f"{len(sheets)} sheets ({TILE}x{TILE} x {FRAMES} frames) -> {HERE}")
    print(f"manifest: {manifest}\npreview:  {preview}")


if __name__ == "__main__":
    main()
