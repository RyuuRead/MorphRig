# SPDX-License-Identifier: GPL-3.0-or-later
"""Facial board layout, armature construction, drivers and board maintenance."""

from contextlib import contextmanager
import json
from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

import bpy
from mathutils import Matrix, Vector

from . import compat, mmr_bridge, semantic_mapper, widget_factory
from .semantic_mapper import ROW_ORDER, ControlSlot, PairedControlGroup
from .widget_factory import TextLabelSpec

BOARD_PREFIX = "MorphRig_Board_"
BOARD_ROOT_NAME = "Board_Root"
EMBEDDED_FACE_ROOT_NAME = "MorphRig_Face_Root"
EMBEDDED_MOUTH_ROOT_NAME = "MorphRig_Mouth_Root"
EMBEDDED_COLLECTION_PREFIX = "MorphRig: "
BOARD_COLLECTION = "Board"
TRACKS_COLLECTION = "Tracks"
FADER_PREFIX = "Fader_"
TRACK_PREFIX = "Track_"
LIMIT_CONSTRAINT_NAME = "MorphRig_Limit"

# Blender ID and bone names hold at most 63 UTF-8 bytes.
_MAX_NAME_BYTES = 63
_CHAR_NAME_BYTES = _MAX_NAME_BYTES - len(widget_factory.WIDGET_COLLECTION_PREFIX) - len("_Mouth")
FACE_RIG_SCALE = 1.2
MOUTH_RIG_SCALE = 1.15
SECTION_SUB_COLUMNS = 2
MOUTH_ROWS = ("Lips", "Vowels")
FACE_ROWS = ("Eyebrows", "Eyes", "Emotes", "Extra")
_PRIMARY_VOWELS = ("A", "I", "U", "E", "O")
_ROW_HEADERS = {
    "Eyebrows": "EYEBROWS",
    "Eyes": "EYES",
    "Lips": "LIPS",
    "Vowels": "VOWELS",
    "Emotes": "EMOTES",
    "Extra": "EXTRAS",
}
_MOUTH_JOYSTICK_AXES = {
    "I": ("LOC_X", 1.0),
    "U": ("LOC_X", -1.0),
    "O": ("LOC_Y", 1.0),
    "E": ("LOC_Y", -1.0),
}
_KUCHISYNC_MOUTH_KEYS = frozenset(
    semantic_mapper.normalize_shape_key_name(key) for key in ("ワ", "ワ1", "ワ2", "口")
)


@dataclass
class FaderPlacement:
    row: str
    label: str
    side: str
    shape_key_name: str
    x: float
    z: float
    is_horizontal: bool = True

    @property
    def track_bottom(self) -> float:
        return self.z


@dataclass
class BoardLayout:
    width: float
    height: float
    track_height: float
    scale: float
    faders: list = field(default_factory=list)
    labels: list = field(default_factory=list)


def _ordered_rows(grouped: Mapping[str, Sequence[PairedControlGroup]]) -> list:
    rows = [row for row in ROW_ORDER if grouped.get(row)]
    rows.extend(row for row in grouped if row not in ROW_ORDER and grouped.get(row))
    return rows


def _flatten_category_items(groups: Sequence[PairedControlGroup]) -> list:
    items = []
    for group in groups:
        if group.is_paired:
            items.append((f"{group.display_label}_R", "R", group.right_slot.shape_key_name))
            items.append((f"{group.display_label}_L", "L", group.left_slot.shape_key_name))
            continue
        slot = group.center_slot or group.right_slot or group.left_slot
        if slot is not None:
            items.append((group.display_label, slot.side, slot.shape_key_name))
    return items


def _split_section_lanes(items: list) -> tuple[list, list, int]:
    if SECTION_SUB_COLUMNS <= 1:
        return items, [], len(items)
    left_count = (len(items) + 1) // SECTION_SUB_COLUMNS
    if (
        0 < left_count < len(items)
        and items[left_count - 1][1] == "R"
        and items[left_count][1] == "L"
        and items[left_count - 1][0][:-2] == items[left_count][0][:-2]
    ):
        left_count += 1
    left_items = items[:left_count]
    right_items = items[left_count:]
    return left_items, right_items, max(len(left_items), len(right_items))


def calculate_board_layout(
    grouped: Mapping[str, Sequence[PairedControlGroup]],
    scale: float = 1.0,
    track_height: float = 0.12,
    base_font: Optional[float] = None,
) -> BoardLayout:
    """Lay out categories top to bottom with two side-by-side slider lanes per section."""
    slot_size = base_font if base_font is not None else 0.0105 * scale
    header_size = 1.28 * slot_size if base_font is not None else 0.0135 * scale
    row_pitch = 0.016 * scale
    category_gap = 0.012 * scale
    label_col_width = 0.090 * scale
    effective_track_height = track_height * 0.55 * scale
    margin = 0.018 * scale
    sub_col_width = label_col_width + effective_track_height
    sub_col_gap = 0.024 * scale

    sections = []
    has_multi_item_section = False
    for row in _ordered_rows(grouped):
        items = _flatten_category_items(grouped[row])
        if not items:
            continue
        if len(items) > 1:
            has_multi_item_section = True
        left_items, right_items, section_item_rows = _split_section_lanes(items)
        sections.append((row, _ROW_HEADERS.get(row, row.upper()), left_items, right_items, section_item_rows))

    used_lanes = 2 if (SECTION_SUB_COLUMNS > 1 and has_multi_item_section) else 1
    num_categories = len(sections)
    total_rows = sum(1 + section_item_rows for _, _, _, _, section_item_rows in sections)
    height = 2.0 * margin + total_rows * row_pitch + max(0, num_categories - 1) * category_gap
    width = 2.0 * margin + used_lanes * sub_col_width + max(0, used_lanes - 1) * sub_col_gap

    layout = BoardLayout(
        width=width,
        height=height,
        track_height=effective_track_height,
        scale=scale,
    )
    label_x0 = margin
    slider_x0 = margin + label_col_width
    label_x1 = margin + sub_col_width + sub_col_gap
    slider_x1 = label_x1 + label_col_width

    y_top = height - margin
    for cat_idx, (row_name, header_text, left_items, right_items, section_item_rows) in enumerate(sections):
        if cat_idx > 0:
            y_top -= category_gap
        header_center_z = y_top - 0.5 * row_pitch
        layout.labels.append(
            TextLabelSpec(header_text, label_x0, header_center_z - 0.35 * header_size, header_size, "LEFT")
        )
        y_top -= row_pitch

        for lane_items, label_x, slider_x in (
            (left_items, label_x0, slider_x0),
            (right_items, label_x1, slider_x1),
        ):
            for row_idx, (label_text, side, shape_key_name) in enumerate(lane_items):
                row_center_z = y_top - (row_idx + 0.5) * row_pitch
                layout.labels.append(
                    TextLabelSpec(label_text, label_x, row_center_z - 0.35 * slot_size, slot_size, "LEFT")
                )
                layout.faders.append(
                    FaderPlacement(
                        row=row_name,
                        label=label_text,
                        side=side,
                        shape_key_name=shape_key_name,
                        x=slider_x,
                        z=row_center_z,
                        is_horizontal=True,
                    )
                )

        y_top -= section_item_rows * row_pitch

    return layout


def _truncate_bytes(text: str, limit: int) -> str:
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text
    return data[:limit].decode("utf-8", errors="ignore")


def _sanitize_token(text: str) -> str:
    chars = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in text)
    token = "_".join(part for part in chars.split("_") if part)
    return token or "Slot"


def _unique_name(base: str, used: set) -> str:
    candidate = _truncate_bytes(base, _MAX_NAME_BYTES)
    counter = 2
    while candidate in used:
        suffix = f"_{counter}"
        candidate = _truncate_bytes(base, _MAX_NAME_BYTES - len(suffix)) + suffix
        counter += 1
    used.add(candidate)
    return candidate


def _palette_for(row: str, side: str) -> str:
    palettes = compat.ROW_COLOR_PALETTES
    if row == "Emotes":
        return palettes["Emotes"]
    if side in ("R", "L"):
        return palettes[side]
    return palettes.get(row, palettes["Vowels"])


def _load_json(board_armature, key: str, default):
    raw = board_armature.get(key)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _is_alive(id_block) -> bool:
    if id_block is None:
        return False
    try:
        id_block.name
    except ReferenceError:
        return False
    return True


def _resolve_target_mesh(board_armature, target_mesh=None):
    if target_mesh is not None:
        return target_mesh
    return bpy.data.objects.get(board_armature.get("morphrig_target_mesh", ""))


def _fader_names(board_armature) -> list:
    fader_map = _load_json(board_armature, "morphrig_fader_map", {})
    if fader_map:
        return [name for name in fader_map if name in board_armature.pose.bones]
    if board_armature.get("morphrig_embedded"):
        return []
    return [pb.name for pb in board_armature.pose.bones if pb.name.startswith(FADER_PREFIX)]


