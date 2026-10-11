'''
Whole-file replacement that a power cut cannot leave half-written — the Pi
loses power without a shutdown.
'''

import contextlib
import os
import secrets


def write_atomic(path: str, text: str, mode: int = 0o666) -> None:
    '''
    Replaces a file's content so a reader, or a power cut, only ever sees the
    whole old file or the whole new one.  The text goes to a temp file in the
    SAME directory (os.replace is only atomic within a filesystem), is flushed
    and fsynced (or the rename can land before the data), then replaces path.
    The temp file never outlives a failure, cancellation included.
    Arguments:
        path (str): The file to replace.
        text (str): Its new content, written as UTF-8.
        mode (int): Permission bits for the new file, before the umask — pass
            0o600 for a file holding anything private.
    '''
    directory = os.path.dirname(path) or "."
    temp = os.path.join(directory, f".{os.path.basename(path)}.{secrets.token_hex(4)}.tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp)
        raise
