# SPDX-License-Identifier: GPL-3.0-or-later

import ast
import json
import os
import sys
import time

import bpy

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

REALISTIC_SHAPE_KEYS = [
    "Basis",
    "---眉---",
    "にこり",
    "怒り右",
    "怒り左",
    "困る2右",
    "まばたき",
    "ｳｨﾝｸ２右",
    "ウィンク2",
    "ｷﾘｯ",
    "にやり３",
    "口横缩げ",
    "あ２",
    "い１",
    "う",
    "え",
    "お",
    "星目 ",
    "はぁと",
    "脸红",
    "！",
    "custom_extra_morph",
]


def _ensure_object_mode():
    active = bpy.context.view_layer.objects.active
    if active is not None and active.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")


def _reset_scene():
    _ensure_object_mode()
    scene = bpy.context.scene
    if hasattr(scene, "morphrig"):
        settings = scene.morphrig
        settings.target_mesh = None
        settings.follow_head_bone = True
        settings.include_emotes_row = True
        settings.include_unmapped_keys = False
        settings.separate_mouth_board = True
        settings.board_scale = 1.0
        settings.track_height = 0.12
        settings.kuchisync_passthrough = False
        settings.show_preview_list = False
        settings.scanned_items.clear()
        settings.active_scanned_index = 0
        settings.last_scanned_mesh = ""

    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for arm in list(bpy.data.armatures):
        bpy.data.armatures.remove(arm)
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh)
    for curve in list(bpy.data.curves):
        bpy.data.curves.remove(curve)
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action)
    for coll in list(bpy.data.collections):
        bpy.data.collections.remove(coll)
    for mat_name in ("MorphRig_Label_Mat", "MorphRig_Mouth_Label_Mat"):
        mat = bpy.data.materials.get(mat_name)
        if mat is not None and mat.users == 0:
            bpy.data.materials.remove(mat)


def _create_test_character_mesh(name="Keqing_Face", shape_keys=None):
    if shape_keys is None:
        shape_keys = REALISTIC_SHAPE_KEYS
    mesh_data = bpy.data.meshes.new(name)
    verts = [(0.0, 0.0, 1.4), (0.15, 0.0, 1.4), (0.0, 0.0, 1.65)]
    mesh_data.from_pydata(verts, [], [(0, 1, 2)])
    mesh_data.update()

    mesh_obj = bpy.data.objects.new(name, mesh_data)
    bpy.context.scene.collection.objects.link(mesh_obj)

    for key_name in shape_keys:
        sk = mesh_obj.shape_key_add(name=key_name, from_mix=False)
        if key_name != "Basis":
            sk.data[2].co.z += 0.01

    return mesh_obj


def _create_armature(name, bones):
    arm_data = bpy.data.armatures.new(name)
    arm_obj = bpy.data.objects.new(name, arm_data)
    bpy.context.scene.collection.objects.link(arm_obj)

    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode="EDIT")
    for bone_name, head, tail in bones:
        eb = arm_data.edit_bones.new(bone_name)
        eb.head = head
        eb.tail = tail
    bpy.ops.object.mode_set(mode="OBJECT")
    return arm_obj


