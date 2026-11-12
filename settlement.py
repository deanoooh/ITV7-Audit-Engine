"""
Settlement verifier — deterministic arithmetic for horse racing settlement tables.

Parses the §28.1 Settlement Table format and computes stake, return, P/L per row
and meeting totals. No AI involved. Pure Python.

Authoritative rules (from Master Analysis Engine v5.28.1-C8.3):
  - Every bet is £1.00 total exposure (£1 WIN or 50p E/W)
  - NO BET and NR = £0.00
  - WIN return = £1 × decimal SP (if 1st)
  - E/W return = (£0.50 × decimal SP if 1st) + (£0.50 × place decimal if placed)
  - place decimal = 1 + (fractional SP × EW fraction)
  - P/L = return − stake
  - ROI = P/L ÷ stake × 100
"""

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Optional, List, Tuple
import re


# ---------- Constants ----------

POSITION_MAP = {
    "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5,
    "6th": 6, "7th": 7, "8th": 8, "9th": 9, "10th": 10,
    "11th": 11, "12th": 12, "13th": 13, "14th": 14, "15th": 15,
}
NON_FINISHERS = {"UR", "PU", "FELL", "BD", "RO", "CO", "F", "NR", "REF", "VOID"}


# ---------- Primitive parsers ----------

def parse_fractional_odds(s: str) -> Optional[Fraction]:
    """'13/8' -> Fraction(13,8); '5/1' -> 5; 'EVS' -> 1; '11/10f' -> 11/10."""
    s = s.strip().upper()
    # strip common suffixes
    for suffix in ("F", "J", "C", "D"):
        if s.endswith(suffix) and "/" in s[:-1]:
            s = s[:-1]
            break
    if s in ("EVS", "EVENS", "EVEN"):
        return Fraction(1, 1)
    m = re.match(r"^(\d+)/(\d+)$", s)
    if not m:
        return None
    return Fraction(int(m.group(1)), int(m.group(2)))


def fractional_to_decimal(frac: Fraction) -> float:
    return float(frac) + 1.0


def parse_place_terms(s: str) -> Tuple[Optional[Fraction], int]:
    """'1/4 odds 2 places' -> (Fraction(1,4), 2). 'Win Only' -> (None, 1)."""
    low = s.strip().lower()
    if "win only" in low or "win-only" in low:
        return (None, 1)
    m = re.search(r"(\d+)/(\d+)\s*odds\s*(\d+)\s*places?", low)
    if not m:
        return (None, 0)
    return (Fraction(int(m.group(1)), int(m.group(2))), int(m.group(3)))


def parse_result(s: str) -> Tuple[Optional[int], bool]:
    """'2nd of 7' -> (2, True). 'UR' -> (None, False). 'NR' -> (None, False)."""
    s = s.strip()
    # take first token, strip punctuation
    first = re.split(r"[\s,(]", s)[0].strip().lower()
    if first in POSITION_MAP:
        return (POSITION_MAP[first], True)
    if first.upper() in NON_FINISHERS or s.upper() in NON_FINISHERS:
        return (None, False)
    return (None, False)


def classify_declared(declared: str) -> str:
    """Return 'WIN', 'EW', 'NOBET', 'NR', or 'UNKNOWN'."""
    d = declared.upper()
    if "NO BET" in d or "🔴" in d or re.search(r"\bNB\d\b", d):
        return "NOBET"
    if "E/W" in d or "EW" in d or "EACH" in d:
        return "EW"
    if "WIN" in d:
        return "WIN"
    return "UNKNOWN"


# ---------- Data model ----------

@dataclass
class Row:
    race_id: str
    race_header: str
    tier: str
    horse: str
    selection_price: str
    declared: str
    result: str
    sp: str
    ew_fraction: Optional[Fraction] = None
    places_paid: int = 0
    stake: float = 0.0
    return_amount: float = 0.0
    pnl: float = 0.0
    errors: List[str] = field(default_factory=list)


# ---------- Core computation ----------

