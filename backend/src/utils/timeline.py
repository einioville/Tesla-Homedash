'''
Segmentation of a logged state timeline into activity windows — trips from
Gear, charging sessions from DetailedChargeState.  Pure logic, no I/O.
'''


def collapse_transitions(history: list) -> list:
    '''
    Collapses consecutive identical readings into transitions.  Logged fields are
    written on every telemetry event (not only on change), so the raw history
    repeats the held value; only the points where it changes are real transitions.
    Arguments:
        history (list): [(timestamp_ms, state), ...] ascending by time.
    Returns:
        list: The same shape, with runs of identical state reduced to their first point.
    '''
    collapsed = []
    previous = None
    for timestamp_ms, state in history:
        if state != previous:
            collapsed.append((timestamp_ms, state))
            previous = state
    return collapsed


def segment(transitions: list, held_before, start_ms: int, end_ms: int, threshold_ms: int,
            is_active, idle_state) -> list:
    '''
    Turns a collapsed timeline into activity windows.  Walks it as contiguous
    [from, to) intervals per held state.  An inactive interval shorter than
    threshold_ms is absorbed into the surrounding window (a traffic-light stop, a
    momentary charging pause); a longer one, or the window end, closes it.
    Arguments:
        transitions (list): Collapsed [(timestamp_ms, state), ...].
        held_before: The state held just before start_ms, or None if nothing was
            logged before the window.  An active held state captures an activity
            already under way at the window boundary.
        start_ms (int): Window start, epoch-ms UTC.
        end_ms (int): Window end, epoch-ms UTC.
        threshold_ms (int): Inactive duration at/above which a window closes.
        is_active (Callable): is_active(state) -> True while the activity runs.
        idle_state: The state assumed before the window when nothing was held, so
            no activity is fabricated that cannot be bounded.
    Returns:
        list: [(window_start_ms, window_end_ms, in_progress), ...].
    '''
    if not transitions:
        return []

    start_state = held_before if held_before is not None else idle_state
    sequence = [(start_ms, start_state)]
    for timestamp_ms, state in transitions:
        if timestamp_ms > start_ms:
            sequence.append((timestamp_ms, state))
    # Re-collapse in case the synthetic start state equals the first transition.
    sequence = collapse_transitions(sequence)

    windows = []
    window_start = None
    last_active_end = None

    for index, (segment_start, state) in enumerate(sequence):
        segment_end = sequence[index + 1][0] if index + 1 < len(sequence) else end_ms

        if is_active(state):
            if window_start is None:
                window_start = segment_start
            last_active_end = segment_end
        elif window_start is not None:
            if segment_end - segment_start >= threshold_ms:
                windows.append((window_start, last_active_end, False))
                window_start = None
                last_active_end = None
            # A shorter gap leaves the window open; the next active segment extends
            # last_active_end across it.

    if window_start is not None:
        # No long-enough closing gap inside the window: still active if the last
        # active segment reaches the window end, else closed at the last activity.
        windows.append((window_start, last_active_end, last_active_end == end_ms))

    return windows
