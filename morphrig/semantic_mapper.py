# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional, Sequence

ROW_ORDER = ("Eyebrows", "Eyes", "Lips", "Vowels", "Emotes", "Extra")
_ROW_INDEX = {name: idx for idx, name in enumerate(ROW_ORDER)}
_SEPARATOR_PREFIXES = ("-" * 3, "=" * 3, "*" * 3, "_" * 3)
_TRAILING_KANJI_SIDE_NUM_RE = re.compile(r"^(.+?)(右|左)(\d+)$")
_INFIX_SIDE_RE = re.compile(r"^(.+?)(?:[_.\- ](right|left|r|l)[_.\- ])(.+)$")


@dataclass
class ControlSlot:
    row: str
    display_label: str
    side: str
    shape_key_name: str
    priority: int = 100


@dataclass
class PairedControlGroup:
    row: str
    display_label: str
    priority: int
    right_slot: Optional[ControlSlot] = None
    left_slot: Optional[ControlSlot] = None
    center_slot: Optional[ControlSlot] = None

    @property
    def is_paired(self) -> bool:
        return self.right_slot is not None and self.left_slot is not None


def normalize_shape_key_name(raw_name: str) -> str:
    if not raw_name:
        return ""
    return unicodedata.normalize("NFKC", raw_name).strip().lower()


def is_ignored_shape_key(index: int, raw_name: str) -> bool:
    if index == 0:
        return True
    stripped = (raw_name or "").strip()
    if not stripped:
        return True
    if stripped.startswith(_SEPARATOR_PREFIXES):
        return True
    norm = normalize_shape_key_name(stripped)
    if norm in ("basis", "基型"):
        return True
    if norm.startswith(_SEPARATOR_PREFIXES):
        return True
    return False


def extract_laterality(norm_name: str) -> tuple[str, str]:
    norm = normalize_shape_key_name(norm_name)
    if not norm:
        return ("", "")

    if norm in ("ウィンク", "ウィンク2"):
        return (norm, "L")

    suffix_rules = (
        ("_right", "R"),
        (".right", "R"),
        ("-right", "R"),
        (" right", "R"),
        ("_left", "L"),
        (".left", "L"),
        ("-left", "L"),
        (" left", "L"),
        ("_r", "R"),
        (".r", "R"),
        ("-r", "R"),
        ("_l", "L"),
        (".l", "L"),
        ("-l", "L"),
        ("右", "R"),
        ("左", "L"),
    )
    for token, side in suffix_rules:
        if norm.endswith(token) and len(norm) > len(token):
            base = norm[: -len(token)].rstrip(" _.-")
            if base:
                return (base, side)

    num_match = _TRAILING_KANJI_SIDE_NUM_RE.match(norm)
    if num_match:
        prefix, kanji_side, digits = num_match.groups()
        side = "R" if kanji_side == "右" else "L"
        return (f"{prefix}{digits}", side)

    prefix_rules = (
        ("right_", "R"),
        ("right.", "R"),
        ("right-", "R"),
        ("right ", "R"),
        ("left_", "L"),
        ("left.", "L"),
        ("left-", "L"),
        ("left ", "L"),
        ("r_", "R"),
        ("r.", "R"),
        ("r-", "R"),
        ("l_", "L"),
        ("l.", "L"),
        ("l-", "L"),
        ("右", "R"),
        ("左", "L"),
    )
    for token, side in prefix_rules:
        if norm.startswith(token) and len(norm) > len(token):
            base = norm[len(token) :].lstrip(" _.-")
            if base:
                return (base, side)

    infix_match = _INFIX_SIDE_RE.match(norm)
    if infix_match:
        head, token, tail = infix_match.groups()
        side = "R" if token in ("right", "r") else "L"
        sep = "_" if "_" in norm else ""
        base = f"{head.rstrip(' _.-')}{sep}{tail.lstrip(' _.-')}".strip(" _.-")
        if base:
            return (base, side)

    return (norm, "")


