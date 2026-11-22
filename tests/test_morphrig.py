# SPDX-License-Identifier: GPL-3.0-or-later

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
    from morphrig import compat, rig_builder

    mesh_obj, mmr_arm = _build_board_fixture()
    board_arm = rig_builder.find_board_for_mesh(bpy.context, mesh_obj)
    assert board_arm is not None
    assert board_arm.name.startswith("MorphRig_Board_")
    assert board_arm.type == "ARMATURE"

    assert board_arm.parent == mmr_arm
    assert board_arm.parent_type == "BONE"
    assert board_arm.parent_bone == "c_head.x"

    collection_names = {c.name for c in board_arm.data.collections}
    for expected in ("Board", "Tracks", "Eyebrows", "Eyes", "Lips", "Vowels", "Emotes"):
        assert expected in collection_names, f"Missing bone collection: {expected}"

    label_objs = [o for o in bpy.data.objects if o.name.startswith("MorphRig_Labels_")]
    assert len(label_objs) == 1
    labels_obj = label_objs[0]
    assert labels_obj.type == "MESH"
    assert labels_obj.hide_select is True
    assert labels_obj.parent == board_arm
    assert labels_obj.parent_type == "BONE"
    assert labels_obj.parent_bone == "Board_Root"
    assert len(labels_obj.data.vertices) > 0

    track_bones = [b for b in board_arm.data.bones if b.name.startswith("Track_")]
    assert len(track_bones) > 0
    for tb in track_bones:
        assert tb.hide_select is True

    fader_pbones = [pb for pb in board_arm.pose.bones if pb.name.startswith("Fader_")]
    assert len(fader_pbones) > 0
    track_height = float(board_arm["morphrig_track_height"])
    for pb in fader_pbones:
        assert tuple(pb.lock_location) == (True, False, True)
        assert tuple(pb.lock_rotation) == (True, True, True)
        assert tuple(pb.lock_scale) == (True, True, True)
        limit_cons = [c for c in pb.constraints if c.type == "LIMIT_LOCATION"]
        assert len(limit_cons) == 1
        con = limit_cons[0]
        assert con.owner_space == "LOCAL"
        assert con.use_transform_limit is True
        assert con.use_min_y is True and abs(con.min_y) < 1e-6
        assert con.use_max_y is True and abs(con.max_y - track_height) < 1e-6
        assert con.use_min_x is True and con.use_max_x is True
        assert con.use_min_z is True and con.use_max_z is True

    drivers = list(mesh_obj.data.shape_keys.animation_data.drivers)
    assert len(drivers) > 0
    for fc in drivers:
        drv = fc.driver
        assert drv.type == "AVERAGE"
        assert len(drv.variables) == 1
        var = drv.variables[0]
        assert var.type == "TRANSFORMS"
        tgt = var.targets[0]
        assert tgt.id == board_arm
        assert tgt.transform_type == "LOC_Y"
        assert tgt.transform_space == "LOCAL_SPACE"
        gen_mods = [m for m in fc.modifiers if m.type == "GENERATOR"]
        assert len(gen_mods) == 1
        assert gen_mods[0].mode == "POLYNOMIAL"
        assert gen_mods[0].poly_order == 1

    fader_pbones[0].location.y = track_height * 0.5
    assert bpy.ops.morphrig.key_all_sliders() == {"FINISHED"}
    assert board_arm.animation_data is not None and board_arm.animation_data.action is not None
    keyed_fcurves = list(compat.iter_action_fcurves(board_arm.animation_data.action))
    assert len(keyed_fcurves) > 0

    assert bpy.ops.morphrig.reset_sliders() == {"FINISHED"}
    for pb in fader_pbones:
        assert abs(pb.location.y) < 1e-6

    assert bpy.ops.morphrig.clear_keyframes() == {"FINISHED"}
    remaining_fcurves = [
        fc for fc in compat.iter_action_fcurves(board_arm.animation_data.action)
        if fc.data_path.endswith(".location")
    ]
    assert len(remaining_fcurves) == 0

    assert bpy.ops.morphrig.scan_shape_keys() == {"FINISHED"}
    settings = bpy.context.scene.morphrig
    assert settings.last_scanned_mesh == mesh_obj.name
    assert len(settings.scanned_items) > 0
    assert settings.show_preview_list is True

    assert bpy.ops.morphrig.rebuild_board() == {"FINISHED"}
    rebuilt_board = rig_builder.find_board_for_mesh(bpy.context, mesh_obj)
    assert rebuilt_board is not None
    assert len(rig_builder.find_all_boards()) == 1
    print("[Stage 3] PASS: procedural board, collections, merged labels, constraints, drivers, keying")


