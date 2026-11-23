# SPDX-License-Identifier: GPL-3.0-or-later
"""Facial board layout, armature construction, drivers and board maintenance."""

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
BOARD_COLLECTION = "Board"
TRACKS_COLLECTION = "Tracks"
FADER_PREFIX = "Fader_"
TRACK_PREFIX = "Track_"
LIMIT_CONSTRAINT_NAME = "MorphRig_Limit"

# Blender ID and bone names hold at most 63 UTF-8 bytes.
_MAX_NAME_BYTES = 63
_CHAR_NAME_BYTES = _MAX_NAME_BYTES - len(widget_factory.WIDGET_COLLECTION_PREFIX) - len("_Mouth")
MAX_COLS_PER_ROW = 9
MAX_ROWS_PER_COL = 14
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


def calculate_board_layout(
    grouped: Mapping[str, Sequence[PairedControlGroup]],
    scale: float = 1.0,
    track_height: float = 0.12,
    base_font: Optional[float] = None,
) -> BoardLayout:
    """Lay out rows into multi-column horizontal sliders (origin at bottom-left)."""
    max_rows_per_col = MAX_ROWS_PER_COL
    slot_size = base_font if base_font is not None else 0.020 * scale
    header_size = 1.25 * slot_size if base_font is not None else 0.025 * scale
    row_pitch = 0.032 * scale
    label_col_width = 0.175 * scale
    col_gap = 0.048 * scale
    margin = 0.035 * scale
    effective_track_height = track_height * scale
    col_width = label_col_width + effective_track_height

    columns = []
    cur_col = []
    for row in _ordered_rows(grouped):
        items = _flatten_category_items(grouped[row])
        if not items:
            continue
        header_text = _ROW_HEADERS.get(row, row.upper())
        if cur_col and len(cur_col) + 1 + len(items) > max_rows_per_col:
            columns.append(cur_col)
            cur_col = []
        cur_col.append(("header", header_text))
        for label_text, side, shape_key_name in items:
            if len(cur_col) >= max_rows_per_col:
                columns.append(cur_col)
                cur_col = []
            cur_col.append(("item", row, label_text, side, shape_key_name))
    if cur_col:
        columns.append(cur_col)

    max_col_rows = max((len(col) for col in columns), default=0)
    height = 2.0 * margin + (max_col_rows * row_pitch if max_col_rows else 0.0)
    num_cols = len(columns)
    width = (
        2.0 * margin + num_cols * col_width + max(0, num_cols - 1) * col_gap
        if num_cols
        else 0.3 * scale
    )

    layout = BoardLayout(
        width=width,
        height=height,
        track_height=effective_track_height,
        scale=scale,
    )
    for col_idx, col in enumerate(columns):
        col_x = margin + col_idx * (col_width + col_gap)
        for row_idx, entry in enumerate(col):
            row_center_z = height - margin - (row_idx + 0.5) * row_pitch
            if entry[0] == "header":
                layout.labels.append(
                    TextLabelSpec(entry[1], col_x, row_center_z - 0.35 * header_size, header_size, "LEFT")
                )
                continue
            _, row_name, label_text, side, shape_key_name = entry
            layout.labels.append(
                TextLabelSpec(label_text, col_x, row_center_z - 0.35 * slot_size, slot_size, "LEFT")
            )
            layout.faders.append(
                FaderPlacement(
                    row=row_name,
                    label=label_text,
                    side=side,
                    shape_key_name=shape_key_name,
                    x=col_x + label_col_width,
                    z=row_center_z,
                    is_horizontal=True,
                )
            )

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
    return [pb.name for pb in board_armature.pose.bones if pb.name.startswith(FADER_PREFIX)]


def _ensure_object_mode(context) -> None:
    view_layer = getattr(context, "view_layer", None)
    active = view_layer.objects.active if view_layer is not None else None
    if active is not None and active.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")


def find_all_boards() -> list:
    return [
        obj
        for obj in bpy.data.objects
        if obj.type == "ARMATURE" and obj.get("morphrig_target_mesh") is not None
    ]