def test_startup_and_mmr_bridge_fallback():
    t0 = time.perf_counter()
    import morphrig
    morphrig.register()
    elapsed = time.perf_counter() - t0
    print(f"[Stage 1] Startup import + register: {elapsed * 1000.0:.2f} ms")

    assert elapsed < 0.1, f"Startup registration too slow: {elapsed:.4f}s"
    for heavy_mod in ("morphrig.rig_builder", "morphrig.widget_factory", "morphrig.semantic_mapper"):
        assert heavy_mod not in sys.modules, f"Heavy module imported at startup: {heavy_mod}"
    if hasattr(bpy.app, "timers"):
        assert bpy.app.timers.is_registered(morphrig._deferred_refresh_panel_category)
        assert morphrig._deferred_refresh_panel_category() is None

    from morphrig import mmr_bridge, ui_panel

    _reset_scene()

    standalone_cat = mmr_bridge.resolve_target_panel_category(bpy.context)
    assert standalone_cat == "MorphRig", f"Expected MorphRig, got {standalone_cat}"

    plain_mesh = _create_test_character_mesh("PlainMesh", ["Basis", "まばたき"])
    plain_info = mmr_bridge.detect_mmr_rig_info(plain_mesh)
    assert plain_info.armature is None
    assert plain_info.head_bone_name == ""
    assert plain_info.is_mmr_rig is False
    assert plain_info.has_legacy_emoji_rig is False

    class SCENE_PT_MMR_Rig_0(bpy.types.Panel):
        bl_label = "Mock MMR Panel"
        bl_idname = "SCENE_PT_MMR_Rig_0"
        bl_space_type = "VIEW_3D"
        bl_region_type = "UI"
        bl_category = "MMR"

        def draw(self, context):
            self.layout.label(text="Mock MMR")

    bpy.utils.register_class(SCENE_PT_MMR_Rig_0)
    try:
        docked_cat = mmr_bridge.resolve_target_panel_category(bpy.context, dock_in_mmr_tab=True)
        assert docked_cat == "MMR", f"Expected MMR, got {docked_cat}"

        undocked_cat = mmr_bridge.resolve_target_panel_category(bpy.context, dock_in_mmr_tab=False)
        assert undocked_cat == "MorphRig", f"Expected MorphRig when undocked, got {undocked_cat}"

        ui_panel.refresh_panel_category(bpy.context)
        assert ui_panel.MORPHRIG_PT_main_panel.bl_category == "MMR"
    finally:
        bpy.utils.unregister_class(SCENE_PT_MMR_Rig_0)

    ui_panel.refresh_panel_category(bpy.context)
    assert ui_panel.MORPHRIG_PT_main_panel.bl_category == "MorphRig"

    mmr_arm = _create_armature(
        "Mock_MMR_Arm",
        [
            ("c_head.x", (0.0, 0.0, 1.4), (0.0, 0.0, 1.6)),
            ("qws_F1", (0.2, 0.0, 1.4), (0.2, 0.0, 1.5)),
        ],
    )
    mod = plain_mesh.modifiers.new(name="Armature", type="ARMATURE")
    mod.object = mmr_arm

    mmr_info = mmr_bridge.detect_mmr_rig_info(plain_mesh)
    assert mmr_info.armature == mmr_arm
    assert mmr_info.head_bone_name == "c_head.x"
    assert mmr_info.is_mmr_rig is True
    assert mmr_info.has_legacy_emoji_rig is True

    hidden = mmr_bridge.toggle_mmr_emoji_rig(bpy.context, mmr_arm, hide=True)
    assert hidden is True
    assert mmr_bridge.is_legacy_emoji_rig_hidden(bpy.context, mmr_arm) is True

    shown = mmr_bridge.toggle_mmr_emoji_rig(bpy.context, mmr_arm, hide=False)
    assert shown is False
    assert mmr_bridge.is_legacy_emoji_rig_hidden(bpy.context, mmr_arm) is False

    bpy.context.scene.morphrig.target_mesh = plain_mesh
    assert bpy.ops.morphrig.toggle_legacy_mmr_emoji() == {"FINISHED"}
    assert mmr_bridge.is_legacy_emoji_rig_hidden(bpy.context, mmr_arm) is True
    assert bpy.ops.morphrig.toggle_legacy_mmr_emoji() == {"FINISHED"}
    assert mmr_bridge.is_legacy_emoji_rig_hidden(bpy.context, mmr_arm) is False
    print("[Stage 1] PASS: startup speed, MMR bridge fallback, mock MMR panel/rig, legacy toggle")


def test_multilingual_semantic_mapper():
    from morphrig import semantic_mapper

    _reset_scene()
    mesh_obj = _create_test_character_mesh("MapperTest", REALISTIC_SHAPE_KEYS)

    assert semantic_mapper.normalize_shape_key_name("ｳｨﾝｸ２右") == "ウィンク2右"
    assert semantic_mapper.normalize_shape_key_name("ｷﾘｯ") == "キリッ"
    assert semantic_mapper.normalize_shape_key_name("星目 ") == "星目"
    assert semantic_mapper.is_ignored_shape_key(0, "Basis") is True
    assert semantic_mapper.is_ignored_shape_key(1, "---眉---") is True

    slots_default = semantic_mapper.scan_mesh_shape_keys(
        mesh_obj,
        include_emotes=True,
        include_unmapped=False,
    )
    slot_by_key = {s.shape_key_name: s for s in slots_default}

    assert "Basis" not in slot_by_key
    assert "---眉---" not in slot_by_key
    assert "custom_extra_morph" not in slot_by_key

    assert slot_by_key["にこり"].row == "Eyebrows"
    assert slot_by_key["怒り右"].row == "Eyebrows" and slot_by_key["怒り右"].side == "R"
    assert slot_by_key["怒り左"].row == "Eyebrows" and slot_by_key["怒り左"].side == "L"
    assert slot_by_key["困る2右"].row == "Eyebrows" and slot_by_key["困る2右"].side == "R"

    assert slot_by_key["まばたき"].row == "Eyes"
    assert slot_by_key["ｳｨﾝｸ２右"].row == "Eyes" and slot_by_key["ｳｨﾝｸ２右"].side == "R"
    assert slot_by_key["ウィンク2"].row == "Eyes" and slot_by_key["ウィンク2"].side == "L"
    assert slot_by_key["ｷﾘｯ"].row == "Eyes"

    assert slot_by_key["にやり３"].row == "Lips"
    assert slot_by_key["口横缩げ"].row == "Lips"

    for vowel_key in ("あ２", "い１", "う", "え", "お"):
        assert slot_by_key[vowel_key].row == "Vowels", f"Expected Vowels for {vowel_key}"

    for emote_key in ("星目 ", "はぁと", "脸红", "！"):
        assert slot_by_key[emote_key].row == "Emotes", f"Expected Emotes for {emote_key}"

    grouped = semantic_mapper.group_control_slots(slots_default, include_emotes=True, include_unmapped=False)

    wink2_groups = [
        g for g in grouped["Eyes"]
        if g.right_slot and g.right_slot.shape_key_name == "ｳｨﾝｸ２右"
    ]
    assert len(wink2_groups) == 1
    assert wink2_groups[0].is_paired is True
    assert wink2_groups[0].left_slot.shape_key_name == "ウィンク2"

    angry_groups = [
        g for g in grouped["Eyebrows"]
        if g.right_slot and g.right_slot.shape_key_name == "怒り右"
    ]
    assert len(angry_groups) == 1
    assert angry_groups[0].is_paired is True
    assert angry_groups[0].left_slot.shape_key_name == "怒り左"

    komaru_groups = [
        g for g in grouped["Eyebrows"]
        if g.center_slot and g.center_slot.shape_key_name == "困る2右"
    ]
    assert len(komaru_groups) == 1
    assert komaru_groups[0].display_label == "Sad 2 (R)"

    slots_with_extra = semantic_mapper.scan_mesh_shape_keys(
        mesh_obj,
        include_emotes=True,
        include_unmapped=True,
    )
    extra_slots = [s for s in slots_with_extra if s.shape_key_name == "custom_extra_morph"]
    assert len(extra_slots) == 1 and extra_slots[0].row == "Extra"
    print("[Stage 2] PASS: multilingual mapping, NFKC normalization, R/L pairing, Extra fallback")


