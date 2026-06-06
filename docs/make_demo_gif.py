from pathlib import Path
import math

from PIL import Image, ImageDraw, ImageFont


OUT = Path(__file__).parent / "assets"
OUT.mkdir(parents=True, exist_ok=True)

W, H = 920, 520
BG = (13, 17, 23)
PANEL = (22, 27, 34)
GREEN = (46, 204, 113)
CYAN = (56, 189, 248)
MAGENTA = (217, 70, 239)
RED = (248, 81, 73)
YELLOW = (245, 158, 11)
TEXT = (226, 232, 240)
DIM = (148, 163, 184)

FONT = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", 20)
BOLD = ImageFont.truetype("C:/Windows/Fonts/consolab.ttf", 24)
TITLE = ImageFont.truetype("C:/Windows/Fonts/consolab.ttf", 34)

STEPS = [
    [
        '$ ghostfix watch "npm run dev" --fix --ai',
        "",
        "> next dev",
        "TypeError: Cannot read properties of undefined",
    ],
    [
        "Parsing error...",
        "language: nodejs",
        "file: src/app/page.tsx:18",
        "root cause located",
    ],
    [
        "Searching codebase...",
        "primary file loaded",
        "related files: 2",
        "context lines: 60",
    ],
    [
        "Asking AI for fix...",
        "root_cause: missing null guard",
        "confidence: 0.84",
        "patch ready",
    ],
    [
        "--- a/src/app/page.tsx",
        "+++ b/src/app/page.tsx",
        "- user.name.toUpperCase()",
        '+ user?.name?.toUpperCase() ?? "Guest"',
    ],
    [
        "Patch applied via git apply",
        "Restarting process after fix...",
        "",
        "Ready in 1.2s",
    ],
]

CAPTIONS = [
    "watching your command",
    "error detected",
    "context collected",
    "AI proposes focused patch",
    "review the diff",
    "fixed and restarted",
]
COLORS = [CYAN, RED, CYAN, MAGENTA, YELLOW, GREEN]


def draw_frame(idx: int, sub: int) -> Image.Image:
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)

    d.rounded_rectangle(
        (34, 34, W - 34, H - 34),
        radius=18,
        fill=PANEL,
        outline=(48, 54, 61),
        width=2,
    )
    d.ellipse((62, 58, 78, 74), fill=RED)
    d.ellipse((88, 58, 104, 74), fill=YELLOW)
    d.ellipse((114, 58, 130, 74), fill=GREEN)

    d.text((58, 104), "GhostFix", font=TITLE, fill=TEXT)
    d.text((238, 116), "AI terminal error watcher", font=FONT, fill=DIM)
    d.line((58, 154, W - 58, 154), fill=(48, 54, 61), width=2)

    d.text((58, 182), CAPTIONS[idx], font=BOLD, fill=COLORS[idx])

    y = 230
    visible = min(len(STEPS[idx]), max(1, sub))
    for line in STEPS[idx][:visible]:
        fill = TEXT
        if "TypeError" in line or line.startswith("-"):
            fill = RED
        if line.startswith("+"):
            fill = GREEN
        if "Patch applied" in line or "Ready" in line:
            fill = GREEN
        d.text((78, y), line, font=FONT, fill=fill)
        y += 42

    pulse = 20 + int(10 * math.sin(sub / 4 * math.pi))
    d.rounded_rectangle(
        (58, H - 112, W - 58, H - 78),
        radius=10,
        fill=(15, 23, 42),
        outline=COLORS[idx],
        width=2,
    )
    d.rectangle((74, H - 100, 74 + idx * 130 + pulse, H - 90), fill=COLORS[idx])
    d.text((78, H - 62), "review first. apply when ready.", font=FONT, fill=DIM)
    return im


frames = []
for step_idx in range(len(STEPS)):
    for sub_idx in range(5):
        frames.append(draw_frame(step_idx, sub_idx))

target = OUT / "ghostfix-demo.gif"
frames[0].save(
    target,
    save_all=True,
    append_images=frames[1:],
    duration=220,
    loop=0,
    optimize=True,
)
print(target)
