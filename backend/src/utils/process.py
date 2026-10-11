'''
Runs an external command to completion under a timeout.  Every command a service
runs to completion goes through run(), so a hung command is always killed and
reaped the same way.  (The updater's streaming build runner is the exception: it
reads output while the step runs.)
'''

import asyncio
import contextlib
import os
import signal


async def run(argv, timeout: float, *, cwd=None, env=None,
              new_session: bool = False) -> tuple[int, str, str]:
    '''
    Runs one command without a shell, stdin from /dev/null, and returns
    (returncode, stdout, stderr) decoded as UTF-8 with bad bytes replaced.
    Raises OSError when the command cannot start, and asyncio.TimeoutError once
    `timeout` has passed — by then the child is killed and reaped.  Catch the
    timeout FIRST: since Python 3.11 asyncio.TimeoutError is the builtin
    TimeoutError, a subclass of OSError.
    Arguments:
        argv (Sequence[str]): Program and arguments.
        timeout (float): Seconds before the child is killed.
        cwd (str | None): Working directory; inherited when None.
        env (dict | None): Complete child environment; inherited when None.
        new_session (bool): Start the child in its own session and kill the
            whole process group on timeout — for a command (git) that forks
            helpers which inherit the pipes and outlive a plain kill.
    '''
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=new_session,
    )
    try:
        out, err = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            if new_session:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            else:
                process.kill()
        await process.wait()
        raise
    return process.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