def _build_board_fixture():
    _reset_scene()
    mesh_obj = _create_test_character_mesh("Keqing_Face", REALISTIC_SHAPE_KEYS)
    mmr_arm = _create_armature(
        "Keqing_Armature",
        [("c_head.x", (0.0, 0.0, 1.4), (0.0, 0.0, 1.6))],
    )
    mod = mesh_obj.modifiers.new(name="Armature", type="ARMATURE")
    mod.object = mmr_arm

    _ensure_object_mode()
    for obj in bpy.context.scene.objects:
        obj.select_set(False)
    mesh_obj.select_set(True)
    bpy.context.view_layer.objects.active = mesh_obj
    bpy.context.scene.morphrig.target_mesh = mesh_obj

    res = bpy.ops.morphrig.generate_board()
    assert res == {"FINISHED"}, f"generate_board returned {res}"
    return mesh_obj, mmr_arm


def test_procedural_board_and_text_mesh_generation():
    from morphrig import compat, rig_builder, semantic_mapper, widget_factory

    mesh_obj, mmr_arm = _build_board_fixture()
    boards = rig_builder.find_boards_for_mesh(bpy.context, mesh_obj)
    assert len(boards) == 2, f"Expected Face and Mouth boards, got {boards}"
    face_board, mouth_board = boards
    assert face_board == rig_builder.find_board_for_mesh(bpy.context, mesh_obj)
    assert face_board.name == "MorphRig_Board_Keqing_Face"
    assert mouth_board.name == "MorphRig_Board_Keqing_Face_Mouth"
    assert face_board.get("morphrig_board_role") == "face"
    assert mouth_board.get("morphrig_board_role") == "mouth"
    assert face_board.get("morphrig_companion_board") == mouth_board.name
    assert mouth_board.get("morphrig_companion_board") == face_board.name

    bounds_min_x = min(v.co.x for v in mesh_obj.data.vertices)
    bounds_max_x = max(v.co.x for v in mesh_obj.data.vertices)
    assert face_board.location.x < bounds_min_x, f"Face board should be left (-X): {face_board.location.x}"
    assert mouth_board.location.x > bounds_max_x, f"Mouth rig should be right (+X): {mouth_board.location.x}"

    for board in (face_board, mouth_board):
        assert board.type == "ARMATURE"
        assert board.parent == mmr_arm
        assert board.parent_type == "BONE"
        assert board.parent_bone == "c_head.x"

    face_colls = {c.name for c in face_board.data.collections}
    mouth_colls = {c.name for c in mouth_board.data.collections}
    for expected in ("Board", "Tracks", "Eyebrows", "Eyes", "Lips", "Emotes"):
        assert expected in face_colls, f"Missing face bone collection: {expected}"
    for expected in ("Board", "Vowels"):
        assert expected in mouth_colls, f"Missing mouth bone collection: {expected}"
    assert "Vowels" not in face_colls
    assert "Eyebrows" not in mouth_colls and "Eyes" not in mouth_colls

    label_objs = {o.name: o for o in bpy.data.objects if o.name.startswith("MorphRig_Labels_")}
    assert set(label_objs.keys()) == {"MorphRig_Labels_Keqing_Face", "MorphRig_Labels_Keqing_Face_Mouth"}

    face_labels = label_objs["MorphRig_Labels_Keqing_Face"]
    assert face_labels.type == "MESH"
    assert face_labels.show_in_front is True
    assert face_labels.display_type == "SOLID"
    assert face_labels.hide_select is True
    assert face_labels.parent == face_board
    assert face_labels.parent_type == "BONE"
    assert face_labels.parent_bone == "Board_Root"
    assert len(face_labels.data.vertices) > 0
    face_mat = face_labels.data.materials[0]
    assert face_mat.name == widget_factory.LABEL_MAT_FACE
    assert tuple(round(c, 4) for c in face_mat.diffuse_color) == (1.0, 1.0, 1.0, 1.0)
    assert any(n.type == "EMISSION" for n in face_mat.node_tree.nodes)

    mouth_labels = label_objs["MorphRig_Labels_Keqing_Face_Mouth"]
    assert mouth_labels.type == "MESH"
    assert mouth_labels.show_in_front is True
    assert mouth_labels.display_type == "SOLID"
    assert mouth_labels.hide_select is True
    assert mouth_labels.parent == mouth_board
    assert mouth_labels.parent_type == "BONE"
    assert mouth_labels.parent_bone == "Board_Root"
    assert len(mouth_labels.data.vertices) > 0
    mouth_mat = mouth_labels.data.materials[0]
    assert mouth_mat.name == widget_factory.LABEL_MAT_MOUTH
    assert any(n.type == "EMISSION" for n in mouth_mat.node_tree.nodes)

    track_bones = [b for b in face_board.data.bones if b.name.startswith("Track_")]
    assert len(track_bones) > 0
    for tb in track_bones:
        assert tb.hide_select is True

    face_faders = [pb for pb in face_board.pose.bones if pb.name.startswith("Fader_")]
    assert len(face_faders) > 0
    fader_data_bones = [face_board.data.bones[pb.name] for pb in face_faders]
    unique_x = sorted({round(b.head_local.x, 6) for b in fader_data_bones})
    assert len(unique_x) == 2, f"Expected 2 side-by-side lane X positions, got {unique_x}"
    for lane_x in unique_x:
        lane_zs = [b.head_local.z for b in fader_data_bones if abs(b.head_local.x - lane_x) < 1e-5]
        assert len(lane_zs) > 0
        assert all(lane_zs[i] > lane_zs[i + 1] for i in range(len(lane_zs) - 1)), (
            f"Lane {lane_x} faders should descend top-to-bottom: {lane_zs}"
        )

    face_slots = [
        s for s in semantic_mapper.scan_mesh_shape_keys(mesh_obj, include_emotes=True, include_unmapped=False)
        if s.shape_key_name not in {"あ２", "い１", "う", "え", "お"}
    ]
    face_grouped = semantic_mapper.group_control_slots(face_slots, include_emotes=True, include_unmapped=False)
    face_layout = rig_builder.calculate_board_layout(
        face_grouped, scale=1.0 * rig_builder.FACE_RIG_SCALE, track_height=0.12
    )
    assert face_layout.width < 0.50, f"Expected compact Face Board width < 0.50, got {face_layout.width}"
    frame_wgt = face_board.pose.bones["Board_Root"].custom_shape
    frame_xs = [v.co.x for v in frame_wgt.data.vertices]
    frame_w = max(frame_xs) - min(frame_xs)
    assert frame_w < 0.50, f"Unexpected frame width: {frame_w}"

    extra_face_keys = [
        "真面目", "上", "下", "前", "笑い", "なごみ", "びっくり", "じと目", "痛み",
        "口角上げ", "口角下げ", "ω", "口横広げ", "てへぺろ", "涙", "汗",
    ]
    full_slots = list(face_slots) + [
        s for s in (semantic_mapper.map_shape_key(k) for k in extra_face_keys) if s is not None
    ]
    full_grouped = semantic_mapper.group_control_slots(full_slots, include_emotes=True, include_unmapped=False)
    full_layout = rig_builder.calculate_board_layout(
        full_grouped, scale=1.0 * rig_builder.FACE_RIG_SCALE, track_height=0.12
    )
    assert full_layout.width < 0.50 and full_layout.height > full_layout.width, (
        f"Expected tall compact 2-lane board for full character: {full_layout.width} x {full_layout.height}"
    )

    face_travel = float(face_board["morphrig_track_height"])
    assert abs(face_travel - (0.12 * 0.55 * 1.2)) < 1e-5, f"Unexpected face_travel: {face_travel}"
    for pb in face_faders:
        assert tuple(pb.lock_location) == (True, False, True)
        assert tuple(pb.lock_rotation) == (True, True, True)
        assert tuple(pb.lock_scale) == (True, True, True)
        limit_cons = [c for c in pb.constraints if c.type == "LIMIT_LOCATION"]
        assert len(limit_cons) == 1
        con = limit_cons[0]
        assert con.owner_space == "LOCAL"
        assert con.use_transform_limit is True
        assert con.use_min_y is True and abs(con.min_y) < 1e-6
        assert con.use_max_y is True and abs(con.max_y - face_travel) < 1e-6
        assert con.use_min_x is True and con.use_max_x is True
        assert con.use_min_z is True and con.use_max_z is True

    box_size = float(mouth_board["morphrig_track_height"])
    assert abs(box_size - (0.13 * 1.15)) < 1e-5, f"Unexpected Mouth Rig box_size: {box_size}"
    half = box_size * 0.5
    pb_a = mouth_board.pose.bones["Fader_Vowel_A"]
    assert pb_a.custom_shape is not None and pb_a.custom_shape.name.startswith("WGT_Mouth_Bar_")
    assert pb_a.color.palette == "THEME03"
    assert tuple(pb_a.lock_location) == (False, True, True)
    con_a = next(c for c in pb_a.constraints if c.type == "LIMIT_LOCATION")
    assert con_a.owner_space == "LOCAL" and con_a.use_transform_limit is True
    assert abs(con_a.min_x) < 1e-6 and abs(con_a.max_x - box_size) < 1e-6
    assert abs(con_a.min_y) < 1e-6 and abs(con_a.max_y) < 1e-6

    pb_joy = mouth_board.pose.bones["Fader_Vowel_UIEO"]
    assert pb_joy.custom_shape is not None and pb_joy.custom_shape.name.startswith("WGT_Mouth_Joy_")
    assert pb_joy.color.palette == "THEME03"
    assert tuple(pb_joy.lock_location) == (False, False, True)
    con_joy = next(c for c in pb_joy.constraints if c.type == "LIMIT_LOCATION")
    assert con_joy.owner_space == "LOCAL" and con_joy.use_transform_limit is True
    assert abs(con_joy.min_x + half) < 1e-6 and abs(con_joy.max_x - half) < 1e-6
    assert abs(con_joy.min_y + half) < 1e-6 and abs(con_joy.max_y - half) < 1e-6

    drivers = list(mesh_obj.data.shape_keys.animation_data.drivers)
    assert len(drivers) > 0
    board_set = {face_board, mouth_board}
    for fc in drivers:
        drv = fc.driver
        assert drv.type == "AVERAGE"
        assert len(drv.variables) == 1
        var = drv.variables[0]
        assert var.type == "TRANSFORMS"
        tgt = var.targets[0]
        assert tgt.id in board_set
        assert tgt.transform_type in ("LOC_X", "LOC_Y")
        assert tgt.transform_space == "LOCAL_SPACE"
        gen_mods = [m for m in fc.modifiers if m.type == "GENERATOR"]
        assert len(gen_mods) == 1
        assert gen_mods[0].mode == "POLYNOMIAL"
        assert gen_mods[0].poly_order == 1

    face_faders[0].location.y = face_travel * 0.5
    pb_a.location.x = box_size * 0.5
    pb_joy.location.x = half * 0.5
    pb_joy.location.y = -half * 0.5
    assert bpy.ops.morphrig.key_all_sliders() == {"FINISHED"}
    face_curves = list(compat.iter_action_fcurves(face_board.animation_data.action))
    mouth_curves = list(compat.iter_action_fcurves(mouth_board.animation_data.action))
    assert any(fc.data_path == f'pose.bones["{face_faders[0].name}"].location' and fc.array_index == 1 for fc in face_curves)
    assert any(fc.data_path == 'pose.bones["Fader_Vowel_A"].location' and fc.array_index == 0 for fc in mouth_curves)
    joy_indices = {fc.array_index for fc in mouth_curves if fc.data_path == 'pose.bones["Fader_Vowel_UIEO"].location'}
    assert joy_indices == {0, 1}, f"Expected X and Y keyframes on Fader_Vowel_UIEO, got {joy_indices}"

    assert bpy.ops.morphrig.reset_sliders() == {"FINISHED"}
    for pb in face_faders + [pb_a, pb_joy]:
        assert pb.location.length < 1e-6

    assert bpy.ops.morphrig.clear_keyframes() == {"FINISHED"}
    for board in (face_board, mouth_board):
        remaining_fcurves = [
            fc for fc in compat.iter_action_fcurves(board.animation_data.action)
            if fc.data_path.endswith(".location")
        ]
        assert len(remaining_fcurves) == 0

    assert bpy.ops.morphrig.scan_shape_keys() == {"FINISHED"}
    settings = bpy.context.scene.morphrig
    assert settings.last_scanned_mesh == mesh_obj.name
    assert len(settings.scanned_items) > 0
    assert settings.show_preview_list is True

    settings.separate_mouth_board = False
    assert bpy.ops.morphrig.rebuild_board() == {"FINISHED"}
    combined_boards = rig_builder.find_boards_for_mesh(bpy.context, mesh_obj)
    assert len(combined_boards) == 1
    combined_board = combined_boards[0]
    assert combined_board.get("morphrig_board_role") == "combined"
    assert combined_board.location.x > bounds_max_x
    assert "morphrig_companion_board" not in combined_board
    combined_colls = {c.name for c in combined_board.data.collections}
    for expected in ("Board", "Tracks", "Eyebrows", "Eyes", "Lips", "Vowels", "Emotes"):
        assert expected in combined_colls, f"Missing combined bone collection: {expected}"
    print("[Stage 3] PASS: Reference 1 Face Board, Reference 2 Mouth Rig, materials, constraints, keying")