def _board_sort_key(board) -> tuple:
    role = board.get("morphrig_board_role", "")
    if role in ("face", "combined"):
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
) -> None:
    arm_data = board.data
    frame_wgt, track_wgt, cap_wgt = widgets
    travel = layout.track_height
    root_length = 0.1 * scale
    fader_length = 0.02 * scale

    _select_board_only(context, board)
    used_names = {BOARD_ROOT_NAME}
    entries = []
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        edit_bones = arm_data.edit_bones
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
            track_name = _unique_name(f"{TRACK_PREFIX}{core}", used_names)

            track = edit_bones.new(track_name)
            track.head = (placement.x, 0.0, placement.z)
            track.tail = (placement.x + travel, 0.0, placement.z)
            track.align_roll(Vector((0.0, -1.0, 0.0)))
            track.parent = root
            track.use_connect = False
            track.use_deform = False
            track.hide_select = True

            fader = edit_bones.new(fader_name)
            fader.head = (placement.x, 0.0, placement.z)
            fader.tail = (placement.x + fader_length, 0.0, placement.z)
            fader.align_roll(Vector((0.0, -1.0, 0.0)))
            fader.parent = root
            fader.use_connect = False
            fader.use_deform = False

            entries.append((placement, fader_name, track_name))
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")

    pose_bones = board.pose.bones
    root_pb = pose_bones[BOARD_ROOT_NAME]
    root_pb.custom_shape = frame_wgt
    root_pb.use_custom_shape_bone_size = False
    compat.assign_bone_to_collection(
        arm_data, root_pb, BOARD_COLLECTION, compat.ROW_COLOR_PALETTES["Board"]
    )

    fader_map = {}
    driver_bindings = []
    for placement, fader_name, track_name in entries:
        track_pb = pose_bones[track_name]
        track_pb.custom_shape = track_wgt
        track_pb.use_custom_shape_bone_size = False
        track_pb.lock_location = (True, True, True)
        track_pb.lock_rotation = (True, True, True)
        track_pb.lock_scale = (True, True, True)
        track_pb.bone.hide_select = True
        compat.assign_bone_to_collection(
            arm_data, track_pb, TRACKS_COLLECTION, compat.ROW_COLOR_PALETTES["Tracks"]
        )

        fader_pb = pose_bones[fader_name]
        palette = _palette_for(placement.row, placement.side)
        _configure_fader_pose_bone(fader_pb, cap_wgt, travel)
        compat.assign_bone_to_collection(arm_data, fader_pb, placement.row, palette)
        fader_map[fader_name] = {
            "shape_key": placement.shape_key_name,
            "row": placement.row,
            "side": placement.side,
            "palette": palette,
        }

    for placement, fader_name, _track_name in entries:
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
    )

    vowel_keys = _collect_vowel_keys(
        [(placement.row, placement.shape_key_name) for placement in layout.faders]
    )
    board["morphrig_target_mesh"] = target_mesh.name
    board["morphrig_vowel_keys"] = json.dumps(vowel_keys, ensure_ascii=False)
    board["morphrig_fader_map"] = json.dumps(fader_map, ensure_ascii=False)
    board["morphrig_driver_bindings"] = json.dumps(driver_bindings, ensure_ascii=False)
    board["morphrig_track_height"] = float(travel)
    board["morphrig_char_name"] = char_name if char_name is not None else board_token
    board["morphrig_widget_collection"] = widget_coll.name
    board["morphrig_labels_object"] = labels_obj.name
    board["morphrig_board_scale"] = scale
    board["morphrig_kuchisync_passthrough"] = False


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
) -> bpy.types.Object:
    frame_wgt = widget_factory.create_board_frame_widget(
        f"WGT_Board_Frame_{board_token}", 0.0, 0.0, layout.width, layout.height, widget_coll
    )
    track_wgt = widget_factory.create_slider_track_widget(
        f"WGT_Slider_Track_{board_token}", layout.track_height, scale, widget_coll
    )
    cap_wgt = widget_factory.create_slider_cap_widget(f"WGT_Slider_Cap_{board_token}", scale, widget_coll)
    board = _create_board_object(context, board_token, target_mesh, char_name, role, location, widget_coll)
    widgets = (frame_wgt, track_wgt, cap_wgt)
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
) -> None:
    arm_data = board.data
    frame_wgt, bar_wgt, joy_wgt = widgets
    half = box_size * 0.5
    bar_y = box_size + bar_gap
    root_length = 0.08 * scale
    bone_length = 0.03 * scale
    has_a = "A" in primary_vowels
    has_uieo = any(key in primary_vowels for key in ("I", "U", "E", "O"))

    _select_board_only(context, board)
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        edit_bones = arm_data.edit_bones
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
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")

    pose_bones = board.pose.bones
    root_pb = pose_bones[BOARD_ROOT_NAME]
    root_pb.custom_shape = frame_wgt
    root_pb.use_custom_shape_bone_size = False
    compat.assign_bone_to_collection(
        arm_data, root_pb, BOARD_COLLECTION, compat.ROW_COLOR_PALETTES["Board"]
    )

    fader_map = {}
    driver_bindings = []
    if has_a:
        slot_a = primary_vowels["A"]
        pb_a = pose_bones["Fader_Vowel_A"]
        _configure_constrained_pose_bone(
            pb_a, bar_wgt, (False, True, True), (0.0, 0.0, 0.0), (box_size, 0.0, 0.0)
        )
        compat.assign_bone_to_collection(arm_data, pb_a, "Vowels", "THEME03")
        compat.bind_fader_driver(
            target_mesh,
            slot_a.shape_key_name,
            board,
            "Fader_Vowel_A",
            box_size,
            transform_type="LOC_X",
            direction=1.0,
        )
        fader_map["Fader_Vowel_A"] = {
            "shape_key": slot_a.shape_key_name,
            "row": "Vowels",
            "side": slot_a.side,
            "palette": "THEME03",
        }
        driver_bindings.append({
            "bone": "Fader_Vowel_A",
            "shape_key": slot_a.shape_key_name,
            "row": "Vowels",
            "side": slot_a.side,
            "axis": "LOC_X",
            "travel": float(box_size),
            "direction": 1.0,
        })

    if has_uieo:
        pb_joy = pose_bones["Fader_Vowel_UIEO"]
        _configure_constrained_pose_bone(
            pb_joy, joy_wgt, (False, False, True), (-half, -half, 0.0), (half, half, 0.0)
        )
        compat.assign_bone_to_collection(arm_data, pb_joy, "Vowels", "THEME03")
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
                "Fader_Vowel_UIEO",
                half,
                transform_type=axis,
                direction=direction,
            )
            driver_bindings.append({
                "bone": "Fader_Vowel_UIEO",
                "shape_key": slot.shape_key_name,
                "row": "Vowels",
                "side": slot.side,
                "axis": axis,
                "travel": float(half),
                "direction": float(direction),
            })
        if first_uieo_slot is not None:
            fader_map["Fader_Vowel_UIEO"] = {
                "shape_key": first_uieo_slot.shape_key_name,
                "row": "Vowels",
                "side": first_uieo_slot.side,
                "palette": "THEME03",
            }

    font_size = 0.030 * scale
    label_specs = []
    if has_a:
        label_specs.append(TextLabelSpec("a", -0.024 * scale, bar_y - 0.008 * scale, font_size, "RIGHT"))
    if "O" in primary_vowels:
        label_specs.append(TextLabelSpec("o", half, box_size - 0.030 * scale, font_size, "CENTER"))
    if "E" in primary_vowels:
        label_specs.append(TextLabelSpec("e", half, 0.012 * scale, font_size, "CENTER"))
    if "U" in primary_vowels:
        label_specs.append(TextLabelSpec("u", 0.022 * scale, half - 0.010 * scale, font_size, "CENTER"))
    if "I" in primary_vowels:
        label_specs.append(TextLabelSpec("i", box_size - 0.022 * scale, half - 0.010 * scale, font_size, "CENTER"))

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
    )

    vowel_keys = _collect_vowel_keys(
        [("Vowels", binding["shape_key"]) for binding in driver_bindings]
    )
    board["morphrig_target_mesh"] = target_mesh.name
    board["morphrig_vowel_keys"] = json.dumps(vowel_keys, ensure_ascii=False)
    board["morphrig_fader_map"] = json.dumps(fader_map, ensure_ascii=False)
    board["morphrig_driver_bindings"] = json.dumps(driver_bindings, ensure_ascii=False)
    board["morphrig_track_height"] = float(box_size)
    board["morphrig_char_name"] = char_name
    board["morphrig_widget_collection"] = widget_coll.name
    board["morphrig_labels_object"] = labels_obj.name
    board["morphrig_board_scale"] = scale
    board["morphrig_kuchisync_passthrough"] = False


