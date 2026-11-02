# SynthMaker Blender pads · Copyright (c) 2026 ViDesk Ltd · MIT licence (see LICENSE beside this file)
"""SynthMaker controls: groovebox pads rendered as 4-frame filmstrips (bpy, Blender 5.2). Controls 3.

A pad is a block of translucent silicone with soft rounded edges, sitting in a satin-black moulded well, the way a
drum machine's or a pad controller's pads do. The silicone glows when lit (an emission in it, which also lights the well round it). Four frames, top to
bottom (the order SynthMaker's Button reads them in):

    0 off      1 pressed (pushed down 0.6 mm and squashed a touch)      2 lit      3 lit and pressed

    Blender -b --factory-startup --python pads.py -- --pad red --out DIR [--size 512] [--still N]

Pads: red, amber, green, blue, white (coloured silicone), and the transport pads play, stop and playstop: dark grey
rubber with a translucent legend (a triangle, a square, or both) that lights green when lit, the way a hardware
transport button shows the song running.

Everything is made here (no downloaded models, textures or HDRIs), with the studio, cameras and render settings of
knob.py's hyper-real round (quality 2): the lights never move, so only the pad moves and glows between frames.
"""

import bpy, math, os, sys, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import knob  # noqa: E402  (the shared studio: lights, camera, engine, strip writer)
from knob import node_mat, set_in  # noqa: E402

PADS = {
    # name: (silicone colour when off (linear), glow colour)
    "red": ((0.42, 0.035, 0.03), (1.0, 0.07, 0.04)),
    "amber": ((0.50, 0.20, 0.025), (1.0, 0.42, 0.04)),
    "green": ((0.08, 0.36, 0.08), (0.20, 1.0, 0.16)),
    "blue": ((0.03, 0.12, 0.48), (0.10, 0.38, 1.0)),
    "white": ((0.62, 0.62, 0.60), (1.0, 0.93, 0.80)),
}
TRANSPORT = {"play": ("tri",), "stop": ("sq",), "playstop": ("tri", "sq")}
LEGEND_GLOW = (0.18, 1.0, 0.25)

W = 1.60         # pad width (scene units; the camera frames 2.7)
H = 0.40         # pad height (its top stands 1 mm proud of the well's lip)
WELL = 2.16      # the well's outside
PRESS = 0.13     # how far a press pushes the pad down (most of the way into its well)


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--pad", default="red", choices=list(PADS) + list(TRANSPORT))
    p.add_argument("--size", type=int, default=512)
    p.add_argument("--samples", type=int, default=768)
    p.add_argument("--still", type=int, default=-1, help="render only this frame (0-3) and stop")
    p.add_argument("--out", required=True)
    p.add_argument("--blend", default="")
    return p.parse_args(argv)


def rounded_box(name, sx, sy, sz, radius, segments=10, z=0.0):
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, z + sz / 2))
    o = bpy.context.object
    o.name = name
    o.scale = (sx, sy, sz)
    bpy.ops.object.transform_apply(scale=True)
    bev = o.modifiers.new("Bevel", "BEVEL")
    bev.width = radius
    bev.segments = segments
    bev.limit_method = "NONE"
    bpy.ops.object.shade_smooth()
    return o


def well():
    """The moulded surround: a satin-black frame with a softly rounded lip, the pad sunk inside it."""
    frame = rounded_box("Well", WELL, WELL, 0.30, 0.10, 8)
    hole = rounded_box("Hole", W + 0.08, W + 0.08, 1.0, 0.16, 8, z=0.06)
    boo = frame.modifiers.new("Hole", "BOOLEAN")
    boo.operation = "DIFFERENCE"
    boo.solver = "EXACT"
    boo.object = hole
    hole.hide_render = True
    hole.hide_viewport = True
    # The lip catches light: bevel what the boolean left sharp.
    lip = frame.modifiers.new("Lip", "BEVEL")
    lip.width = 0.02
    lip.segments = 3
    lip.limit_method = "ANGLE"
    frame.data.materials.append(knob.satin_plastic("Satin", color=0.012, rough0=0.32))
    return frame


