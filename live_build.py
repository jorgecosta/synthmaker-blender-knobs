# SynthMaker Blender knobs · Copyright (c) 2026 ViDesk Ltd · MIT licence (see LICENSE beside this file)
"""Builds the aluminium knob in Blender's interface step by step, as someone would live, for the tutorial's screen
recording (Tools/recorder records the window). Each step waits, says what it does in the 3D view's header and
does it with the operators a person would use, so the viewport shows it happening.

    Blender --factory-startup --python live_build.py -- [--pace 1.0] [--quit] [--shots DIR]

--pace scales every pause (2.0 = twice as slow); --quit closes Blender at the end; --shots saves Blender's own
screenshot of its window after each step (no macOS permission needed), to check a run without recording it.
The steps: a cylinder, rings cut into its side, a bevel on the top edge, a knurl from Geometry Nodes, smooth
shading, brushed aluminium, the studio lights and the top camera, the sweep keyed over 128 frames, then the sweep
played in the rendered viewport. The full strip renders through the studio queue, never from this session.
"""

import bpy, bmesh, math, os, sys, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import knob as K  # noqa: E402  (the same materials, lights and camera as the rendered strips)


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--pace", type=float, default=1.0)
    p.add_argument("--quit", action="store_true")
    p.add_argument("--shots", default="")
    p.add_argument("--ui-scale", type=float, default=1.35)
    # A take timed to Ned's lines (Controls 1): [[seconds, "step"], …] from the moment `--go` appears; the start's
    # wall-clock time goes to `--t0-out`, so the cut can line the take up with the narration.
    p.add_argument("--timeline", default="")
    p.add_argument("--go", default="")
    p.add_argument("--t0-out", default="")
    return p.parse_args(argv)


A = args()


def view3d():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                region = next(r for r in area.regions if r.type == "WINDOW")
                return window, area, region
    return None, None, None


def in_view(op, **kw):
    window, area, region = view3d()
    with bpy.context.temp_override(window=window, area=area, region=region):
        return op(**kw)


def say(text):
    if A.timeline:   # a take for a video: Ned names the steps, so no step numbers
        text = text.split(" · ", 1)[-1] if text[:1].isdigit() else text
    _, area, _ = view3d()
    if area:
        area.header_text_set(text)
    print("STEP", text)


def knob_object():
    return bpy.data.objects.get("Knob")


# ---------------------------------------------------------------- the steps

def clear():
    # A fresh start file closes the splash screen (it closes on any file load); the timer is persistent, so it lives on.
    bpy.ops.wm.read_homefile(use_empty=False)
    # Bigger interface text, so the video reads on a phone (`--ui-scale`, 1.35 by default).
    bpy.context.preferences.view.ui_scale = A.ui_scale
    say("SynthMaker · a knob from scratch")
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    _, area, _ = view3d()
    space = area.spaces.active
    space.shading.type = "SOLID"
    space.overlay.show_wireframes = False
    in_view(bpy.ops.view3d.view_axis, type="FRONT")


def cylinder():
    say("1 · Add a cylinder: 384 sides, radius 1, height 0.55")
    bpy.ops.mesh.primitive_cylinder_add(vertices=384, radius=1.0, depth=0.55, location=(0, 0, 0.275))
    o = bpy.context.object
    o.name = "Knob"
    # The base at the origin, so heights inside (the knurl's grip, the engraved line) read as on the strips.
    bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)
    in_view(bpy.ops.view3d.view_axis, type="FRONT")
    in_view(bpy.ops.view3d.view_selected)
    in_view(bpy.ops.view3d.view_orbit, angle=math.radians(25), type="ORBITUP")


def rings():
    say("2 · Cut rings into the side, so the knurl has edges to move")
    o = knob_object()
    bm = bmesh.new()
    bm.from_mesh(o.data)
    side = [e for e in bm.edges if abs(e.verts[0].co.z - e.verts[1].co.z) > 0.3]
    bmesh.ops.subdivide_edges(bm, edges=side, cuts=10, use_grid_fill=False)
    bm.to_mesh(o.data)
    bm.free()
    _, area, _ = view3d()
    area.spaces.active.overlay.show_wireframes = True


def bevel():
    say("3 · Bevel the top edge: the polished chamfer that catches the light")
    o = knob_object()
    m = o.modifiers.new("Bevel", "BEVEL")
    m.width = 0.045
    m.segments = 4
    m.limit_method = "ANGLE"
    m.angle_limit = math.radians(60)


