"""
ISRO's own picture of the water, alongside our numbers.

MOSDAC publishes a daily coastal water-quality composite from Oceansat-3
(EOS-06, the OCM3 instrument) as a rendered image, at a predictable path:

    /look/E6_OCM/preview/2026/06SEP/E06OCML3CQ_20260906_01km_LAC_chl_v1.0.0.jpg

So the date is enough to build the URL. No ordering, no login, no key.

WHY THIS IS AN IMAGE AND NOT A NUMBER

It would be easy to sample the colour of a pixel, run it back through the
colour bar, and call the result a chlorophyll reading. That would be wrong.
JPEG compression shifts colours, the scale is logarithmic and unlabelled
between ticks, and land, cloud and no-data all render as their own colours
that a naive sampler would read as values. A number obtained that way looks
exactly like a real measurement and cannot be checked by the person relying on
it.

So this module returns a picture and says so. Our numbers keep coming from
NOAA's gridded product, which publishes actual values with actual units. What
ISRO adds here is the authoritative Indian view of the same water on the same
day, shown next to the answer with its source named.

The honest claim, and the one the deck makes, is exactly that: the numbers are
NOAA's, the picture beside them is ISRO's, and neither is dressed up as the
other.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

BASE = "https://mosdac.gov.in/look/E6_OCM/preview"

# MOSDAC writes the month as a three-letter uppercase abbreviation.
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
          "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")

# How many days back to offer before giving up. The composite is published a
# day or two behind, and further back than this it stops describing today.
MAX_AGE_DAYS = 4


@dataclass(frozen=True)
class Preview:
    url: str
    day: date
    age_days: int
    label: str          # what the source line should read
    caption_key: str    # phrase key, so the caption is translated


def url_for(day: date) -> str:
    """The published path for one day's coastal water-quality composite."""
    folder = f"{day.day:02d}{MONTHS[day.month - 1]}"
    stamp = f"{day.year}{day.month:02d}{day.day:02d}"
    return (f"{BASE}/{day.year}/{folder}/"
            f"E06OCML3CQ_{stamp}_01km_LAC_chl_v1.0.0.jpg")


def candidates(today: date | None = None) -> list[Preview]:
    """Recent days, newest first.

    The image is built into the page rather than fetched here: a HEAD request
    per candidate would spend part of the answer budget on a picture, and the
    browser can simply try the next one if a day is missing.
    """
    today = today or date.today()
    out = []
    for back in range(1, MAX_AGE_DAYS + 1):
        day = today - timedelta(days=back)
        out.append(Preview(
            url=url_for(day),
            day=day,
            age_days=back,
            label="MOSDAC / SAC · EOS-06",
            caption_key="isro_preview",
        ))
    return out
