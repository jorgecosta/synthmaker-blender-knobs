SynthMaker Blender knobs (MIT licence, see LICENSE)

Procedural knobs and a toggle switch for Blender 5.2, rendered as filmstrips: one transparent PNG holding every
position of the control, frame 0 (the minimum) at the top. The same format KnobMan, JUCE and HISE use.

Render the aluminium knob as a 128-frame strip, 256 px per frame, seen from the top:

    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python knob.py -- \
        --look A --cam top --frames 128 --size 256 --out strips --blend strips/knobA.blend

Looks: A brushed aluminium, B vintage bakelite, C dark with a glowing ring, D a drive pedal's knob (soft-touch
black on a skirt, over a printed 0-10 scale that stays still), S toggle switch (2 frames), T a three-way selector
(a chicken-head pointer over three dots, 3 frames), P a faceplate. Cameras: top or iso (30 degrees). --quality 2 adds scratches, wear and a product-photo studio.

live_build.py builds the knob step by step in Blender's interface (open Blender with it: --python live_build.py).
make_set.py packs strips into a .smcontrols file that SynthMaker opens (AirDrop, Messages or Files).
sheet.swift and strips.swift (macOS) make contact sheets and scaled strips.

Blender is free and open source software from the Blender Foundation (blender.org); this script is not made or
endorsed by the Blender Foundation.
