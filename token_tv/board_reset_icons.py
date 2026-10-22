"""One small icon per board page for the saved resets (the user, 2026-10-20).

the user asked for something that fits each screen instead of the same hearts everywhere: little houses on the city,
palm trees on the surf page, and so on. Each of the three icons is ONE saved reset, bright when available and faint
when not; `+` marks more than three. While the number is unknown, or only an old confirmed one is known, the three icons
stay (all faint when unknown, the last known count when old) and ONE faint dot is added at the end of the row: no `?`
and no OLD, which dirtied the screen (`marked`). Nothing here derives a count from anything: it only draws
`banked_hearts()`.

Pixel icons are tiny grids: `#` is the body, `o` a detail in a second tone, `.` is empty. The cockpit's rocket is
drawn as a smooth vector in `board_art`, where the page is smooth too.
"""

ICONS = {
    # the city: a little house with a lighter roof and a door
    'house': ('...o...', '..ooo..', '.ooooo.', '#######', '.##.##.', '.##.##.'),
    # Neon City: a lightning bolt
    'bolt': ('..###.', '.###..', '.####.', '..##..', '.##...'),
    # TIDAL RUSH: a palm tree with its trunk in a darker tone
    'palm': ('...###...', '.##.#.##.', '#..###..#', '...#o#...', '....o....', '....o....', '....o....', '....o....', '...ooo...'),
    # TOKEN RUN: a chequered flag
    'flag': ('##o#o#o', '#o#o#o#', '##o#o#o', '#......', '#......', '#......'),
}


# how the `o` cells differ from the body when the icon is bright: towards white (+) or black (-), by that fraction
DETAIL = {'house': .38, 'bolt': 0, 'palm': -.5, 'flag': -.72}


def size(icon):
    rows = ICONS[icon]
    return len(rows[0]), len(rows)


def cells(icon):
    """(x, y, tone, edge) for every cell of the icon; `tone` is '#' or 'o', `edge` marks its silhouette's border."""
    rows = ICONS[icon]
    width, height = size(icon)

    def solid(x, y):
        return 0 <= x < width and 0 <= y < height and rows[y][x] != '.'

    for y, row in enumerate(rows):
        for x, tone in enumerate(row):
            if tone == '.':
                continue
            edge = not all(solid(nx, ny) for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)))
            yield x, y, tone, edge


def hollow(icon):
    """The (x, y) cells drawn, dim, for a reset that is NOT available: the silhouette's edge, except the flag, whose bare outline
    read as a letter P, so it keeps its pole and its dark squares (a faint chequered flag)."""
    if icon == 'flag':
        return [(x, y) for x, y, tone, _ in cells(icon) if tone == 'o' or x == 0]
    return [(x, y) for x, y, _, edge in cells(icon) if edge]


def marked(count, old):
    """True while the number of saved resets is unknown, or only an old confirmed one is known: the row then ends in ONE faint
    dot (the user, 2026-10-20: "el puntito disimulado al final, no un ? ni OLD"). Zero is not marked: three faint icons and no dot."""
    return count is None or bool(old)


def mark(count, old):
    """The only text beside the icons: `+` when the count is more than three. Nothing is written for unknown or old."""
    return '+' if count is not None and count > 3 else ''
