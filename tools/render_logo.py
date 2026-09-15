"""Render the DIVA brand assets as transparent PNG and multi-size Windows ICO."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
ASSETS.mkdir(exist_ok=True)
SCALE = 3


def font(size: int, bold: bool = True):
    font_path = Path(ImageFont.__file__).parent / "fonts" / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
    try:
        return ImageFont.truetype(str(font_path), size * SCALE)
    except OSError:
        return ImageFont.load_default(size * SCALE)


def draw_icon(size: int = 512) -> Image.Image:
    factor = size / 512
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    def pt(x, y):
        return round(x * factor), round(y * factor)
    def coords(values):
        return [round(value * factor) for value in values]

    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=round(116 * factor), fill="#151a33")
    waveform = [(75, 267), (117, 267), (141, 193), (179, 361), (220, 110),
                (262, 390), (302, 200), (334, 304), (365, 267), (437, 267)]
    for index, (a, b) in enumerate(zip(waveform, waveform[1:])):
        mix = index / max(1, len(waveform) - 2)
        start = (255, 78, 161)
        end = (72, 224, 232)
        color = tuple(round(start[c] * (1 - mix) + end[c] * mix) for c in range(3)) + (235,)
        draw.line([pt(*a), pt(*b)], fill=color, width=max(1, round(29 * factor)), joint="curve")
    for x in (212, 269, 326):
        draw.line([pt(x, 126), pt(x, 486)], fill=(255, 255, 255, 30), width=max(1, round(18 * factor)))
    draw.polygon([pt(211, 210), pt(350, 298), pt(211, 386)], fill="#e9fbff",
                 outline="#151a33", width=max(1, round(18 * factor)))
    return image


icon = draw_icon(512)
icon.save(ASSETS / "diva-icon.png")
icon.save(ASSETS / "diva-icon.ico", format="ICO",
          sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

logo = Image.new("RGBA", (720 * SCALE, 300 * SCALE), (0, 0, 0, 0))
mark = draw_icon(240 * SCALE)
logo.alpha_composite(mark, (24 * SCALE, 30 * SCALE))
draw = ImageDraw.Draw(logo)
draw.text((300 * SCALE, 54 * SCALE), "DIVA", font=font(94), fill="#151a33", spacing=2 * SCALE)
draw.text((304 * SCALE, 166 * SCALE), "USM CONVERTER", font=font(30), fill="#6a738e", spacing=3 * SCALE)
for x in range(304, 642, 2):
    t = (x - 304) / (642 - 304)
    color = (round(255 * (1 - t) + 72 * t), round(78 * (1 - t) + 224 * t),
             round(161 * (1 - t) + 232 * t), 255)
    draw.line((x * SCALE, 229 * SCALE, (x + 1) * SCALE, 229 * SCALE), fill=color, width=7 * SCALE)
logo.save(ASSETS / "diva-logo.png")
