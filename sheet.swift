// Contact sheets for control filmstrips, with CoreGraphics (no third-party tools).
//
//   swift sheet.swift --out sheet.png --title "Look A" [--cols 8] [--cell 192] [--bg 1c1c1e] ITEM...
//
// An ITEM is a PNG ("still.png" or "Label=still.png"), or frames picked from a vertical strip:
// "Label=strip.png#128@0,16,32" (frame count, then the frames to show; "@8" alone = 8 evenly spaced).
// A row break is "--row" (optionally "--row=Caption"). Also: `swift sheet.swift --sizes strip.png` prints the
// strip's PNG size and what HEIC (with alpha) would weigh, through ImageIO as iOS has it; and
// `swift sheet.swift --heic in.png out.heic 0.8` writes the HEIC copy the app would keep (alpha kept).
import AppKit
import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

func load(_ path: String) -> CGImage {
    guard let src = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
          let img = CGImageSourceCreateImageAtIndex(src, 0, nil) else { fatalError("can't read \(path)") }
    return img
}

func encode(_ img: CGImage, _ type: UTType, quality: Double? = nil) -> Data {
    let data = NSMutableData()
    let dest = CGImageDestinationCreateWithData(data, type.identifier as CFString, 1, nil)!
    var opts: [CFString: Any] = [:]
    if let quality { opts[kCGImageDestinationLossyCompressionQuality] = quality }
    CGImageDestinationAddImage(dest, img, opts as CFDictionary)
    CGImageDestinationFinalize(dest)
    return data as Data
}

func color(_ hex: String) -> CGColor {
    let v = UInt32(hex, radix: 16) ?? 0x1c1c1e
    return CGColor(red: CGFloat((v >> 16) & 255) / 255, green: CGFloat((v >> 8) & 255) / 255, blue: CGFloat(v & 255) / 255, alpha: 1)
}

var args = Array(CommandLine.arguments.dropFirst())

if args.first == "--heic", args.count == 4 {
    let png = (try? Data(contentsOf: URL(fileURLWithPath: args[1])))?.count ?? 0
    let img = load(args[1])
    let heic = encode(img, .heic, quality: Double(args[3]) ?? 0.8)
    try! heic.write(to: URL(fileURLWithPath: args[2]))
    print(String(format: "%@  %dx%d  PNG %.0f KB  ->  HEIC %.0f KB", (args[1] as NSString).lastPathComponent, img.width, img.height,
                 Double(png) / 1024, Double(heic.count) / 1024))
    exit(0)
}

if args.first == "--sizes" {
    for path in args.dropFirst() {
        let png = (try? Data(contentsOf: URL(fileURLWithPath: path)))?.count ?? 0
        let img = load(path)
        let heic80 = encode(img, .heic, quality: 0.8).count
        let heic60 = encode(img, .heic, quality: 0.6).count
        print(String(format: "%@  %dx%d  PNG %.0f KB  HEIC q0.8 %.0f KB  HEIC q0.6 %.0f KB", (path as NSString).lastPathComponent,
                     img.width, img.height, Double(png) / 1024, Double(heic80) / 1024, Double(heic60) / 1024))
    }
    exit(0)
}

