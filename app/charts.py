"""A sensor's history drawn: a number's as a line (a tile's graph, and the larger one a long press opens), and on and
off as a timeline. A history is [(when, state)], oldest first, when in seconds since 1970; its first state is the one
the time shown began with, and the last lasts until now."""


def number(text):
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return value if value == value and abs(value) != float('inf') else None


def numbers(points):
    """The history's numbers, [(when, value)], leaving out what isn't one (unavailable, unknown)."""
    return [(when, value) for when, value in ((when, number(state)) for when, state in points) if value is not None]


def spans(points, start, end):
    """The history as [(from, to, state)] between start and end."""
    found = []
    for index, (when, state) in enumerate(points):
        until = points[index + 1][0] if index + 1 < len(points) else end
        when, until = max(when, start), min(until, end)
        if until > when:
            found.append((when, until, state))
    return found


def value_range(values, low=None, high=None):
    """(low, high) for a line: as given, or the values' least and most with a little room."""
    if low is None or high is None:
        least, most = min(values), max(values)
        room = (most - least) * 0.1 or max(abs(most) * 0.05, 0.5)
        low = least - room if low is None else low
        high = most + room if high is None else high
    return low, high if high > low else low + 1


def line(draw, box, points, start, end, colour, fill=None, low=None, high=None, width=2):
    """A number's history as a line in box, filled below it with fill if given. Returns the (low, high) it drew
    between, or None when there are no numbers."""
    values = numbers(points)
    if not values:
        return None
    left, top, right, bottom = box
    # Each column of pixels has the average of what's in it, so a busy sensor draws no more than the box is wide
    columns = {}
    for when, value in values:
        when = min(max(when, start), end)
        column = round(left + (when - start) * (right - left) / max(end - start, 1))
        columns.setdefault(column, []).append(value)
    shown = [(column, sum(found) / len(found)) for column, found in sorted(columns.items())]
    if shown[-1][0] < right:
        shown.append((right, shown[-1][1]))  # the last lasts until now
    if shown[0][0] > left and values[0][0] <= start:
        shown.insert(0, (left, shown[0][1]))
    low, high = value_range([value for _, value in shown], low, high)

    def y(value):
        value = min(max(value, low), high)
        return bottom - (value - low) * (bottom - top) / (high - low)
    xy = [(x, y(value)) for x, value in shown]
    if fill:
        draw.polygon(xy + [(xy[-1][0], bottom), (xy[0][0], bottom)], fill=fill)
    if len(xy) == 1:
        xy.append(xy[0])
    draw.line(xy, fill=colour, width=width, joint='curve')
    return low, high


def timeline(draw, box, points, start, end, on, off, is_on=lambda state: state == 'on', radius=6):
    """On and off's history as a strip in box: off's colour along it, on's where it was on."""
    left, top, right, bottom = box
    draw.rounded_rectangle((left, top, right - 1, bottom - 1), radius=radius, fill=off)
    for since, until, state in spans(points, start, end):
        if is_on(state):
            x0 = left + (since - start) * (right - left) / (end - start)
            x1 = left + (until - start) * (right - left) / (end - start)
            draw.rectangle((round(x0), top, max(round(x1), round(x0) + 1) - 1, bottom - 1), fill=on)
