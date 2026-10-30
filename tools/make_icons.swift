// Renders the Hivebar menu-bar icon (an asterisk inside a hexagon) and prints
// base64 PNGs for hivebar.30s.py's ICONS table.
// Usage: swift tools/make_icons.swift
import AppKit

let size: CGFloat = 36  // 18pt @2x

func symbol(_ name: String, _ points: CGFloat, _ weight: NSFont.Weight) -> NSImage {
    let config = NSImage.SymbolConfiguration(pointSize: points, weight: weight)
    return NSImage(systemSymbolName: name, accessibilityDescription: nil)!.withSymbolConfiguration(config)!
}

// Alert icons are a solid hexagon with a white asterisk, so they stay readable on any
// wallpaper; the plain icon is an outline that macOS tints for light and dark menu bars.
func render(_ color: NSColor, filled: Bool) -> String {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size), pixelsHigh: Int(size),
                               bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                               colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    let layers: [(String, CGFloat, NSFont.Weight, NSColor)] = filled
        ? [("hexagon.fill", size * 0.86, .medium, color), ("asterisk", size * 0.40, .heavy, .white)]
        : [("hexagon", size * 0.86, .medium, color), ("asterisk", size * 0.40, .heavy, color)]
    for (name, points, weight, tint) in layers {
        let img = symbol(name, points, weight)
        let rect = NSRect(x: (size - img.size.width) / 2, y: (size - img.size.height) / 2,
                          width: img.size.width, height: img.size.height)
        img.draw(in: rect)
        let layer = NSImage(size: img.size, flipped: false) { r in
            img.draw(in: r)
            tint.set()
            r.fill(using: .sourceAtop)
            return true
        }
        layer.draw(in: rect)
    }
    NSGraphicsContext.restoreGraphicsState()
    rep.size = NSSize(width: size / 2, height: size / 2)  // mark as @2x so it shows at 18pt
    return rep.representation(using: .png, properties: [:])!.base64EncodedString()
}

for (key, color, filled) in [("template", NSColor.black, false), ("orange", NSColor.systemOrange, true),
                             ("red", NSColor.systemRed, true)] {
    print("    \"\(key)\": \"\(render(color, filled: filled))\",")
}