def _view3d_override(context, obj) -> dict:
    override = {
        "active_object": obj,
        "object": obj,
        "selected_objects": [obj] if obj is not None else [],
        "selected_editable_objects": [obj] if obj is not None else [],
    }
    wm = getattr(context, "window_manager", None)
    if wm is not None:
        win = getattr(context, "window", None)
        windows = [win] if win is not None else list(getattr(wm, "windows", ()))
        for candidate_win in windows:
            screen = getattr(candidate_win, "screen", None)
            if screen is None:
                continue
            for area in screen.areas:
                if area.type == "VIEW_3D":
                    override["window"] = candidate_win
                    override["screen"] = screen
                    override["area"] = area
                    for region in area.regions:
                        if region.type == "WINDOW":
                            override["region"] = region
                            break
                    return override
    return override


def _set_object_mode(context, obj, mode: str) -> None:
    if obj is None or obj.mode == mode:
        return
    view_layer = getattr(context, "view_layer", None)
    if view_layer is not None:
        view_layer.objects.active = obj
    with context.temp_override(**_view3d_override(context, obj)):
        bpy.ops.object.mode_set(mode=mode)


@contextmanager
def _edit_armature_context(context, board):
    # Temporarily unhide if needed so VIEW_3D mode_set.poll() always has a valid active object.
    was_hide_viewport = bool(getattr(board, "hide_viewport", False))
    was_hide_temp = bool(board.hide_get()) if hasattr(board, "hide_get") else False
    if was_hide_viewport:
        board.hide_viewport = False
    if was_hide_temp:
        board.hide_set(False)
    _select_board_only(context, board)
    _set_object_mode(context, board, "EDIT")
    try:
        yield board.data.edit_bones
    finally:
        _set_object_mode(context, board, "OBJECT")
        if was_hide_temp:
            board.hide_set(True)
        if was_hide_viewport:
            board.hide_viewport = True


def _ensure_object_mode(context) -> None:
    view_layer = getattr(context, "view_layer", None)
    active = view_layer.objects.active if view_layer is not None else None
    if active is not None and active.mode != "OBJECT":
        _set_object_mode(context, active, "OBJECT")


def find_all_boards() -> list:
    return [
        obj
        for obj in bpy.data.objects
        if obj.type == "ARMATURE" and obj.get("morphrig_target_mesh") is not None
    ]


def _board_sort_key(board) -> tuple:
    role = board.get("morphrig_board_role", "")
    if role in ("embedded", "face", "combined") or board.get("morphrig_embedded"):
        return (0, board.name)
    if role == "mouth" or board.name.endswith("_Mouth"):
        return (2, board.name)
    return (1, board.name)


def _companion_boards(board_armature) -> list:
    if not _is_alive(board_armature) or board_armature.type != "ARMATURE":
        return []
    boards = [board_armature]
    seen = {board_armature.name}
    target_name = board_armature.get("morphrig_target_mesh", "")

    companion_name = board_armature.get("morphrig_companion_board", "")
    if companion_name and companion_name not in seen:
        companion = bpy.data.objects.get(companion_name)
        if (
            _is_alive(companion)
            and companion.type == "ARMATURE"
            and (not target_name or companion.get("morphrig_target_mesh") == target_name)
        ):
            boards.append(companion)
            seen.add(companion.name)

    if target_name:
        for board in find_all_boards():
            if board.name not in seen and board.get("morphrig_target_mesh") == target_name:
                boards.append(board)
                seen.add(board.name)
    return boards


def find_boards_for_mesh(context, target_mesh=None) -> list:
    """Return all boards bound to target_mesh, ordered primary first and mouth second."""
    boards = find_all_boards()
    if not boards:
        return []

    if target_mesh is not None:
        matched = [b for b in boards if b.get("morphrig_target_mesh") == target_mesh.name]
        return sorted(matched, key=_board_sort_key)

    active = getattr(context, "active_object", None) if context is not None else None
    if active is not None and active in boards:
        mesh_name = active.get("morphrig_target_mesh", "")
        if mesh_name:
            matched = [b for b in boards if b.get("morphrig_target_mesh") == mesh_name]
            return sorted(matched, key=_board_sort_key)
        return [active]

    scene = getattr(context, "scene", None) if context is not None else None
    candidates = []
    settings = getattr(scene, "morphrig", None)
    if settings is not None and settings.target_mesh is not None:
        candidates.append(settings.target_mesh)
    if active is not None and active.type == "MESH":
        candidates.append(active)
    for mesh in candidates:
        matched = [b for b in boards if b.get("morphrig_target_mesh") == mesh.name]
        if matched:
            return sorted(matched, key=_board_sort_key)

    if scene is not None:
        scene_boards = [b for b in boards if scene.objects.get(b.name) is not None]
        if scene_boards:
            return sorted(scene_boards, key=_board_sort_key)
    return sorted(boards, key=_board_sort_key)


def find_board_for_mesh(context, target_mesh=None) -> Optional[bpy.types.Object]:
    """Return the primary board bound to target_mesh, or the active board if selected."""
    if target_mesh is None and context is not None:
        active = getattr(context, "active_object", None)
        if active is not None and active.type == "ARMATURE" and active.get("morphrig_target_mesh") is not None:
            return active
    boards = find_boards_for_mesh(context, target_mesh)
    return boards[0] if boards else None


def remove_boards_for_mesh(context, target_mesh=None) -> int:
    """Remove all facial boards bound to target_mesh and return the count removed."""
    removed = 0
    for board in find_boards_for_mesh(context, target_mesh):
        if remove_facial_board(context, board):
            removed += 1
    return removed


def _coerce_slots(slots_override, target_mesh) -> list:
    key_blocks = target_mesh.data.shape_keys.key_blocks
    slots = []
    seen = set()
    for item in slots_override:
        if not getattr(item, "enabled", True):
            continue
        shape_key_name = getattr(item, "shape_key_name", "")
        if not shape_key_name or shape_key_name in seen or key_blocks.get(shape_key_name) is None:
            continue
        if isinstance(item, ControlSlot):
            slot = item
        else:
            slot = ControlSlot(
                row=getattr(item, "row", "") or getattr(item, "row_category", "") or "Extra",
                display_label=getattr(item, "display_label", "") or shape_key_name,
                side=getattr(item, "side", "") or "",
                shape_key_name=shape_key_name,
                priority=int(getattr(item, "priority", 100)),
            )
        seen.add(shape_key_name)
        slots.append(slot)
    return slots


def _world_bounds(context, obj):
    context.view_layer.update()
    depsgraph = context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    corners = [eval_obj.matrix_world @ Vector(corner) for corner in eval_obj.bound_box]
    mins = Vector((min(c.x for c in corners), min(c.y for c in corners), min(c.z for c in corners)))
    maxs = Vector((max(c.x for c in corners), max(c.y for c in corners), max(c.z for c in corners)))
    return mins, maxs


def _parent_to_bone_keep_world(context, child, parent_arm, bone_name: str) -> None:
    # Bone parenting attaches at the bone tail, so the inverse includes the length offset.
    context.view_layer.update()
    depsgraph = context.evaluated_depsgraph_get()
    arm_eval = parent_arm.evaluated_get(depsgraph)
    pose_bone = arm_eval.pose.bones[bone_name]
    parent_matrix = (
        arm_eval.matrix_world
        @ pose_bone.matrix
        @ Matrix.Translation((0.0, pose_bone.bone.length, 0.0))
    )
    world = child.matrix_basis.copy()
    child.parent = parent_arm
    child.parent_type = "BONE"
    child.parent_bone = bone_name
    child.matrix_parent_inverse = parent_matrix.inverted_safe()
    child.matrix_basis = world


def _configure_constrained_pose_bone(
    pose_bone,
    custom_shape,
    lock_location: tuple[bool, bool, bool],
    min_xyz: tuple[float, float, float],
    max_xyz: tuple[float, float, float],
) -> None:
    pose_bone.rotation_mode = "XYZ"
    pose_bone.lock_location = lock_location
    pose_bone.lock_rotation = (True, True, True)
    pose_bone.lock_scale = (True, True, True)
    pose_bone.custom_shape = custom_shape
    pose_bone.use_custom_shape_bone_size = False

    limit = pose_bone.constraints.new("LIMIT_LOCATION")
    limit.name = LIMIT_CONSTRAINT_NAME
    limit.owner_space = "LOCAL"
    limit.use_transform_limit = True
    limit.use_min_x = True
    limit.use_max_x = True
    limit.use_min_y = True
    limit.use_max_y = True
    limit.use_min_z = True
    limit.use_max_z = True
    limit.min_x, limit.min_y, limit.min_z = min_xyz
    limit.max_x, limit.max_y, limit.max_z = max_xyz