def _find_fader_bone(boards, target_shape_key):
    if not isinstance(boards, (list, tuple)):
        boards = [boards]
    for board in boards:
        bindings = json.loads(board.get("morphrig_driver_bindings", "[]"))
        for entry in bindings:
            if entry.get("shape_key") == target_shape_key:
                return board, entry["bone"]
        fader_map = json.loads(board["morphrig_fader_map"])
        for bone_name, info in fader_map.items():
            if info.get("shape_key") == target_shape_key:
                return board, bone_name
    raise AssertionError(f"Missing fader bone for shape key {target_shape_key}")


def _eval_shape_key(mesh_obj, key_name):
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    eval_mesh = mesh_obj.evaluated_get(depsgraph)
    return eval_mesh.data.shape_keys.key_blocks[key_name].value


def test_fader_to_shapekey_evaluation():
    from morphrig import rig_builder

    mesh_obj, _ = _build_board_fixture()
    boards = rig_builder.find_boards_for_mesh(bpy.context, mesh_obj)
    assert len(boards) == 2
    face_board, mouth_board = boards

    face_travel = float(face_board["morphrig_track_height"])
    for target_sk in ("怒り右", "まばたき"):
        board, fader_name = _find_fader_bone(face_board, target_sk)
        board.pose.bones[fader_name].location.y = face_travel

    box_size = float(mouth_board["morphrig_track_height"])
    half = box_size * 0.5
    mouth_board.pose.bones["Fader_Vowel_A"].location.x = box_size
    assert abs(_eval_shape_key(mesh_obj, "怒り右") - 1.0) < 1e-4
    assert abs(_eval_shape_key(mesh_obj, "まばたき") - 1.0) < 1e-4
    assert abs(_eval_shape_key(mesh_obj, "あ２") - 1.0) < 1e-4

    pb_joy = mouth_board.pose.bones["Fader_Vowel_UIEO"]
    for loc, active_sk, inactive_sk in (
        ((half, 0.0, 0.0), "い１", "う"),
        ((-half, 0.0, 0.0), "う", "い１"),
        ((0.0, half, 0.0), "お", "え"),
        ((0.0, -half, 0.0), "え", "お"),
    ):
        pb_joy.location = loc
        assert abs(_eval_shape_key(mesh_obj, active_sk) - 1.0) < 1e-4, f"Expected {active_sk} == 1.0 at {loc}"
        assert abs(_eval_shape_key(mesh_obj, inactive_sk)) < 1e-4, f"Expected {inactive_sk} == 0.0 at {loc}"

    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_labels = next(o for o in bpy.data.objects if o.name.startswith("MorphRig_Labels_")).evaluated_get(depsgraph)
    eval_board = face_board.evaluated_get(depsgraph)
    first_v_world = eval_labels.matrix_world @ eval_labels.data.vertices[0].co
    board_origin = eval_board.matrix_world.translation
    assert (first_v_world - board_origin).length < 2.0, (
        f"Labels drifted from board origin: {first_v_world} vs {board_origin}"
    )
    print("[Stage 4] PASS: horizontal sliders, Fader_Vowel_A, and 4-way Fader_Vowel_UIEO evaluation")


