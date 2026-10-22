"""Compare two calibrations joint by joint."""

from dataclasses import dataclass, field

from so101.calibration import JointCalibration

# Fields compared, in display order. ``id`` is not a calibration result.
DIFF_FIELDS = ("homing_offset", "range_min", "range_max", "drive_mode")


@dataclass(frozen=True)
class FieldChange:
    joint: str
    field: str
    old: int
    new: int

    @property
    def delta(self) -> int:
        return self.new - self.old


@dataclass(frozen=True)
class CalibrationDiff:
    changes: list[FieldChange] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.changes or self.added or self.removed)


def diff_calibrations(
    old: dict[str, JointCalibration], new: dict[str, JointCalibration]
) -> CalibrationDiff:
    """Per-field changes for joints in both, plus joints only in one."""
    changes = [
        FieldChange(name, f, getattr(old[name], f), getattr(new[name], f))
        for name in old
        if name in new
        for f in DIFF_FIELDS
        if getattr(old[name], f) != getattr(new[name], f)
    ]
    return CalibrationDiff(
        changes=changes,
        added=[n for n in new if n not in old],
        removed=[n for n in old if n not in new],
    )


def format_diff(diff: CalibrationDiff) -> str:
    """Render a diff as a plain-text table; one row per changed field."""
    if not diff.has_changes:
        return "no differences"
    lines: list[str] = []
    if diff.changes:
        rows = [("joint", "field", "old", "new", "delta")] + [
            (c.joint, c.field, str(c.old), str(c.new), f"{c.delta:+d}")
            for c in diff.changes
        ]
        widths = [max(len(r[i]) for r in rows) for i in range(5)]
        for row in rows:
            cells = [
                cell.ljust(w) if i < 2 else cell.rjust(w)
                for i, (cell, w) in enumerate(zip(row, widths, strict=True))
            ]
            lines.append("  ".join(cells).rstrip())
    if diff.removed:
        lines.append(f"removed: {', '.join(diff.removed)}")
    if diff.added:
        lines.append(f"added: {', '.join(diff.added)}")
    return "\n".join(lines)
