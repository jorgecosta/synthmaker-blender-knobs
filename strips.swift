// Joins rendered frames into app filmstrips, scaled with high-quality filtering (CoreGraphics, no third-party tools).
//
//   swift strips.swift FRAMES_DIR OUT.png SIZE [COUNT]
//
// Reads f_0001.png … in order and keeps COUNT of them (all by default), each the rendered frame nearest to its own
// value k / (COUNT − 1), so a 64-frame strip made from 128 renders still runs evenly from the minimum to the
// maximum. Each is scaled to SIZE × SIZE and stacked top to bottom, frame 0 at the top.
// Rendering at 512 px and scaling to 256 gives a supersampled strip: less noise, cleaner edges.
import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

let a = CommandLine.arguments
guard a.count >= 4, let size = Int(a[3]) else { fputs("usage: strips.swift FRAMES_DIR OUT.png SIZE [COUNT]\n", stderr); exit(2) }
let files = try FileManager.default.contentsOfDirectory(atPath: a[1]).filter { $0.hasPrefix("f_") && $0.hasSuffix(".png") }.sorted()
guard !files.isEmpty else { fputs("no frames in \(a[1])\n", stderr); exit(1) }
let count = a.count > 4 ? min(max(2, Int(a[4]) ?? files.count), files.count) : files.count
let picks = count == files.count ? Array(0..<count)
    : (0..<count).map { Int((Double($0) * Double(files.count - 1) / Double(count - 1)).rounded()) }
let ctx = CGContext(data: nil, width: size, height: size * picks.count, bitsPerComponent: 8, bytesPerRow: 0,
                    space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
ctx.interpolationQuality = .high
for (row, i) in picks.enumerated() {
    let url = URL(fileURLWithPath: a[1]).appending(path: files[i])
    guard let src = CGImageSourceCreateWithURL(url as CFURL, nil), let img = CGImageSourceCreateImageAtIndex(src, 0, nil) else {
        fputs("can't read \(files[i])\n", stderr); exit(1)
    }
    // CoreGraphics' origin is bottom left: frame 0 goes at the top.
    ctx.draw(img, in: CGRect(x: 0, y: size * (picks.count - 1 - row), width: size, height: size))
}
let dest = CGImageDestinationCreateWithURL(URL(fileURLWithPath: a[2]) as CFURL, UTType.png.identifier as CFString, 1, nil)!
CGImageDestinationAddImage(dest, ctx.makeImage()!, nil)
guard CGImageDestinationFinalize(dest) else { fputs("can't write \(a[2])\n", stderr); exit(1) }
print("STRIP \(a[2]) \(size)x\(size * picks.count) \(picks.count) frames")