def _configure_fader_pose_bone(pose_bone, cap_widget, travel: float) -> None:
    _configure_constrained_pose_bone(
        pose_bone,
        cap_widget,
        (True, False, True),
        (0.0, 0.0, 0.0),
        (0.0, travel, 0.0),
    )


def _select_board_only(context, board) -> None:
    view_layer = context.view_layer
    for obj in list(view_layer.objects.selected):
        obj.select_set(False)
    board.select_set(True)
    view_layer.objects.active = board


def _create_board_object(context, board_token: str, target_mesh, char_name: str, role: str, location: Vector, widget_coll):
    board_name = f"{BOARD_PREFIX}{board_token}"
    arm_data = bpy.data.armatures.new(board_name)
    arm_data.display_type = "STICK"
    board = bpy.data.objects.new(board_name, arm_data)
    board.location = location
    board.show_in_front = True
    context.scene.collection.objects.link(board)

    board["morphrig_target_mesh"] = target_mesh.name
    board["morphrig_char_name"] = char_name
    board["morphrig_board_role"] = role
    board["morphrig_widget_collection"] = widget_coll.name
    return board


def _collect_vowel_keys(entries) -> list:
    vowel_keys = []
    seen = set()
    for row, sk_name in entries:
        norm_name = semantic_mapper.normalize_shape_key_name(sk_name)
        if row == "Vowels" or norm_name in _KUCHISYNC_MOUTH_KEYS:
            if sk_name not in seen:
                seen.add(sk_name)
                vowel_keys.append(sk_name)
    return vowel_keys


def _assign_visible_collection(
    arm_data,
    pose_bone,
    collection_name: str,
    palette: str,
    owned_collections: Optional[list] = None,
):
    coll = compat.assign_bone_to_collection(arm_data, pose_bone, collection_name, palette)
    if coll is not None:
        coll.is_visible = True
        if owned_collections is not None and collection_name not in owned_collections:
            owned_collections.append(collection_name)
    return coll


def _bind_face_sliders_pose(
    board,
    target_mesh,
    entries: Sequence[tuple],
    cap_wgt,
    travel: float,
    collection_prefix: str = "",
    owned_collections: Optional[list] = None,
) -> tuple[dict, list]:
    arm_data = board.data
    pose_bones = board.pose.bones
    fader_map = {}
    driver_bindings = []

    for placement, fader_name in entries:
        fader_pb = pose_bones[fader_name]
        palette = _palette_for(placement.row, placement.side)
        _configure_fader_pose_bone(fader_pb, cap_wgt, travel)
        _assign_visible_collection(
            arm_data, fader_pb, f"{collection_prefix}{placement.row}", palette, owned_collections
        )
        fader_map[fader_name] = {
            "shape_key": placement.shape_key_name,
            "row": placement.row,
            "side": placement.side,
            "palette": palette,
        }
        compat.bind_fader_driver(
            target_mesh,
            placement.shape_key_name,
            board,
            fader_name,
            travel,
            transform_type="LOC_Y",
            direction=1.0,
        )
        driver_bindings.append({
            "bone": fader_name,
            "shape_key": placement.shape_key_name,
            "row": placement.row,
            "side": placement.side,
            "axis": "LOC_Y",
            "travel": float(travel),
            "direction": 1.0,
        })

    return fader_map, driver_bindings


def _bind_mouth_joystick_pose(
    board,
    target_mesh,
    primary_vowels: dict,
    box_size: float,
    bar_wgt,
    joy_wgt,
    collection_name: str,
    bone_a_name: str = "Fader_Vowel_A",
    bone_joy_name: str = "Fader_Vowel_UIEO",
    owned_collections: Optional[list] = None,
) -> tuple[dict, list]:
    arm_data = board.data
    pose_bones = board.pose.bones
    half = box_size * 0.5
    fader_map = {}
    driver_bindings = []

    if "A" in primary_vowels and bone_a_name:
        slot_a = primary_vowels["A"]
        pb_a = pose_bones[bone_a_name]
        _configure_constrained_pose_bone(
            pb_a, bar_wgt, (False, True, True), (0.0, 0.0, 0.0), (box_size, 0.0, 0.0)
        )
        _assign_visible_collection(arm_data, pb_a, collection_name, "THEME03", owned_collections)
        compat.bind_fader_driver(
            target_mesh,
            slot_a.shape_key_name,
            board,
            bone_a_name,
            box_size,
            transform_type="LOC_X",
            direction=1.0,
        )
        fader_map[bone_a_name] = {
            "shape_key": slot_a.shape_key_name,
            "row": "Vowels",
            "side": slot_a.side,
            "palette": "THEME03",
        }
        driver_bindings.append({
            "bone": bone_a_name,
            "shape_key": slot_a.shape_key_name,
            "row": "Vowels",
            "side": slot_a.side,
            "axis": "LOC_X",
            "travel": float(box_size),
            "direction": 1.0,
        })

    if bone_joy_name and any(key in primary_vowels for key in ("I", "U", "E", "O")):
        pb_joy = pose_bones[bone_joy_name]
        _configure_constrained_pose_bone(
            pb_joy, joy_wgt, (False, False, True), (-half, -half, 0.0), (half, half, 0.0)
        )
        _assign_visible_collection(arm_data, pb_joy, collection_name, "THEME03", owned_collections)
        first_uieo_slot = None
        for vowel in ("I", "U", "O", "E"):
            slot = primary_vowels.get(vowel)
            if slot is None:
                continue
            if first_uieo_slot is None:
                first_uieo_slot = slot
            axis, direction = _MOUTH_JOYSTICK_AXES[vowel]
            compat.bind_fader_driver(
                target_mesh,
                slot.shape_key_name,
                board,
                bone_joy_name,
                half,
                transform_type=axis,
                direction=direction,
            )
            driver_bindings.append({
                "bone": bone_joy_name,
                "shape_key": slot.shape_key_name,
                "row": "Vowels",
                "side": slot.side,
                "axis": axis,
                "travel": float(half),
                "direction": float(direction),
            })
        if first_uieo_slot is not None:
            fader_map[bone_joy_name] = {
                "shape_key": first_uieo_slot.shape_key_name,
                "row": "Vowels",
                "side": first_uieo_slot.side,
                "palette": "THEME03",
            }

    return fader_map, driver_bindings


def _mouth_label_specs(primary_vowels: dict, box_size: float, bar_y: float, scale: float) -> list:
    half = box_size * 0.5
    font_size = 0.018 * scale
    specs = []
    if "A" in primary_vowels:
        specs.append(TextLabelSpec("a", -0.014 * scale, bar_y - 0.005 * scale, font_size, "RIGHT"))
    if "O" in primary_vowels:
        specs.append(TextLabelSpec("o", half, box_size - 0.019 * scale, font_size, "CENTER"))
    if "E" in primary_vowels:
        specs.append(TextLabelSpec("e", half, 0.007 * scale, font_size, "CENTER"))
    if "U" in primary_vowels:
        specs.append(TextLabelSpec("u", 0.014 * scale, half - 0.006 * scale, font_size, "CENTER"))
    if "I" in primary_vowels:
        specs.append(TextLabelSpec("i", box_size - 0.014 * scale, half - 0.006 * scale, font_size, "CENTER"))
    return specs