var out = "sheet.png", title = "", cols = 8, cell = 192, bg = "1c1c1e"
var rows: [(caption: String, items: [(label: String, image: CGImage)])] = [("", [])]
var i = 0
while i < args.count {
    let a = args[i]
    switch a {
    case "--out": out = args[i + 1]; i += 2; continue
    case "--title": title = args[i + 1]; i += 2; continue
    case "--cols": cols = Int(args[i + 1])!; i += 2; continue
    case "--cell": cell = Int(args[i + 1])!; i += 2; continue
    case "--bg": bg = args[i + 1]; i += 2; continue
    default: break
    }
    if a.hasPrefix("--row") {
        let caption = a.contains("=") ? String(a.split(separator: "=", maxSplits: 1)[1]) : ""
        if rows.last!.items.isEmpty { rows[rows.count - 1].caption = caption } else { rows.append((caption, [])) }
        i += 1
        continue
    }
    var label = "", spec = a
    if let eq = a.firstIndex(of: "="), !a[..<eq].contains("/") { label = String(a[..<eq]); spec = String(a[a.index(after: eq)...]) }
    if let hash = spec.firstIndex(of: "#") {
        let path = String(spec[..<hash])
        let rest = spec[spec.index(after: hash)...].split(separator: "@")
        let n = Int(rest[0])!
        let picks: [Int]
        if rest.count > 1, rest[1].contains(",") { picks = rest[1].split(separator: ",").map { Int($0)! } }
        else { let k = rest.count > 1 ? Int(rest[1])! : 8; picks = (0..<k).map { k == 1 ? 0 : Int((Double($0) * Double(n - 1) / Double(k - 1)).rounded()) } }
        let strip = load(path)
        let fh = strip.height / n
        for p in picks {
            let frame = strip.cropping(to: CGRect(x: 0, y: p * fh, width: strip.width, height: fh))!
            let pct = n > 1 ? Int((Double(p) / Double(n - 1) * 100).rounded()) : 0
            rows[rows.count - 1].items.append(((label.isEmpty ? "" : label + " ") + (n == 2 ? (p == 0 ? "off" : "on") : "\(pct)%"), frame))
        }
    } else {
        rows[rows.count - 1].items.append((label, load(spec)))
    }
    i += 1
}

let pad = 16, labelH = 22, titleH = title.isEmpty ? 0 : 44, captionH = 24
let maxItems = rows.map { $0.items.count }.max() ?? 1
let ncols = min(cols, maxItems)
let gridRows = rows.reduce(0) { $0 + max(1, Int(ceil(Double($1.items.count) / Double(ncols)))) }
let captions = rows.filter { !$0.caption.isEmpty }.count
let W = pad + ncols * (cell + pad)
let H = pad + titleH + captions * captionH + gridRows * (cell + labelH + pad)
let ctx = CGContext(data: nil, width: W, height: H, bitsPerComponent: 8, bytesPerRow: 0, space: CGColorSpace(name: CGColorSpace.sRGB)!,
                    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
ctx.setFillColor(color(bg))
ctx.fill(CGRect(x: 0, y: 0, width: W, height: H))
ctx.interpolationQuality = .high
NSGraphicsContext.current = NSGraphicsContext(cgContext: ctx, flipped: false)
let light = (Int(bg, radix: 16) ?? 0) > 0x808080
func text(_ s: String, x: Int, yTop: Int, size: CGFloat, bold: Bool = false, alpha: CGFloat = 0.8) {
    let attrs: [NSAttributedString.Key: Any] = [
        .font: bold ? NSFont.systemFont(ofSize: size, weight: .semibold) : NSFont.monospacedDigitSystemFont(ofSize: size, weight: .regular),
        .foregroundColor: (light ? NSColor.black : NSColor.white).withAlphaComponent(alpha)]
    NSAttributedString(string: s, attributes: attrs).draw(at: CGPoint(x: x, y: H - yTop - Int(size * 1.25)))
}
var y = pad
if !title.isEmpty { text(title, x: pad, yTop: y, size: 22, bold: true, alpha: 0.95); y += titleH }
for row in rows {
    if !row.caption.isEmpty { text(row.caption, x: pad, yTop: y, size: 14, bold: true, alpha: 0.65); y += captionH }
    for (k, item) in row.items.enumerated() {
        let c = k % ncols
        if k > 0 && c == 0 { y += cell + labelH + pad }
        let x = pad + c * (cell + pad)
        ctx.draw(item.image, in: CGRect(x: x, y: H - y - cell, width: cell, height: cell))
        if !item.label.isEmpty { text(item.label, x: x, yTop: y + cell + 3, size: 12) }
    }
    y += cell + labelH + pad
}
let png = encode(ctx.makeImage()!, .png)
try! png.write(to: URL(fileURLWithPath: out))
print("SHEET", out, W, "x", H)
