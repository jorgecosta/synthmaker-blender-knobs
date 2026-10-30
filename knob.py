# SynthMaker Blender knobs · Copyright (c) 2026 ViDesk Ltd · MIT licence (see LICENSE beside this file)
"""SynthMaker controls: procedural knobs and switches rendered as filmstrips (bpy, Blender 5.2).

One parameterised script builds a control from scratch, keys its sweep, saves the .blend and renders the frames
as transparent PNGs, then joins them into a vertical filmstrip (frame 0 at the top, the KnobMan / JUCE / HISE
convention). Everything is made here: no downloaded models, textures or HDRIs, so the output is ours to ship.

    Blender -b --factory-startup --python knob.py -- --look A --cam top --frames 128 --size 256 --out DIR

Looks:
    A  brushed aluminium: concentric-brushed top, polished chamfer, straight knurl, engraved black line
    B  vintage bakelite: fluted brown-black body with a skirt, spun-nickel cap, engraved line
    C  modern dark: soft-touch body, glowing indicator, a static value ring that lights up to the value
    D  drive pedal: a chunky soft-touch knob on a skirt, a white pointer line over its top and skirt, and a printed
       0-10 scale around it that stays still while the knob turns (Controls 2, the Drive set)
    S  bat-handle toggle switch (2 frames: off = lever down, on = lever up)
    R  look D made hyper-real (30 Oct): satin moulded plastic with micro-roughness, polished ridges and a faint
       smudge, a spun-aluminium cap, the white pointer paint-filled in a groove over the top and down the skirt, a
       screen-printed 0-10 scale (Inter numerals); always quality 2, AgX colour (highlights roll off, never clip)
    RT the three-way selector in look R: a satin-black chicken head with rounded edges on a spun-aluminium base
    T  a three-way selector: a chicken-head pointer over three printed dots (3 frames: left, middle, right;
       Controls 2's Soft / Hard / Fold)
    P  a faceplate (12:5) of dark anodised, brushed aluminium with four screws and an engraved border: an
       Image to put behind a module's knobs (one frame, 960 x 400)

Cameras: top (orthographic, straight down) or iso (orthographic, tilted 30 degrees from vertical).
Rendering: Cycles, transparent film, a shadow catcher so the soft shadow lands in the alpha, the Standard view
transform (not AgX/Filmic: UI art must keep its colours; look R alone uses AgX, being black, white and aluminium)
and sRGB PNG with straight alpha.
The lights never move, so highlights stay put while the knob turns: what makes a rendered strip look real
compared with one image rotated in code.
"""

import bpy, bmesh, math, os, sys, argparse
import numpy as np

SWEEP = math.radians(300)          # min at 7 o'clock, max at 5 o'clock
Q = 1                              # look version: 1 = the first strips, 2 = the hyper-real round (--quality 2)


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--look", default="A", choices=["A", "B", "C", "D", "R", "RT", "S", "T", "P"])
    p.add_argument("--cam", default="top", choices=["top", "iso"])
    p.add_argument("--frames", type=int, default=128)
    p.add_argument("--size", type=int, default=256)
    p.add_argument("--samples", type=int, default=160)
    p.add_argument("--engine", default="cycles", choices=["cycles", "eevee"])
    p.add_argument("--still", type=int, default=-1, help="render only this frame index (0-based) and stop")
    p.add_argument("--out", required=True)
    p.add_argument("--blend", default="", help="save the scene here before rendering")
    p.add_argument("--glow", default="0.10,0.78,1.0", help="look C's glow colour, linear RGB")
    p.add_argument("--view", default="", help="look R's view transform: agx (its default), agx-punchy, filmic or standard")
    p.add_argument("--no-strip", action="store_true", help="render the frames only (strips.swift joins and scales them)")
    p.add_argument("--quality", type=int, default=1, choices=[1, 2],
                   help="2: polar brushing, scratches, a smudge, grime in the knurl, a rim light, long-lens cameras, more samples")
    return p.parse_args(argv)


# ---------------------------------------------------------------- scene

def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    s = bpy.context.scene
    s.render.film_transparent = True
    s.view_settings.view_transform = "Standard"
    s.view_settings.look = "None"
    s.view_settings.exposure = 0
    s.view_settings.gamma = 1
    s.display_settings.display_device = "sRGB"
    s.render.image_settings.file_format = "PNG"
    s.render.image_settings.color_mode = "RGBA"
    s.render.image_settings.color_depth = "8"
    s.render.image_settings.compression = 90
    return s


def use_engine(s, engine, samples, size):
    s.render.resolution_x = s.render.resolution_y = size
    s.render.resolution_percentage = 100
    if engine == "eevee":
        s.render.engine = "BLENDER_EEVEE"
        s.eevee.taa_render_samples = 32
        return
    s.render.engine = "CYCLES"
    c = s.cycles
    c.samples = samples
    c.use_adaptive_sampling = True
    c.adaptive_threshold = 0.004
    c.use_denoising = True
    c.denoiser = "OPENIMAGEDENOISE"
    c.denoising_prefilter = "ACCURATE"
    c.max_bounces = 8
    c.glossy_bounces = 6
    c.transparent_max_bounces = 8
    c.filter_width = 1.2
    c.sample_clamp_indirect = 8
    try:  # GPU only (Metal), as the studio's queue jobs do
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.compute_device_type = "METAL"
        prefs.get_devices()
        metal = [d for d in prefs.devices if d.type == "METAL"]
        for d in prefs.devices:
            d.use = d.type == "METAL"
        if metal:
            c.device = "GPU"
            print("DEVICES METAL", [d.name for d in metal])
    except Exception as e:
        print("DEVICES CPU", e)


