"""Shared fantasy-point scoring formulas, applied to a common stat-line dict.

Expected stat keys (season totals, all positions may not have all keys):
  pass_att, pass_cmp, pass_yds, pass_td, pass_int,
  rush_att, rush_yds, rush_td,
  targets, rec, rec_yds, rec_td,
  fum
"""


def _g(stats, key):
    return stats.get(key) or 0


def passing_points(stats):
    return (
        _g(stats, "pass_yds") * 0.04
        + _g(stats, "pass_td") * 4
        - _g(stats, "pass_int") * 2
    )


def rushing_points(stats):
    return _g(stats, "rush_yds") * 0.1 + _g(stats, "rush_td") * 6


def receiving_points(stats, ppr):
    return (
        _g(stats, "rec_yds") * 0.1
        + _g(stats, "rec_td") * 6
        + _g(stats, "rec") * ppr
    )


def fumble_points(stats):
    return -_g(stats, "fum") * 2


def qb_points(stats):
    return passing_points(stats) + rushing_points(stats) + fumble_points(stats)


def std_points(stats):
    return rushing_points(stats) + receiving_points(stats, 0) + fumble_points(stats)


def half_ppr_points(stats):
    return rushing_points(stats) + receiving_points(stats, 0.5) + fumble_points(stats)


def ppr_points(stats):
    return rushing_points(stats) + receiving_points(stats, 1) + fumble_points(stats)


def te_premium_points(stats):
    return rushing_points(stats) + receiving_points(stats, 1.5) + fumble_points(stats)


def round2(x):
    return round(x, 2)