def test_kuchisync_passthrough():
    from morphrig import rig_builder

    _reset_scene()
    shape_keys = list(REALISTIC_SHAPE_KEYS) + ["ワ"]
    mesh_obj = _create_test_character_mesh("Keqing_Kuchi", shape_keys)
    bpy.context.view_layer.objects.active = mesh_obj
    bpy.context.scene.morphrig.target_mesh = mesh_obj
    assert bpy.ops.morphrig.generate_board() == {"FINISHED"}

    boards = rig_builder.find_boards_for_mesh(bpy.context, mesh_obj)
    assert len(boards) == 2
    face_board, mouth_board = boards

    for target_sk in ("怒り右", "まばたき"):
        board, fader_name = _find_fader_bone(face_board, target_sk)
        board.pose.bones[fader_name].location.y = float(board["morphrig_track_height"])

    box_size = float(mouth_board["morphrig_track_height"])
    half = box_size * 0.5
    mouth_board.pose.bones["Fader_Vowel_A"].location.x = box_size
    mouth_board.pose.bones["Fader_Vowel_UIEO"].location = (half, 0.0, 0.0)

    assert bpy.ops.morphrig.toggle_kuchisync() == {"FINISHED"}
    assert bpy.context.scene.morphrig.kuchisync_passthrough is True
    assert bool(face_board["morphrig_kuchisync_passthrough"]) is True
    assert bool(mouth_board["morphrig_kuchisync_passthrough"]) is True

    drivers_by_path = {
        fc.data_path: fc for fc in mesh_obj.data.shape_keys.animation_data.drivers
    }
    for vowel_sk in ("あ２", "い１", "う", "え", "お", "ワ"):
        dp = f'key_blocks["{vowel_sk}"].value'
        assert dp not in drivers_by_path, f"Vowel driver should be removed during passthrough: {vowel_sk}"

    for active_sk in ("まばたき", "怒り右"):
        dp = f'key_blocks["{active_sk}"].value'
        assert dp in drivers_by_path and drivers_by_path[dp].mute is False

    assert mouth_board.pose.bones["Fader_Vowel_A"].color.palette == "DEFAULT"
    assert mouth_board.pose.bones["Fader_Vowel_UIEO"].color.palette == "DEFAULT"

    kb = mesh_obj.data.shape_keys.key_blocks["あ２"]
    kb.value = 0.85
    assert kb.keyframe_insert(data_path="value", frame=5) is True
    bpy.context.scene.frame_set(5)
    assert abs(_eval_shape_key(mesh_obj, "あ２") - 0.85) < 1e-4
    assert abs(_eval_shape_key(mesh_obj, "まばたき") - 1.0) < 1e-4
    assert abs(_eval_shape_key(mesh_obj, "怒り右") - 1.0) < 1e-4

    assert bpy.ops.morphrig.toggle_kuchisync() == {"FINISHED"}
    assert bpy.context.scene.morphrig.kuchisync_passthrough is False
    drivers_by_path = {
        fc.data_path: fc for fc in mesh_obj.data.shape_keys.animation_data.drivers
    }
    for vowel_sk in ("あ２", "い１", "う", "え", "お", "ワ"):
        dp = f'key_blocks["{vowel_sk}"].value'
        assert dp in drivers_by_path, f"Vowel driver should be rebound: {vowel_sk}"
        fc = drivers_by_path[dp]
        assert fc.driver.type == "AVERAGE"
        assert any(m.type == "GENERATOR" for m in fc.modifiers)

    assert mouth_board.pose.bones["Fader_Vowel_A"].color.palette == "THEME03"
    assert mouth_board.pose.bones["Fader_Vowel_UIEO"].color.palette == "THEME03"

    assert abs(_eval_shape_key(mesh_obj, "あ２") - 1.0) < 1e-4
    assert abs(_eval_shape_key(mesh_obj, "い１") - 1.0) < 1e-4
    mouth_board.pose.bones["Fader_Vowel_UIEO"].location = (0.0, -half, 0.0)
    assert abs(_eval_shape_key(mesh_obj, "え") - 1.0) < 1e-4
    print("[Stage 5] PASS: KuchiSync passthrough releases and re-binds all vowel drivers across both boards")