def _create_mouth_joystick_board(
    context,
    target_mesh,
    primary_vowels: dict,
    char_name: str,
    bounds_max: Vector,
    mid_y: float,
    scale: float,
    widget_coll,
) -> bpy.types.Object:
    mouth_token = f"{char_name}_Mouth"
    box_size = 0.22 * scale
    bar_gap = 0.032 * scale
    bar_y = box_size + bar_gap
    total_height = bar_y + 0.02 * scale
    location = Vector((bounds_max.x + 0.14, mid_y, bounds_max.z - total_height))

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
        )
    except Exception:
        _discard_partial_board(context, board, widgets)
        raise
    return board


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
) -> bpy.types.Object:
    if target_mesh is None or target_mesh.type != "MESH":
        raise ValueError("Target must be a mesh object.")
    if target_mesh.data.shape_keys is None:
        raise ValueError(f"'{target_mesh.name}' has no shape keys.")

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

    created_boards = []
    if separate_mouth_board and primary_vowels:
        if face_grouped:
            face_layout = calculate_board_layout(face_grouped, scale=scale, track_height=height_val)
            face_location = Vector((bounds_min.x - 0.18 - face_layout.width, mid_y, bounds_max.z - face_layout.height))
            face_board = _create_single_board(
                context, target_mesh, face_layout, char_name, char_name, "face", face_location, scale, widget_coll
            )
            try:
                mouth_board = _create_mouth_joystick_board(
                    context, target_mesh, primary_vowels, char_name, bounds_max, mid_y, scale, widget_coll
                )
            except Exception:
                remove_facial_board(context, face_board)
                raise
            face_board["morphrig_companion_board"] = mouth_board.name
            mouth_board["morphrig_companion_board"] = face_board.name
            created_boards = [face_board, mouth_board]
        else:
            mouth_board = _create_mouth_joystick_board(
                context, target_mesh, primary_vowels, char_name, bounds_max, mid_y, scale, widget_coll
            )
            created_boards = [mouth_board]
    else:
        layout = calculate_board_layout(grouped, scale=scale, track_height=height_val)
        has_face = any(row not in MOUTH_ROWS and groups for row, groups in grouped.items())
        has_mouth = any(row in MOUTH_ROWS and groups for row, groups in grouped.items())
        role = "combined" if (has_face and has_mouth) else ("face" if has_face else "mouth")
        board_location = Vector((bounds_max.x + 0.18, mid_y, bounds_max.z - layout.height))
        board = _create_single_board(
            context, target_mesh, layout, char_name, char_name, role, board_location, scale, widget_coll
        )
        created_boards = [board]

    if follow_head_bone:
        info = mmr_bridge.detect_mmr_rig_info(target_mesh)
        mmr_arm = info.armature
        head_bone_name = info.head_bone_name
        if mmr_arm is not None and head_bone_name and mmr_arm.pose.bones.get(head_bone_name) is not None:
            for board in created_boards:
                if mmr_arm is not board:
                    _parent_to_bone_keep_world(context, board, mmr_arm, head_bone_name)

    context.view_layer.update()
    return created_boards[0]


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
            palette = "THEME03" if is_mouth_role else _palette_for(entry.get("row", "Vowels"), entry.get("side", ""))
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


