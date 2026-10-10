'''
Screensaver photo import from a USB stick (the Options view's "Kuvakansio" row).

The screensaver plays whatever is in one FIXED folder,
$XDG_CONFIG_HOME/Tesla-Homedash/screensaver, beside backend_config.json.  Photos
can be copied there over scp; this service is the way to do it from the panel:

  1. list the USB drives (lsblk), leaving out anything the system runs from,
  2. mount the chosen one if nothing has (udisksctl, as the backend's own user),
  3. find the tesla_homedash_screensaver folder in its root and count the images,
  4. copy them into the screensaver folder, then unmount what step 2 mounted.

The frontend decides nothing and touches no device: every step is a system call,
and those belong to the backend.  The flow runs for one client at a time, and
every state packet echoes that client's flow epoch so a reply from a dialog that
was closed is dropped on arrival.

Deployment note: udisksctl mounts through polkit.  A process outside the desktop
session (a `systemd --user` unit may be) can be refused; the README has the rule
that grants it.  A stick the desktop already mounted needs no mount at all.
'''

import asyncio
import json
import logging
import os
import shutil
import struct
import threading

from ..utils import protocol

logger = logging.getLogger("usb_import_service")

# The folder looked for in the ROOT of the stick, matched case-insensitively:
# FAT and exFAT keep whatever case the user typed on another computer.
FOLDER_NAME = "tesla_homedash_screensaver"

# The extensions the screensaver plays — the same list as the frontend's
# ScreensaverPhotos, so nothing is copied that would then never be shown.
IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif"})

# Only a volume mounted under one of these counts as removable media. Anything
# mounted elsewhere ("/", "/boot/firmware", swap, a USB SSD holding /home) is
# part of the running system, and so is every other volume on the same disk.
_REMOVABLE_MOUNT_ROOTS = ("/media/", "/run/media/", "/mnt/")

# Filesystems that hold no files to copy.
_SKIPPED_FSTYPES = frozenset({"swap", "crypto_LUKS", "LVM2_member", "linux_raid_member"})

_LSBLK_COLUMNS = "NAME,PATH,TYPE,TRAN,HOTPLUG,LABEL,SIZE,FSTYPE,MOUNTPOINT,MODEL,VENDOR"

# lsblk answers in milliseconds; udisksctl can take a few seconds on a slow stick
# (a vfat fsck-on-mount), and anything beyond this means it is not answering.
_COMMAND_TIMEOUT_SECONDS = 30.0

# How often copy progress is sent while files are copied.
_PROGRESS_INTERVAL_SECONDS = 0.25

# Left free on the target filesystem after a copy. The screensaver folder shares
# it with InfluxDB and the logs, and a full root filesystem takes those down.
_FREE_SPACE_MARGIN_BYTES = 200 * 1024 * 1024


def screensaver_dir() -> str:
    '''
    The screensaver's photo folder: $XDG_CONFIG_HOME (or ~/.config) /
    Tesla-Homedash / screensaver — the same path the frontend's
    ScreensaverPhotos resolves, beside backend_config.json.
    '''
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config")
    return os.path.join(base, "Tesla-Homedash", "screensaver")


def usb_volumes(document: dict) -> list:
    '''
    Picks the importable volumes out of an `lsblk -J` document: filesystems on
    USB (or hot-pluggable) disks, none of whose volumes is mounted outside the
    removable-media roots.  A stick formatted without a partition table carries
    its filesystem on the disk itself, which is listed then.
    Arguments:
        document (dict): Parsed `lsblk -J -b -o <_LSBLK_COLUMNS>` output.
    '''
    volumes = []
    for disk in document.get("blockdevices") or []:
        if disk.get("type") != "disk":
            continue
        if disk.get("tran") != "usb" and not _truthy(disk.get("hotplug")):
            continue
        nodes = [disk, *_descendants(disk)]
        if any(_is_system_mount(node.get("mountpoint")) for node in nodes):
            continue
        model = " ".join(part for part in (
            (disk.get("vendor") or "").strip(), (disk.get("model") or "").strip()) if part)
        filesystems = [node for node in nodes[1:] if node.get("fstype")]
        if not filesystems and disk.get("fstype"):
            filesystems = [disk]
        for node in filesystems:
            if node.get("fstype") in _SKIPPED_FSTYPES or not node.get("path"):
                continue
            volumes.append({
                "device": node["path"],
                "label": (node.get("label") or "").strip(),
                "size": _as_int(node.get("size")),
                "fstype": node.get("fstype") or "",
                "model": model,
                "mountpoint": node.get("mountpoint") or "",
            })
    return volumes