_RAW_SEMANTIC_ENTRIES: tuple[tuple[str, str, int, tuple[str, ...]], ...] = (
    ("Eyebrows", "Happy", 10, ("にこり", "brow_happy")),
    ("Eyebrows", "Angry", 20, ("怒り", "怒った", "brow_angry")),
    ("Eyebrows", "Angry 2", 21, ("怒り2", "怒った2")),
    ("Eyebrows", "Sad", 30, ("困る", "心配する", "やっかい", "brow_sad")),
    ("Eyebrows", "Sad 2", 31, ("困る2", "心配する2")),
    ("Eyebrows", "Serious", 40, ("真面目", "brow_serious")),
    ("Eyebrows", "Up", 50, ("上", "brow_up")),
    ("Eyebrows", "Down", 60, ("下", "brow_down")),
    ("Eyebrows", "Furrow", 70, ("前", "手前", "brow_furrow")),
    ("Eyebrows", "Furrow 2", 71, ("手前2",)),
    ("Eyes", "Blink", 10, ("まばたき", "blink", "eye_blink")),
    ("Eyes", "Wink", 20, ("ウィンク", "wink", "eye_wink")),
    ("Eyes", "Wink 2", 21, ("ウィンク2", "wink_2", "wink2")),
    ("Eyes", "Smile", 30, ("笑い", "喜び", "eye_smile")),
    ("Eyes", "Smile 2", 31, ("笑い2", "喜び2")),
    ("Eyes", "Calm", 40, ("なごみ", "慈愛", "eye_calm")),
    ("Eyes", "Calm 2", 41, ("慈愛2",)),
    ("Eyes", "Wide", 50, ("びっくり", "驚かす", "eye_wide", "surprise")),
    ("Eyes", "Jito", 60, ("じと目", "ジト目", "jito")),
    ("Eyes", "Jito 2", 61, ("じと目2", "ジト目2")),
    ("Eyes", "Sharp", 70, ("怒り目", "キリッ", "eye_sharp")),
    ("Eyes", "Sharp 2", 71, ("キリッ2",)),
    ("Eyes", "Pain", 80, ("痛み", "eye_pain")),
    ("Eyes", "Pain 2", 81, ("痛み2",)),
    ("Eyes", "Pain 3", 82, ("痛み3",)),
    ("Eyes", "Lid Adj", 90, ("眼角上", "眼角下", "下眼上")),
    ("Lips", "Smile", 10, ("にやり", "にっこり", "ワ", "口角上げ", "smile", "grin", "mouth_smile")),
    ("Lips", "Smile 1", 11, ("ワ1",)),
    ("Lips", "Smile 2", 12, ("にやり2", "ワ2")),
    ("Lips", "Smile 3", 13, ("にやり3",)),
    ("Lips", "Frown", 20, ("口角下げ", "ムッ", "∧", "frown", "snarl", "mouth_frown")),
    ("Lips", "Frown 2", 21, ("口角下げ2",)),
    ("Lips", "Cat", 30, ("ω", "倒ω", "cat")),
    ("Lips", "Wide", 40, ("口横広げ", "mouth_wide")),
    ("Lips", "Narrow", 50, ("口横狭め", "口横缩げ", "mouth_narrow", "pucker")),
    ("Lips", "Narrow 2", 51, ("口横缩げ2",)),
    ("Lips", "Tongue", 60, ("てへぺろ", "ぺろっ", "舌広げ", "tongue")),
    ("Lips", "Mouth H/V", 70, ("口上", "口下", "口")),
    ("Vowels", "A", 10, ("あ", "大口", "a", "aa", "mouth_a")),
    ("Vowels", "A 2", 11, ("あ2",)),
    ("Vowels", "I", 20, ("い", "i", "ih", "mouth_i")),
    ("Vowels", "I 1", 21, ("い1",)),
    ("Vowels", "I 2", 22, ("い2",)),
    ("Vowels", "U", 30, ("う", "u", "ou", "mouth_u")),
    ("Vowels", "E", 40, ("え", "えー", "e", "eh", "mouth_e")),
    ("Vowels", "E 2", 41, ("え2",)),
    ("Vowels", "E 3", 42, ("え3",)),
    ("Vowels", "O", 50, ("お", "o", "oh", "mouth_o")),
    ("Vowels", "O 2", 51, ("お2",)),
    ("Vowels", "N", 60, ("ん", "n", "m")),
    ("Emotes", "Star", 10, ("星目", "star")),
    ("Emotes", "Heart", 20, ("はぁと", "heart")),
    ("Emotes", "Dizzy", 30, ("はちゅ目", "dizzy")),
    ("Emotes", "Blush", 40, ("照れ", "脸红", "blush")),
    ("Emotes", "Tears", 50, ("涙", "tears")),
    ("Emotes", "Sweat", 60, ("汗", "汗颜", "sweat")),
    ("Emotes", "Bang", 70, ("！", "bang")),
    ("Emotes", "Bang 2", 71, ("！！",)),
    ("Emotes", "Query", 80, ("？", "question")),
    ("Emotes", "Vein", 90, ("怒", "111", "1111", "11+", "anger_mark")),
)


def _build_semantic_dict() -> dict[str, tuple[str, str, int]]:
    mapping: dict[str, tuple[str, str, int]] = {}
    for row, label, priority, aliases in _RAW_SEMANTIC_ENTRIES:
        for alias in aliases:
            norm_alias = normalize_shape_key_name(alias)
            if norm_alias:
                mapping[norm_alias] = (row, label, priority)
    return mapping


_SEMANTIC_DICT = _build_semantic_dict()