def knurl():
    say("4 · Knurl it with Geometry Nodes: 60 teeth, pushed in along the radius, only on the grip")
    o = knob_object()
    ng = bpy.data.node_groups.new("Knurl", "GeometryNodeTree")
    ng.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    n, l = ng.nodes, ng.links
    gin, gout = n.new("NodeGroupInput"), n.new("NodeGroupOutput")
    pos = n.new("GeometryNodeInputPosition")
    sep = n.new("ShaderNodeSeparateXYZ")
    l.new(pos.outputs[0], sep.inputs[0])

    def m(op, a, b=None):
        node = n.new("ShaderNodeMath")
        node.operation = op
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                node.inputs[i].default_value = v
            else:
                l.new(v, node.inputs[i])
        return node.outputs[0]

    theta = m("ARCTAN2", sep.outputs["X"], sep.outputs["Y"])
    teeth = m("FRACT", m("MULTIPLY", theta, 60 / (2 * math.pi)))
    tri = m("SUBTRACT", 1.0, m("ABSOLUTE", m("SUBTRACT", m("MULTIPLY", teeth, 2.0), 1.0)))
    grip = n.new("ShaderNodeMapRange")
    grip.interpolation_type = "SMOOTHSTEP"
    l.new(sep.outputs["Z"], grip.inputs["Value"])
    grip.inputs["From Min"].default_value, grip.inputs["From Max"].default_value = 0.06, 0.12
    top = n.new("ShaderNodeMapRange")
    top.interpolation_type = "SMOOTHSTEP"
    l.new(sep.outputs["Z"], top.inputs["Value"])
    top.inputs["From Min"].default_value, top.inputs["From Max"].default_value = 0.47, 0.42
    depth = m("MULTIPLY", m("MULTIPLY", tri, -0.035), m("MULTIPLY", grip.outputs[0], top.outputs[0]))
    radial = n.new("ShaderNodeCombineXYZ")
    l.new(sep.outputs["X"], radial.inputs["X"])
    l.new(sep.outputs["Y"], radial.inputs["Y"])
    norm = n.new("ShaderNodeVectorMath")
    norm.operation = "NORMALIZE"
    l.new(radial.outputs[0], norm.inputs[0])
    scale = n.new("ShaderNodeVectorMath")
    scale.operation = "SCALE"
    l.new(norm.outputs[0], scale.inputs[0])
    l.new(depth, scale.inputs["Scale"])
    setp = n.new("GeometryNodeSetPosition")
    l.new(gin.outputs[0], setp.inputs["Geometry"])
    l.new(scale.outputs[0], setp.inputs["Offset"])
    l.new(setp.outputs[0], gout.inputs[0])
    mod = o.modifiers.new("Knurl", "NODES")
    mod.node_group = ng
    in_view(bpy.ops.view3d.view_orbit, angle=math.radians(-10), type="ORBITUP")


def smooth():
    say("5 · Shade smooth by angle: soft teeth, a crisp chamfer")
    _, area, _ = view3d()
    area.spaces.active.overlay.show_wireframes = False
    o = knob_object()
    o.data.polygons.foreach_set("use_smooth", [True] * len(o.data.polygons))
    o.data.update()
    try:
        bpy.ops.object.shade_smooth_by_angle(angle=math.radians(38))
    except Exception as e:
        print("smooth by angle:", e)


def material():
    say("6 · Brushed aluminium: concentric brushing, an engraved line along +Y")
    o = knob_object()
    o.data.materials.clear()
    o.data.materials.append(K.brushed_alu("Brushed", line_r=(0.28, 0.80), zmin=0.53))
    _, area, _ = view3d()
    area.spaces.active.shading.type = "MATERIAL"


def studio():
    say("7 · The studio: a key light from the top left, softboxes for the metal, a shadow catcher, a top camera")
    K.world(bpy.context.scene)
    K.lights()
    K.shadow_catcher()
    K.camera("top", 2.75)
    s = bpy.context.scene
    s.render.film_transparent = True
    s.view_settings.view_transform = "Standard"
    s.render.engine = "BLENDER_EEVEE"
    s.render.resolution_x = s.render.resolution_y = 256
    # In the viewport: no shadow catcher plane (Eevee shows it as a white floor) and no overlays; the render keeps both.
    bpy.data.objects["ShadowCatcher"].hide_set(True)
    for name in ("CardL", "CardR", "CardF"):
        bpy.data.objects[name].hide_set(True)
    _, area, _ = view3d()
    space = area.spaces.active
    space.shading.type = "RENDERED"
    space.overlay.show_overlays = False
    in_view(bpy.ops.view3d.view_camera)
    in_view(bpy.ops.view3d.view_center_camera)


def sweep():
    say("8 · Key the sweep: frame 1 at 7 o'clock, frame 128 at 5 o'clock, linear")
    s = bpy.context.scene
    s.frame_start, s.frame_end = 1, 128
    bpy.context.preferences.edit.keyframe_new_interpolation_type = "LINEAR"
    o = knob_object()
    for f, v in ((1, 0.0), (128, 1.0)):
        o.rotation_euler.z = K.SWEEP / 2 - K.SWEEP * v
        o.keyframe_insert("rotation_euler", index=2, frame=f)
    s.frame_set(1)