def _descendants(node: dict):
    '''
    Yields every child of an lsblk node, depth first.
    Arguments:
        node (dict): An lsblk block-device entry.
    '''
    for child in node.get("children") or []:
        yield child
        yield from _descendants(child)


def _is_system_mount(mountpoint) -> bool:
    '''
    True for a volume the running system uses: mounted anywhere but under a
    removable-media root.
    Arguments:
        mountpoint (str | None): lsblk's MOUNTPOINT column.
    '''
    if not mountpoint:
        return False
    return not mountpoint.startswith(_REMOVABLE_MOUNT_ROOTS)


def _truthy(value) -> bool:
    '''
    Reads an lsblk boolean column, which older util-linux prints as "1"/"0".
    Arguments:
        value: The column's JSON value.
    '''
    return value is True or value in (1, "1")


def _as_int(value) -> int:
    '''
    Reads an lsblk -b size, which older util-linux prints as a string.
    Arguments:
        value: The column's JSON value.
    '''
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def scan_folder(mountpoint: str):
    '''
    Finds the import folder in the root of a mounted volume and lists the images
    directly inside it (not in subfolders: the screensaver does not play those).
    Hidden files are skipped — a Mac leaves a "._IMG_0001.jpg" beside every photo
    it copies to a FAT stick.  Returns (folder path or None, sorted names, bytes).
    Arguments:
        mountpoint (str): Where the volume is mounted.
    '''
    folder = None
    with os.scandir(mountpoint) as entries:
        for entry in entries:
            if entry.name.casefold() == FOLDER_NAME and entry.is_dir(follow_symlinks=False):
                folder = entry.path
                break
    if folder is None:
        return None, [], 0
    names = []
    total = 0
    with os.scandir(folder) as entries:
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if os.path.splitext(entry.name)[1].lower() not in IMAGE_EXTENSIONS:
                continue
            if not entry.is_file(follow_symlinks=False):
                continue
            names.append(entry.name)
            total += entry.stat(follow_symlinks=False).st_size
    names.sort(key=str.casefold)
    return folder, names, total


def destination_name(target: str, name: str, size: int):
    '''
    The name to copy `name` to in `target`, or None when it is already there.
    A file of the same name AND size counts as already imported (importing the
    same stick twice copies nothing); a different file that happens to share the
    name — two cameras both numbering from IMG_0001 — gets " (2)", " (3)", ...
    rather than replacing a photo that is already on the dashboard.
    Arguments:
        target (str): The screensaver folder.
        name (str): The file's name on the stick.
        size (int): The file's size in bytes.
    '''
    stem, extension = os.path.splitext(name)
    candidate = name
    suffix = 1
    while True:
        path = os.path.join(target, candidate)
        if not os.path.exists(path):
            return candidate
        if os.path.getsize(path) == size:
            return None
        suffix += 1
        candidate = f"{stem} ({suffix}){extension}"


class _Refused(Exception):
    '''A step that cannot go on; the message is Finnish and shown verbatim.'''