def silicone(name, color, glow, legend=()):
    """Translucent silicone: subsurface scattering in the pad's colour, a matte top with a fine moulding texture, and
    an emission that a keyed value turns on for the lit frames (a light under the pad, seen through the silicone).
    Lit, the surface colour dims so the glow, not the studio's light on it, gives the colour: it stays saturated.
    `legend` (transport pads): the pad is dark rubber and only a printed triangle and/or square on its top glows."""
    m, nt, b = node_mat(name)
    rubber = bool(legend)
    set_in(b, Roughness=0.62 if rubber else 0.55, Subsurface_Weight=0.0 if rubber else 0.6, Subsurface_Scale=0.25,
           Specular_IOR_Level=0.3, Sheen_Weight=0.2, Sheen_Roughness=0.6)
    b.inputs["Subsurface Radius"].default_value = (1.0, 0.6, 0.4)
    b.inputs["Emission Color"].default_value = (*glow, 1)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 160
    noise.inputs["Detail"].default_value = 3
    nt.links.new(tc.outputs["Object"], noise.inputs["Vector"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.08
    nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    lit = nt.nodes.new("ShaderNodeValue")
    lit.name = "Lit"

    def math(op, x, y=None):
        n = nt.nodes.new("ShaderNodeMath")
        n.operation = op
        for i, v in enumerate((x, y)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = v
            else:
                nt.links.new(v, n.inputs[i])
        return n.outputs[0]

    if rubber:
        # The legend's mask from the pad's own coordinates (its top is at z = +H/2): 1 inside a shape, 0 outside.
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        nt.links.new(tc.outputs["Object"], sep.inputs[0])
        x, y, z = sep.outputs["X"], sep.outputs["Y"], sep.outputs["Z"]
        top = math("GREATER_THAN", z, H * 0.35)
        mask = None
        gap = 0.30 if len(legend) == 2 else 0.0
        for i, kind in enumerate(legend):
            cx = (i - (len(legend) - 1) / 2) * gap * 2
            dx = math("SUBTRACT", x, cx)
            ay = math("ABSOLUTE", y)
            if kind == "tri":
                r = 0.27 if len(legend) == 1 else 0.20
                left = math("GREATER_THAN", dx, -0.62 * r)
                # inside while 0.95r - dx - 1.57|y| > 0
                slope = math("SUBTRACT", math("SUBTRACT", 0.95 * r, dx), math("MULTIPLY", ay, 1.57))
                inside = math("MULTIPLY", left, math("GREATER_THAN", slope, 0.0))
            else:
                r = 0.22 if len(legend) == 1 else 0.16
                inside = math("LESS_THAN", math("MAXIMUM", math("ABSOLUTE", dx), ay), r)
            mask = inside if mask is None else math("MAXIMUM", mask, inside)
        mask = math("MULTIPLY", mask, top)
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.inputs["A"].default_value = (*color, 1)
        mix.inputs["B"].default_value = (0.42, 0.44, 0.42, 1)   # the legend's ink, pale when unlit
        # Lit, the ink darkens and the light behind it shows through, green (strong enough to glow, not to clip white).
        ink = nt.nodes.new("ShaderNodeMix")
        ink.data_type = "RGBA"
        ink.inputs["A"].default_value = (0.42, 0.44, 0.42, 1)
        ink.inputs["B"].default_value = (0.03, 0.10, 0.04, 1)
        nt.links.new(lit.outputs[0], ink.inputs["Factor"])
        nt.links.new(ink.outputs["Result"], mix.inputs["B"])
        nt.links.new(mask, mix.inputs["Factor"])
        nt.links.new(mix.outputs["Result"], b.inputs["Base Color"])
        nt.links.new(math("MULTIPLY", math("MULTIPLY", lit.outputs[0], mask), 0.9), b.inputs["Emission Strength"])
    else:
        # Lit: the surface colour drops to 35% and the glow takes over.
        dim = nt.nodes.new("ShaderNodeMix")
        dim.data_type = "RGBA"
        dim.inputs["A"].default_value = (*color, 1)
        dim.inputs["B"].default_value = (color[0] * 0.35, color[1] * 0.35, color[2] * 0.35, 1)
        nt.links.new(lit.outputs[0], dim.inputs["Factor"])
        nt.links.new(dim.outputs["Result"], b.inputs["Base Color"])
        nt.links.new(math("MULTIPLY", lit.outputs[0], 1.15), b.inputs["Emission Strength"])
    return m, lit


def main():
    a = args()
    knob.Q = 2
    s = knob.reset()
    knob.world(s)
    knob.lights_v2()
    knob.shadow_catcher()
    s.frame_start, s.frame_end = 1, 4
    transport = a.pad in TRANSPORT

    well()
    if transport:
        color, glow = (0.030, 0.031, 0.034), LEGEND_GLOW
    else:
        color, glow = PADS[a.pad]
    pad = rounded_box("Pad", W, W, H, 0.20, 12, z=0.0)
    mat, pad_lit = silicone("Silicone", color, glow, legend=TRANSPORT.get(a.pad, ()))
    pad.data.materials.append(mat)
    # The four frames: off, pressed, lit, lit and pressed. Constant between keys.
    for f, (pressed, lit) in enumerate(((0, 0), (1, 0), (0, 1), (1, 1)), start=1):
        # The pad's origin is its middle: pushed down, squashed a touch and a little narrower to the long lens.
        pad.location.z = H / 2 - PRESS * pressed
        pad.keyframe_insert("location", index=2, frame=f)
        pad.scale = (1.0 - 0.02 * pressed, 1.0 - 0.02 * pressed, 1.0 - 0.10 * pressed)
        pad.keyframe_insert("scale", frame=f)
        pad_lit.outputs[0].default_value = float(lit)
        pad_lit.outputs[0].keyframe_insert("default_value", frame=f)

    knob.camera_v2("top", 2.7, target_z=0.2)
    knob.use_engine(s, "cycles", a.samples, a.size)
    knob.use_engine_v2(s, a.samples)
    os.makedirs(a.out, exist_ok=True)
    if a.blend:
        os.makedirs(os.path.dirname(a.blend), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=a.blend)
        print("BLEND", a.blend)
    if a.still >= 0:
        s.frame_set(a.still + 1)
        s.render.filepath = os.path.join(a.out, f"still_pad_{a.pad}_{a.still}.png")
        bpy.ops.render.render(write_still=True)
        print("STILL", s.render.filepath)
        return
    fdir = os.path.join(a.out, f"frames_pad_{a.pad}")
    os.makedirs(fdir, exist_ok=True)
    s.render.filepath = os.path.join(fdir, "f_")
    s.render.use_overwrite = False   # resumable
    bpy.ops.render.render(animation=True)
    paths = [os.path.join(fdir, f"f_{f:04d}.png") for f in range(1, 5)]
    if not all(os.path.exists(p) for p in paths):
        print("ERROR missing frames")
        sys.exit(1)
    print("FRAMES", fdir, 4)


if __name__ == "__main__":
    main()