def _populate_board(
    context,
    board,
    target_mesh,
    layout,
    board_token: str,
    scale: float,
    widget_coll,
    widgets,
    char_name: Optional[str] = None,
    build_options: Optional[dict] = None,
) -> None:
    arm_data = board.data
    frame_wgt, cap_wgt = widgets
    travel = layout.track_height
    root_length = 0.05 * scale
    fader_length = 0.012 * scale

    used_names = {BOARD_ROOT_NAME}
    entries = []
    with _edit_armature_context(context, board) as edit_bones:
        root = edit_bones.new(BOARD_ROOT_NAME)
        root.head = (0.0, 0.0, 0.0)
        root.tail = (0.0, 0.0, root_length)
        root.roll = 0.0
        root.use_deform = False

        for placement in layout.faders:
            core = f"{placement.row}_{_sanitize_token(placement.label)}"
            if placement.side and not core.endswith(f"_{placement.side}"):
                core = f"{core}_{placement.side}"
            fader_name = _unique_name(f"{FADER_PREFIX}{core}", used_names)

            fader = edit_bones.new(fader_name)
            fader.head = (placement.x, 0.0, placement.z)
            fader.tail = (placement.x + fader_length, 0.0, placement.z)
            fader.align_roll(Vector((0.0, -1.0, 0.0)))
            fader.parent = root
            fader.use_connect = False
            fader.use_deform = False

            entries.append((placement, fader_name))

    root_pb = board.pose.bones[BOARD_ROOT_NAME]
    root_pb.custom_shape = frame_wgt
    root_pb.use_custom_shape_bone_size = False
    _assign_visible_collection(
        arm_data, root_pb, BOARD_COLLECTION, compat.ROW_COLOR_PALETTES["Board"]
    )

    fader_map, driver_bindings = _bind_face_sliders_pose(
        board, target_mesh, entries, cap_wgt, travel
    )

    labels_obj = widget_factory.build_merged_board_labels_object(
        context,
        board_token,
        layout.labels,
        board,
        board_root_bone_name=BOARD_ROOT_NAME,
        board_root_length=root_length,
        target_collection=context.scene.collection,
        label_color=(1.0, 1.0, 1.0, 1.0),
        material_name=widget_factory.LABEL_MAT_FACE,
        resolution_u=3,
    )

    vowel_keys = _collect_vowel_keys(
        [(placement.row, placement.shape_key_name) for placement in layout.faders]
    )
    owned_bones = [BOARD_ROOT_NAME] + [name for _, name in entries]
    board["morphrig_embedded"] = False
    board["morphrig_target_mesh"] = target_mesh.name
    board["morphrig_vowel_keys"] = json.dumps(vowel_keys, ensure_ascii=False)
    board["morphrig_fader_map"] = json.dumps(fader_map, ensure_ascii=False)
    board["morphrig_driver_bindings"] = json.dumps(driver_bindings, ensure_ascii=False)
    board["morphrig_owned_bones"] = json.dumps(owned_bones, ensure_ascii=False)
    board["morphrig_track_height"] = float(travel)
    board["morphrig_char_name"] = char_name if char_name is not None else board_token
    board["morphrig_widget_collection"] = widget_coll.name
    board["morphrig_labels_objects"] = json.dumps([labels_obj.name], ensure_ascii=False)
    board["morphrig_labels_object"] = labels_obj.name
    board["morphrig_board_scale"] = scale
    board["morphrig_kuchisync_passthrough"] = False
    board["morphrig_build_options"] = json.dumps(build_options or {}, ensure_ascii=False)


def _discard_partial_board(context, board, widgets) -> None:
    remove_facial_board(context, board)
    for obj in widgets:
        if _is_alive(obj):
            _remove_object_with_mesh(obj)


def _create_single_board(
    context,
    target_mesh,
    layout: BoardLayout,
    board_token: str,
    char_name: str,
    role: str,
    location: Vector,
    scale: float,
    widget_coll,
    build_options: Optional[dict] = None,
) -> bpy.types.Object:
    track_rects = [(p.x, p.z, layout.track_height, 0.0048 * scale) for p in layout.faders]
    frame_wgt = widget_factory.create_board_frame_widget(
        f"WGT_Board_Frame_{board_token}",
        0.0,
        0.0,
        layout.width,
        layout.height,
        widget_coll,
        track_rects=track_rects,
    )
    cap_wgt = widget_factory.create_slider_cap_widget(f"WGT_Slider_Cap_{board_token}", scale, widget_coll)
    board = _create_board_object(context, board_token, target_mesh, char_name, role, location, widget_coll)
    widgets = (frame_wgt, cap_wgt)
    try:
        _populate_board(
            context,
            board,
            target_mesh,
            layout,
            board_token,
            scale,
            widget_coll,
            widgets,
            char_name=char_name,
            build_options=build_options,
        )
    except Exception:
        _discard_partial_board(context, board, widgets)
        raise
    return board


def _extract_primary_vowels(slots: Sequence[ControlSlot]) -> tuple[dict, list]:
    chosen = {}
    for slot in slots:
        if slot.row != "Vowels":
            continue
        parts = slot.display_label.strip().split()
        vowel = parts[0].upper() if parts else ""
        if vowel not in _PRIMARY_VOWELS:
            continue
        prev = chosen.get(vowel)
        if prev is None or slot.priority < prev.priority:
            chosen[vowel] = slot

    chosen_ids = {id(slot) for slot in chosen.values()}
    remaining = [slot for slot in slots if id(slot) not in chosen_ids]
    return chosen, remaining


def _populate_mouth_joystick_board(
    context,
    board,
    target_mesh,
    primary_vowels: dict,
    mouth_token: str,
    char_name: str,
    scale: float,
    widget_coll,
    widgets,
    box_size: float,
    bar_gap: float,
    build_options: Optional[dict] = None,
) -> None:
    arm_data = board.data
    frame_wgt, bar_wgt, joy_wgt = widgets
    half = box_size * 0.5
    bar_y = box_size + bar_gap
    root_length = 0.05 * scale
    bone_length = 0.018 * scale
    has_a = "A" in primary_vowels
    has_uieo = any(key in primary_vowels for key in ("I", "U", "E", "O"))

    with _edit_armature_context(context, board) as edit_bones:
        root = edit_bones.new(BOARD_ROOT_NAME)
        root.head = (0.0, 0.0, 0.0)
        root.tail = (0.0, 0.0, root_length)
        root.roll = 0.0
        root.use_deform = False

        if has_a:
            bone_a = edit_bones.new("Fader_Vowel_A")
            bone_a.head = (0.0, 0.0, bar_y)
            bone_a.tail = (0.0, 0.0, bar_y + bone_length)
            bone_a.roll = 0.0
            bone_a.parent = root
            bone_a.use_connect = False
            bone_a.use_deform = False

        if has_uieo:
            bone_joy = edit_bones.new("Fader_Vowel_UIEO")
            bone_joy.head = (half, 0.0, half)
            bone_joy.tail = (half, 0.0, half + bone_length)
            bone_joy.roll = 0.0
            bone_joy.parent = root
            bone_joy.use_connect = False
            bone_joy.use_deform = False

    root_pb = board.pose.bones[BOARD_ROOT_NAME]
    root_pb.custom_shape = frame_wgt
    root_pb.use_custom_shape_bone_size = False
    _assign_visible_collection(
        arm_data, root_pb, BOARD_COLLECTION, compat.ROW_COLOR_PALETTES["Board"]
    )

    fader_map, driver_bindings = _bind_mouth_joystick_pose(
        board, target_mesh, primary_vowels, box_size, bar_wgt, joy_wgt, "Vowels"
    )
    label_specs = _mouth_label_specs(primary_vowels, box_size, bar_y, scale)
    labels_obj = widget_factory.build_merged_board_labels_object(
        context,
        mouth_token,
        label_specs,
        board,
        board_root_bone_name=BOARD_ROOT_NAME,
        board_root_length=root_length,
        target_collection=context.scene.collection,
        label_color=(1.0, 0.62, 0.18, 1.0),
        material_name=widget_factory.LABEL_MAT_MOUTH,
        resolution_u=4,
    )

    vowel_keys = _collect_vowel_keys(
        [("Vowels", binding["shape_key"]) for binding in driver_bindings]
    )
    owned_bones = [BOARD_ROOT_NAME] + list(fader_map.keys())
    board["morphrig_embedded"] = False
    board["morphrig_target_mesh"] = target_mesh.name
    board["morphrig_vowel_keys"] = json.dumps(vowel_keys, ensure_ascii=False)
    board["morphrig_fader_map"] = json.dumps(fader_map, ensure_ascii=False)
    board["morphrig_driver_bindings"] = json.dumps(driver_bindings, ensure_ascii=False)
    board["morphrig_owned_bones"] = json.dumps(owned_bones, ensure_ascii=False)
    board["morphrig_track_height"] = float(box_size)
    board["morphrig_mouth_box_size"] = float(box_size)
    board["morphrig_char_name"] = char_name
    board["morphrig_widget_collection"] = widget_coll.name
    board["morphrig_labels_objects"] = json.dumps([labels_obj.name], ensure_ascii=False)
    board["morphrig_labels_object"] = labels_obj.name
    board["morphrig_board_scale"] = scale
    board["morphrig_kuchisync_passthrough"] = False
    board["morphrig_build_options"] = json.dumps(build_options or {}, ensure_ascii=False)


