"""Software updates from a zip file (GitHub's "Code > Download ZIP", or a release zip), installed from the
service web page or a USB stick.

check(zip)   opens it and checks it really is this dash: dash.py and the other main files are there,
             every .py file compiles, nothing tries to unpack outside its folder. Reads its version.
install(zip) unpacks it next to the software folder, carries over what's yours (config.toml and your splash
             pictures), then swaps folders: the running copy becomes <folder>.previous, the new one takes
             its place. The new default config is saved beside yours as config.toml.new (compare them for
             new settings). The dash then restarts itself.
restore()    swaps <folder>.previous back in (one step back).

Not carried over: the .git folder (after an update from a zip the folder is no longer a git checkout;
"git clone" afresh if you want git back). If the update changes the files in tools/ (services, sudoers),
run  sudo bash tools/setup-pi.sh  again.
"""
import json
import logging
import os
import re
import shutil
import time
import zipfile

log = logging.getLogger("updater")

NEEDED = ("dash.py", "screens.py", "config.toml", "version.py")
MAX_BYTES = 200 * 1024 * 1024        # unpacked size limit
KEEP = ("config.toml",)              # yours: always carried over
KEEP_DIRS = ("splash",)              # yours if you changed or added them: carried over


class UpdateError(Exception):
    pass


def _root(names):
    """The folder inside the zip that holds dash.py ('' or 'bobcat-dash-main/')."""
    hits = [n[:-len("dash.py")] for n in names if n == "dash.py" or n.endswith("/dash.py")]
    hits = [h for h in hits if h.count("/") <= 1]
    if not hits:
        raise UpdateError("not a Bobcat dash zip: there's no dash.py in it")
    return min(hits, key=len)


def version_of(text):
    v = re.search(r'^VERSION\s*=\s*"([^"]+)"', text, re.M)
    b = re.search(r'^BUILD_DATE\s*=\s*"([^"]+)"', text, re.M)
    return (v.group(1) if v else "?"), (b.group(1) if b else "?")


def current_version(repo):
    try:
        with open(os.path.join(repo, "version.py")) as f:
            return version_of(f.read())
    except OSError:
        return "?", "?"


def check(path):
    """Returns {"version", "build", "files", "size", "root"}; raises UpdateError when it's no good."""
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        raise UpdateError(f"not a zip file ({e})")
    with z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        names = [i.filename for i in infos]
        root = _root(names)
        size = 0
        for i in infos:
            n = i.filename
            if n.startswith("/") or ".." in n.split("/") or "\\" in n:
                raise UpdateError(f"unsafe path in the zip: {n}")
            size += i.file_size
        if size > MAX_BYTES:
            raise UpdateError(f"too big unpacked ({size / 1e6:.0f} MB)")
        mine = [n for n in names if n.startswith(root)]
        missing = [f for f in NEEDED if root + f not in mine]
        if missing:
            raise UpdateError("files missing: " + ", ".join(missing))
        bad = []
        for n in mine:
            if n.endswith(".py"):
                try:
                    compile(z.read(n), n, "exec")
                except (SyntaxError, ValueError) as e:
                    bad.append(f"{n[len(root):]} ({e.__class__.__name__}, line {getattr(e, 'lineno', '?')})")
        if bad:
            raise UpdateError("python files that don't compile: " + "; ".join(bad[:5]))
        version, build = version_of(z.read(root + "version.py").decode("utf-8", "replace"))
        return {"version": version, "build": build, "files": len(mine), "size": size, "root": root}


def install(path, repo, data_dir=None):
    """Unpack, carry over config.toml and splash pictures, swap folders. Returns check()'s info.
    Raises UpdateError (and leaves the running copy as it was) when anything goes wrong."""
    info = check(path)
    repo = os.path.abspath(repo)
    new, prev = repo + ".new", repo + ".previous"
    shutil.rmtree(new, ignore_errors=True)
    try:
        os.makedirs(new)
        with zipfile.ZipFile(path) as z:
            for i in z.infolist():
                if i.is_dir() or not i.filename.startswith(info["root"]):
                    continue
                rel = i.filename[len(info["root"]):]
                dest = os.path.join(new, rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with z.open(i) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
                mode = (i.external_attr >> 16) & 0o777
                if mode & 0o100 or rel.startswith("tools/") and not os.path.splitext(rel)[1]:
                    os.chmod(dest, 0o755)
        for name in KEEP:
            if os.path.exists(os.path.join(repo, name)):
                if os.path.exists(os.path.join(new, name)):
                    shutil.copy2(os.path.join(new, name), os.path.join(new, name + ".new"))
                shutil.copy2(os.path.join(repo, name), os.path.join(new, name))
        for d in KEEP_DIRS:
            src_dir = os.path.join(repo, d)
            if os.path.isdir(src_dir):
                for f in os.listdir(src_dir):
                    s = os.path.join(src_dir, f)
                    if os.path.isfile(s):
                        os.makedirs(os.path.join(new, d), exist_ok=True)
                        shutil.copy2(s, os.path.join(new, d, f))
    except OSError as e:
        shutil.rmtree(new, ignore_errors=True)
        raise UpdateError(f"couldn't unpack it ({e})")
    old_version = current_version(repo)
    shutil.rmtree(prev, ignore_errors=True)
    os.rename(repo, prev)
    try:
        os.rename(new, repo)
    except OSError as e:
        os.rename(prev, repo)                        # put the running copy back
        raise UpdateError(f"couldn't swap folders ({e})")
    _record(data_dir, "install", old_version, (info["version"], info["build"]))
    log.info("installed v%s (%s) over v%s; the old copy is %s", info["version"], info["build"], old_version[0], prev)
    return info


def previous(repo):
    """(version, build) of the copy restore() would bring back, or None."""
    prev = os.path.abspath(repo) + ".previous"
    return current_version(prev) if os.path.isfile(os.path.join(prev, "dash.py")) else None


def restore(repo, data_dir=None):
    repo = os.path.abspath(repo)
    prev, tmp = repo + ".previous", repo + ".swap"
    if previous(repo) is None:
        raise UpdateError("there's no previous version to go back to")
    now_v, back_v = current_version(repo), current_version(prev)
    shutil.rmtree(tmp, ignore_errors=True)
    os.rename(repo, tmp)
    os.rename(prev, repo)
    os.rename(tmp, prev)                             # so restore() again goes forward again
    _record(data_dir, "restore", now_v, back_v)
    return back_v


def history(data_dir):
    try:
        with open(os.path.join(data_dir, "updates.json")) as f:
            return json.load(f).get("updates", [])
    except (OSError, ValueError):
        return []


def _record(data_dir, what, old, new):
    if not data_dir:
        return
    from service import write_json
    h = history(data_dir)
    h.append({"what": what, "t": time.time(), "from": f"{old[0]} ({old[1]})", "to": f"{new[0]} ({new[1]})"})
    try:
        write_json(data_dir, "updates.json", {"updates": h[-50:]})
    except OSError as e:
        log.error("can't save updates.json: %s", e)