def test_clean_removal():
    from morphrig import rig_builder, widget_factory

    mesh_obj, _ = _build_board_fixture()
    assert len(rig_builder.find_all_boards()) == 2
    assert bpy.ops.morphrig.remove_board() == {"FINISHED"}

    leftover_boards = [o for o in bpy.data.objects if o.name.startswith("MorphRig_Board_")]
    leftover_arms = [a for a in bpy.data.armatures if a.name.startswith("MorphRig_Board_")]
    leftover_labels = [o for o in bpy.data.objects if o.name.startswith("MorphRig_Labels_")]
    leftover_colls = [c for c in bpy.data.collections if c.name.startswith("MorphRig_Widgets_")]
    leftover_widgets = [o for o in bpy.data.objects if o.name.startswith("WGT_")]
    leftover_wgt_meshes = [m for m in bpy.data.meshes if m.name.startswith("WGT_") or m.name.startswith("MorphRig_Labels_")]

    assert not leftover_boards, f"Leftover boards: {leftover_boards}"
    assert not leftover_arms, f"Leftover armatures: {leftover_arms}"
    assert not leftover_labels, f"Leftover labels: {leftover_labels}"
    assert not leftover_colls, f"Leftover widget collections: {leftover_colls}"
    assert not leftover_widgets, f"Leftover widget objects: {leftover_widgets}"
    assert not leftover_wgt_meshes, f"Leftover widget/label meshes: {leftover_wgt_meshes}"
    assert widget_factory.LABEL_MAT_FACE not in bpy.data.materials
    assert widget_factory.LABEL_MAT_MOUTH not in bpy.data.materials

    anim_data = mesh_obj.data.shape_keys.animation_data
    remaining_drivers = list(anim_data.drivers) if anim_data else []
    assert not remaining_drivers, f"Leftover shape key drivers: {remaining_drivers}"
    print("[Stage 6] PASS: clean removal of Face/Mouth boards, materials, and drivers with zero orphans")