def world(s):
    """A dark studio: a soft gradient from a dim floor to a brighter ceiling, for metal to reflect."""
    w = bpy.data.worlds.new("Studio")
    s.world = w
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.35
    ramp.color_ramp.elements[0].color = (0.006, 0.006, 0.007, 1)
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color = (0.30, 0.30, 0.31, 1)
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.inputs["From Min"].default_value = -1
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = 1.0
    out = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(tc.outputs["Generated"], sep.inputs[0])
    nt.links.new(sep.outputs["Z"], mr.inputs["Value"])
    nt.links.new(mr.outputs["Result"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
    nt.links.new(bg.outputs[0], out.inputs[0])


def look_at(obj, target):
    d = (obj.location - target)
    obj.rotation_euler = d.to_track_quat("Z", "Y").to_euler()


def area_light(name, loc, size, energy, color=(1, 1, 1), size_y=None):
    from mathutils import Vector
    l = bpy.data.lights.new(name, "AREA")
    l.energy = energy
    l.color = color
    if size_y:
        l.shape = "RECTANGLE"
        l.size, l.size_y = size, size_y
    else:
        l.shape = "DISK"
        l.size = size
    o = bpy.data.objects.new(name, l)
    bpy.context.scene.collection.objects.link(o)
    o.location = loc
    look_at(o, Vector((0, 0, 0.3)))
    return o


def card(name, loc, sx, sy, strength):
    """An emissive softbox the camera never sees: only reflections pick it up."""
    from mathutils import Vector
    bpy.ops.mesh.primitive_plane_add(size=1, location=loc)
    o = bpy.context.object
    o.name = name
    o.scale = (sx, sy, 1)
    look_at(o, Vector((0, 0, 0.3)))
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    e = nt.nodes.new("ShaderNodeEmission")
    e.inputs["Strength"].default_value = strength
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(e.outputs[0], out.inputs[0])
    o.data.materials.append(m)
    o.visible_camera = False
    o.visible_diffuse = False
    o.visible_shadow = False
    o.visible_transmission = False
    o.visible_volume_scatter = False
    return o


def lights():
    # Key from the top left (UI convention), a soft overhead that only lights (metal never mirrors it, or a flat
    # top seen from above goes white), a cool fill from the right, a warm kicker low behind.
    area_light("Key", (-3.2, 3.4, 5.2), 3.0, 300)
    top = area_light("Top", (0.0, 0.6, 7.0), 7.0, 110)
    top.visible_glossy = False
    area_light("Fill", (4.5, -1.8, 2.6), 4.0, 45, (0.85, 0.92, 1.0))
    area_light("Kick", (0.5, 4.8, 1.2), 2.5, 45, (1.0, 0.92, 0.82))
    # Softboxes for metal: a long strip upper left, a square upper right, a low strip in front.
    card("CardL", (-3.0, 2.0, 3.4), 1.2, 5.0, 1.3)
    card("CardR", (3.0, 2.6, 3.0), 2.4, 2.4, 0.5)
    card("CardF", (0.0, -4.0, 2.2), 6.0, 0.8, 0.25)


def shadow_catcher():
    bpy.ops.mesh.primitive_plane_add(size=12, location=(0, 0, 0))
    o = bpy.context.object
    o.name = "ShadowCatcher"
    o.is_shadow_catcher = True
    return o


def camera(kind, scale, target_z=0.28):
    from mathutils import Vector
    c = bpy.data.cameras.new("Cam")
    c.type = "ORTHO"
    c.ortho_scale = scale
    c.clip_end = 100
    o = bpy.data.objects.new("Cam", c)
    bpy.context.scene.collection.objects.link(o)
    if kind == "top":
        o.location = (0, 0, 20)
        o.rotation_euler = (0, 0, 0)
    else:
        tilt = math.radians(30)
        o.location = (0, -20 * math.sin(tilt), target_z + 20 * math.cos(tilt))
        o.rotation_euler = (tilt, 0, 0)
    bpy.context.scene.camera = o
    return o


# ---------------------------------------------------------------- geometry

def lathe(name, profile, segments, ridge=None, cap_top=True, cap_bottom=False, mat_of=None):
    """A solid of revolution around Z. `profile` is [(r, z, w)], bottom to top; w (0..1) is how much of
    `ridge(theta)` (an inward depth) applies on that ring: knurls and flutes. `mat_of(r, z)` picks a face's
    material slot from its centre."""
    bm = bmesh.new()
    rings = []
    for (r, z, w) in profile:
        ring = []
        for i in range(segments):
            t = 2 * math.pi * i / segments
            rr = r - (ridge(t) * w if ridge and w else 0)
            ring.append(bm.verts.new((rr * math.sin(t), rr * math.cos(t), z)))
        rings.append(ring)
    for a, b in zip(rings, rings[1:]):
        for i in range(segments):
            j = (i + 1) % segments
            bm.faces.new((a[i], a[j], b[j], b[i]))
    if cap_top:
        top = rings[-1]
        c = bm.verts.new((0, 0, profile[-1][1]))
        for i in range(segments):
            bm.faces.new((top[i], top[(i + 1) % segments], c))
    if cap_bottom:
        bot = rings[0]
        c = bm.verts.new((0, 0, profile[0][1]))
        for i in range(segments):
            bm.faces.new((bot[(i + 1) % segments], bot[i], c))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    if mat_of:
        for f in bm.faces:
            ctr = f.calc_center_median()
            f.material_index = mat_of(math.hypot(ctr.x, ctr.y), ctr.z)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    me.set_sharp_from_angle(angle=math.radians(38))
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


def fillet(p0, corner, p1, n=4, w=0.0):
    """A rounded corner from p0 through `corner` to p1 (a quadratic Bezier), as profile points."""
    pts = []
    for k in range(1, n):
        t = k / n
        r = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * corner[0] + t * t * p1[0]
        z = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * corner[1] + t * t * p1[1]
        pts.append((r, z, w))
    return pts


# ---------------------------------------------------------------- materials

def node_mat(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs[0], out.inputs[0])
    return m, nt, bsdf


def set_in(node, **kw):
    for k, v in kw.items():
        node.inputs[k.replace("_", " ")].default_value = v


def obj_coords(nt):
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Object"], sep.inputs[0])
    return tc, sep


def math_node(nt, op, a, b=None, c=None, clamp=False):
    n = nt.nodes.new("ShaderNodeMath")
    n.operation = op
    n.use_clamp = clamp
    for i, v in enumerate((a, b, c)):
        if v is None:
            continue
        if isinstance(v, (int, float)):
            n.inputs[i].default_value = v
        else:
            nt.links.new(v, n.inputs[i])
    return n.outputs[0]


def smooth_band(nt, x, lo, hi, soft):
    """1 inside [lo, hi], 0 outside, with soft edges."""
    a = nt.nodes.new("ShaderNodeMapRange")
    a.interpolation_type = "SMOOTHSTEP"
    nt.links.new(x, a.inputs["Value"])
    a.inputs["From Min"].default_value = lo - soft
    a.inputs["From Max"].default_value = lo + soft
    b = nt.nodes.new("ShaderNodeMapRange")
    b.interpolation_type = "SMOOTHSTEP"
    nt.links.new(x, b.inputs["Value"])
    b.inputs["From Min"].default_value = hi + soft
    b.inputs["From Max"].default_value = hi - soft
    return math_node(nt, "MULTIPLY", a.outputs[0], b.outputs[0])


def line_mask(nt, sep, half_width, r0, r1, zmin):
    """The indicator line: a thin band along +Y on the top face, in object space (it turns with the knob)."""
    ax = math_node(nt, "ABSOLUTE", sep.outputs["X"])
    across = smooth_band(nt, ax, -1, half_width, 0.006)
    along = smooth_band(nt, sep.outputs["Y"], r0, r1, 0.008)
    up = smooth_band(nt, sep.outputs["Z"], zmin, 10, 0.004)
    return math_node(nt, "MULTIPLY", math_node(nt, "MULTIPLY", across, along), up)


def concentric_bump(nt, tc, scale, strength, distortion=1.5):
    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.wave_type = "RINGS"
    wave.rings_direction = "Z"
    wave.inputs["Scale"].default_value = scale
    wave.inputs["Distortion"].default_value = distortion
    wave.inputs["Detail"].default_value = 3
    wave.inputs["Detail Scale"].default_value = 2.0
    nt.links.new(tc.outputs["Object"], wave.inputs["Vector"])
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 420
    nt.links.new(tc.outputs["Object"], noise.inputs["Vector"])
    mix = math_node(nt, "MULTIPLY_ADD", wave.outputs["Fac"], 0.8, noise.outputs["Fac"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = strength
    bump.inputs["Distance"].default_value = 0.02
    nt.links.new(mix, bump.inputs["Height"])
    return bump


def brushed_alu(name, engraved=True, line_r=(0.30, 0.84), zmin=0.5):
    m, nt, b = node_mat(name)
    tc, sep = obj_coords(nt)
    set_in(b, Metallic=1.0, Roughness=0.34, Anisotropic=0.85)
    tan = nt.nodes.new("ShaderNodeTangent")
    tan.direction_type = "RADIAL"
    tan.axis = "Z"
    nt.links.new(tan.outputs[0], b.inputs["Tangent"])
    bump = concentric_bump(nt, tc, 70, 0.22)
    base = nt.nodes.new("ShaderNodeMix")
    base.data_type = "RGBA"
    base.inputs[6].default_value = (0.64, 0.65, 0.67, 1)
    base.inputs[7].default_value = (0.012, 0.012, 0.013, 1)
    if engraved:
        mask = line_mask(nt, sep, 0.030, line_r[0], line_r[1], zmin)
        nt.links.new(mask, base.inputs["Factor"])
        nt.links.new(math_node(nt, "SUBTRACT", 1.0, mask), b.inputs["Metallic"])
        nt.links.new(math_node(nt, "MULTIPLY_ADD", mask, 0.31, 0.34), b.inputs["Roughness"])
        # The groove: the line sits lower than the brushed face.
        lb = nt.nodes.new("ShaderNodeBump")
        lb.invert = True
        lb.inputs["Strength"].default_value = 0.9
        lb.inputs["Distance"].default_value = 0.03
        nt.links.new(mask, lb.inputs["Height"])
        nt.links.new(bump.outputs["Normal"], lb.inputs["Normal"])
        nt.links.new(lb.outputs["Normal"], b.inputs["Normal"])
    else:
        nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    nt.links.new(base.outputs[2], b.inputs["Base Color"])
    return m


def metal(name, color, rough, aniso=0.0):
    m, nt, b = node_mat(name)
    set_in(b, Base_Color=(*color, 1), Metallic=1.0, Roughness=rough, Anisotropic=aniso)
    if aniso:
        tan = nt.nodes.new("ShaderNodeTangent")
        tan.direction_type = "RADIAL"
        tan.axis = "Z"
        nt.links.new(tan.outputs[0], b.inputs["Tangent"])
    return m


def bakelite(name):
    m, nt, b = node_mat(name)
    tc, sep = obj_coords(nt)
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 6
    noise.inputs["Detail"].default_value = 8
    nt.links.new(tc.outputs["Object"], noise.inputs["Vector"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.012, 0.006, 0.004, 1)
    ramp.color_ramp.elements[1].color = (0.040, 0.019, 0.009, 1)
    ramp.color_ramp.elements[0].position = 0.35
    ramp.color_ramp.elements[1].position = 0.70
    nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    set_in(b, Roughness=0.32, Coat_Weight=0.6, Coat_Roughness=0.10, Specular_IOR_Level=0.5)
    wob = nt.nodes.new("ShaderNodeTexNoise")
    wob.inputs["Scale"].default_value = 30
    nt.links.new(tc.outputs["Object"], wob.inputs["Vector"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.04
    nt.links.new(wob.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Coat Normal"])
    return m


def spun_cap(name, line_r, zmin):
    """Spun nickel: concentric machining, an engraved black line."""
    m, nt, b = node_mat(name)
    tc, sep = obj_coords(nt)
    set_in(b, Metallic=1.0, Roughness=0.22, Anisotropic=0.7)
    tan = nt.nodes.new("ShaderNodeTangent")
    tan.direction_type = "RADIAL"
    tan.axis = "Z"
    nt.links.new(tan.outputs[0], b.inputs["Tangent"])
    bump = concentric_bump(nt, tc, 110, 0.18, distortion=0.6)
    mask = line_mask(nt, sep, 0.028, line_r[0], line_r[1], zmin)
    base = nt.nodes.new("ShaderNodeMix")
    base.data_type = "RGBA"
    base.inputs[6].default_value = (0.80, 0.77, 0.70, 1)
    base.inputs[7].default_value = (0.010, 0.009, 0.008, 1)
    nt.links.new(mask, base.inputs["Factor"])
    nt.links.new(base.outputs[2], b.inputs["Base Color"])
    nt.links.new(math_node(nt, "SUBTRACT", 1.0, mask), b.inputs["Metallic"])
    nt.links.new(math_node(nt, "MULTIPLY_ADD", mask, 0.3, 0.22), b.inputs["Roughness"])
    lb = nt.nodes.new("ShaderNodeBump")
    lb.invert = True
    lb.inputs["Strength"].default_value = 0.8
    lb.inputs["Distance"].default_value = 0.03
    nt.links.new(mask, lb.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], lb.inputs["Normal"])
    nt.links.new(lb.outputs["Normal"], b.inputs["Normal"])
    return m


def soft_touch(name, rough=0.55, color=(0.022, 0.023, 0.027)):
    m, nt, b = node_mat(name)
    set_in(b, Base_Color=(*color, 1), Roughness=rough, Specular_IOR_Level=0.45, Sheen_Weight=0.25, Sheen_Roughness=0.4)
    tc, _ = obj_coords(nt)
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = 260
    nt.links.new(tc.outputs["Object"], n.inputs["Vector"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.06
    nt.links.new(n.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    return m


def glow_top(name, glow, line_r, zmin):
    """Look C's top: glossy dark dish with a glowing indicator line."""
    m, nt, b = node_mat(name)
    tc, sep = obj_coords(nt)
    set_in(b, Base_Color=(0.018, 0.019, 0.022, 1), Roughness=0.28, Specular_IOR_Level=0.6,
           Coat_Weight=0.3, Coat_Roughness=0.2)
    mask = line_mask(nt, sep, 0.034, line_r[0], line_r[1], zmin)
    b.inputs["Emission Color"].default_value = (*glow, 1)
    nt.links.new(math_node(nt, "MULTIPLY", mask, 9.0), b.inputs["Emission Strength"])
    return m


# ---------------------------------------------------------------- quality 2 (round 2, 28 Oct): the hyper-real pass

def use_engine_v2(s, samples):
    """More samples, a tighter noise threshold and a glossy filter against fireflies; the seed stays the same on
    every frame, so the noise left for the denoiser doesn't crawl as the knob turns."""
    c = s.cycles
    c.samples = max(samples, 768)
    c.adaptive_threshold = 0.0015
    c.adaptive_min_samples = 96
    c.blur_glossy = 0.15
    c.sample_clamp_indirect = 3
    c.seed = 7
    c.use_animated_seed = False
    c.filter_width = 1.0


def lights_v2():
    """A product-photo studio: a big soft key top left, a narrow hard rim strip behind (the bright line along the far
    edge), a cool fill, an overhead that only lights, and softboxes for the metal to mirror."""
    area_light("Key", (-3.4, 3.0, 5.6), 3.6, 390)
    area_light("Rim", (0.4, 5.2, 2.6), 6.0, 260, (1.0, 0.97, 0.92), size_y=0.5)   # long side horizontal
    top = area_light("Top", (0.0, 0.4, 7.0), 7.0, 70)
    top.visible_glossy = False
    area_light("Fill", (4.6, -2.2, 2.4), 4.0, 40, (0.84, 0.91, 1.0))
    card("CardL", (-3.2, 1.6, 3.2), 1.0, 5.0, 1.15)
    card("CardR", (3.2, 2.2, 3.4), 2.0, 2.6, 0.45)
    card("CardF", (0.0, -4.2, 2.0), 6.0, 0.7, 0.14)
    card("CardRim", (0.0, 4.8, 1.4), 6.0, 0.3, 1.6)


def camera_v2(kind, scale, target_z=0.28):
    """A long lens from far away, as product shots are taken: top-down at 135 mm (a sliver of the side shows all
    round), the tilted view at 100 mm. Never any depth of field."""
    from mathutils import Vector
    c = bpy.data.cameras.new("Cam")
    c.type = "PERSP"
    c.lens = 135 if kind == "top" else 100
    c.sensor_width = 36
    c.dof.use_dof = False
    c.clip_end = 200
    o = bpy.data.objects.new("Cam", c)
    bpy.context.scene.collection.objects.link(o)
    d = c.lens * scale / c.sensor_width            # distance that frames `scale` units across
    if kind == "top":
        o.location = (0, 0, target_z + d)
        o.rotation_euler = (0, 0, 0)
    else:
        tilt = math.radians(30)
        o.location = (0, -d * math.sin(tilt), target_z + d * math.cos(tilt))
        o.rotation_euler = (tilt, 0, 0)
    bpy.context.scene.camera = o
    return o


def polar(nt, tc):
    """(r, cos θ, sin θ) of the object point: brushing that goes round the centre with no seam."""
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Object"], sep.inputs[0])
    xy = nt.nodes.new("ShaderNodeCombineXYZ")
    nt.links.new(sep.outputs["X"], xy.inputs["X"])
    nt.links.new(sep.outputs["Y"], xy.inputs["Y"])
    ln = nt.nodes.new("ShaderNodeVectorMath")
    ln.operation = "LENGTH"
    nt.links.new(xy.outputs[0], ln.inputs[0])
    nrm = nt.nodes.new("ShaderNodeVectorMath")
    nrm.operation = "NORMALIZE"
    nt.links.new(xy.outputs[0], nrm.inputs[0])
    return ln.outputs["Value"], nrm.outputs[0], sep


def brushing(nt, tc, r_scale=420.0, around=1.5):
    """Concentric brushing: fine rings of slightly different gloss, varying gently around the circle."""
    r, unit, _ = polar(nt, tc)
    v = nt.nodes.new("ShaderNodeCombineXYZ")
    nt.links.new(math_node(nt, "MULTIPLY", r, r_scale), v.inputs["X"])
    sc = nt.nodes.new("ShaderNodeVectorMath")
    sc.operation = "SCALE"
    nt.links.new(unit, sc.inputs[0])
    sc.inputs["Scale"].default_value = around
    add = nt.nodes.new("ShaderNodeVectorMath")
    add.operation = "ADD"
    nt.links.new(v.outputs[0], add.inputs[0])
    nt.links.new(sc.outputs[0], add.inputs[1])
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.noise_dimensions = "3D"
    n.inputs["Scale"].default_value = 1.0
    n.inputs["Detail"].default_value = 4
    n.inputs["Roughness"].default_value = 0.7
    nt.links.new(add.outputs[0], n.inputs["Vector"])
    return n.outputs["Fac"]


def scratches(nt, tc, density=0.70):
    """Sparse micro-scratches in a few directions: long thin noise streaks, kept only at their peaks."""
    out = None
    for k, ang in enumerate((17, 71, 128, 160, 205, 248, 300, 335)):
        m = nt.nodes.new("ShaderNodeMapping")
        m.inputs["Rotation"].default_value = (0, 0, math.radians(ang))
        m.inputs["Location"].default_value = (k * 3.1, k * 1.7, 0)
        m.inputs["Scale"].default_value = (3.5, 140.0, 1.0)
        nt.links.new(tc.outputs["Object"], m.inputs["Vector"])
        n = nt.nodes.new("ShaderNodeTexNoise")
        n.inputs["Scale"].default_value = 2.2
        n.inputs["Detail"].default_value = 1
        nt.links.new(m.outputs[0], n.inputs["Vector"])
        cut = nt.nodes.new("ShaderNodeMapRange")
        nt.links.new(n.outputs["Fac"], cut.inputs["Value"])
        cut.inputs["From Min"].default_value = density + 0.004 * k
        cut.inputs["From Max"].default_value = density + 0.03 + 0.004 * k
        out = cut.outputs[0] if out is None else math_node(nt, "MAXIMUM", out, cut.outputs[0])
    return out


def smudge(nt, tc, where=(0.35, -0.25), size=0.32):
    """A faint thumb smudge: a soft blob of slightly rougher, duller metal off centre."""
    m = nt.nodes.new("ShaderNodeMapping")
    m.inputs["Location"].default_value = (-where[0], -where[1], 0)
    nt.links.new(tc.outputs["Object"], m.inputs["Vector"])
    ln = nt.nodes.new("ShaderNodeVectorMath")
    ln.operation = "LENGTH"
    nt.links.new(m.outputs[0], ln.inputs[0])
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = 9
    n.inputs["Detail"].default_value = 6
    nt.links.new(tc.outputs["Object"], n.inputs["Vector"])
    blob = nt.nodes.new("ShaderNodeMapRange")
    blob.interpolation_type = "SMOOTHSTEP"
    nt.links.new(ln.outputs["Value"], blob.inputs["Value"])
    blob.inputs["From Min"].default_value = size
    blob.inputs["From Max"].default_value = size * 0.35
    return math_node(nt, "MULTIPLY", blob.outputs[0], n.outputs["Fac"])


def brushed_alu_v2(name, line_r, zmin, tint_a=(0.60, 0.61, 0.63), tint_b=(0.68, 0.685, 0.70)):
    m, nt, b = node_mat(name)
    tc, sep = obj_coords(nt)
    tan = nt.nodes.new("ShaderNodeTangent")
    tan.direction_type = "RADIAL"
    tan.axis = "Z"
    nt.links.new(tan.outputs[0], b.inputs["Tangent"])
    set_in(b, Metallic=1.0, Anisotropic=0.9)
    brush = brushing(nt, tc)
    scr = scratches(nt, tc)
    smu = smudge(nt, tc)
    # Roughness: 0.24–0.34 along the brushing, a little lower in the scratches, higher in the smudge.
    rough = math_node(nt, "MULTIPLY_ADD", brush, 0.10, 0.24)
    rough = math_node(nt, "MULTIPLY_ADD", scr, -0.05, rough)
    rough = math_node(nt, "MULTIPLY_ADD", smu, 0.045, rough)   # faint: stronger read as a stain in the tilted view
    mask = line_mask(nt, sep, 0.026, line_r[0], line_r[1], zmin)
    rough = math_node(nt, "MULTIPLY_ADD", mask, 0.35, rough)
    nt.links.new(rough, b.inputs["Roughness"])
    base = nt.nodes.new("ShaderNodeMix")
    base.data_type = "RGBA"
    tint = nt.nodes.new("ShaderNodeMix")
    tint.data_type = "RGBA"
    tint.inputs[6].default_value = (*tint_a, 1)
    tint.inputs[7].default_value = (*tint_b, 1)
    nt.links.new(brush, tint.inputs["Factor"])
    nt.links.new(tint.outputs[2], base.inputs[6])
    base.inputs[7].default_value = (0.010, 0.010, 0.011, 1)
    nt.links.new(mask, base.inputs["Factor"])
    nt.links.new(base.outputs[2], b.inputs["Base Color"])
    nt.links.new(math_node(nt, "SUBTRACT", 1.0, mask), b.inputs["Metallic"])
    # Height: brushing grooves, scratches cut in, the engraved line sunk; one bump node chain.
    h = math_node(nt, "MULTIPLY", brush, 0.6)
    h = math_node(nt, "MULTIPLY_ADD", scr, -0.25, h)
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.06
    bump.inputs["Distance"].default_value = 0.004
    nt.links.new(h, bump.inputs["Height"])
    lb = nt.nodes.new("ShaderNodeBump")
    lb.invert = True
    lb.inputs["Strength"].default_value = 0.9
    lb.inputs["Distance"].default_value = 0.02
    nt.links.new(mask, lb.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], lb.inputs["Normal"])
    nt.links.new(lb.outputs["Normal"], b.inputs["Normal"])
    return m


def polished_v2(name, color=(0.86, 0.86, 0.88)):
    """The chamfer: polished, but not perfect: roughness that wanders a little, and a few fine scratches."""
    m, nt, b = node_mat(name)
    tc, _ = obj_coords(nt)
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = 40
    nt.links.new(tc.outputs["Object"], n.inputs["Vector"])
    scr = scratches(nt, tc, density=0.66)
    rough = math_node(nt, "MULTIPLY_ADD", n.outputs["Fac"], 0.06, 0.07)
    rough = math_node(nt, "MULTIPLY_ADD", scr, 0.10, rough)
    set_in(b, Base_Color=(*color, 1), Metallic=1.0, Anisotropic=0.25)
    tan = nt.nodes.new("ShaderNodeTangent")
    tan.direction_type = "RADIAL"
    tan.axis = "Z"
    nt.links.new(tan.outputs[0], b.inputs["Tangent"])
    nt.links.new(rough, b.inputs["Roughness"])
    return m


def knurl_v2(name, color=(0.50, 0.505, 0.52)):
    """Knurled metal: crisp teeth, grime settled in the grooves (ambient occlusion), worn bright tips."""
    m, nt, b = node_mat(name)
    ao = nt.nodes.new("ShaderNodeAmbientOcclusion")
    ao.inputs["Distance"].default_value = 0.03
    ao.samples = 8
    dirt = nt.nodes.new("ShaderNodeMix")
    dirt.data_type = "RGBA"
    dirt.inputs[6].default_value = (0.11, 0.105, 0.10, 1)
    dirt.inputs[7].default_value = (*color, 1)
    grime = nt.nodes.new("ShaderNodeMapRange")
    nt.links.new(ao.outputs["AO"], grime.inputs["Value"])
    grime.inputs["From Min"].default_value = 0.65
    grime.inputs["From Max"].default_value = 1.0
    nt.links.new(grime.outputs[0], dirt.inputs["Factor"])
    nt.links.new(dirt.outputs[2], b.inputs["Base Color"])
    nt.links.new(math_node(nt, "MULTIPLY_ADD", grime.outputs[0], -0.12, 0.44), b.inputs["Roughness"])
    set_in(b, Metallic=1.0)
    return m



def bakelite_v2(name):
    """Bakelite that has lived: the mottled brown-black resin and its clear gloss, edges rubbed lighter and duller
    where fingers turn it (convex edges, from Cycles' pointiness), and a little dust settled on the upward faces."""
    m = bakelite(name)
    nt = m.node_tree
    b = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    base_link = next(l for l in nt.links if l.to_socket == b.inputs["Base Color"])
    resin = base_link.from_socket
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    edge = nt.nodes.new("ShaderNodeMapRange")
    edge.interpolation_type = "SMOOTHSTEP"
    nt.links.new(geo.outputs["Pointiness"], edge.inputs["Value"])
    edge.inputs["From Min"].default_value = 0.53
    edge.inputs["From Max"].default_value = 0.60
    tc = nt.nodes.new("ShaderNodeTexCoord")
    wn = nt.nodes.new("ShaderNodeTexNoise")
    wn.inputs["Scale"].default_value = 60
    nt.links.new(tc.outputs["Object"], wn.inputs["Vector"])
    wear = math_node(nt, "MULTIPLY", edge.outputs[0], math_node(nt, "MULTIPLY_ADD", wn.outputs["Fac"], 0.8, 0.4), clamp=True)
    worn = nt.nodes.new("ShaderNodeMix")
    worn.data_type = "RGBA"
    nt.links.new(resin, worn.inputs[6])
    worn.inputs[7].default_value = (0.11, 0.06, 0.035, 1)
    nt.links.new(wear, worn.inputs["Factor"])
    # Dust: sparse fine specks, only where a face looks up.
    up = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geo.outputs["Normal"], up.inputs[0])
    upward = nt.nodes.new("ShaderNodeMapRange")
    nt.links.new(up.outputs["Z"], upward.inputs["Value"])
    upward.inputs["From Min"].default_value, upward.inputs["From Max"].default_value = 0.3, 0.9
    dn = nt.nodes.new("ShaderNodeTexNoise")
    dn.inputs["Scale"].default_value = 520
    dn.inputs["Detail"].default_value = 2
    nt.links.new(tc.outputs["Object"], dn.inputs["Vector"])
    speck = nt.nodes.new("ShaderNodeMapRange")
    nt.links.new(dn.outputs["Fac"], speck.inputs["Value"])
    speck.inputs["From Min"].default_value, speck.inputs["From Max"].default_value = 0.66, 0.72
    dust = math_node(nt, "MULTIPLY", math_node(nt, "MULTIPLY", speck.outputs[0], upward.outputs[0]), 0.7)
    dusty = nt.nodes.new("ShaderNodeMix")
    dusty.data_type = "RGBA"
    nt.links.new(worn.outputs[2], dusty.inputs[6])
    dusty.inputs[7].default_value = (0.30, 0.28, 0.26, 1)
    nt.links.new(dust, dusty.inputs["Factor"])
    nt.links.new(dusty.outputs[2], b.inputs["Base Color"])
    rough = math_node(nt, "MULTIPLY_ADD", wear, 0.25, 0.30)
    rough = math_node(nt, "MULTIPLY_ADD", dust, 0.6, rough, clamp=True)
    nt.links.new(rough, b.inputs["Roughness"])
    nt.links.new(math_node(nt, "MULTIPLY_ADD", math_node(nt, "MAXIMUM", wear, dust), -0.6, 0.6), b.inputs["Coat Weight"])
    return m


# ---------------------------------------------------------------- looks

def knob_A():
    """Brushed aluminium: skirt, straight knurl (60 teeth), polished chamfer, concentric-brushed top."""
    teeth = 60

    def ridge(t):
        x = (teeth * t / (2 * math.pi)) % 1.0
        return 0.034 * (1 - abs(2 * x - 1)) ** 0.8

    P = [(1.00, 0.0, 0)]
    P += [(1.00, 0.06, 0), (0.985, 0.075, 0)]
    P += [(0.96, 0.085, 0)]
    P += [(0.955, 0.10, 0.3), (0.955, 0.12, 1), (0.955, 0.25, 1), (0.955, 0.38, 1), (0.955, 0.43, 1), (0.955, 0.45, 0.3)]
    P += [(0.955, 0.465, 0)]
    P += fillet((0.955, 0.465), (0.955, 0.50), (0.92, 0.515), 4)
    P += [(0.92, 0.515, 0), (0.885, 0.535, 0)]
    P += fillet((0.885, 0.535), (0.875, 0.54), (0.86, 0.54), 3)
    P += [(0.86, 0.54, 0), (0.6, 0.542, 0), (0.3, 0.544, 0)]
    top_z = 0.53

    def mat_of(r, z):
        if z > 0.538 and r < 0.865: return 0             # brushed top
        if z > 0.47: return 1                             # polished chamfer
        if z < 0.09: return 1                             # polished skirt edge
        return 2                                          # knurl
    o = lathe("Knob", P, teeth * (12 if Q == 2 else 8), ridge, mat_of=mat_of)
    if Q == 2:
        o.data.materials.append(brushed_alu_v2("Brushed", line_r=(0.28, 0.80), zmin=top_z))
        o.data.materials.append(polished_v2("Polished"))
        o.data.materials.append(knurl_v2("Knurl"))
    else:
        o.data.materials.append(brushed_alu("Brushed", line_r=(0.28, 0.80), zmin=top_z))
        o.data.materials.append(metal("Polished", (0.86, 0.86, 0.88), 0.10))
        o.data.materials.append(metal("Knurl", (0.60, 0.605, 0.62), 0.38, aniso=0.0))
    return [o], 3.05   # room for the soft shadow inside the frame


def knob_B():
    """Vintage bakelite: a skirt with a rounded rim, a tapered fluted body (18 flutes), a spun nickel cap."""
    flutes = 18

    def ridge(t):
        return 0.055 * (0.5 + 0.5 * math.cos(flutes * t)) ** 1.6

    P = [(1.10, 0.0, 0)]
    P += fillet((1.10, 0.0), (1.13, 0.0), (1.13, 0.04), 3)
    P += [(1.13, 0.04, 0)]
    P += fillet((1.13, 0.04), (1.13, 0.10), (1.05, 0.11), 4)
    P += [(1.05, 0.11, 0), (0.92, 0.125, 0)]
    P += fillet((0.92, 0.125), (0.86, 0.13), (0.86, 0.17), 3, w=0.2)
    P += [(0.86, 0.17, 0.6), (0.84, 0.28, 1), (0.81, 0.40, 1), (0.785, 0.50, 1), (0.77, 0.56, 0.7)]
    P += fillet((0.77, 0.56), (0.76, 0.61), (0.70, 0.625), 4, w=0.2)
    P += [(0.70, 0.625, 0), (0.675, 0.625, 0), (0.665, 0.615, 0)]          # the lip around the cap
    P += [(0.64, 0.612, 0)]
    P += fillet((0.64, 0.612), (0.62, 0.635), (0.58, 0.638), 3)
    P += [(0.58, 0.638, 0), (0.40, 0.644, 0), (0.2, 0.647, 0)]

    def mat_of(r, z):
        return 1 if (z > 0.605 and r < 0.655) else 0
    o = lathe("Knob", P, flutes * 16, ridge, mat_of=mat_of)
    if Q == 2:
        o.data.materials.append(bakelite_v2("Bakelite"))
        o.data.materials.append(brushed_alu_v2("Cap", (0.14, 0.56), 0.63, (0.66, 0.635, 0.58), (0.76, 0.735, 0.68)))
    else:
        o.data.materials.append(bakelite("Bakelite"))
        o.data.materials.append(spun_cap("Cap", (0.14, 0.56), 0.63))
    return [o], 3.05   # room for the soft shadow inside the frame


def knob_C(glow):
    """Modern dark: a soft-touch body with a fine grip band, a glossy dish top with a glowing line, and a
    static ring around it that lights from the minimum up to the value."""
    teeth = 90

    def ridge(t):
        return 0.012 * (0.5 + 0.5 * math.cos(teeth * t))

    P = [(0.90, 0.0, 0)]
    P += [(0.90, 0.03, 0)]
    P += fillet((0.90, 0.03), (0.905, 0.06), (0.905, 0.08), 2)
    P += [(0.905, 0.10, 1), (0.905, 0.30, 1), (0.905, 0.40, 1), (0.905, 0.42, 0)]
    P += fillet((0.905, 0.42), (0.905, 0.50), (0.84, 0.505), 5)
    P += [(0.84, 0.505, 0), (0.80, 0.50, 0), (0.78, 0.49, 0)]           # into the dish
    P += [(0.6, 0.474, 0), (0.3, 0.466, 0), (0.1, 0.464, 0)]

    def mat_of(r, z):
        return 1 if (z > 0.45 and r < 0.80) else 0
    o = lathe("Knob", P, teeth * 4, ridge, mat_of=mat_of)
    o.data.materials.append(soft_touch("SoftTouch"))
    o.data.materials.append(glow_top("Dish", glow, (0.36, 0.70), 0.44))
    ring, halo, value = value_ring(glow)
    return [o], 3.1, (ring, halo, value)


def value_ring(glow, r_in=1.07, r_out=1.15):
    """A flat annulus on the panel: a dark track whose lit part runs from the minimum to the value, plus a soft
    halo plane over it (transparent where unlit, so the PNG's alpha carries the glow)."""
    def annulus(name, a, b, z, segs=360):
        bm = bmesh.new()
        inner = [bm.verts.new((a * math.sin(2 * math.pi * i / segs), a * math.cos(2 * math.pi * i / segs), z)) for i in range(segs)]
        outer = [bm.verts.new((b * math.sin(2 * math.pi * i / segs), b * math.cos(2 * math.pi * i / segs), z)) for i in range(segs)]
        for i in range(segs):
            j = (i + 1) % segs
            bm.faces.new((inner[i], inner[j], outer[j], outer[i]))
        me = bpy.data.meshes.new(name)
        bm.to_mesh(me)
        bm.free()
        o = bpy.data.objects.new(name, me)
        bpy.context.scene.collection.objects.link(o)
        return o

    def lit_nodes(nt, soft=0.004):
        """lit (0..1) for this point: its clockwise angle from 12 o'clock against the value; `soft` is the fade at
        the lit end (the halo's is wider, so its glow trails off past the end of the ring like real light)."""
        tc, sep = obj_coords(nt)
        theta = math_node(nt, "ARCTAN2", sep.outputs["X"], sep.outputs["Y"])           # clockwise from +Y
        t = math_node(nt, "DIVIDE", math_node(nt, "ADD", theta, SWEEP / 2), SWEEP)      # 0 at the minimum
        val = nt.nodes.new("ShaderNodeValue")
        val.name = val.label = "Value"
        inside = smooth_band(nt, t, 0.0, 1.0, max(0.002, soft / 2))
        below = nt.nodes.new("ShaderNodeMapRange")
        below.interpolation_type = "SMOOTHSTEP"
        nt.links.new(t, below.inputs["Value"])
        # lit when t <= value: from (value + 0.004) down to (value - 0.004)
        add_hi = math_node(nt, "ADD", val.outputs[0], soft)
        add_lo = math_node(nt, "SUBTRACT", val.outputs[0], soft)
        nt.links.new(add_hi, below.inputs["From Min"])
        nt.links.new(add_lo, below.inputs["From Max"])
        # A sliver is always lit at the minimum so 0 still shows where the ring starts.
        lit = math_node(nt, "MULTIPLY", inside, below.outputs[0])
        return lit, val, sep

    ring = annulus("Ring", r_in, r_out, 0.004)
    m, nt, b = node_mat("RingTrack")
    lit, val_ring, _ = lit_nodes(nt)
    set_in(b, Base_Color=(0.075, 0.078, 0.085, 1), Roughness=0.45)
    b.inputs["Emission Color"].default_value = (*glow, 1)
    nt.links.new(math_node(nt, "MULTIPLY", lit, 7.0), b.inputs["Emission Strength"])
    # The dim, unlit track still shows: a faint emission everywhere on the sweep.
    ring.data.materials.append(m)

    halo = annulus("Halo", 0.92, 1.42 if Q == 1 else 1.55, 0.010)
    hm = bpy.data.materials.new("Halo")
    hm.use_nodes = True
    hnt = hm.node_tree
    hnt.nodes.clear()
    lit2, val_halo, sep = lit_nodes(hnt, 0.004 if Q == 1 else 0.02)
    vlen = hnt.nodes.new("ShaderNodeVectorMath")
    vlen.operation = "LENGTH"
    tc2 = hnt.nodes.new("ShaderNodeTexCoord")
    hnt.links.new(tc2.outputs["Object"], vlen.inputs[0])
    d = math_node(hnt, "DIVIDE", math_node(hnt, "SUBTRACT", vlen.outputs["Value"], (r_in + r_out) / 2), 0.085)
    fall = math_node(hnt, "EXPONENT", math_node(hnt, "MULTIPLY", math_node(hnt, "MULTIPLY", d, d), -1.0))
    outside_knob = smooth_band(hnt, vlen.outputs["Value"], 0.93, 9, 0.01)
    if Q == 2:   # the bloom a camera sees: a tight core plus a wide, faint tail
        tail = math_node(hnt, "EXPONENT", math_node(hnt, "MULTIPLY", math_node(hnt, "ABSOLUTE", d), -0.75))
        fade = smooth_band(hnt, vlen.outputs["Value"], 0, 1.30, 0.17)   # gone well before the frame's edge
        fall = math_node(hnt, "MULTIPLY_ADD", math_node(hnt, "MULTIPLY", tail, fade), 0.30, math_node(hnt, "MULTIPLY", fall, 0.8))
    fac = math_node(hnt, "MULTIPLY", math_node(hnt, "MULTIPLY", fall, lit2), 0.55)
    fac = math_node(hnt, "MULTIPLY", fac, outside_knob, clamp=True)
    tr = hnt.nodes.new("ShaderNodeBsdfTransparent")
    em = hnt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (*glow, 1)
    em.inputs["Strength"].default_value = 2.2
    mix = hnt.nodes.new("ShaderNodeMixShader")
    hnt.links.new(fac, mix.inputs["Fac"])
    hnt.links.new(tr.outputs[0], mix.inputs[1])
    hnt.links.new(em.outputs[0], mix.inputs[2])
    out = hnt.nodes.new("ShaderNodeOutputMaterial")
    hnt.links.new(mix.outputs[0], out.inputs[0])
    halo.data.materials.append(hm)
    halo.visible_shadow = False
    halo.visible_diffuse = False
    halo.visible_glossy = False
    return ring, halo, [nt.nodes["Value"], hnt.nodes["Value"]]


def print_mat(name, color=(0.86, 0.86, 0.84)):
    """Silk-screened paint: an off-white, slightly rough print that never glows."""
    m, nt, b = node_mat(name)
    set_in(b, Base_Color=(*color, 1), Roughness=0.62, Specular_IOR_Level=0.35)
    return m


def drive_body(name):
    """Look D's body: soft-touch black with a white pointer line along +Y, over the top and down across the skirt."""
    m, nt, b = node_mat(name)
    tc, sep = obj_coords(nt)
    set_in(b, Base_Color=(0.018, 0.018, 0.02, 1), Roughness=0.52, Specular_IOR_Level=0.45, Sheen_Weight=0.25,
           Sheen_Roughness=0.4)
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = 260
    nt.links.new(tc.outputs["Object"], n.inputs["Vector"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.05
    nt.links.new(n.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    # The pointer: on the top from near the centre to the edge, and on the skirt's top face out to its rim.
    top = line_mask(nt, sep, 0.045, 0.18, 0.80, 0.60)
    skirt = math_node(nt, "MULTIPLY", line_mask(nt, sep, 0.05, 0.86, 1.10, 0.10),
                      smooth_band(nt, sep.outputs["Z"], -1, 0.20, 0.01))
    mask = math_node(nt, "MINIMUM", math_node(nt, "ADD", top, skirt), 1.0)
    col = nt.nodes.new("ShaderNodeMix")
    col.data_type = "RGBA"
    col.inputs[6].default_value = (0.018, 0.018, 0.02, 1)
    col.inputs[7].default_value = (0.90, 0.90, 0.88, 1)
    nt.links.new(mask, col.inputs["Factor"])
    nt.links.new(col.outputs[2], b.inputs["Base Color"])
    nt.links.new(math_node(nt, "MULTIPLY_ADD", mask, 0.10, 0.52), b.inputs["Roughness"])
    return m


def value_at(v, r):
    """Where value v (0..1) sits on a circle of radius r, as the knob points at it: 7 o'clock to 5 o'clock."""
    a = math.pi / 2 + SWEEP / 2 - SWEEP * v
    return (r * math.cos(a), r * math.sin(a))


def scale_marks(count, r_num, r_tick, paint, numbers=True, size=0.17):
    """The printed scale that doesn't turn: a tick and a number for 0..count-1, flat on the floor."""
    objs = []
    for k in range(count):
        v = k / (count - 1)
        x, y = value_at(v, r_tick)
        bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=0.028, depth=0.004, location=(x, y, 0.002))
        dot = bpy.context.object
        dot.name = f"Tick{k}"
        dot.data.materials.append(paint)
        objs.append(dot)
        if not numbers:
            continue
        curve = bpy.data.curves.new(f"Num{k}", "FONT")
        curve.body = str(k)
        curve.align_x, curve.align_y = "CENTER", "CENTER"
        curve.size = size
        curve.extrude = 0.0015
        t = bpy.data.objects.new(f"Num{k}", curve)
        bpy.context.scene.collection.objects.link(t)
        t.location = (*value_at(v, r_num), 0.002)
        t.data.materials.append(paint)
        objs.append(t)
    return objs


def knob_D():
    """A drive pedal knob: a wide skirt with a rounded rim, a tall slightly tapered body with 36 shallow grip
    flutes, a flat top with a soft edge; the white pointer runs over the top and the skirt. The 0-10 scale is printed
    round it and stays still."""
    flutes = 36

    def ridge(t):
        return 0.018 * (0.5 + 0.5 * math.cos(flutes * t)) ** 2

    P = [(1.10, 0.0, 0)]
    P += fillet((1.10, 0.0), (1.12, 0.0), (1.12, 0.03), 3)
    P += [(1.12, 0.03, 0)]
    P += fillet((1.12, 0.03), (1.12, 0.10), (1.06, 0.115), 4)
    P += [(1.06, 0.115, 0), (0.90, 0.125, 0)]
    P += fillet((0.90, 0.125), (0.84, 0.13), (0.84, 0.17), 3, w=0.3)
    P += [(0.84, 0.17, 0.8), (0.83, 0.30, 1), (0.82, 0.44, 1), (0.81, 0.54, 0.8)]
    P += fillet((0.81, 0.54), (0.80, 0.62), (0.72, 0.625), 5, w=0.2)
    P += [(0.72, 0.625, 0), (0.40, 0.628, 0), (0.15, 0.63, 0)]
    o = lathe("Knob", P, flutes * 12, ridge)
    o.data.materials.append(drive_body("Drive"))
    marks = scale_marks(11, 1.42, 1.22, print_mat("Print"))
    return [o] + marks, 3.55   # the numbers and the soft shadow inside the frame


def selector_T():
    """A three-way selector: a black chicken-head pointer on a round base, over three printed dots. It points at
    the left dot, the middle one or the right one."""
    objs = []
    base = lathe("Base", [(0.62, 0.0, 0), (0.62, 0.06, 0), (0.58, 0.10, 0), (0.30, 0.11, 0)], 128)
    base.data.materials.append(metal("Nickel", (0.70, 0.70, 0.70), 0.30, aniso=0.5))
    objs.append(base)
    # The chicken head: a tapered bar, round at the back, pointed at the front, with a white line along it.
    from mathutils import Vector
    bm = bmesh.new()
    outline = []
    for i in range(48):            # the round back
        t = math.pi + math.pi * i / 47
        outline.append((0.30 * math.cos(t), -0.10 + 0.30 * math.sin(t) * 0.9))
    outline += [(0.30, -0.10), (0.11, 0.78), (0.0, 0.86), (-0.11, 0.78), (-0.30, -0.10)]
    vs = [bm.verts.new((x, y, 0.11)) for x, y in outline]
    face = bm.faces.new(vs)
    ext = bmesh.ops.extrude_face_region(bm, geom=[face])
    top = [v for v in ext["geom"] if isinstance(v, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=top, vec=Vector((0, 0, 0.30)))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new("Pointer")
    bm.to_mesh(me)
    bm.free()
    head = bpy.data.objects.new("Pointer", me)
    bpy.context.scene.collection.objects.link(head)
    bev = head.modifiers.new("Bevel", "BEVEL")
    bev.width = 0.035
    bev.segments = 4
    m, nt, b = node_mat("Bakelite black")
    tc, sep = obj_coords(nt)
    set_in(b, Base_Color=(0.02, 0.02, 0.022, 1), Roughness=0.30, Specular_IOR_Level=0.55, Coat_Weight=0.4,
           Coat_Roughness=0.15)
    line = line_mask(nt, sep, 0.03, 0.05, 0.74, 0.40)
    col = nt.nodes.new("ShaderNodeMix")
    col.data_type = "RGBA"
    col.inputs[6].default_value = (0.02, 0.02, 0.022, 1)
    col.inputs[7].default_value = (0.90, 0.90, 0.88, 1)
    nt.links.new(line, col.inputs["Factor"])
    nt.links.new(col.outputs[2], b.inputs["Base Color"])
    head.data.materials.append(m)
    objs.append(head)
    paint = print_mat("Print")
    for k, ang in enumerate(SELECTOR):
        a = math.pi / 2 + ang
        bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=0.07, depth=0.004,
                                            location=(1.05 * math.cos(a), 1.05 * math.sin(a), 0.002))
        dot = bpy.context.object
        dot.name = f"Dot{k}"
        dot.data.materials.append(paint)
        objs.append(dot)
    return objs, 2.9, head


SELECTOR = [math.radians(45), 0.0, math.radians(-45)]   # left, middle, right (seen from above, +Y up)


def switch_S():
    """A bat-handle toggle: washer, hex nut, threaded bushing and a chrome lever that tips forward or back."""
    objs = []
    chrome = metal("Chrome", (0.90, 0.90, 0.92), 0.07)
    nickel = metal("Nickel", (0.78, 0.77, 0.74), 0.20, aniso=0.6)
    washer = lathe("Washer", [(0.80, 0.0, 0), (0.80, 0.035, 0), (0.78, 0.05, 0), (0.42, 0.05, 0)], 128)
    washer.data.materials.append(nickel)
    objs.append(washer)
    # Hex nut: a 6-sided lathe with bevelled top edge.
    nut = lathe("Nut", [(0.62, 0.05, 0), (0.62, 0.17, 0), (0.58, 0.21, 0), (0.40, 0.21, 0)], 6)
    nut.rotation_euler.z = math.radians(30)
    bev = nut.modifiers.new("Bevel", "BEVEL")
    bev.width = 0.015
    bev.segments = 3
    bev.limit_method = "ANGLE"
    nut.data.materials.append(nickel)
    objs.append(nut)
    bush = lathe("Bushing", [(0.36, 0.21, 0), (0.36, 0.33, 0), (0.33, 0.36, 0), (0.17, 0.36, 0)], 96)
    bush.data.materials.append(chrome)
    objs.append(bush)
    # The lever: a lathe along its own Z, thin at the pivot, swelling to a rounded "bat" tip.
    L = [(0.0, 0.0, 0), (0.10, 0.0, 0), (0.105, 0.2, 0), (0.115, 0.6, 0), (0.135, 0.95, 0), (0.155, 1.10, 0)]
    L += fillet((0.155, 1.10), (0.165, 1.22), (0.08, 1.25), 5)
    L += [(0.08, 1.25, 0), (0.0, 1.255, 0)]
    lever = lathe("Lever", L, 64, cap_top=False)
    lever.location = (0, 0, 0.33)
    lever.data.materials.append(chrome)
    objs.append(lever)
    return objs, 3.7, lever   # the lever's long shadow stays inside the frame


def panel_P():
    """A faceplate: a bevelled slab of charcoal anodised aluminium, brushed along its length, an engraved border
    filled with silver, four slotted screws. Labels come from the face (SwiftUI Text), not the picture."""
    from mathutils import Vector
    w, h, t = 3.0, 1.25, 0.06
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, t / 2))
    plate = bpy.context.object
    plate.name = "Plate"
    plate.scale = (w, h, t)
    bpy.ops.object.transform_apply(scale=True)
    bev = plate.modifiers.new("Bevel", "BEVEL")
    bev.width = 0.018
    bev.segments = 4
    m, nt, b = node_mat("Anodised")
    tc, sep = obj_coords(nt)
    set_in(b, Base_Color=(0.045, 0.046, 0.05, 1), Metallic=1.0, Roughness=0.36, Anisotropic=0.7)
    tan = nt.nodes.new("ShaderNodeTangent")
    tan.direction_type = "RADIAL"
    tan.axis = "Y"
    nt.links.new(tan.outputs[0], b.inputs["Tangent"])
    stretch = nt.nodes.new("ShaderNodeMapping")
    stretch.inputs["Scale"].default_value = (2.0, 160.0, 1.0)
    nt.links.new(tc.outputs["Object"], stretch.inputs["Vector"])
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 3.0
    noise.inputs["Detail"].default_value = 6
    nt.links.new(stretch.outputs[0], noise.inputs["Vector"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.12
    nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    # The engraved border: a thin rounded-rectangle line inset from the edge, silver in a shallow groove.
    ax = math_node(nt, "ABSOLUTE", sep.outputs["X"])
    ay = math_node(nt, "ABSOLUTE", sep.outputs["Y"])
    r = 0.2      # the border's corner radius: its corners curve away from the screws
    dx = math_node(nt, "MAXIMUM", math_node(nt, "SUBTRACT", ax, w / 2 - 0.13 - r), 0.0)
    dy = math_node(nt, "MAXIMUM", math_node(nt, "SUBTRACT", ay, h / 2 - 0.13 - r), 0.0)
    d = math_node(nt, "SQRT", math_node(nt, "ADD", math_node(nt, "MULTIPLY", dx, dx), math_node(nt, "MULTIPLY", dy, dy)))
    line = smooth_band(nt, d, r - 0.006, r + 0.006, 0.003)
    top = smooth_band(nt, sep.outputs["Z"], t - 0.002, 10, 0.001)
    line = math_node(nt, "MULTIPLY", line, top)
    col = nt.nodes.new("ShaderNodeMix")
    col.data_type = "RGBA"
    col.inputs[6].default_value = (0.045, 0.046, 0.05, 1)
    col.inputs[7].default_value = (0.62, 0.62, 0.64, 1)
    nt.links.new(line, col.inputs["Factor"])
    nt.links.new(col.outputs[2], b.inputs["Base Color"])
    nt.links.new(math_node(nt, "MULTIPLY_ADD", line, -0.4, 0.36), b.inputs["Roughness"])
    lb = nt.nodes.new("ShaderNodeBump")
    lb.invert = True
    lb.inputs["Strength"].default_value = 0.6
    lb.inputs["Distance"].default_value = 0.01
    nt.links.new(line, lb.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], lb.inputs["Normal"])
    nt.links.new(lb.outputs["Normal"], b.inputs["Normal"])
    plate.data.materials.append(m)
    objs = [plate]
    screw_mat = metal("Screw", (0.70, 0.70, 0.72), 0.25, aniso=0.5)
    for sx in (-1, 1):
        for sy in (-1, 1):
            P = [(0.055, 0.0, 0), (0.055, 0.012, 0)]
            P += fillet((0.055, 0.012), (0.055, 0.03), (0.035, 0.034), 4)
            P += [(0.035, 0.034, 0), (0.01, 0.036, 0)]
            s = lathe("Screw", P, 48)
            s.location = (sx * (w / 2 - 0.1), sy * (h / 2 - 0.1), t)
            s.rotation_euler.z = math.radians(25 + 40 * (sx + 2 * sy))
            s.data.materials.append(screw_mat)
            # The slot: a dark bar sunk into the head.
            bpy.ops.mesh.primitive_cube_add(size=1, location=(s.location.x, s.location.y, t + 0.03))
            slot = bpy.context.object
            slot.scale = (0.085, 0.012, 0.02)
            slot.rotation_euler.z = s.rotation_euler.z
            dark, _, db = node_mat("Slot")
            set_in(db, Base_Color=(0.01, 0.01, 0.01, 1), Roughness=0.6)
            slot.data.materials.append(dark)
            objs += [s, slot]
    return objs, 3.2


# ---------------------------------------------------------------- look R (30 Oct): the drive knob, hyper-real

def noise_tex(nt, tc, scale, detail=2.0, rough=0.5, out="Fac"):
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = scale
    n.inputs["Detail"].default_value = detail
    n.inputs["Roughness"].default_value = rough
    nt.links.new(tc.outputs["Object"], n.inputs["Vector"])
    return n.outputs[out]


def satin_plastic(name, pointer=None, color=0.013, rough0=0.27, dust_amount=0.0):
    """Moulded satin-black plastic, as on a real pedal knob: a fine mould texture (micro-roughness), gloss that
    wanders a little, edges and flute ridges polished brighter by fingers (Cycles' pointiness), a faint thumb smudge
    and, if asked, a little dust. `pointer(nt, sep)` returns the mask of the white line: paint laid in a sunk groove."""
    m, nt, b = node_mat(name)
    tc, sep = obj_coords(nt)
    set_in(b, Specular_IOR_Level=0.5, Sheen_Weight=0.04, Sheen_Roughness=0.45)
    wander = noise_tex(nt, tc, 7, detail=5)                 # broad gloss variation across the moulding
    mould = noise_tex(nt, tc, 170, detail=3, rough=0.6)     # the mould's fine texture
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    edge = nt.nodes.new("ShaderNodeMapRange")
    edge.interpolation_type = "SMOOTHSTEP"
    nt.links.new(geo.outputs["Pointiness"], edge.inputs["Value"])
    edge.inputs["From Min"].default_value, edge.inputs["From Max"].default_value = 0.515, 0.58
    smu = smudge(nt, tc, where=(-0.30, 0.22), size=0.30)
    # Dust: a few soft specks, only where a face looks up.
    up = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geo.outputs["Normal"], up.inputs[0])
    upward = nt.nodes.new("ShaderNodeMapRange")
    nt.links.new(up.outputs["Z"], upward.inputs["Value"])
    upward.inputs["From Min"].default_value, upward.inputs["From Max"].default_value = 0.5, 0.95
    speck = nt.nodes.new("ShaderNodeMapRange")
    nt.links.new(noise_tex(nt, tc, 95, detail=1), speck.inputs["Value"])
    speck.inputs["From Min"].default_value, speck.inputs["From Max"].default_value = 0.73, 0.78
    dust = math_node(nt, "MULTIPLY", math_node(nt, "MULTIPLY", speck.outputs[0], upward.outputs[0]), dust_amount)
    rough = math_node(nt, "MULTIPLY_ADD", wander, 0.10, rough0)        # 0.27-0.37: satin, not matte, not gloss
    rough = math_node(nt, "MULTIPLY_ADD", mould, 0.06, rough)
    rough = math_node(nt, "MULTIPLY_ADD", edge.outputs[0], -0.12, rough)
    rough = math_node(nt, "MULTIPLY_ADD", smu, 0.10, rough)
    rough = math_node(nt, "MULTIPLY_ADD", dust, 0.5, rough)
    plastic = nt.nodes.new("ShaderNodeMix")
    plastic.data_type = "RGBA"
    plastic.inputs[6].default_value = (color, color, color * 1.08, 1)
    plastic.inputs[7].default_value = (0.24, 0.23, 0.22, 1)            # dust
    nt.links.new(dust, plastic.inputs["Factor"])
    h = math_node(nt, "MULTIPLY", mould, 1.0)
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.035
    bump.inputs["Distance"].default_value = 0.004
    nt.links.new(h, bump.inputs["Height"])
    normal = bump.outputs["Normal"]
    color_out = plastic.outputs[2]
    if pointer:
        mask = pointer(nt, sep)
        paint = nt.nodes.new("ShaderNodeMix")
        paint.data_type = "RGBA"
        nt.links.new(color_out, paint.inputs[6])
        ink = nt.nodes.new("ShaderNodeMix")
        ink.data_type = "RGBA"
        ink.inputs[6].default_value = (0.70, 0.70, 0.68, 1)
        ink.inputs[7].default_value = (0.80, 0.80, 0.78, 1)
        nt.links.new(noise_tex(nt, tc, 60, detail=4), ink.inputs["Factor"])
        nt.links.new(ink.outputs[2], paint.inputs[7])
        nt.links.new(mask, paint.inputs["Factor"])
        color_out = paint.outputs[2]
        rough = math_node(nt, "MULTIPLY_ADD", mask, 0.18, rough)        # the paint is duller than the plastic
        lb = nt.nodes.new("ShaderNodeBump")
        lb.invert = True
        lb.inputs["Strength"].default_value = 0.5
        lb.inputs["Distance"].default_value = 0.012
        nt.links.new(mask, lb.inputs["Height"])
        nt.links.new(normal, lb.inputs["Normal"])
        normal = lb.outputs["Normal"]
    nt.links.new(color_out, b.inputs["Base Color"])
    nt.links.new(rough, b.inputs["Roughness"])
    nt.links.new(normal, b.inputs["Normal"])
    return m


def ink_mat(name):
    """Screen-printed ink: off-white, a little uneven in tone and gloss, a faint grain."""
    m, nt, b = node_mat(name)
    tc, _ = obj_coords(nt)
    tone = nt.nodes.new("ShaderNodeMix")
    tone.data_type = "RGBA"
    tone.inputs[6].default_value = (0.66, 0.66, 0.64, 1)
    tone.inputs[7].default_value = (0.76, 0.76, 0.74, 1)
    nt.links.new(noise_tex(nt, tc, 40, detail=5), tone.inputs["Factor"])
    nt.links.new(tone.outputs[2], b.inputs["Base Color"])
    grain = noise_tex(nt, tc, 260, detail=2)
    nt.links.new(math_node(nt, "MULTIPLY_ADD", grain, 0.12, 0.42), b.inputs["Roughness"])
    set_in(b, Specular_IOR_Level=0.4)
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.08
    bump.inputs["Distance"].default_value = 0.002
    nt.links.new(grain, bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    return m


def scale_marks_R(count, r_num, r_tick, paint, size=0.19):
    """Look R's printed scale: Inter numerals (Blender's own font, OFL), a touch bolder, and round tick dots; a
    film of ink, so the edges stay crisp."""
    font = None
    try:
        font = bpy.data.fonts.load(os.path.join(bpy.utils.system_resource("DATAFILES"), "fonts", "Inter.woff2"))
    except Exception as e:
        print("FONT default", e)
    objs = []
    for k in range(count):
        v = k / (count - 1)
        x, y = value_at(v, r_tick)
        bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=0.032, depth=0.003, location=(x, y, 0.0015))
        dot = bpy.context.object
        dot.name = f"Tick{k}"
        dot.data.materials.append(paint)
        objs.append(dot)
        curve = bpy.data.curves.new(f"Num{k}", "FONT")
        if font:
            curve.font = font
        curve.body = str(k)
        curve.align_x, curve.align_y = "CENTER", "CENTER"
        curve.size = size
        curve.offset = 0.0035            # a little weight, as a printed scale has
        curve.extrude = 0.001
        curve.resolution_u = 24
        t = bpy.data.objects.new(f"Num{k}", curve)
        bpy.context.scene.collection.objects.link(t)
        t.location = (*value_at(v, r_num), 0.0015)
        t.data.materials.append(paint)
        objs.append(t)
    return objs


def drive_profile_R(ridged=True):
    """Look R's profile: look D's chunky body on a wide skirt, with rounder fillets (they carry the highlights), a
    top domed by a hair, and a spun-aluminium cap set in the centre."""
    flutes = 36
    ridge = (lambda t: 0.022 * (0.5 + 0.5 * math.cos(flutes * t)) ** 2) if ridged else None
    P = [(1.10, 0.0, 0)]
    P += fillet((1.10, 0.0), (1.125, 0.0), (1.125, 0.03), 4)
    P += [(1.125, 0.03, 0)]
    P += fillet((1.125, 0.03), (1.125, 0.105), (1.06, 0.118), 7)
    P += [(1.06, 0.118, 0), (0.98, 0.122, 0), (0.90, 0.127, 0)]
    P += fillet((0.90, 0.127), (0.84, 0.132), (0.84, 0.18), 5, w=0.3)
    P += [(0.84, 0.18, 0.8), (0.835, 0.24, 1), (0.83, 0.30, 1), (0.825, 0.37, 1), (0.82, 0.44, 1), (0.815, 0.50, 1),
          (0.81, 0.54, 1)]
    # The flutes run up into the rounded top edge and fade out across it: one clean scalloped edge, not two.
    top_edge = fillet((0.81, 0.54), (0.80, 0.625), (0.71, 0.632), 9)
    P += [(r, z, (1 - k / len(top_edge)) ** 1.5) for k, (r, z, _) in enumerate(top_edge, start=1)]
    P += [(0.71, 0.632, 0), (0.60, 0.639, 0), (0.48, 0.644, 0), (0.37, 0.647, 0)]
    # The cap's seat: a fine dark gap, then the cap with a small polished chamfer.
    P += [(0.352, 0.647, 0), (0.346, 0.636, 0), (0.338, 0.636, 0)]
    P += fillet((0.338, 0.636), (0.336, 0.651), (0.318, 0.654), 4)
    P += [(0.318, 0.654, 0), (0.22, 0.656, 0), (0.10, 0.657, 0)]
    return P, ridge, flutes


def drive_pointer_R(nt, sep):
    """The white line: on the top from the cap out over the edge, and over the skirt and down its rim."""
    top = line_mask(nt, sep, 0.040, 0.39, 0.835, 0.58)
    skirt = math_node(nt, "MULTIPLY", line_mask(nt, sep, 0.046, 0.875, 1.20, 0.03),
                      smooth_band(nt, sep.outputs["Z"], -1, 0.20, 0.01))
    return math_node(nt, "MINIMUM", math_node(nt, "ADD", top, skirt), 1.0)


def knob_R():
    """Look R: look D made real. Satin moulded plastic (micro-roughness, polished ridges, a faint smudge), a
    spun-aluminium cap, a paint-filled white pointer over the top and down the skirt, a screen-printed 0-10 scale that
    stays still, Controls 1's studio and its contact shadow."""
    P, ridge, flutes = drive_profile_R()

    def mat_of(r, z):
        return 1 if (r < 0.337 and z > 0.640) else 0
    o = lathe("Knob", P, flutes * 16, ridge, mat_of=mat_of)
    o.data.materials.append(satin_plastic("Satin", drive_pointer_R))
    o.data.materials.append(brushed_alu_v2("Cap", line_r=(8, 9), zmin=5))   # no line on the cap
    marks = scale_marks_R(11, 1.42, 1.22, ink_mat("Ink"))
    return [o] + marks, 3.55   # framed as look D, so the knob is the same size in the app


def selector_R():
    """The three-way selector in look R: a satin-black chicken head (drafted sides, rounded edges, a paint-filled
    line) on a spun-aluminium base with a polished chamfer, over three screen-printed dots."""
    from mathutils import Vector
    objs = []
    P = [(0.64, 0.0, 0), (0.64, 0.05, 0)]
    P += fillet((0.64, 0.05), (0.64, 0.088), (0.602, 0.092), 5)
    P += [(0.602, 0.092, 0), (0.585, 0.096, 0), (0.40, 0.098, 0), (0.20, 0.10, 0)]
    base = lathe("Base", P, 256, mat_of=lambda r, z: 0 if (z > 0.093 and r < 0.59) else 1)
    base.data.materials.append(brushed_alu_v2("Spun", line_r=(8, 9), zmin=5))
    base.data.materials.append(polished_v2("Polished"))
    objs.append(base)
    # The chicken head: round at the back, pointed at the front; the top a little smaller than the bottom (the
    # mould's draft), every edge rounded so it catches the light.
    bm = bmesh.new()
    # The outline: a round back (r 0.30) and a round tip (r 0.07), joined by their common tangents.
    R, r, c1, c2 = 0.30, 0.07, -0.10, 0.78
    phi = math.asin((R - r) / (c2 - c1))
    outline = []
    for i in range(64):            # the back, counter-clockwise through the bottom
        t = math.pi - phi + (math.pi + 2 * phi) * i / 63
        outline.append((R * math.cos(t), c1 + R * math.sin(t)))
    for i in range(24):            # the tip, over the top
        t = phi + (math.pi - 2 * phi) * i / 23
        outline.append((r * math.cos(t), c2 + r * math.sin(t)))
    vs = [bm.verts.new((x, y, 0.098)) for x, y in outline]
    face = bm.faces.new(vs)
    ext = bmesh.ops.extrude_face_region(bm, geom=[face])
    top = [v for v in ext["geom"] if isinstance(v, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=top, vec=Vector((0, 0, 0.34)))
    for v in top:                  # the draft: scaled towards a point on the centre line, a little behind the pivot
        v.co.x *= 0.92
        v.co.y = 0.2 + (v.co.y - 0.2) * 0.95
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    sharp = [e for e in bm.edges if e.calc_face_angle(0) > math.radians(30)]
    bmesh.ops.bevel(bm, geom=sharp, offset=0.055, segments=6, profile=0.5, affect="EDGES", clamp_overlap=True)
    me = bpy.data.meshes.new("Pointer")
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    head = bpy.data.objects.new("Pointer", me)
    bpy.context.scene.collection.objects.link(head)
    wn = head.modifiers.new("Normals", "WEIGHTED_NORMAL")   # flat faces stay flat, the rounds stay smooth
    wn.keep_sharp = True
    wn.mode = "FACE_AREA"
    head.data.materials.append(satin_plastic("Satin", lambda nt, sep: line_mask(nt, sep, 0.026, 0.02, 0.70, 0.425)))
    objs.append(head)
    ink = ink_mat("Ink")
    for k, ang in enumerate(SELECTOR):
        a = math.pi / 2 + ang
        bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=0.07, depth=0.003,
                                            location=(1.05 * math.cos(a), 1.05 * math.sin(a), 0.0015))
        dot = bpy.context.object
        dot.name = f"Dot{k}"
        dot.data.materials.append(ink)
        objs.append(dot)
    return objs, 2.9, head


def color_R(s, view=""):
    """Look R's colour management: AgX rolls the highlights off as film does instead of clipping them; its
    medium-high contrast look keeps the black plastic black and the paint white."""
    view = view or "agx-high"
    vt, look, ev = {"agx": ("AgX", "AgX - Medium High Contrast", 0.35), "agx-punchy": ("AgX", "AgX - Punchy", 0.35),
                    "agx-high": ("AgX", "AgX - High Contrast", 0.45), "filmic": ("Filmic", "None", 0.3),
                    "standard": ("Standard", "None", 0.0)}[view]
    s.view_settings.view_transform = vt
    s.view_settings.look = look
    s.view_settings.exposure = ev


# ---------------------------------------------------------------- strip

def write_strip(frame_paths, out_png):
    """Joins frames top to bottom (frame 0 at the top) into one PNG, keeping straight alpha."""
    imgs = [bpy.data.images.load(p, check_existing=False) for p in frame_paths]
    w, h = imgs[0].size
    arrs = []
    for im in imgs:
        a = np.empty(w * h * 4, dtype=np.float32)
        im.pixels.foreach_get(a)
        arrs.append(a.reshape(h, w, 4))
    # Blender stores rows bottom-up, so the last frame goes first.
    strip = np.concatenate(arrs[::-1], axis=0)
    out = bpy.data.images.new("strip", w, h * len(imgs), alpha=True)
    out.alpha_mode = "STRAIGHT"
    out.pixels.foreach_set(strip.ravel())
    out.filepath_raw = out_png
    out.file_format = "PNG"
    out.save()
    for im in imgs:
        bpy.data.images.remove(im)
    print("STRIP", out_png, w, "x", h * len(imgs), len(imgs), "frames")


# ---------------------------------------------------------------- main

def main():
    global Q
    a = args()
    Q = 2 if a.look in ("R", "RT") else a.quality     # look R is built on the hyper-real round
    glow = tuple(float(x) for x in a.glow.split(","))
    s = reset()
    world(s)
    lights_v2() if Q == 2 else lights()
    shadow_catcher()
    frames = {"S": 2, "T": 3, "RT": 3}.get(a.look, a.frames)
    bpy.context.preferences.edit.keyframe_new_interpolation_type = "LINEAR"
    s.frame_start, s.frame_end = 1, frames
    values = []
    if a.look == "A":
        objs, scale = knob_A()
    elif a.look == "B":
        objs, scale = knob_B()
    elif a.look == "C":
        objs, scale, (ring, halo, values) = knob_C(glow)
    elif a.look == "D":
        objs, scale = knob_D()
    elif a.look == "R":
        objs, scale = knob_R()
    elif a.look == "T":
        objs, scale, pointer = selector_T()
    elif a.look == "RT":
        objs, scale, pointer = selector_R()
    elif a.look == "P":
        objs, scale = panel_P()
        frames = 1
        s.frame_end = 1
    else:
        objs, scale, lever = switch_S()
    (camera_v2 if Q == 2 else camera)(a.cam, scale, target_z=0.55 if a.look == "S" else 0.28)
    use_engine(s, a.engine, a.samples, a.size)
    if Q == 2 and a.engine == "cycles":
        use_engine_v2(s, a.samples)
    if a.look in ("R", "RT"):
        color_R(s, a.view)
    if a.look == "P":   # a 12:5 picture, the camera's width spanning the plate
        s.render.resolution_x, s.render.resolution_y = a.size * 3, round(a.size * 1.25)

    # The sweep: frame 1 is the minimum, frame N the maximum, linear in between.
    if a.look == "P":
        pass
    elif a.look == "S":
        for f, ang in ((1, -30), (2, 30)):          # off: lever tipped towards the viewer's bottom; on: top
            lever.rotation_euler.x = math.radians(-ang)
            lever.keyframe_insert("rotation_euler", index=0, frame=f)
    elif a.look in ("T", "RT"):
        for f, ang in enumerate(SELECTOR, start=1):   # one frame per position, constant between them
            pointer.rotation_euler.z = ang
            pointer.keyframe_insert("rotation_euler", index=2, frame=f)
    else:
        knob = objs[0]
        for f, v in ((1, 0.0), (frames, 1.0)):
            knob.rotation_euler.z = SWEEP / 2 - SWEEP * v
            knob.keyframe_insert("rotation_euler", index=2, frame=f)
            for node in values:
                node.outputs[0].default_value = v
                node.outputs[0].keyframe_insert("default_value", frame=f)

    os.makedirs(a.out, exist_ok=True)
    if a.blend:
        os.makedirs(os.path.dirname(a.blend), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=a.blend)
        print("BLEND", a.blend)

    tag = f"{a.look}_{a.cam}" + ("_q2" if Q == 2 else "")
    if a.still >= 0:
        s.frame_set(a.still + 1)
        s.render.filepath = os.path.join(a.out, f"still_{tag}_{a.still:03d}.png")
        bpy.ops.render.render(write_still=True)
        print("STILL", s.render.filepath)
        return
    fdir = os.path.join(a.out, f"frames_{tag}")
    os.makedirs(fdir, exist_ok=True)
    s.render.filepath = os.path.join(fdir, "f_")
    s.render.use_overwrite = False                     # resumable
    s.render.use_placeholder = False
    bpy.ops.render.render(animation=True)
    paths = [os.path.join(fdir, f"f_{f:04d}.png") for f in range(1, frames + 1)]
    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        print("ERROR missing frames", len(missing))
        sys.exit(1)
    name = {"S": "switch", "T": "selector", "RT": "selectorR", "P": "panel"}.get(a.look, f"knob{a.look}")
    if a.no_strip:
        print("FRAMES", fdir, frames)
        return
    write_strip(paths, os.path.join(a.out, f"{name}_{a.cam}_{frames}f_{a.size}" + ("_q2" if Q == 2 else "") + ".png"))


if __name__ == "__main__":
    main()
