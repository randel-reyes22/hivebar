// Renders the Hivebar menu-bar icon (an asterisk inside a hexagon) and prints
// base64 PNGs for hivebar.30s.py's ICONS table.
// Usage: swift tools/make_icons.swift
import AppKit

let size: CGFloat = 36  // 18pt @2x

func symbol(_ name: String, _ points: CGFloat, _ weight: NSFont.Weight) -> NSImage {
    let config = NSImage.SymbolConfiguration(pointSize: points, weight: weight)
    return NSImage(systemSymbolName: name, accessibilityDescription: nil)!.withSymbolConfiguration(config)!
}

func render(_ color: NSColor) -> String {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size), pixelsHigh: Int(size),
                               bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                               colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    for (name, points, weight) in [("hexagon", size * 0.86, NSFont.Weight.medium),
                                   ("asterisk", size * 0.40, NSFont.Weight.heavy)] {
        let img = symbol(name, points, weight)
        let rect = NSRect(x: (size - img.size.width) / 2, y: (size - img.size.height) / 2,
                          width: img.size.width, height: img.size.height)
        img.draw(in: rect)
        color.set()
        rect.fill(using: .sourceAtop)
    }
    NSGraphicsContext.restoreGraphicsState()
    rep.size = NSSize(width: size / 2, height: size / 2)  // mark as @2x so it shows at 18pt
    return rep.representation(using: .png, properties: [:])!.base64EncodedString()
}

for (key, color) in [("template", NSColor.black), ("orange", NSColor.systemOrange), ("red", NSColor.systemRed)] {
    print("    \"\(key)\": \"\(render(color))\",")
}