def _build_two_armature_mmr_rig():
    _reset_scene()
    mmd_arm = _create_armature(
        "刻晴_arm",
        [("頭", (0.0, 0.0, 1.4), (0.0, 0.0, 1.6))],
    )
    rig_arm = _create_armature(
        "RIG-刻晴_arm",
        [("head", (0.0, 0.0, 1.4), (0.0, 0.0, 1.6))],
    )
    rig_arm["mmr"] = True

    con = mmd_arm.pose.bones["頭"].constraints.new("COPY_TRANSFORMS")
    con.target = rig_arm
    con.subtarget = "head"

    body_mesh = _create_test_character_mesh("刻晴_body", ["Basis", "body_dummy"])
    body_mod = body_mesh.modifiers.new(name="Armature", type="ARMATURE")
    body_mod.object = mmd_arm

    face_mesh = _create_test_character_mesh("刻晴_mesh", REALISTIC_SHAPE_KEYS)
    face_mod = face_mesh.modifiers.new(name="Armature", type="ARMATURE")
    face_mod.object = mmd_arm
    return face_mesh, mmd_arm, rig_arm


def test_two_armature_mmr_bridge():
    from morphrig import mmr_bridge

    face_mesh, mmd_arm, rig_arm = _build_two_armature_mmr_rig()

    info = mmr_bridge.detect_mmr_rig_info(face_mesh)
    assert info.armature == rig_arm, f"Expected RIG-刻晴_arm, got {info.armature}"
    assert info.is_mmr_rig is True
    assert info.head_bone_name == "head", f"Expected head, got {info.head_bone_name}"

    resolved_from_rig = mmr_bridge.find_face_mesh_for_armature(rig_arm, bpy.context.scene)
    assert resolved_from_rig == face_mesh, f"Expected 刻晴_mesh, got {resolved_from_rig}"

    resolved_from_mmd = mmr_bridge.find_face_mesh_for_armature(mmd_arm, bpy.context.scene)
    assert resolved_from_mmd == face_mesh, f"Expected 刻晴_mesh from mmd arm, got {resolved_from_mmd}"
    print("[Stage 7] PASS: two-armature MMR bridge detection and find_face_mesh_for_armature")


class _RecordingLayout:
    def __init__(self, records=None):
        self.records = records if records is not None else []
        self.enabled = True
        self.scale_y = 1.0

    def box(self):
        return _RecordingLayout(self.records)

    def row(self, align=False):
        return _RecordingLayout(self.records)

    def column(self, align=False):
        return _RecordingLayout(self.records)

    def grid_flow(self, **kwargs):
        return _RecordingLayout(self.records)

    def label(self, text="", icon="NONE"):
        self.records.append(("label", text, icon))

    def prop(self, data, prop_name, text="", icon="NONE", emboss=True, slider=False):
        self.records.append(("prop", prop_name, text, icon))

    def operator(self, op_idname, text="", icon="NONE", depress=False):
        self.records.append(("operator", op_idname, text, icon))
        return None