def play():
    say("9 · Play it: every frame is one knob position")
    window, _, _ = view3d()
    if window and not window.screen.is_animation_playing:
        in_view(bpy.ops.screen.animation_play)


def render():
    """One frame rendered as the strip is (Cycles, transparent, the shadow on its catcher), shown full window. The
    full 128-frame strip renders through the studio's queue, never here."""
    say("10 · Render: transparent, with its shadow; every frame becomes one row of the filmstrip")
    window, _, _ = view3d()
    if window and window.screen.is_animation_playing:
        in_view(bpy.ops.screen.animation_cancel, restore_frame=False)
    s = bpy.context.scene
    s.frame_set(44)
    K.use_engine(s, "cycles", 48, 512)
    s.render.film_transparent = True
    s.view_settings.view_transform = "Standard"
    bpy.context.preferences.view.render_display_type = "AREA"   # in the 3D view itself: "SCREEN" swaps the window, and the recording loses it
    _, area, region = view3d()
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.render.render("INVOKE_DEFAULT")

    def fit():
        """The finished frame filling the view, not 512 pixels lost in the middle."""
        for w in bpy.context.window_manager.windows:
            for a in w.screen.areas:
                if a.type == "IMAGE_EDITOR":
                    r = next(x for x in a.regions if x.type == "WINDOW")
                    with bpy.context.temp_override(window=w, area=a, region=r):
                        try:
                            bpy.ops.image.view_all(fit_view=True)
                        except Exception as e:
                            print("view_all:", e)
        return None
    bpy.app.timers.register(fit, first_interval=0.6)
    bpy.app.timers.register(fit, first_interval=4.0)


def back():
    """Out of the render view, and the knob turning again in the viewport."""
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "IMAGE_EDITOR":
                with bpy.context.temp_override(window=window, area=area):
                    try:
                        bpy.ops.render.view_cancel()
                    except Exception as e:
                        print("view_cancel:", e)
                break
    s = bpy.context.scene
    s.render.engine = "BLENDER_EEVEE"
    bpy.app.timers.register(lambda: (play(), None)[1], first_interval=0.4)
    say("Free in the description: the script that builds this knob")


def stop():
    window, _, _ = view3d()
    if window and window.screen.is_animation_playing:
        in_view(bpy.ops.screen.animation_cancel, restore_frame=False)
    say("A filmstrip of 128 frames, ready for SynthMaker")


STEPS = [(clear, 1.0), (cylinder, 3.0), (rings, 2.5), (bevel, 2.5), (knurl, 3.5), (smooth, 2.5), (material, 3.5),
         (studio, 4.0), (sweep, 2.5), (play, 6.0), (stop, 2.0)]
state = {"i": 0}


def tick():
    i = state["i"]
    if i >= len(STEPS):
        if A.quit:
            bpy.ops.wm.quit_blender()
        return None
    step, pause = STEPS[i]
    try:
        step()
    except Exception as e:
        print("STEP FAILED", step.__name__, repr(e))
    if A.shots:
        os.makedirs(A.shots, exist_ok=True)
        path = os.path.join(A.shots, f"step_{i:02d}_{step.__name__}.png")
        # Blender's own copy of its window: no screen-recording permission involved.
        def shot(path=path):
            window, area, region = view3d()
            with bpy.context.temp_override(window=window):
                bpy.ops.screen.screenshot(filepath=path)
            return None
        bpy.app.timers.register(shot, first_interval=min(1.2, pause * A.pace * 0.8))
    state["i"] = i + 1
    return pause * A.pace


NAMED = {f.__name__: f for f in (clear, cylinder, rings, bevel, knurl, smooth, material, studio, sweep, play, render, back, stop)}


def timed():
    """The timeline mode: wait for the go file, then run each named step at its time."""
    import json, time
    plan = json.load(open(A.timeline))
    if A.go and not os.path.exists(A.go):
        return 0.05
    t0 = time.time()
    if A.t0_out:
        open(A.t0_out, "w").write(f"{t0:.4f}\n")
    for at, name in plan:
        def run(name=name):
            try:
                NAMED[name]()
            except Exception as e:
                print("STEP FAILED", name, repr(e))
            if name == "stop" and A.quit:
                bpy.app.timers.register(lambda: (bpy.ops.wm.quit_blender(), None)[1], first_interval=1.0)
            return None
        bpy.app.timers.register(run, first_interval=max(0.01, at), persistent=True)
    return None


if A.timeline:
    bpy.app.timers.register(timed, first_interval=1.0, persistent=True)
else:
    bpy.app.timers.register(tick, first_interval=1.5, persistent=True)
