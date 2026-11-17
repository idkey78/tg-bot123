from __future__ import annotations

import math


def total_pages(total: int, size: int) -> int:
    return max(1, math.ceil(total / size))


def clamp_page(page: int, pages: int) -> int:
    return min(max(page, 0), pages - 1)