def _create_mouth_joystick_board(
    context,
    target_mesh,
    primary_vowels: dict,
    char_name: str,
    bounds_max: Vector,
    mid_y: float,
    scale: float,
    widget_coll,
    build_options: Optional[dict] = None,
) -> bpy.types.Object:
    mouth_token = f"{char_name}_Mouth"
    box_size = 0.13 * scale
    bar_gap = 0.020 * scale
    bar_y = box_size + bar_gap
    total_height = bar_y + 0.014 * scale
    location = Vector((bounds_max.x + 0.09, mid_y, bounds_max.z - total_height))

    frame_wgt = widget_factory.create_mouth_frame_widget(
        f"WGT_Mouth_Frame_{mouth_token}", box_size, bar_gap, widget_coll
    )
    bar_wgt = (
        widget_factory.create_mouth_bar_cap_widget(f"WGT_Mouth_Bar_{mouth_token}", scale, widget_coll)
        if "A" in primary_vowels
        else None
    )
    joy_wgt = (
        widget_factory.create_mouth_joystick_widget(f"WGT_Mouth_Joy_{mouth_token}", scale, widget_coll)
        if any(key in primary_vowels for key in ("I", "U", "E", "O"))
        else None
    )
    board = _create_board_object(context, mouth_token, target_mesh, char_name, "mouth", location, widget_coll)
    widgets = tuple(obj for obj in (frame_wgt, bar_wgt, joy_wgt) if obj is not None)
    try:
        _populate_mouth_joystick_board(
            context,
            board,
            target_mesh,
            primary_vowels,
            mouth_token,
            char_name,
            scale,
            widget_coll,
            (frame_wgt, bar_wgt, joy_wgt),
            box_size,
            bar_gap,
            build_options=build_options,
        )
    except Exception:
        _discard_partial_board(context, board, widgets)
        raise
    return board


def _build_embedded_mmr_rig(
    context,
    target_mesh,
    embed_arm,
    head_bone_name: str,
    grouped: dict,
    face_grouped: dict,
    primary_vowels: dict,
    char_name: str,
    widget_coll,
    face_scale: float,
    mouth_scale: float,
    height_val: float,
    follow_head_bone: bool,
    separate_mouth_board: bool,
    bounds_min: Vector,
    bounds_max: Vector,
    mid_y: float,
    build_options: dict,
) -> bpy.types.Object:
    arm_world = embed_arm.matrix_world.copy()
    inv_arm = arm_world.inverted_safe()
    s = arm_world.to_scale()
    arm_scale = max(sum(abs(v) for v in s) / 3.0, 1e-6)
    rot_inv = arm_world.to_quaternion().to_matrix().inverted()
    axis_x = (rot_inv @ Vector((1.0, 0.0, 0.0))).normalized()
    axis_z = (rot_inv @ Vector((0.0, 0.0, 1.0))).normalized()
    axis_front = (rot_inv @ Vector((0.0, -1.0, 0.0))).normalized()

    local_face_scale = face_scale / arm_scale
    local_mouth_scale = mouth_scale / arm_scale
    has_mouth = bool(separate_mouth_board and primary_vowels)
    active_face_grouped = face_grouped if has_mouth else grouped
    has_face = bool(active_face_grouped)

    face_layout = None
    face_origin_local = None
    if has_face:
        face_layout = calculate_board_layout(
            active_face_grouped, scale=local_face_scale, track_height=height_val
        )
        if has_mouth:
            face_world_origin = Vector((
                bounds_min.x - 0.10 - face_layout.width * arm_scale,
                mid_y,
                bounds_max.z - face_layout.height * arm_scale,
            ))
        else:
            face_world_origin = Vector((
                bounds_max.x + 0.10,
                mid_y,
                bounds_max.z - face_layout.height * arm_scale,
            ))
        face_origin_local = inv_arm @ face_world_origin

    local_box_size = 0.0
    local_half = 0.0
    local_bar_gap = 0.0
    local_bar_y = 0.0
    mouth_origin_local = None
    if has_mouth:
        local_box_size = 0.13 * local_mouth_scale
        local_half = local_box_size * 0.5
        local_bar_gap = 0.020 * local_mouth_scale
        local_bar_y = local_box_size + local_bar_gap
        mouth_total_height_world = (local_bar_y + 0.014 * local_mouth_scale) * arm_scale
        mouth_world_origin = Vector((
            bounds_max.x + 0.09,
            mid_y,
            bounds_max.z - mouth_total_height_world,
        ))
        mouth_origin_local = inv_arm @ mouth_world_origin

    owned_bones = []
    root_bones = []
    owned_collections = []
    label_obj_names = []
    created_widgets = []

    # Mark embedded ownership before mutating so rollback never deletes the host armature.
    embed_arm["morphrig_embedded"] = True
    embed_arm["morphrig_board_role"] = "embedded"
    embed_arm["morphrig_target_mesh"] = target_mesh.name
    embed_arm["morphrig_char_name"] = char_name
    embed_arm["morphrig_widget_collection"] = widget_coll.name
    embed_arm["morphrig_owned_bones"] = json.dumps(owned_bones, ensure_ascii=False)
    embed_arm["morphrig_root_bones"] = json.dumps(root_bones, ensure_ascii=False)
    embed_arm["morphrig_owned_collections"] = json.dumps(owned_collections, ensure_ascii=False)
    embed_arm["morphrig_labels_objects"] = json.dumps(label_obj_names, ensure_ascii=False)

    face_root_name = ""
    mouth_root_name = ""
    bone_a_name = ""
    bone_joy_name = ""
    face_entries = []

    try:
        arm_data = embed_arm.data
        try:
            with _edit_armature_context(context, embed_arm) as edit_bones:
                used_names = set(edit_bones.keys())
                head_eb = edit_bones.get(head_bone_name) if (follow_head_bone and head_bone_name) else None

                if has_face:
                    face_root_name = _unique_name(EMBEDDED_FACE_ROOT_NAME, used_names)
                    face_root = edit_bones.new(face_root_name)
                    face_root.head = face_origin_local
                    face_root.tail = face_origin_local + (0.05 * local_face_scale) * axis_z
                    face_root.align_roll(axis_front)
                    face_root.use_deform = False
                    if head_eb is not None:
                        face_root.parent = head_eb
                        face_root.use_connect = False
                    root_bones.append(face_root_name)
                    owned_bones.append(face_root_name)

                    fader_len = 0.012 * local_face_scale
                    for placement in face_layout.faders:
                        core = f"{placement.row}_{_sanitize_token(placement.label)}"
                        if placement.side and not core.endswith(f"_{placement.side}"):
                            core = f"{core}_{placement.side}"
                        fader_name = _unique_name(f"{FADER_PREFIX}{core}", used_names)
                        fader = edit_bones.new(fader_name)
                        fader.head = face_origin_local + placement.x * axis_x + placement.z * axis_z
                        fader.tail = fader.head + fader_len * axis_x
                        fader.align_roll(axis_front)
                        fader.parent = face_root
                        fader.use_connect = False
                        fader.use_deform = False
                        face_entries.append((placement, fader_name))
                        owned_bones.append(fader_name)

                if has_mouth:
                    mouth_root_name = _unique_name(EMBEDDED_MOUTH_ROOT_NAME, used_names)
                    mouth_root = edit_bones.new(mouth_root_name)
                    mouth_root.head = mouth_origin_local
                    mouth_root.tail = mouth_origin_local + (0.05 * local_mouth_scale) * axis_z
                    mouth_root.align_roll(axis_front)
                    mouth_root.use_deform = False
                    if head_eb is not None:
                        mouth_root.parent = head_eb
                        mouth_root.use_connect = False
                    root_bones.append(mouth_root_name)
                    owned_bones.append(mouth_root_name)

                    joy_len = 0.018 * local_mouth_scale
                    if "A" in primary_vowels:
                        bone_a_name = _unique_name("Fader_Vowel_A", used_names)
                        bone_a = edit_bones.new(bone_a_name)
                        bone_a.head = mouth_origin_local + local_bar_y * axis_z
                        bone_a.tail = bone_a.head + joy_len * axis_z
                        bone_a.align_roll(axis_front)
                        bone_a.parent = mouth_root
                        bone_a.use_connect = False
                        bone_a.use_deform = False
                        owned_bones.append(bone_a_name)

                    if any(key in primary_vowels for key in ("I", "U", "E", "O")):
                        bone_joy_name = _unique_name("Fader_Vowel_UIEO", used_names)
                        bone_joy = edit_bones.new(bone_joy_name)
                        bone_joy.head = mouth_origin_local + local_half * axis_x + local_half * axis_z
                        bone_joy.tail = bone_joy.head + joy_len * axis_z
                        bone_joy.align_roll(axis_front)
                        bone_joy.parent = mouth_root
                        bone_joy.use_connect = False
                        bone_joy.use_deform = False
                        owned_bones.append(bone_joy_name)
        finally:
            embed_arm["morphrig_owned_bones"] = json.dumps(owned_bones, ensure_ascii=False)
            embed_arm["morphrig_root_bones"] = json.dumps(root_bones, ensure_ascii=False)

        board_coll_name = f"{EMBEDDED_COLLECTION_PREFIX}{BOARD_COLLECTION}"
        fader_map = {}
        driver_bindings = []
        vowel_entries = []

        if has_face:
            track_rects = [
                (p.x, p.z, face_layout.track_height, 0.0048 * local_face_scale)
                for p in face_layout.faders
            ]
            face_frame_wgt = widget_factory.create_board_frame_widget(
                f"WGT_Board_Frame_{char_name}",
                0.0,
                0.0,
                face_layout.width,
                face_layout.height,
                widget_coll,
                track_rects=track_rects,
            )
            face_cap_wgt = widget_factory.create_slider_cap_widget(
                f"WGT_Slider_Cap_{char_name}", local_face_scale, widget_coll
            )
            created_widgets.extend([face_frame_wgt, face_cap_wgt])

            face_root_pb = embed_arm.pose.bones[face_root_name]
            face_root_pb.custom_shape = face_frame_wgt
            face_root_pb.use_custom_shape_bone_size = False
            _assign_visible_collection(
                arm_data,
                face_root_pb,
                board_coll_name,
                compat.ROW_COLOR_PALETTES["Board"],
                owned_collections,
            )

            face_fmap, face_bindings = _bind_face_sliders_pose(
                embed_arm,
                target_mesh,
                face_entries,
                face_cap_wgt,
                face_layout.track_height,
                collection_prefix=EMBEDDED_COLLECTION_PREFIX,
                owned_collections=owned_collections,
            )
            fader_map.update(face_fmap)
            driver_bindings.extend(face_bindings)
            vowel_entries.extend((p.row, p.shape_key_name) for p in face_layout.faders)

            face_labels = widget_factory.build_merged_board_labels_object(
                context,
                char_name,
                face_layout.labels,
                embed_arm,
                board_root_bone_name=face_root_name,
                board_root_length=0.05 * local_face_scale,
                target_collection=context.scene.collection,
                label_color=(1.0, 1.0, 1.0, 1.0),
                material_name=widget_factory.LABEL_MAT_FACE,
                resolution_u=3,
            )
            label_obj_names.append(face_labels.name)

        if has_mouth:
            mouth_token = f"{char_name}_Mouth"
            mouth_frame_wgt = widget_factory.create_mouth_frame_widget(
                f"WGT_Mouth_Frame_{mouth_token}", local_box_size, local_bar_gap, widget_coll
            )
            created_widgets.append(mouth_frame_wgt)
            mouth_bar_wgt = None
            mouth_joy_wgt = None
            if bone_a_name:
                mouth_bar_wgt = widget_factory.create_mouth_bar_cap_widget(
                    f"WGT_Mouth_Bar_{mouth_token}", local_mouth_scale, widget_coll
                )
                created_widgets.append(mouth_bar_wgt)
            if bone_joy_name:
                mouth_joy_wgt = widget_factory.create_mouth_joystick_widget(
                    f"WGT_Mouth_Joy_{mouth_token}", local_mouth_scale, widget_coll
                )
                created_widgets.append(mouth_joy_wgt)

            mouth_root_pb = embed_arm.pose.bones[mouth_root_name]
            mouth_root_pb.custom_shape = mouth_frame_wgt
            mouth_root_pb.use_custom_shape_bone_size = False
            _assign_visible_collection(
                arm_data,
                mouth_root_pb,
                board_coll_name,
                compat.ROW_COLOR_PALETTES["Board"],
                owned_collections,
            )

            mouth_fmap, mouth_bindings = _bind_mouth_joystick_pose(
                embed_arm,
                target_mesh,
                primary_vowels,
                local_box_size,
                mouth_bar_wgt,
                mouth_joy_wgt,
                f"{EMBEDDED_COLLECTION_PREFIX}Vowels",
                bone_a_name=bone_a_name,
                bone_joy_name=bone_joy_name,
                owned_collections=owned_collections,
            )
            fader_map.update(mouth_fmap)
            driver_bindings.extend(mouth_bindings)
            vowel_entries.extend(("Vowels", b["shape_key"]) for b in mouth_bindings)

            mouth_specs = _mouth_label_specs(
                primary_vowels, local_box_size, local_bar_y, local_mouth_scale
            )
            mouth_labels = widget_factory.build_merged_board_labels_object(
                context,
                mouth_token,
                mouth_specs,
                embed_arm,
                board_root_bone_name=mouth_root_name,
                board_root_length=0.05 * local_mouth_scale,
                target_collection=context.scene.collection,
                label_color=(1.0, 0.62, 0.18, 1.0),
                material_name=widget_factory.LABEL_MAT_MOUTH,
                resolution_u=4,
            )
            label_obj_names.append(mouth_labels.name)

        vowel_keys = _collect_vowel_keys(vowel_entries)
        embed_arm["morphrig_owned_collections"] = json.dumps(owned_collections, ensure_ascii=False)
        embed_arm["morphrig_labels_objects"] = json.dumps(label_obj_names, ensure_ascii=False)
        embed_arm["morphrig_labels_object"] = label_obj_names[0] if label_obj_names else ""
        embed_arm["morphrig_fader_map"] = json.dumps(fader_map, ensure_ascii=False)
        embed_arm["morphrig_driver_bindings"] = json.dumps(driver_bindings, ensure_ascii=False)
        embed_arm["morphrig_vowel_keys"] = json.dumps(vowel_keys, ensure_ascii=False)
        embed_arm["morphrig_track_height"] = float(
            face_layout.track_height if face_layout is not None else local_box_size
        )
        embed_arm["morphrig_mouth_box_size"] = float(local_box_size)
        embed_arm["morphrig_board_scale"] = float(face_scale if has_face else mouth_scale)
        embed_arm["morphrig_kuchisync_passthrough"] = False
        embed_arm["morphrig_build_options"] = json.dumps(build_options, ensure_ascii=False)
    except Exception:
        embed_arm["morphrig_owned_collections"] = json.dumps(owned_collections, ensure_ascii=False)
        embed_arm["morphrig_labels_objects"] = json.dumps(label_obj_names, ensure_ascii=False)
        remove_facial_board(context, embed_arm)
        for obj in created_widgets:
            if _is_alive(obj):
                _remove_object_with_mesh(obj)
        raise

    return embed_arm