def _driver_targets_board(fcurve, board_armature) -> bool:
    for variable in fcurve.driver.variables:
        for target in variable.targets:
            if target.id == board_armature:
                return True
    return False


def _remove_board_drivers(board_armature) -> int:
    removed = 0
    for key in bpy.data.shape_keys:
        anim = key.animation_data
        if anim is None:
            continue
        stale = [fc for fc in anim.drivers if _driver_targets_board(fc, board_armature)]
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
    """Delete a board with its drivers, labels, widgets and armature data, leaving no orphans."""
    if not _is_alive(board_armature) or board_armature.type != "ARMATURE":
        return False
    _ensure_object_mode(context)

    board_name = board_armature.name
    target_mesh = _resolve_target_mesh(board_armature)
    removed_any = False
    if target_mesh is not None and getattr(target_mesh.data, "shape_keys", None) is not None:
        sk_names = {
            info.get("shape_key", "")
            for info in _load_json(board_armature, "morphrig_fader_map", {}).values()
        }
        sk_names.update(
            entry.get("shape_key", "")
            for entry in _load_json(board_armature, "morphrig_driver_bindings", [])
        )
        for sk_name in sk_names:
            if sk_name and compat.remove_shape_key_driver(target_mesh, sk_name):
                removed_any = True
    if _remove_board_drivers(board_armature) > 0:
        removed_any = True
    if removed_any and target_mesh is not None and getattr(target_mesh.data, "shape_keys", None) is not None:
        anim = target_mesh.data.shape_keys.animation_data
        if anim is not None and not anim.drivers and anim.action is None and not anim.nla_tracks:
            target_mesh.data.shape_keys.animation_data_clear()

    labels_name = board_armature.get("morphrig_labels_object", "")
    labels = [
        obj
        for obj in bpy.data.objects
        if obj.parent == board_armature
        and (obj.name == labels_name or obj.name.startswith(widget_factory.LABELS_OBJECT_PREFIX))
    ]
    for obj in labels:
        _remove_object_with_mesh(obj)

    widgets = {pb.custom_shape for pb in board_armature.pose.bones if pb.custom_shape is not None}
    widget_coll = bpy.data.collections.get(board_armature.get("morphrig_widget_collection", ""))

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
