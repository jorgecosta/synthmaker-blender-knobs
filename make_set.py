#!/usr/bin/env python3
# SynthMaker Blender knobs · Copyright (c) 2026 ViDesk Ltd · MIT licence (see LICENSE beside this file)
"""Writes a SynthMaker controls set (.smcontrols, SM-066 step 1) from rendered strips.

    make_set.py OUT.smcontrols "Set name" kind:camera:size:sweep:path[:slice[:id]] [...]

kind is knob, switch or image; camera top or iso (or -); size in points; sweep in degrees (or -). The picture's
frame count comes from its shape for knobs and switches (height / width), 1 for an image. id names the control in
the set ("selector"); by default it's knob, toggle or faceplate (knob-iso for the tilted camera). The file is the JSON
SynthMaker reads (ControlSet in SynthMaker/Model/ControlSet.swift): each picture's bytes in base64, its pixel size,
its frames, nine-slice insets for a background picture (slice = "top,leading,bottom,trailing" in pixels), and an id that is the first 8 bytes of its SHA-256, so the app can check nothing was swapped.
"""
import base64, hashlib, json, os, subprocess, sys, uuid


def size_of(path):
    out = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", path], capture_output=True, text=True).stdout
    vals = {l.split(":")[0].strip(): int(l.split(":")[1]) for l in out.splitlines()[1:] if ":" in l}
    return vals["pixelWidth"], vals["pixelHeight"]


def main():
    out, name, specs = sys.argv[1], sys.argv[2], sys.argv[3:]
    controls = []
    for spec in specs:
        parts = spec.split(":")
        kind, camera, size, sweep, path = parts[:5]
        slice_px = [int(v) for v in parts[5].split(",")] if len(parts) > 5 and parts[5] else None
        given_id = parts[6] if len(parts) > 6 and parts[6] else None
        data = open(path, "rb").read()
        w, h = size_of(path)
        frames = 1 if kind == "image" else h // w
        stem = os.path.splitext(os.path.basename(path))[0]
        nice = {"knob": "knob", "switch": "toggle", "image": "faceplate"}[kind]
        control = {
            "id": given_id or nice + ("-iso" if camera == "iso" else ""),   # "knob", "toggle", "faceplate"; "knob-iso" tilted
            "kind": kind,
            "image": {"id": hashlib.sha256(data).digest()[:8].hex(), "name": f"{name} {given_id or nice}", "data": base64.b64encode(data).decode(),
                      "width": w, "height": h, "frames": frames},
        }
        if slice_px: control["image"]["slice"] = slice_px
        if camera != "-": control["camera"] = camera
        if size != "-": control["size"] = float(size)
        if sweep != "-": control["sweep"] = float(sweep)
        controls.append(control)
        print(f"{stem}: {kind} {w}x{h} {frames} frames {len(data) // 1024} KB")
    doc = {"schemaVersion": 1, "id": str(uuid.uuid5(uuid.NAMESPACE_URL, "synthmaker:controls/" + name)).upper(),
           "name": name, "author": "SynthMaker", "controls": controls}
    with open(out, "w") as f:
        json.dump(doc, f, sort_keys=True, separators=(",", ":"))
    print("SET", out, os.path.getsize(out) // 1024, "KB")


if __name__ == "__main__":
    main()