def build_facial_board(
    context,
    target_mesh,
    slots_override=None,
    follow_head_bone: bool = True,
    include_emotes: bool = True,
    include_unmapped: bool = False,
    board_scale: float = 1.0,
    track_height: float = 0.12,
    separate_mouth_board: bool = True,
    merge_into_mmr_rig: bool = True,
) -> bpy.types.Object:
    if target_mesh is None or target_mesh.type != "MESH":
        raise ValueError("Target must be a mesh object.")
    if target_mesh.data.shape_keys is None:
        raise ValueError(f"'{target_mesh.name}' has no shape keys.")

    mmr_bridge.install_mmr_rig_poll_guard()
    view_layer = getattr(context, "view_layer", None)
    prev_active = view_layer.objects.active if view_layer is not None else None
    prev_mode = prev_active.mode if prev_active is not None else "OBJECT"

    _ensure_object_mode(context)
    for board in find_all_boards():
        if board.get("morphrig_target_mesh") == target_mesh.name:
            remove_facial_board(context, board)

    if slots_override is not None:
        slots = _coerce_slots(slots_override, target_mesh)
    else:
        slots = semantic_mapper.scan_mesh_shape_keys(
            target_mesh, include_emotes=include_emotes, include_unmapped=include_unmapped
        )
    grouped = semantic_mapper.group_control_slots(
        slots, include_emotes=include_emotes, include_unmapped=include_unmapped
    )
    if not grouped:
        raise ValueError(f"No mappable shape keys found on '{target_mesh.name}'.")

    scale = float(board_scale)
    face_scale = scale * FACE_RIG_SCALE
    mouth_scale = scale * MOUTH_RIG_SCALE
    height_val = float(track_height)
    char_name = _truncate_bytes(_sanitize_token(target_mesh.name), _CHAR_NAME_BYTES)
    bounds_min, bounds_max = _world_bounds(context, target_mesh)
    mid_y = (bounds_min.y + bounds_max.y) / 2.0
    widget_coll = widget_factory.ensure_widget_collection(context, char_name)

    primary_vowels = {}
    face_grouped = grouped
    if separate_mouth_board:
        primary_vowels, remaining_slots = _extract_primary_vowels(slots)
        if primary_vowels:
            face_grouped = semantic_mapper.group_control_slots(
                remaining_slots, include_emotes=include_emotes, include_unmapped=include_unmapped
            )

    build_options = {
        "follow_head_bone": bool(follow_head_bone),
        "include_emotes": bool(include_emotes),
        "include_unmapped": bool(include_unmapped),
        "board_scale": scale,
        "track_height": height_val,
        "separate_mouth_board": bool(separate_mouth_board),
    }

    mmr_info = mmr_bridge.detect_mmr_rig_info(target_mesh)
    embed_arm = None
    if (
        merge_into_mmr_rig
        and mmr_info.is_mmr_rig
        and mmr_bridge.is_final_mmr_controller_rig(mmr_info.armature)
    ):
        candidate = mmr_info.armature
        bound_mesh = candidate.get("morphrig_target_mesh")
        if bound_mesh is None or bound_mesh == target_mesh.name:
            embed_arm = candidate

    if embed_arm is not None:
        result = _build_embedded_mmr_rig(
            context,
            target_mesh,
            embed_arm,
            mmr_info.head_bone_name,
            grouped,
            face_grouped,
            primary_vowels,
            char_name,
            widget_coll,
            face_scale,
            mouth_scale,
            height_val,
            follow_head_bone,
            separate_mouth_board,
            bounds_min,
            bounds_max,
            mid_y,
            build_options,
        )
        if prev_active is embed_arm and prev_mode == "POSE":
            _select_board_only(context, embed_arm)
            _set_object_mode(context, embed_arm, "POSE")
        context.view_layer.update()
        return result

    created_boards = []
    if separate_mouth_board and primary_vowels:
        if face_grouped:
            face_layout = calculate_board_layout(face_grouped, scale=face_scale, track_height=height_val)
            face_location = Vector((bounds_min.x - 0.10 - face_layout.width, mid_y, bounds_max.z - face_layout.height))
            face_board = _create_single_board(
                context,
                target_mesh,
                face_layout,
                char_name,
                char_name,
                "face",
                face_location,
                face_scale,
                widget_coll,
                build_options=build_options,
            )
            try:
                mouth_board = _create_mouth_joystick_board(
                    context,
                    target_mesh,
                    primary_vowels,
                    char_name,
                    bounds_max,
                    mid_y,
                    mouth_scale,
                    widget_coll,
                    build_options=build_options,
                )
            except Exception:
                remove_facial_board(context, face_board)
                raise
            face_board["morphrig_companion_board"] = mouth_board.name
            mouth_board["morphrig_companion_board"] = face_board.name
            created_boards = [face_board, mouth_board]
        else:
            mouth_board = _create_mouth_joystick_board(
                context,
                target_mesh,
                primary_vowels,
                char_name,
                bounds_max,
                mid_y,
                mouth_scale,
                widget_coll,
                build_options=build_options,
            )
            created_boards = [mouth_board]
    else:
        layout = calculate_board_layout(grouped, scale=face_scale, track_height=height_val)
        has_face = any(row not in MOUTH_ROWS and groups for row, groups in grouped.items())
        has_mouth = any(row in MOUTH_ROWS and groups for row, groups in grouped.items())
        role = "combined" if (has_face and has_mouth) else ("face" if has_face else "mouth")
        board_location = Vector((bounds_max.x + 0.10, mid_y, bounds_max.z - layout.height))
        board = _create_single_board(
            context,
            target_mesh,
            layout,
            char_name,
            char_name,
            role,
            board_location,
            face_scale,
            widget_coll,
            build_options=build_options,
        )
        created_boards = [board]

    if follow_head_bone:
        mmr_arm = mmr_info.armature
        head_bone_name = mmr_info.head_bone_name
        if mmr_arm is not None and head_bone_name and mmr_arm.pose.bones.get(head_bone_name) is not None:
            for board in created_boards:
                if mmr_arm is not board:
                    _parent_to_bone_keep_world(context, board, mmr_arm, head_bone_name)

    context.view_layer.update()
    return created_boards[0]