def _collect_ui_panel_icon_literals():
    ui_path = os.path.join(PROJECT_ROOT, "morphrig", "ui_panel.py")
    with open(ui_path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=ui_path)
    icons = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "safe_icon":
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    icons.add(arg.value)
                elif isinstance(arg, ast.IfExp):
                    for branch in (arg.body, arg.orelse):
                        if isinstance(branch, ast.Constant) and isinstance(branch.value, str):
                            icons.add(branch.value)
    return sorted(icons)


def test_safe_icon_and_panel_draw():
    from morphrig import compat, rig_builder, ui_panel

    panel_icons = _collect_ui_panel_icon_literals()
    assert "ARMATURE_DATA" in panel_icons
    for icon_name in panel_icons:
        resolved = compat.safe_icon(icon_name)
        assert resolved == icon_name, f"Expected valid icon '{icon_name}', got '{resolved}'"

    fallback = compat.safe_icon("__MORPHRIG_INVALID_ICON__")
    assert fallback in ("BLANK1", "NONE"), f"Unexpected invalid-icon fallback: {fallback}"

    class _PanelProxy:
        def __init__(self, layout):
            self.layout = layout

        _draw_panel_body = ui_panel.MORPHRIG_PT_main_panel._draw_panel_body
        draw = ui_panel.MORPHRIG_PT_main_panel.draw

    def _draw_records():
        rec = _RecordingLayout()
        _PanelProxy(rec).draw(bpy.context)
        errors = [r for r in rec.records if r[0] == "label" and "MorphRig UI error:" in r[1]]
        assert not errors, f"Panel draw hit error boundary: {errors}"
        return rec.records

    _reset_scene()
    bpy.context.view_layer.objects.active = None
    empty_records = _draw_records()
    empty_labels = [r[1] for r in empty_records if r[0] == "label"]
    empty_props = {(r[1], r[2]) for r in empty_records if r[0] == "prop"}
    empty_ops = {r[1] for r in empty_records if r[0] == "operator"}
    assert any("Standalone mode" in t for t in empty_labels)
    assert any("Select a face mesh with shape keys" in t for t in empty_labels)
    assert ("separate_mouth_board", "Separate mouth board") in empty_props
    assert {"morphrig.scan_shape_keys", "morphrig.generate_board"}.issubset(empty_ops)
    assert "morphrig.toggle_kuchisync" not in empty_ops

    face_mesh, _mmd_arm, rig_arm = _build_two_armature_mmr_rig()
    bpy.context.scene.morphrig.target_mesh = face_mesh
    assert bpy.ops.morphrig.scan_shape_keys() == {"FINISHED"}
    assert bpy.context.scene.morphrig.show_preview_list is True

    preview_records = _draw_records()
    preview_labels = [r[1] for r in preview_records if r[0] == "label"]
    assert any(t.startswith("MMR linked: RIG-刻晴_arm (Head: head)") for t in preview_labels)
    assert any(t.startswith("Eyebrows:") for t in preview_labels)
    assert any("[Eyebrows]" in t for t in preview_labels)

    bpy.context.scene.morphrig.target_mesh = None
    bpy.context.view_layer.objects.active = rig_arm
    arm_active_records = _draw_records()
    arm_active_labels = [r[1] for r in arm_active_records if r[0] == "label"]
    assert any(t.startswith("MMR linked: RIG-刻晴_arm (Head: head)") for t in arm_active_labels)
    assert bpy.context.scene.morphrig.target_mesh is None

    bpy.context.scene.morphrig.target_mesh = face_mesh
    assert bpy.ops.morphrig.generate_board() == {"FINISHED"}
    board_records = _draw_records()
    board_ops = {r[1] for r in board_records if r[0] == "operator"}
    board_op_labels = {(r[1], r[2]) for r in board_records if r[0] == "operator"}
    expected_box3_ops = {
        "morphrig.toggle_kuchisync",
        "morphrig.reset_sliders",
        "morphrig.key_all_sliders",
        "morphrig.clear_keyframes",
        "morphrig.rebuild_board",
        "morphrig.remove_board",
    }
    assert expected_box3_ops.issubset(board_ops), f"Missing Box 3 ops: {expected_box3_ops - board_ops}"
    assert ("morphrig.toggle_kuchisync", "KuchiSync passthrough (release vowel drivers)") in board_op_labels

    assert rig_builder.remove_boards_for_mesh(bpy.context, face_mesh) == 2
    assert rig_builder.find_board_for_mesh(bpy.context, face_mesh) is None
    print("[Stage 8] PASS: safe_icon lookup + MORPHRIG_PT_main_panel.draw across all 4 UI states")


def run_all():
    test_startup_and_mmr_bridge_fallback()
    test_multilingual_semantic_mapper()
    test_procedural_board_and_text_mesh_generation()
    test_fader_to_shapekey_evaluation()
    test_kuchisync_passthrough()
    test_clean_removal()
    test_two_armature_mmr_bridge()
    test_safe_icon_and_panel_draw()
    _reset_scene()
    print("ALL 8 MORPHRIG TEST STAGES PASSED")


if __name__ == "__main__":
    import traceback

    try:
        run_all()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
