'''
Reductions over a history read's (count, timestamps_ms, values) result, shared by
the trip and charging summaries.  Each returns NaN when the series is missing or
empty, so a partial-data trip or session still yields a well-formed record.
'''
import numpy as np


def series_values(result):
    '''
    Extracts the values array from a read result, or None if it is empty/missing.
    Arguments:
        result (tuple | None): The (count, timestamps, values) triple or None.
    '''
    if result is None:
        return None
    count, _timestamps, values = result
    if count == 0 or len(values) == 0:
        return None
    return values


def delta(result) -> float:
    '''
    Last minus first value of a series (a lifetime-counter delta), or NaN.
    Arguments:
        result (tuple | None): The (count, timestamps, values) triple or None.
    '''
    values = series_values(result)
    if values is None:
        return float("nan")
    return float(values[-1] - values[0])


def first(result) -> float:
    '''
    First value of a series, or NaN.
    Arguments:
        result (tuple | None): The (count, timestamps, values) triple or None.
    '''
    values = series_values(result)
    return float(values[0]) if values is not None else float("nan")


def last(result) -> float:
    '''
    Last value of a series, or NaN.
    Arguments:
        result (tuple | None): The (count, timestamps, values) triple or None.
    '''
    values = series_values(result)
    return float(values[-1]) if values is not None else float("nan")


def positive_increment(values) -> float:
    '''
    Sum of an accumulator's positive steps — the energy it delivered, robust to a
    value carried into the window or a reset inside it (a plain in-window max
    over-counts both).  NaN with fewer than two samples: nothing to difference.
    Arguments:
        values (ndarray | None): The accumulator's samples, ascending by time.
    '''
    if values is None or len(values) < 2:
        return float("nan")
    return float(np.clip(np.diff(values), 0.0, None).sum())