def _find_fader_bone_name(board_arm, target_shape_key):
    fader_map = json.loads(board_arm["morphrig_fader_map"])
    for bone_name, info in fader_map.items():
        if info.get("shape_key") == target_shape_key:
            return bone_name
    raise AssertionError(f"Missing fader bone for shape key {target_shape_key}")


def test_fader_to_shapekey_evaluation():
    from morphrig import rig_builder

    mesh_obj, _ = _build_board_fixture()
    board_arm = rig_builder.find_board_for_mesh(bpy.context, mesh_obj)
    track_height = float(board_arm["morphrig_track_height"])

    for target_sk in ("怒り右", "まばたき"):
        fader_name = _find_fader_bone_name(board_arm, target_sk)
        board_arm.pose.bones[fader_name].location.y = track_height

    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    eval_mesh = mesh_obj.evaluated_get(depsgraph)

    for target_sk in ("怒り右", "まばたき"):
        val = eval_mesh.data.shape_keys.key_blocks[target_sk].value
        assert abs(val - 1.0) < 1e-4, f"Expected {target_sk} == 1.0, got {val}"

    eval_labels = next(o for o in bpy.data.objects if o.name.startswith("MorphRig_Labels_")).evaluated_get(depsgraph)
    eval_board = board_arm.evaluated_get(depsgraph)
    first_v_world = eval_labels.matrix_world @ eval_labels.data.vertices[0].co
    board_origin = eval_board.matrix_world.translation
    assert (first_v_world - board_origin).length < 2.0, (
        f"Labels drifted from board origin: {first_v_world} vs {board_origin}"
    )
    print("[Stage 4] PASS: pose fader location.y -> evaluated shape key value == 1.0")


def test_kuchisync_passthrough():
    from morphrig import rig_builder

    mesh_obj, _ = _build_board_fixture()
    board_arm = rig_builder.find_board_for_mesh(bpy.context, mesh_obj)
    track_height = float(board_arm["morphrig_track_height"])

    for target_sk in ("怒り右", "まばたき"):
        board_arm.pose.bones[_find_fader_bone_name(board_arm, target_sk)].location.y = track_height

    assert bpy.ops.morphrig.toggle_kuchisync() == {"FINISHED"}
    assert bpy.context.scene.morphrig.kuchisync_passthrough is True

    drivers_by_path = {
        fc.data_path: fc for fc in mesh_obj.data.shape_keys.animation_data.drivers
    }
    for vowel_sk in ("あ２", "い１", "う", "え", "お"):
        dp = f'key_blocks["{vowel_sk}"].value'
        assert dp in drivers_by_path
        assert drivers_by_path[dp].mute is True, f"Vowel driver should be muted: {vowel_sk}"

    for active_sk in ("まばたき", "怒り右"):
        dp = f'key_blocks["{active_sk}"].value'
        assert drivers_by_path[dp].mute is False, f"Non-vowel driver should stay active: {active_sk}"

    mesh_obj.data.shape_keys.key_blocks["あ２"].value = 0.75
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    eval_mesh = mesh_obj.evaluated_get(depsgraph)
    assert abs(eval_mesh.data.shape_keys.key_blocks["あ２"].value - 0.75) < 1e-4
    assert abs(eval_mesh.data.shape_keys.key_blocks["まばたき"].value - 1.0) < 1e-4

    assert bpy.ops.morphrig.toggle_kuchisync() == {"FINISHED"}
    assert bpy.context.scene.morphrig.kuchisync_passthrough is False
    for vowel_sk in ("あ２", "い１", "う", "え", "お"):
        dp = f'key_blocks["{vowel_sk}"].value'
        assert drivers_by_path[dp].mute is False, f"Vowel driver should be unmuted: {vowel_sk}"
    print("[Stage 5] PASS: KuchiSync passthrough mutes vowels while keeping non-vowels active")


def test_clean_removal():
    mesh_obj, _ = _build_board_fixture()
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

    anim_data = mesh_obj.data.shape_keys.animation_data
    remaining_drivers = list(anim_data.drivers) if anim_data else []
    assert not remaining_drivers, f"Leftover shape key drivers: {remaining_drivers}"
    print("[Stage 6] PASS: clean removal with zero orphan boards, labels, widgets, or drivers")


def run_all():
    test_startup_and_mmr_bridge_fallback()
    test_multilingual_semantic_mapper()
    test_procedural_board_and_text_mesh_generation()
    test_fader_to_shapekey_evaluation()
    test_kuchisync_passthrough()
    test_clean_removal()
    _reset_scene()
    print("ALL 6 MORPHRIG TEST STAGES PASSED")


if __name__ == "__main__":
    run_all()