class UsbImportService:
    '''
    Serves the USB_IMPORT_* codes: lists USB drives, mounts one, counts its
    photos and copies them into the screensaver folder.
    Arguments:
        server (Server): TCP server used to reply to the client running the flow.
        target_dir (str): The screensaver folder; defaults to screensaver_dir().
    '''

    def __init__(self, server, target_dir: str | None = None):
        self.__server = server
        self.__target = target_dir or screensaver_dir()
        # Serialises the flow's steps; the copy itself runs outside it, in its
        # own task, so a CLOSE can reach it.
        self.__lock = asyncio.Lock()
        self.__writer = None
        self.__flow_id = 0
        self.__state = self.__fresh_state()
        # The volume the flow is on, and whether THIS service mounted it (and so
        # must unmount it). A stick the desktop mounted is left as it was.
        self.__device = None
        self.__mountpoint = None
        self.__mounted_here = False
        self.__folder = None
        self.__names = []
        self.__copy_task = None
        self.__cancel = threading.Event()

    # ── Protocol handlers ─────────────────────────────────────────

    async def handle_list(self, payload: bytes, writer) -> None:
        '''
        Starts (or restarts) a flow for this client and replies with the drives.
        Releases the volume a previous scan mounted, since the user is choosing
        again.
        Arguments:
            payload (bytes): len(4B) + UTF-8 JSON {"flowId"}.
            writer (StreamWriter): The client running the flow.
        '''
        request = self.__decode(payload, "USB_IMPORT_LIST")
        if request is None:
            return
        flow_id = self.__flow_id_of(request)
        if self.__copying():
            await self.__server.send_to(writer, self.__frame(dict(
                self.__fresh_state(), flowId=flow_id, phase="error",
                message="Kuvien kopiointi on jo käynnissä")))
            return
        async with self.__lock:
            self.__writer = writer
            self.__flow_id = flow_id
            await self.__release()
            await self.__send(phase="listing")
            try:
                drives = await self.__list_volumes()
            except _Refused as e:
                await self.__send(phase="error", message=str(e))
                return
            await self.__send(phase="drives", drives=drives)

    async def handle_scan(self, payload: bytes, writer) -> None:
        '''
        Mounts the chosen drive if nothing has, then finds the import folder and
        counts its images.
        Arguments:
            payload (bytes): len(4B) + UTF-8 JSON {"flowId", "device"}.
            writer (StreamWriter): The client running the flow.
        '''
        request = self.__decode(payload, "USB_IMPORT_SCAN")
        if request is None or not self.__owns(request, writer) or self.__copying():
            return
        async with self.__lock:
            await self.__release()
            device = request.get("device")
            await self.__send(phase="scanning")
            try:
                volume = await self.__volume(device)
                mountpoint = volume["mountpoint"]
                if not mountpoint:
                    mountpoint = await self.__mount(volume["device"])
                    self.__mounted_here = True
                self.__device = volume["device"]
                self.__mountpoint = mountpoint
                folder, names, size = await asyncio.to_thread(scan_folder, mountpoint)
            except _Refused as e:
                await self.__send(phase="error", message=str(e))
                return
            except OSError as e:
                logger.warning("Could not read %s: %s", self.__mountpoint, e)
                await self.__send(phase="error", message="USB-muistin lukeminen epäonnistui")
                return
            self.__folder = folder
            self.__names = names
            logger.info("USB import: %s on %s has %s", volume["device"], mountpoint,
                        f"{len(names)} images in {folder}" if folder else f"no {FOLDER_NAME}")
            await self.__send(phase="ready", device=volume, found=folder is not None,
                              count=len(names), bytes=size, total=len(names))

    async def handle_start(self, payload: bytes, writer) -> None:
        '''
        Copies the scanned images into the screensaver folder, in a task of its
        own that reports progress, and unmounts the drive afterwards if this
        service mounted it.
        Arguments:
            payload (bytes): len(4B) + UTF-8 JSON {"flowId", "device"}.
            writer (StreamWriter): The client running the flow.
        '''
        request = self.__decode(payload, "USB_IMPORT_START")
        if request is None or not self.__owns(request, writer) or self.__copying():
            return
        async with self.__lock:
            if (self.__state["phase"] != "ready" or not self.__names
                    or request.get("device") != self.__device):
                await self.__send(phase="error", message="Valitse USB-muisti uudelleen")
                return
            try:
                os.makedirs(self.__target, exist_ok=True)
                free = shutil.disk_usage(self.__target).free
            except OSError as e:
                logger.warning("Screensaver folder %s is not usable: %s", self.__target, e)
                await self.__send(phase="error", message="Kuvakansioon ei voi kirjoittaa")
                return
            if self.__state["bytes"] + _FREE_SPACE_MARGIN_BYTES > free:
                await self.__send(phase="error", message="Laitteella ei ole tarpeeksi tilaa kuville")
                return
            self.__cancel.clear()
            await self.__send(phase="copying", copied=0, skipped=0)
            self.__copy_task = asyncio.create_task(self.__copy())

    async def handle_close(self, payload: bytes, writer) -> None:
        '''
        Ends the flow: a copy stops after the file it is on (what was copied
        stays), and a volume this service mounted is unmounted.  Nothing is
        replied — the dialog is already gone.
        Arguments:
            payload (bytes): len(4B) + UTF-8 JSON {"flowId"}.
            writer (StreamWriter): The client running the flow.
        '''
        request = self.__decode(payload, "USB_IMPORT_CLOSE")
        if request is None or not self.__owns(request, writer):
            return
        if self.__copying():
            # The copy task unmounts on its own way out.
            self.__cancel.set()
            self.__writer = None
            return
        async with self.__lock:
            await self.__release()
            self.__writer = None
            self.__state = self.__fresh_state()

    # ── The copy ──────────────────────────────────────────────────

    async def __copy(self) -> None:
        '''
        Runs the copy on a worker thread, sends progress while it runs, then
        unmounts and reports the outcome.
        '''
        progress = {"copied": 0, "skipped": 0}
        worker = asyncio.create_task(asyncio.to_thread(
            self.__copy_files, self.__folder or "", list(self.__names), progress))
        sent = None
        while not worker.done():
            await asyncio.wait({worker}, timeout=_PROGRESS_INTERVAL_SECONDS)
            if (progress["copied"], progress["skipped"]) != sent:
                sent = (progress["copied"], progress["skipped"])
                await self.__send(copied=sent[0], skipped=sent[1])
        error = worker.exception()
        async with self.__lock:
            unmounted = await self.__release()
            copied, skipped = progress["copied"], progress["skipped"]
            if error is not None:
                logger.warning("USB import failed after %d files: %s", copied, error)
                await self.__send(phase="error", copied=copied, skipped=skipped,
                                  unmounted=unmounted,
                                  message=f"Kopiointi epäonnistui ({copied} kuvaa kopioitu)")
            else:
                logger.info("USB import %s: %d copied, %d already there",
                            "cancelled" if self.__cancel.is_set() else "finished",
                            copied, skipped)
                await self.__send(phase="done", copied=copied, skipped=skipped,
                                  unmounted=unmounted)
        self.__copy_task = None

    def __copy_files(self, folder: str, names: list, progress: dict) -> None:
        '''
        Copies each image into the screensaver folder (worker thread).  Each one
        is written under a hidden temporary name and renamed into place, so the
        screensaver never lists a half-written photo.  Stops between files once
        cancelled; raises OSError on the first file that cannot be copied.
        Arguments:
            folder (str): The import folder on the stick.
            names (list): Image names in it, from scan_folder().
            progress (dict): {"copied", "skipped"} counters, updated in place.
        '''
        for name in names:
            if self.__cancel.is_set():
                return
            source = os.path.join(folder, name)
            target_name = destination_name(self.__target, name, os.path.getsize(source))
            if target_name is None:
                progress["skipped"] += 1
                continue
            partial = os.path.join(self.__target, f".{target_name}.part")
            try:
                shutil.copyfile(source, partial)
                os.replace(partial, os.path.join(self.__target, target_name))
            except OSError:
                try:
                    os.remove(partial)
                except OSError:
                    pass
                raise
            progress["copied"] += 1

    # ── System calls ──────────────────────────────────────────────

    async def __list_volumes(self) -> list:
        '''Runs lsblk and returns usb_volumes() of its answer.'''
        code, out, err = await self.__run(
            "lsblk", "-J", "-b", "-o", _LSBLK_COLUMNS)
        if code != 0:
            logger.warning("lsblk failed (%s): %s", code, err)
            raise _Refused("USB-laitteiden haku epäonnistui")
        try:
            return usb_volumes(json.loads(out))
        except (ValueError, AttributeError) as e:
            logger.warning("Unreadable lsblk output: %s", e)
            raise _Refused("USB-laitteiden haku epäonnistui") from e

    async def __volume(self, device) -> dict:
        '''
        Looks `device` up in a fresh listing.  A device path from the client is
        only ever used if it is one of the USB volumes listed right now — the
        request must not be able to name, say, the system disk.
        Arguments:
            device (str): A "device" value from the drive list.
        '''
        for volume in await self.__list_volumes():
            if volume["device"] == device:
                return volume
        raise _Refused("USB-muistia ei enää löydy — onko se irrotettu?")

    async def __mount(self, device: str) -> str:
        '''
        Mounts a volume with udisksctl and returns where it landed.
        Arguments:
            device (str): The volume's device path.
        '''
        if shutil.which("udisksctl") is None:
            raise _Refused("USB-muistia ei voi liittää: udisksctl puuttuu")
        code, _out, err = await self.__run(
            "udisksctl", "mount", "-b", device, "--no-user-interaction")
        if code != 0 and "AlreadyMounted" not in err:
            logger.warning("udisksctl mount %s failed (%s): %s", device, code, err)
            if "NotAuthorized" in err:
                raise _Refused("Taustapalvelulla ei ole oikeutta liittää USB-muistia")
            raise _Refused("USB-muistin liittäminen epäonnistui")
        volume = await self.__volume(device)
        if not volume["mountpoint"]:
            raise _Refused("USB-muistin liittäminen epäonnistui")
        logger.info("Mounted %s at %s", device, volume["mountpoint"])
        return volume["mountpoint"]

    async def __release(self) -> bool:
        '''
        Forgets the flow's volume, unmounting it if this service mounted it.
        Returns True when it was unmounted here.  The caller holds the lock.
        '''
        device, mounted_here = self.__device, self.__mounted_here
        self.__device = self.__mountpoint = self.__folder = None
        self.__mounted_here = False
        self.__names = []
        if device is None or not mounted_here:
            return False
        code, _out, err = await self.__run(
            "udisksctl", "unmount", "-b", device, "--no-user-interaction")
        if code != 0:
            logger.warning("udisksctl unmount %s failed (%s): %s", device, code, err)
            return False
        logger.info("Unmounted %s", device)
        return True

    @staticmethod
    async def __run(*argv) -> tuple:
        '''
        Runs a command without a shell and returns (exit code, stdout, stderr);
        -1 when it could not run or did not answer in time.
        Arguments:
            argv (str): The command and its arguments.
        '''
        try:
            process = await asyncio.create_subprocess_exec(
                *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        except OSError as e:
            return -1, "", str(e)
        try:
            out, err = await asyncio.wait_for(
                process.communicate(), timeout=_COMMAND_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return -1, "", f"{argv[0]} timed out"
        return (process.returncode, out.decode("utf-8", "replace"),
                err.decode("utf-8", "replace").strip())

    # ── State ─────────────────────────────────────────────────────

    @staticmethod
    def __fresh_state() -> dict:
        '''The state document of a flow that has done nothing yet.'''
        return {"phase": "idle", "message": "", "drives": [], "device": None,
                "found": False, "count": 0, "bytes": 0, "copied": 0, "skipped": 0,
                "total": 0, "unmounted": False}

    async def __send(self, **changes) -> None:
        '''
        Updates the state document and sends it to the client running the flow.
        A new phase clears the previous one's message.
        Arguments:
            changes: State fields to set.
        '''
        if "phase" in changes and "message" not in changes:
            changes["message"] = ""
        self.__state.update(changes)
        if self.__writer is not None:
            await self.__server.send_to(
                self.__writer, self.__frame(dict(self.__state, flowId=self.__flow_id)))

    @staticmethod
    def __frame(state: dict) -> bytes:
        '''
        Frames a USB_IMPORT_STATE packet.
        Arguments:
            state (dict): The state document, flowId included.
        '''
        body = json.dumps(state).encode("utf-8")
        return protocol.frame(protocol.USB_IMPORT_STATE,
                              bytes((1,)) + struct.pack("!I", len(body)) + body)

    def __copying(self) -> bool:
        '''True while a copy task is running.'''
        return self.__copy_task is not None and not self.__copy_task.done()

    def __owns(self, request: dict, writer) -> bool:
        '''
        True when a request belongs to the live flow: the same client and epoch.
        Arguments:
            request (dict): The parsed request.
            writer (StreamWriter): The client that sent it.
        '''
        return writer is self.__writer and self.__flow_id_of(request) == self.__flow_id

    @staticmethod
    def __flow_id_of(request: dict) -> int:
        '''
        Reads the frontend's flow epoch; anything missing or malformed reads as 0.
        Arguments:
            request (dict): The parsed request.
        '''
        value = request.get("flowId")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return 0
        return value

    @staticmethod
    def __decode(payload: bytes, label: str):
        '''
        Parses a len(4B) + UTF-8 JSON request body; None if unreadable.
        Arguments:
            payload (bytes): The raw handler payload.
            label (str): Packet name, for the warning line.
        '''
        if len(payload) < 4:
            logger.warning("%s: payload too short (%d bytes)", label, len(payload))
            return None
        length = int.from_bytes(payload[:4], "big")
        if len(payload) < 4 + length:
            logger.warning("%s: truncated body", label)
            return None
        try:
            body = json.loads(payload[4:4 + length].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            logger.warning("%s: malformed JSON (%s)", label, e)
            return None
        return body if isinstance(body, dict) else None