def merge_standalone_boards_into_mmr(context, target_mesh=None) -> list:
    """Embed existing standalone facial boards into their detected final MMR rigs."""
    standalone = [
        board
        for board in find_all_boards()
        if not bool(board.get("morphrig_embedded", False))
        and (target_mesh is None or board.get("morphrig_target_mesh") == target_mesh.name)
    ]
    if not standalone:
        return []

    grouped_by_mesh = {}
    for board in sorted(standalone, key=_board_sort_key):
        mesh_name = board.get("morphrig_target_mesh", "")
        if mesh_name:
            grouped_by_mesh.setdefault(mesh_name, []).append(board)

    merged = []
    for mesh_name, boards in grouped_by_mesh.items():
        mesh = bpy.data.objects.get(mesh_name)
        if mesh is None or mesh.type != "MESH" or mesh.data is None or mesh.data.shape_keys is None:
            continue
        mmr_info = mmr_bridge.detect_mmr_rig_info(mesh)
        if not (mmr_info.is_mmr_rig and mmr_bridge.is_final_mmr_controller_rig(mmr_info.armature)):
            continue
        primary = boards[0]
        build_opts = _load_json(primary, "morphrig_build_options", {})
        was_passthrough = any(bool(b.get("morphrig_kuchisync_passthrough", False)) for b in boards)
        embedded_arm = build_facial_board(
            context,
            mesh,
            follow_head_bone=bool(build_opts.get("follow_head_bone", True)),
            include_emotes=bool(build_opts.get("include_emotes", True)),
            include_unmapped=bool(build_opts.get("include_unmapped", False)),
            board_scale=float(build_opts.get("board_scale", 1.0)),
            track_height=float(build_opts.get("track_height", 0.12)),
            separate_mouth_board=bool(build_opts.get("separate_mouth_board", True)),
            merge_into_mmr_rig=True,
        )
        if was_passthrough:
            set_kuchisync_passthrough(embedded_arm, mesh, enabled=True)
        if embedded_arm not in merged:
            merged.append(embedded_arm)
    return merged


def _iter_passthrough_bindings(board, vowel_keys: set, fader_map: dict, driver_bindings: list) -> list:
    if driver_bindings:
        return [
            entry
            for entry in driver_bindings
            if entry.get("row") == "Vowels" or entry.get("shape_key") in vowel_keys
        ]
    default_travel = float(board.get("morphrig_track_height", 0.12))
    return [
        {
            "bone": fader_name,
            "shape_key": info.get("shape_key", ""),
            "row": info.get("row", "Vowels"),
            "side": info.get("side", ""),
            "axis": "LOC_Y",
            "travel": default_travel,
            "direction": 1.0,
        }
        for fader_name, info in fader_map.items()
        if info.get("row") == "Vowels" or info.get("shape_key") in vowel_keys
    ]


def _release_board_vowel_drivers(
    board,
    target_mesh,
    vowel_keys: set,
    fader_map: dict,
    driver_bindings: list,
) -> int:
    shape_keys = getattr(getattr(target_mesh, "data", None), "shape_keys", None)
    key_blocks = shape_keys.key_blocks if shape_keys is not None else None
    release_keys = set(vowel_keys)
    updated = 0

    for entry in _iter_passthrough_bindings(board, vowel_keys, fader_map, driver_bindings):
        sk_name = entry.get("shape_key", "")
        bone_name = entry.get("bone", "")
        removed = False
        if sk_name:
            release_keys.add(sk_name)
            removed = compat.remove_shape_key_driver(target_mesh, sk_name)
        pose_bone = board.pose.bones.get(bone_name)
        if pose_bone is not None:
            compat.set_pose_bone_color(pose_bone, compat.ROW_COLOR_PALETTES["MUTED"])
        if pose_bone is not None or removed:
            updated += 1

    for sk_name in release_keys:
        if sk_name:
            compat.remove_shape_key_driver(target_mesh, sk_name)

    if shape_keys is not None and shape_keys.animation_data is not None and release_keys:
        anim = shape_keys.animation_data
        paths = set()
        for sk_name in release_keys:
            if not sk_name:
                continue
            if key_blocks is not None and key_blocks.get(sk_name) is not None:
                paths.add(key_blocks[sk_name].path_from_id("value"))
            paths.add(f'key_blocks["{sk_name}"].value')
            paths.add(f"key_blocks['{sk_name}'].value")
        residual = [fc for fc in anim.drivers if fc.data_path in paths]
        for fcurve in residual:
            anim.drivers.remove(fcurve)
        if not anim.drivers and anim.action is None and not anim.nla_tracks:
            shape_keys.animation_data_clear()

    return updated


def _rebind_board_vowel_drivers(
    board,
    target_mesh,
    vowel_keys: set,
    fader_map: dict,
    driver_bindings: list,
) -> int:
    shape_keys = getattr(getattr(target_mesh, "data", None), "shape_keys", None)
    key_blocks = shape_keys.key_blocks if shape_keys is not None else None
    default_travel = float(board.get("morphrig_track_height", 0.12))
    is_mouth_role = board.get("morphrig_board_role") == "mouth"
    updated = 0

    for entry in _iter_passthrough_bindings(board, vowel_keys, fader_map, driver_bindings):
        bone_name = entry.get("bone", "")
        sk_name = entry.get("shape_key", "")
        axis = entry.get("axis", "LOC_Y")
        travel = float(entry.get("travel", default_travel))
        direction = float(entry.get("direction", 1.0))
        pose_bone = board.pose.bones.get(bone_name)
        if pose_bone is None:
            continue
        if sk_name and key_blocks is not None and key_blocks.get(sk_name) is not None:
            compat.bind_fader_driver(
                target_mesh,
                sk_name,
                board,
                bone_name,
                travel,
                transform_type=axis,
                direction=direction,
            )
        palette = fader_map.get(bone_name, {}).get("palette")
        if not palette:
            is_mouth_bone = is_mouth_role or bone_name in ("Fader_Vowel_A", "Fader_Vowel_UIEO")
            palette = "THEME03" if is_mouth_bone else _palette_for(entry.get("row", "Vowels"), entry.get("side", ""))
        compat.set_pose_bone_color(pose_bone, palette)
        updated += 1

    return updated