def compute_row(row: Row) -> Row:
    row.errors = []
    kind = classify_declared(row.declared)

    # NR detection
    if row.result.strip().upper().startswith("NR") or kind == "NR":
        row.stake = 0.0
        row.return_amount = 0.0
        row.pnl = 0.0
        return row

    if kind == "NOBET":
        row.stake = 0.0
        row.return_amount = 0.0
        row.pnl = 0.0
        return row

    if kind == "UNKNOWN":
        row.errors.append(f"Unknown declared method: {row.declared!r}")
        return row

    # Both WIN and EW have £1.00 total exposure
    row.stake = 1.00

    sp_frac = parse_fractional_odds(row.sp)
    if sp_frac is None:
        row.errors.append(f"Cannot parse SP: {row.sp!r}")
        return row

    sp_dec = fractional_to_decimal(sp_frac)
    position, _ = parse_result(row.result)

    if kind == "WIN":
        row.return_amount = round(1.00 * sp_dec, 2) if position == 1 else 0.0

    elif kind == "EW":
        if row.ew_fraction is None:
            row.errors.append("EW declared but place terms unparseable")
            return row
        win_component = 0.0
        place_component = 0.0
        if position == 1:
            win_component = round 0.50 * sp_dec
        if position is not None and position <= row.places_paid:
            place_dec = 1 + float(sp_frac * row.ew_fraction)
            place_component = round 0.50 * place_dec
        row.return_amount = round(win_component + place_component, 2)

    row.pnl = round(row.return_amount - row.stake, 2)
    return row


# ---------- Table parser ----------

# Normalise dashes so one regex handles all variants
def _normalise(text: str) -> str:
    text = text.replace("–", "—")  # en-dash to em-dash
    text = re.sub(r"\s+-\s+", " — ", text)  # space-hyphen-space
    return text


RACE_HEADER_RE = re.compile(r"^===\s*RACE\s+\d+\s*—\s*(.+?)\s*===\s*$", re.IGNORECASE)
TERMS_RE = re.compile(
    r"ACTIVE\s+RUNNERS?:\s*(\d+)\s+PLACE\s+TERMS:\s*(.+)$", re.IGNORECASE
)
ROW_RE = re.compile(
    r"^(PRIMARY|SECONDARY|CHAOS)\s*:\s*(.+?)\s*—\s*selection\s+(.+?)\s*—\s*"
    r"declared\s+(.+?)\s*—\s*result\s+(.+?)\s*—\s*SP\s+(.+?)$",
    re.IGNORECASE,
)


def parse_settlement_table(text: str) -> Tuple[List[Row], List[str]]:
    """Parse a §28.1 Settlement Table. Returns (rows, warnings)."""
    rows: List[Row] = []
    warnings: List[str] = []

    text = _normalise(text)
    current_header = ""
    current_id = ""
    current_frac: Optional[Fraction] = None
    current_places = 0

    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("---") or line.upper().startswith("ENGINE:"):
            continue
        if line.upper().startswith("SNAPSHOT BLOCK") or line.upper().startswith("RACES:"):
            continue

        m = RACE_HEADER_RE.match(line)
        if m:
            current_header = m.group(1)
            current_id = current_header.split("—")[0].strip() or current_header[:20]
            current_frac = None
            current_places = 0
            continue

        m = TERMS_RE.search(line)
        if m:
            terms_str = m.group(2).strip()
            frac, places = parse_place_terms(terms_str)
            if frac is None and "win only" not in terms_str.lower():
                warnings.append(f"Unparseable place terms: {terms_str!r}")
            else:
                current_frac = frac
                current_places = places
            continue

        m = ROW_RE.match(line)
        if m:
            tier, horse, price, declared, result, sp = (
                m.group(1).strip(),
                m.group(2).strip(),
                m.group(3).strip(),
                m.group(4).strip(),
                m.group(5).strip(),
                m.group(6).strip(),
            )
            row = Row(
                race_id=current_id,
                race_header=current_header,
                tier=tier,
                horse=horse,
                selection_price=price,
                declared=declared,
                result=result,
                sp=sp,
                ew_fraction=current_frac,
                places_paid=current_places,
            )
            rows.append(compute_row(row))
            continue

        warnings.append(f"Unparsed: {line[:100]}")

    return rows, warnings


