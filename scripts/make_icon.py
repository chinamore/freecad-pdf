"""Generates assets/icon.png and assets/icon.ico for the application."""
from PIL import Image, ImageDraw, ImageFont

S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# dark navy rounded square (matches app theme)
d.rounded_rectangle([8, 8, S - 8, S - 8], radius=48, fill=(15, 29, 50, 255))

# balloon circle (red) with number 1
cx, cy, r = S // 2, S // 2 - 12, 78
d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(239, 51, 64, 255), width=18)
try:
    font = ImageFont.truetype("DejaVuSans-Bold.ttf", 96)
except OSError:
    font = ImageFont.load_default()
d.text((cx, cy - 8), "1", font=font, fill=(255, 255, 255, 255), anchor="mm")

# small sketcher-style axes mark bottom-left (nod to the 2D sketcher)
ax_x, ax_y = 52, S - 40
d.line([ax_x, ax_y, ax_x + 34, ax_y], fill=(22, 163, 74, 255), width=10)
d.line([ax_x, ax_y, ax_x, ax_y - 34], fill=(34, 134, 213, 255), width=10)

img.save("assets/icon.png")
img.save("assets/icon.ico",
         sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icons written to assets/icon.png, assets/icon.ico")
