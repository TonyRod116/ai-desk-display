"""Small, legible extra-credit readout in each board face's Codex instrument."""
from PIL import ImageDraw

from token_tv.credits import exhausted_credits, format_balance
from token_tv.display import overview_rows
from token_tv.themes import face

# Each badge replaces the numeric weekly percentage. The weekly bars, reset
# and saved-reset icons remain unchanged, including the VS knockout state.
BOXES = {
    'game-boy': (30, 62, 125, 91),
    'paradise': (197, 54, 310, 91),
    'code-forge': (69, 163, 151, 190),
    'surf': (7, 23, 135, 52),
    'dials': (24, 168, 93, 202),
    'arcade': (8, 56, 128, 84),
    'cockpit': (48, 85, 117, 125),
    'countdown': (14, 196, 94, 219),
}


def apply_credit_badges(images, names, snapshot):
    rows = [row for row in overview_rows(snapshot) if row.get('provider') == 'codex']
    balance = exhausted_credits(rows[0]) if rows else None
    if balance is None:
        return
    balance = format_balance(balance)
    for name, image in zip(names, images):
        x0, y0, x1, y1 = BOXES[name]
        background, ink = {
            'game-boy': ('#a4bd52', '#263c25'),
            'paradise': ('#e3e9d1', '#4e3404'),
        }.get(name, ('#101827', '#ffe2a0'))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((x0, y0, x1, y1), radius=2, fill=background)
        height, width = y1 - y0, x1 - x0
        label_size = 5 if height < 20 else 7
        label_font = face('oxanium.woff2', label_size)
        draw.text((x0 + 3, y0 + 1), 'CREDITS', font=label_font, fill=ink)
        for size in range(min(20, height - label_size - 2), 4, -1):
            number_font = face('oxanium.woff2', size)
            if draw.textlength(balance, font=number_font) <= width - 6:
                break
        draw.text((x0 + 3, y0 + label_size + 1), balance, font=number_font, fill=ink)