def set_kuchisync_passthrough(board_armature, target_mesh=None, enabled: bool = True) -> int:
    """Detach or re-bind vowel shape key drivers across companion boards."""
    boards = _companion_boards(board_armature)
    if not boards:
        return 0

    release = bool(enabled)
    updated = 0
    for board in boards:
        board_mesh = _resolve_target_mesh(board, target_mesh)
        vowel_keys = set(_load_json(board, "morphrig_vowel_keys", []))
        fader_map = _load_json(board, "morphrig_fader_map", {})
        driver_bindings = _load_json(board, "morphrig_driver_bindings", [])
        if release:
            updated += _release_board_vowel_drivers(
                board, board_mesh, vowel_keys, fader_map, driver_bindings
            )
        else:
            updated += _rebind_board_vowel_drivers(
                board, board_mesh, vowel_keys, fader_map, driver_bindings
            )
        board["morphrig_kuchisync_passthrough"] = release

    ctx = getattr(bpy, "context", None)
    view_layer = getattr(ctx, "view_layer", None) if ctx is not None else None
    if view_layer is not None:
        view_layer.update()
    return updated


def reset_all_sliders(board_armature) -> int:
    boards = _companion_boards(board_armature)
    if not boards:
        return 0
    count = 0
    for board in boards:
        for name in _fader_names(board):
            board.pose.bones[name].location = (0.0, 0.0, 0.0)
            count += 1
    return count


def key_all_sliders(context, board_armature, frame=None) -> int:
    boards = _companion_boards(board_armature)
    if not boards:
        return 0
    if frame is None:
        frame = context.scene.frame_current
    count = 0
    for board in boards:
        for name in _fader_names(board):
            pose_bone = board.pose.bones[name]
            keyed = False
            for axis_idx in (0, 1):
                if not pose_bone.lock_location[axis_idx]:
                    if pose_bone.keyframe_insert(
                        data_path="location", index=axis_idx, frame=float(frame), group=name
                    ):
                        keyed = True
            if keyed:
                count += 1
    return count


def clear_board_keyframes(board_armature) -> int:
    boards = _companion_boards(board_armature)
    if not boards:
        return 0
    removed = 0
    for board in boards:
        removed += compat.clear_fader_keyframes(board, _fader_names(board))
    return removed


def _driver_targets_board(fcurve, board_armature, owned_bones=None) -> bool:
    for variable in fcurve.driver.variables:
        for target in variable.targets:
            if target.id == board_armature:
                if owned_bones is None or target.bone_target in owned_bones:
                    return True
    return False


def _remove_board_drivers(board_armature, owned_bones=None) -> int:
    removed = 0
    for key in bpy.data.shape_keys:
        anim = key.animation_data
        if anim is None:
            continue
        stale = [
            fc for fc in anim.drivers if _driver_targets_board(fc, board_armature, owned_bones=owned_bones)
        ]
        for fcurve in stale:
            anim.drivers.remove(fcurve)
            removed += 1
        if stale and not anim.drivers and anim.action is None and not anim.nla_tracks:
            key.animation_data_clear()
    return removed


def _remove_object_with_mesh(obj) -> None:
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if isinstance(data, bpy.types.Mesh) and data.users == 0:
        bpy.data.meshes.remove(data)


def remove_facial_board(context, board_armature) -> bool:
    """Delete standalone board or strip embedded MorphRig controls without touching host rig data."""
    if not _is_alive(board_armature) or board_armature.type != "ARMATURE":
        return False
    _ensure_object_mode(context)

    board_name = board_armature.name
    is_embedded = bool(board_armature.get("morphrig_embedded", False))
    target_mesh = _resolve_target_mesh(board_armature)

    owned_bones = set(_load_json(board_armature, "morphrig_owned_bones", []))
    root_bones = set(_load_json(board_armature, "morphrig_root_bones", []))
    fader_map = _load_json(board_armature, "morphrig_fader_map", {})
    driver_bindings = _load_json(board_armature, "morphrig_driver_bindings", [])
    owned_bones.update(root_bones)
    owned_bones.update(fader_map.keys())
    owned_bones.update(entry.get("bone", "") for entry in driver_bindings)
    owned_bones.discard("")

    removed_any = False
    if target_mesh is not None and getattr(target_mesh.data, "shape_keys", None) is not None:
        sk_names = {info.get("shape_key", "") for info in fader_map.values()}
        sk_names.update(entry.get("shape_key", "") for entry in driver_bindings)
        for sk_name in sk_names:
            if sk_name and compat.remove_shape_key_driver(target_mesh, sk_name):
                removed_any = True
    driver_bone_filter = owned_bones if is_embedded else None
    if _remove_board_drivers(board_armature, owned_bones=driver_bone_filter) > 0:
        removed_any = True
    if removed_any and target_mesh is not None and getattr(target_mesh.data, "shape_keys", None) is not None:
        anim = target_mesh.data.shape_keys.animation_data
        if anim is not None and not anim.drivers and anim.action is None and not anim.nla_tracks:
            target_mesh.data.shape_keys.animation_data_clear()

    label_names = set(_load_json(board_armature, "morphrig_labels_objects", []))
    labels_name = board_armature.get("morphrig_labels_object", "")
    if labels_name:
        label_names.add(labels_name)

    widget_coll = bpy.data.collections.get(board_armature.get("morphrig_widget_collection", ""))

    if is_embedded:
        compat.clear_fader_keyframes(board_armature, list(owned_bones))
        labels = [
            obj
            for obj in bpy.data.objects
            if obj.parent == board_armature
            and (
                obj.name in label_names
                or (
                    obj.name.startswith(widget_factory.LABELS_OBJECT_PREFIX)
                    and obj.parent_bone in root_bones
                )
            )
        ]
        for obj in labels:
            _remove_object_with_mesh(obj)

        widgets = {
            board_armature.pose.bones[name].custom_shape
            for name in owned_bones
            if name in board_armature.pose.bones and board_armature.pose.bones[name].custom_shape is not None
        }
        if owned_bones:
            with _edit_armature_context(context, board_armature) as edit_bones:
                for bone_name in owned_bones:
                    eb = edit_bones.get(bone_name)
                    if eb is not None:
                        edit_bones.remove(eb)

        owned_collections = _load_json(board_armature, "morphrig_owned_collections", [])
        bone_colls = getattr(board_armature.data, "collections", None)
        if bone_colls is not None:
            for coll_name in owned_collections:
                coll = bone_colls.get(coll_name)
                if coll is not None:
                    bone_colls.remove(coll)

        for key in [k for k in list(board_armature.keys()) if k.startswith("morphrig_")]:
            del board_armature[key]
    else:
        labels = [
            obj
            for obj in bpy.data.objects
            if obj.parent == board_armature
            and (obj.name in label_names or obj.name.startswith(widget_factory.LABELS_OBJECT_PREFIX))
        ]
        for obj in labels:
            _remove_object_with_mesh(obj)

        widgets = {pb.custom_shape for pb in board_armature.pose.bones if pb.custom_shape is not None}
        action = board_armature.animation_data.action if board_armature.animation_data else None
        arm_data = board_armature.data
        bpy.data.objects.remove(board_armature, do_unlink=True)
        if arm_data is not None and arm_data.users == 0:
            bpy.data.armatures.remove(arm_data)
        if action is not None and action.users == 0:
            bpy.data.actions.remove(action)

    remaining_boards = find_all_boards()
    for other in remaining_boards:
        if other.get("morphrig_companion_board") == board_name:
            del other["morphrig_companion_board"]

    other_widgets = {
        pb.custom_shape
        for other in remaining_boards
        for pb in other.pose.bones
        if pb.custom_shape is not None
    }
    for obj in widgets:
        if _is_alive(obj) and obj not in other_widgets:
            _remove_object_with_mesh(obj)

    if widget_coll is not None:
        shared = any(
            board.get("morphrig_widget_collection") == widget_coll.name for board in remaining_boards
        )
        if not shared:
            for obj in list(widget_coll.objects):
                _remove_object_with_mesh(obj)
        if not widget_coll.objects and not widget_coll.children:
            bpy.data.collections.remove(widget_coll)

    widget_factory.cleanup_unused_label_materials()
    return True