def map_shape_key(raw_name: str, include_unmapped: bool = False) -> Optional[ControlSlot]:
    norm = normalize_shape_key_name(raw_name)
    if not norm:
        return None

    direct_hit = _SEMANTIC_DICT.get(norm)
    if direct_hit is not None:
        _, side = extract_laterality(norm)
        row, label, priority = direct_hit
        return ControlSlot(
            row=row,
            display_label=label,
            side=side,
            shape_key_name=raw_name,
            priority=priority,
        )

    base_name, side = extract_laterality(norm)
    mapped = _SEMANTIC_DICT.get(base_name)
    if mapped is not None:
        row, label, priority = mapped
        return ControlSlot(
            row=row,
            display_label=label,
            side=side,
            shape_key_name=raw_name,
            priority=priority,
        )

    if not include_unmapped:
        return None

    fallback_label = raw_name.strip() or norm
    if side and base_name and base_name != norm:
        fallback_label = base_name
    return ControlSlot(
        row="Extra",
        display_label=fallback_label,
        side=side,
        shape_key_name=raw_name,
        priority=1000,
    )


def scan_mesh_shape_keys(
    mesh_obj,
    include_emotes: bool = True,
    include_unmapped: bool = False,
) -> list[ControlSlot]:
    if mesh_obj is None:
        return []
    mesh_data = getattr(mesh_obj, "data", None)
    shape_keys = getattr(mesh_data, "shape_keys", None) if mesh_data is not None else None
    key_blocks = getattr(shape_keys, "key_blocks", None) if shape_keys is not None else None
    if not key_blocks:
        return []

    slots: list[ControlSlot] = []
    for index, key_block in enumerate(key_blocks):
        raw_name = getattr(key_block, "name", "")
        if is_ignored_shape_key(index, raw_name):
            continue
        slot = map_shape_key(raw_name, include_unmapped=include_unmapped)
        if slot is None:
            continue
        if not include_emotes and slot.row == "Emotes":
            continue
        slots.append(slot)

    slots.sort(key=lambda s: (_ROW_INDEX.get(s.row, len(ROW_ORDER)), s.priority))
    return slots


def group_control_slots(
    slots: Sequence[ControlSlot],
    include_emotes: bool = True,
    include_unmapped: bool = False,
) -> dict[str, list[PairedControlGroup]]:
    filtered: list[ControlSlot] = []
    for slot in slots:
        row = slot.row if slot.row in _ROW_INDEX else "Extra"
        if not include_emotes and row == "Emotes":
            continue
        if not include_unmapped and row == "Extra":
            continue
        if row != slot.row:
            slot = ControlSlot(
                row=row,
                display_label=slot.display_label,
                side=slot.side,
                shape_key_name=slot.shape_key_name,
                priority=slot.priority,
            )
        filtered.append(slot)

    filtered.sort(key=lambda s: (_ROW_INDEX.get(s.row, len(ROW_ORDER)), s.priority))

    buckets: dict[tuple[str, str], dict[str, list[ControlSlot]]] = {}
    bucket_order: list[tuple[str, str]] = []
    for slot in filtered:
        key = (slot.row, slot.display_label)
        if key not in buckets:
            buckets[key] = {"R": [], "L": [], "": []}
            bucket_order.append(key)
        side_key = slot.side if slot.side in ("R", "L") else ""
        buckets[key][side_key].append(slot)

    grouped_by_row: dict[str, list[PairedControlGroup]] = {}
    for row, label in bucket_order:
        side_map = buckets[(row, label)]
        r_list = side_map["R"]
        l_list = side_map["L"]
        c_list = side_map[""]

        pair_count = min(len(r_list), len(l_list))
        groups = grouped_by_row.setdefault(row, [])

        for idx in range(pair_count):
            r_slot = r_list[idx]
            l_slot = l_list[idx]
            groups.append(
                PairedControlGroup(
                    row=row,
                    display_label=label,
                    priority=min(r_slot.priority, l_slot.priority),
                    right_slot=r_slot,
                    left_slot=l_slot,
                )
            )

        for leftover_slot in r_list[pair_count:] + l_list[pair_count:]:
            groups.append(
                PairedControlGroup(
                    row=row,
                    display_label=f"{leftover_slot.display_label} ({leftover_slot.side})",
                    priority=leftover_slot.priority,
                    center_slot=leftover_slot,
                )
            )

        for center_slot in c_list:
            groups.append(
                PairedControlGroup(
                    row=row,
                    display_label=center_slot.display_label,
                    priority=center_slot.priority,
                    center_slot=center_slot,
                )
            )

    ordered_result: dict[str, list[PairedControlGroup]] = {}
    for row in ROW_ORDER:
        row_groups = grouped_by_row.get(row)
        if row_groups:
            row_groups.sort(key=lambda g: g.priority)
            ordered_result[row] = row_groups
    return ordered_result
