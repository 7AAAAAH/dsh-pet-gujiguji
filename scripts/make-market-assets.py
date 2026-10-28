"""Create the storefront icon and screenshots from the pet's own artwork."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
POSES = ASSETS / "poses"
OUT_ICON = ASSETS / "icon-180.png"
OUT_SCREENSHOT = ASSETS / "screenshot-1.png"
FONT_PATH = Path(r"C:\Windows\Fonts\msyh.ttc")


def font(size: int):
    try:
        return ImageFont.truetype(str(FONT_PATH), size)
    except OSError:
        return ImageFont.load_default()


def cover(source: Image.Image, size: tuple[int, int]) -> Image.Image:
    image = source.convert("RGBA")
    scale = max(size[0] / image.width, size[1] / image.height)
    image = image.resize(
        (round(image.width * scale), round(image.height * scale)),
        Image.Resampling.LANCZOS,
    )
    left = (image.width - size[0]) // 2
    top = (image.height - size[1]) // 2
    return image.crop((left, top, left + size[0], top + size[1]))


def rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def make_icon():
    size = (180, 180)
    background = Image.new("RGBA", size, (0, 0, 0, 0))
    gradient = Image.new("RGBA", size)
    pixels = gradient.load()
    for y in range(size[1]):
        for x in range(size[0]):
            t = (x + y) / (size[0] + size[1])
            pixels[x, y] = (
                round(34 + 15 * t),
                round(53 + 22 * t),
                round(55 + 12 * t),
                255,
            )
    background.alpha_composite(gradient)
    pet = cover(Image.open(POSES / "idle_0.png"), (150, 150))
    background.alpha_composite(pet, (15, 12))
    background.putalpha(rounded_mask(size, 38))
    background.save(OUT_ICON, optimize=True)


def card(size: tuple[int, int], fill=(33, 35, 40, 235), radius=18):
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (0, 0, size[0] - 1, size[1] - 1),
        radius=radius,
        fill=fill,
        outline=(255, 255, 255, 18),
        width=1,
    )
    return image


def make_screenshot():
    size = (1280, 720)
    screenshot = Image.new("RGBA", size, (17, 20, 24, 255))
    draw = ImageDraw.Draw(screenshot)
    for y in range(size[1]):
        shade = round(20 + 10 * y / size[1])
        draw.line((0, y, size[0], y), fill=(shade, shade + 3, shade + 6, 255))
    for x in range(-400, 1400, 48):
        draw.line((x, 0, x + 300, 720), fill=(255, 255, 255, 5), width=1)

    title_font = font(38)
    subtitle_font = font(20)
    card_title = font(22)
    card_body = font(16)
    small = font(14)

    draw.text((84, 74), "咕叽咕叽桌宠", font=title_font, fill=(238, 246, 241, 255))
    draw.text(
        (86, 126),
        "GujiGuji · DeepSeek Harness 桌面悬浮宠物",
        font=subtitle_font,
        fill=(166, 186, 177, 255),
    )

    bubble = card((440, 116), fill=(31, 32, 37, 230), radius=20)
    bubble_draw = ImageDraw.Draw(bubble)
    bubble_draw.ellipse((24, 25, 32, 33), fill=(154, 216, 184, 255))
    bubble_draw.text((43, 16), "大肥鱼", font=card_title, fill=(242, 244, 248, 255))
    bubble_draw.text(
        (43, 53),
        "正在分析请求 · 任务状态实时同步",
        font=card_body,
        fill=(174, 180, 192, 255),
    )
    bubble_draw.line((408, 26, 421, 26), fill=(220, 225, 231, 255), width=2)
    screenshot.alpha_composite(bubble, (84, 224))

    notes = card((440, 260), fill=(32, 35, 39, 238), radius=22)
    notes_draw = ImageDraw.Draw(notes)
    notes_draw.text((26, 22), "像 Codex 一样工作", font=card_title, fill=(238, 242, 246, 255))
    features = [
        "只在桌面显示一只宠物",
        "空闲不显示任务气泡",
        "单击随机动作，双击伸头 / 歪头",
        "双击展开 / 收起 DSH",
        "大小、透明度与物理可调",
        "双屏拖动、贴边避让",
    ]
    for index, text in enumerate(features):
        y = 68 + index * 30
        notes_draw.ellipse((28, y + 7, 34, y + 13), fill=(154, 216, 184, 255))
        notes_draw.text(
            (45, y),
            text,
            font=card_body,
            fill=(206, 213, 220, 255),
            stroke_width=1,
            stroke_fill=(32, 35, 39, 255),
        )
    screenshot.alpha_composite(notes, (84, 366))

    stage = card((620, 440), fill=(28, 34, 36, 242), radius=26)
    stage_draw = ImageDraw.Draw(stage)
    stage_draw.text((28, 24), "桌面悬浮预览", font=card_title, fill=(230, 237, 234, 255))
    stage_draw.text(
        (28, 60),
        "任务气泡与宠物同时只出现一份",
        font=small,
        fill=(158, 171, 177, 255),
    )
    stage_pet = cover(Image.open(POSES / "idle_0.png"), (250, 270))
    stage.alpha_composite(stage_pet, (185, 140))
    stage_bubble = card((380, 92), fill=(31, 32, 37, 235), radius=18)
    stage_bubble_draw = ImageDraw.Draw(stage_bubble)
    stage_bubble_draw.ellipse((20, 19, 28, 27), fill=(154, 216, 184, 255))
    stage_bubble_draw.text((36, 10), "大肥鱼", font=card_title, fill=(242, 244, 248, 255))
    stage_bubble_draw.text(
        (36, 45),
        "正在分析请求",
        font=card_body,
        fill=(174, 180, 192, 255),
    )
    stage_bubble_draw.line((346, 22, 360, 22), fill=(220, 225, 231, 255), width=2)
    stage.alpha_composite(stage_bubble, (120, 94))
    screenshot.alpha_composite(stage, (572, 190))

    footer = "dsh-pet-gujiguji  ·  Windows  ·  MIT"
    draw.text((86, 670), footer, font=small, fill=(116, 132, 124, 255))
    screenshot.convert("RGB").save(OUT_SCREENSHOT, optimize=True)


if __name__ == "__main__":
    make_icon()
    make_screenshot()
    print(OUT_ICON)
    print(OUT_SCREENSHOT)