# ---------- Verification output ----------

def build_verified_totals(rows: List[Row], meeting: str, date: str) -> str:
    total_staked = round(sum(r.stake for r in rows), 2)
    total_return = round(sum(r.return_amount for r in rows), 2)
    net_pnl = round(total_return - total_staked, 2)
    roi = round((net_pnl / total_staked * 100) if total_staked else 0.0, 2)

    tiers = {"PRIMARY": [], "SECONDARY": [], "CHAOS": []}
    for r in rows:
        tiers.setdefault(r.tier.upper(), []).append(r)

    tier_lines = ["TIER AUDIT"]
    for name in ("PRIMARY", "SECONDARY", "CHAOS"):
        trows = tiers.get(name, [])
        if not trows:
            continue
        t_stake = round(sum(r.stake for r in trows), 2)
        t_ret = round(sum(r.return_amount for r in trows), 2)
        t_pnl = round(t_ret - t_stake, 2)
        t_roi = round((t_pnl / t_stake * 100) if t_stake else 0.0, 2)
        t_bets = sum(1 for r in trows if r.stake > 0)
        t_wins = sum(1 for r in trows if r.stake > 0 and parse_result(r.result)[0] == 1)
        t_places = sum(
            1
            for r in trows
            if r.stake > 0
            and (parse_result(r.result)[0] or 999) > 1
            and r.return_amount > 0
        )
        tier_lines.append(
            f"{name:9} {t_bets} bets | {t_wins}W {t_places}P | "
            f"£{t_stake:.2f} staked | £{t_ret:.2f} returned | "
            f"£{t_pnl:+.2f} P/L | {t_roi:+.2f}% ROI"
        )

    winners = [r.horse for r in rows if r.stake > 0 and parse_result(r.result)[0] == 1]
    placed = [
        r.horse
        for r in rows
        if r.stake > 0
        and (parse_result(r.result)[0] or 999) > 1
        and r.return_amount > 0
    ]
    unplaced = sum(
        1 for r in rows if r.stake > 0 and parse_result(r.result)[0] is None and r.return_amount == 0
    )
    nobets = sum(1 for r in rows if classify_declared(r.declared) == "NOBET")
    nrs = sum(1 for r in rows if r.result.strip().upper().startswith("NR"))

    return "\n".join(
        [
            f"--- BEGIN VERIFIED TOTALS — {meeting} {date} ---",
            f"Active bets: {sum(1 for r in rows if r.stake > 0)}",
            f"Total staked: £{total_staked:.2f}",
            f"Total returned: £{total_return:.2f}",
            f"Net P/L: £{net_pnl:+.2f}",
            f"ROI: {roi:+.2f}%",
            "",
            *tier_lines,
            "",
            f"WINNERS COUNTED: {len(winners)} — {', '.join(winners) if winners else 'none'}",
            f"PLACES PAID: {len(placed)} — {', '.join(placed) if placed else 'none'}",
            f"UNPLACED: {unplaced}",
            f"NO BETS: {nobets}",
            f"NON-RUNNERS: {nrs}",
            f"--- END VERIFIED TOTALS — {meeting} {date} ---",
        ]
    )


# ---------- Validation ----------

def validate(rows: List[Row]) -> List[str]:
    errors: List[str] = []
    if not rows:
        return ["No rows parsed — paste the settlement table and check the format"]

    for r in rows:
        if r.stake not in (0.0, 1.0):
            errors.append(f"{r.horse}: stake £{r.stake} not £0 or £1")
        for e in r.errors:
            errors.append(f"{r.race_id} {r.tier} {r.horse}: {e}")

    race_counts: dict = {}
    for r in rows:
        race_counts[r.race_id] = race_counts.get(r.race_id, 0) + 1
    for race, count in race_counts.items():
        if count != 3:
            errors.append(f"{race}: {count} rows (expected 3)")

    return errors
