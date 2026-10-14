"""Small, dependency-free geometry helpers for image-space regions."""


def _four_finite_numbers(values, name):
    if len(values) != 4:
        raise ValueError("{} must contain four numbers".format(name))
    try:
        result = tuple(float(value) for value in values)
    except (TypeError, ValueError):
        raise ValueError("{} must contain four numbers".format(name))
    if any(value != value or value in (float("inf"), float("-inf")) for value in result):
        raise ValueError("{} must contain finite numbers".format(name))
    return result


def clip_box(box, width, height):
    """Clip an XYXY box to an image and reject empty or malformed boxes."""
    x1, y1, x2, y2 = _four_finite_numbers(box, "box")
    if width <= 0 or height <= 0:
        raise ValueError("image dimensions must be positive")
    clipped = (max(0.0, min(float(width), x1)),
               max(0.0, min(float(height), y1)),
               max(0.0, min(float(width), x2)),
               max(0.0, min(float(height), y2)))
    if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
        return None
    return clipped


def normalized_roi_to_pixels(roi, width, height, normalized=True):
    """Convert an XYXY ROI to pixel coordinates, clipping to the frame."""
    x1, y1, x2, y2 = _four_finite_numbers(roi, "ROI")
    if normalized:
        x1, x2 = x1 * width, x2 * width
        y1, y2 = y1 * height, y2 * height
    result = clip_box((x1, y1, x2, y2), width, height)
    if result is None:
        raise ValueError("ROI does not overlap the image")
    return result


def intersection_over_box_area(box, roi):
    """Return the fraction of the hand box covered by an ROI (0..1)."""
    x1, y1, x2, y2 = _four_finite_numbers(box, "box")
    rx1, ry1, rx2, ry2 = _four_finite_numbers(roi, "ROI")
    area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if area == 0:
        return 0.0
    intersection = max(0.0, min(x2, rx2) - max(x1, rx1)) * max(
        0.0, min(y2, ry2) - max(y1, ry1)
    )
    return intersection / area


def box_roi_overlap(box, roi):
    """Alias kept for callers that use the shorter overlap terminology."""
    return intersection_over_box_area(box, roi)


def validate_polygon(points, normalized=False):
    """Return finite convex polygon vertices; reject ambiguous/self-crossing ROIs.

    Convex ROIs are sufficient for a perspective-projected painting and make
    clipping against hand rectangles exact and predictable.
    """
    if not isinstance(points, (list, tuple)) or len(points) < 3:
        raise ValueError("polygon must contain at least three points")
    result = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError("each polygon point must be [x, y]")
        try:
            x, y = float(point[0]), float(point[1])
        except (TypeError, ValueError):
            raise ValueError("polygon coordinates must be numbers")
        if any(value != value or value in (float("inf"), float("-inf"))
               for value in (x, y)):
            raise ValueError("polygon coordinates must be finite")
        if normalized and not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            raise ValueError("normalized polygon coordinates must be between 0 and 1")
        result.append((x, y))

    if len(set(result)) != len(result):
        raise ValueError("polygon points must be distinct")
    if _polygon_area(result) <= 1e-12:
        raise ValueError("polygon area must be positive")
    signs = []
    for index in range(len(result)):
        a, b, c = result[index - 1], result[index], result[(index + 1) % len(result)]
        cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        if abs(cross) <= 1e-12:
            raise ValueError("polygon must not contain collinear adjacent edges")
        signs.append(cross > 0)
    if any(sign != signs[0] for sign in signs):
        raise ValueError("polygon must be simple and convex, with points in perimeter order")
    return result


def _polygon_area(points):
    return abs(sum(points[index][0] * points[(index + 1) % len(points)][1]
                   - points[(index + 1) % len(points)][0] * points[index][1]
                   for index in range(len(points)))) / 2.0


def normalized_polygon_to_pixels(points, width, height):
    """Scale a normalized ROI polygon to pixel coordinates."""
    if width <= 0 or height <= 0:
        raise ValueError("image dimensions must be positive")
    normalized = validate_polygon(points, normalized=True)
    return [(x * width, y * height) for x, y in normalized]


def polygon_bounds(points):
    """Return the XYXY envelope of a polygon."""
    points = validate_polygon(points)
    return (min(point[0] for point in points), min(point[1] for point in points),
            max(point[0] for point in points), max(point[1] for point in points))


def point_in_polygon(point, polygon):
    """Test a point against a polygon, including its boundary."""
    x, y = float(point[0]), float(point[1])
    vertices = validate_polygon(polygon)
    inside = False
    for index, first in enumerate(vertices):
        second = vertices[(index + 1) % len(vertices)]
        dx, dy = second[0] - first[0], second[1] - first[1]
        cross = (x - first[0]) * dy - (y - first[1]) * dx
        if (abs(cross) <= 1e-9
                and min(first[0], second[0]) - 1e-9 <= x <= max(first[0], second[0]) + 1e-9
                and min(first[1], second[1]) - 1e-9 <= y <= max(first[1], second[1]) + 1e-9):
            return True
        if (first[1] > y) != (second[1] > y):
            crossing_x = first[0] + (y - first[1]) * dx / dy
            if x < crossing_x:
                inside = not inside
    return inside


def _clip_polygon_to_box(polygon, box):
    """Sutherland-Hodgman clip of a convex polygon against an XYXY box."""
    x1, y1, x2, y2 = box
    output = list(polygon)
    boundaries = (
        (lambda p: p[0] >= x1, lambda a, b: (x1, a[1] + (b[1] - a[1]) * (x1 - a[0]) / (b[0] - a[0]))),
        (lambda p: p[0] <= x2, lambda a, b: (x2, a[1] + (b[1] - a[1]) * (x2 - a[0]) / (b[0] - a[0]))),
        (lambda p: p[1] >= y1, lambda a, b: (a[0] + (b[0] - a[0]) * (y1 - a[1]) / (b[1] - a[1]), y1)),
        (lambda p: p[1] <= y2, lambda a, b: (a[0] + (b[0] - a[0]) * (y2 - a[1]) / (b[1] - a[1]), y2)),
    )
    for inside, intersect in boundaries:
        source, output = output, []
        if not source:
            break
        previous = source[-1]
        previous_inside = inside(previous)
        for current in source:
            current_inside = inside(current)
            if current_inside != previous_inside:
                output.append(intersect(previous, current))
            if current_inside:
                output.append(current)
            previous, previous_inside = current, current_inside
    return output


def intersection_over_box_area_polygon(box, polygon):
    """Return fraction of an XYXY box covered by a convex polygon ROI."""
    x1, y1, x2, y2 = _four_finite_numbers(box, "box")
    area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if area == 0:
        return 0.0
    clipped = _clip_polygon_to_box(validate_polygon(polygon), (x1, y1, x2, y2))
    return min(1.0, _polygon_area(clipped) / area) if len(clipped) >= 3 else 0.0

