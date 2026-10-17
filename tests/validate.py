"""Run with Python + lupa.lua51; all catalog writes use a temporary addon copy."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(os.environ["TEMP"]) / "scw-validation-runtime"))
from lupa.lua51 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "SirusChatWheel"
MOCK = (ROOT / "tests/wow_mock.lua").read_text(encoding="utf-8")
PS = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
checks, failures = 0, []


def check(condition, message):
    global checks
    checks += 1
    if not condition:
        failures.append(message)
        print("FAIL:", message)


class Client:
    def __init__(self, player="Sender", root=ADDON, epoch=None):
        self.log = []
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.g = self.lua.globals()
        self.g.emit = lambda *args: self.log.append(args)
        self.lua.execute(MOCK)
        self.g.player = player
        if epoch is not None:
            self.g.epoch = epoch
        for file in root.joinpath("SirusChatWheel.toc").read_text(encoding="utf-8-sig").splitlines():
            if file and not file.startswith("#"):
                self.lua.execute(root.joinpath(file).read_text(encoding="utf-8-sig"), name=file)
        self.g.FireEvent("ADDON_LOADED", "SirusChatWheel")
        self.g.FireEvent("PLAYER_LOGIN")
        self.a = self.g.SirusChatWheel

    def call(self, method, *args):
        return self.a[method](self.a, *args)

    def events(self, kind):
        return [item for item in self.log if item[0] == kind]

    def tick(self, seconds):
        self.g.Tick(seconds)


def pump(sender, receiver):
    """Deliver queued wire messages after the caller's selected latency."""
    messages = sender.events("packet")[:]
    sender.log[:] = [event for event in sender.log if event[0] != "packet"]
    for _, prefix, packet, channel, target in messages:
        receiver.call("HandleAddonSound", prefix, packet, channel, sender.g.player)


def test_base():
    c = Client()
    check(c.lua.eval("_VERSION") == "Lua 5.1", "real Lua 5.1 runtime")
    check(c.a.ready and len(c.a.soundList) == 2, "TOC startup and bundled sounds")
    check(c.g.binding == c.a.binding, "first login binds Y")
    check(len(c.a.textChoices) == 12, "12 text choices")
    entries = c.call("BuildPickerEntries")
    check(entries[2].kind == "text" and entries[13].kind == "text" and entries[15].kind == "sound", "picker order")
    directions = [(0, 100), (100, 100), (100, 0), (100, -100), (0, -100), (-100, -100), (-100, 0), (-100, 100)]
    for i, (dx, dy) in enumerate(directions, 1):
        check(c.call("GetSector", dx, dy, 16) == i, f"sector {i}")
    check(c.call("GetSector", 0, 0, 16) is None, "deadzone cancels")
    root = ET.parse(ADDON / "Bindings.xml").getroot()
    binding = root.find("Binding")
    check(binding.get("runOnUp") == "true", "binding receives release")
    c.g.keystate = "down"
    c.lua.execute(binding.text)
    check(c.a.active and c.g.cursor is not None, "Y down opens and hides cursor")
    check(c.a.originX == 400 and c.a.originY == 300, "origin is current cursor position")
    c.g.cursorY = 400
    c.g.keystate = "up"
    c.lua.execute(binding.text)
    check(not c.a.active and c.g.cursor is None, "Y up closes and restores cursor")
    check(len(c.events("chat")) == 1 and c.events("chat")[0][2] == "RAID", "release resamples and sends raid text")
    c.log.clear()
    c.call("OpenWheel", True)
    c.g.cursorX += 100
    c.call("CloseWheel", True)
    check(not c.events("chat") and not c.events("play"), "preview never sends")
    c.g.focus = True
    c.call("HandleKey", "down")
    check(not c.a.active, "text focus does not open wheel")
    c.g.focus = None
    c.call("HandleKey", "up")
    c.g.combat = True
    c.call("HandleKey", "down")
    check(c.a.active, "wheel opens in combat")
    c.a.overlay.scripts.OnMouseDown(c.a.overlay)
    check(not c.a.active and not c.events("chat"), "click cancels")
    labels = [w for _, w in c.a.wheelRoot.children.items() if w.kind == "FontString"]
    check(len(labels) == 8 and all(abs(w.size - 22.4) < 0.001 for w in labels), "eight labels enlarged 40%, no footer")
    icons = [w for _, w in c.a.wheelRoot.children.items() if w.kind == "Texture" and w.texture and w.texture[1].endswith("Speaker.tga")]
    check(len(icons) == 8 and all(w.points[1][1] == "RIGHT" and w.points[1][3] == "LEFT" and w.points[1][5] == 0 for w in icons), "speaker vertically centered left of entire label")
    c.a.options.default()
    c.call("ApplyOptions")
    check(len(c.a.db.slots) == 8, "options default and apply")


def test_limits_and_network():
    c, r = Client(), Client("Receiver")
    sid = c.a.soundList[1].id
    check(c.call("SendSound", sid), "first sound accepted")
    pump(c, r)
    check(len(r.events("play")) == 1, "raid hidden packet plays on peer")
    c.tick(1)
    check(c.call("SendSound", sid), "second sound accepted")
    pump(c, r)
    before = len(c.log)
    check(not c.call("SendSound", sid), "third sound rejected")
    added = c.log[before:]
    check(len(added) == 1 and added[0][0] == "error" and added[0][2] == 1, "third attempt only red error, no chat or sound")
    c.a.options.default()
    c.call("ApplyOptions")
    check(not c.call("SendSound", sid), "defaults preserve rate limit")
    c.tick(28.99)
    check(not c.call("SendSound", sid), "29.99 seconds still blocked")
    c.tick(0.01)
    check(c.call("SendSound", sid), "first use expires at 30 seconds")
    check(not c.call("SendSound", sid), "second use retains independent expiry")
    c.tick(1)
    check(c.call("SendSound", sid), "second use expires independently")
    r.log.clear()
    r.call("HandleSayDiscovery", r.a.soundList[1].title, "Sender")
    check(not r.events("play"), "chat title alone cannot play audio")
    r.log.clear()
    packet = f"P|{sid}|nonce1|{c.a.clips[sid].digest}"
    r.tick(31)
    check(r.call("HandleAddonSound", c.a.prefix, packet, "RAID", "Sender"), "valid raid command accepted")
    check(not r.call("HandleAddonSound", c.a.prefix, packet, "RAID", "Sender"), "repeated command rejected")
    check(not r.call("HandleAddonSound", c.a.prefix, packet.replace("nonce1", "nonce2"), "RAID", "Outsider"), "nonmember command rejected")
    r.a.db.receiveSounds = False
    check(not r.call("HandleAddonSound", c.a.prefix, packet.replace("nonce1", "nonce3"), "RAID", "Sender"), "incoming sounds setting")


def test_delayed_say():
    c, r = Client(), Client("Receiver")
    c.a.db.channel = "SAY"
    for index in (1, 2):
        sid = c.a.soundList[index].id
        c.call("SendSound", sid)
        if index == 1:
            c.tick(1.1)
    # Both public messages arrive before hidden queries have reached the sender.
    for event in c.events("chat"):
        r.call("HandleSayDiscovery", event[1], "Sender")
        r.tick(1.1)
    pump(r, c)
    responses = len(c.events("packet"))
    pump(c, r)
    r.tick(10)
    check(responses == 2 and len(r.events("play")) == 2, "both accepted SAY sounds survive delayed confirmation")
    c, r = Client(), Client("Receiver")
    c.a.db.channel = "SAY"
    for index in (1, 2):
        c.call("SendSound", c.a.soundList[index].id)
        c.tick(0.2)
    for event in c.events("chat"):
        r.call("HandleSayDiscovery", event[1], "Sender")
        r.tick(0.2)
    pump(r, c)
    responses = len(c.events("packet"))
    pump(c, r)
    r.tick(10)
    check(responses == 2 and len(r.events("play")) == 2, "two SAY sounds within one second both synchronize")
    c, r = Client(), Client("Receiver")
    c.a.db.channel = "SAY"
    sid = c.a.soundList[1].id
    for _ in range(2):
        check(c.call("SendSound", sid), "repeated same sound accepted within limit")
    for event in c.events("chat"):
        r.call("HandleSayDiscovery", event[1], "Sender")
    pump(r, c)
    packets = c.events("packet")[:]
    pump(c, r)
    r.tick(10)
    check(len(r.events("play")) == 2, "two identical SAY sounds receive separate confirmations")
    before = len(r.events("play"))
    for _, prefix, packet, channel, _ in packets:
        r.call("HandleAddonSound", prefix, packet, channel, "Sender")
    r.tick(10)
    check(len(r.events("play")) == before, "replaying SAY confirmations cannot replay audio")
    c.tick(7)
    r.tick(2)
    r.call("HandleSayDiscovery", c.a.clips[sid].title, "Sender")
    pump(r, c)
    check(not c.events("packet"), "expired SAY actions cannot confirm manual chat")


def test_send_failure():
    c = Client()
    sid = c.a.soundList[1].id
    c.lua.execute('SendChatMessage = function() error("simulated send failure") end')
    check(not c.call("SendSound", sid), "chat failure rejects sound action")
    check(len(c.a.db.soundUses) == 0 and len(c.a.recentSoundActions) == 0, "chat failure restores limit and confirmations")
    check(not c.events("packet") and not c.events("play"), "chat failure sends no packet or audio")


def run_catalog(path):
    env = os.environ.copy()
    # Do not inherit the bundled PowerShell 7 module path into Windows PS5.1.
    env["PSModulePath"] = str(PS.parent / "Modules") + ";" + str(Path(os.environ["ProgramFiles"]) / "WindowsPowerShell/Modules")
    process = subprocess.run([str(PS), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(path / "SoundCatalog.ps1")], capture_output=True, env=env)
    if process.returncode:
        raise RuntimeError(process.stdout.decode(errors="replace") + process.stderr.decode(errors="replace"))


def test_catalog():
    with tempfile.TemporaryDirectory(prefix="scw-check-") as folder:
        addon = Path(folder) / "SirusChatWheel"
        shutil.copytree(ADDON, addon)
        nested = addon / "Sounds/Русские записи"
        nested.mkdir()
        # Synthetic MPEG1 Layer III frames test catalog/filter paths, not decoding.
        mp3 = (b"\xff\xfb\x90\x00" + bytes(413)) * 4
        (nested / "Тест.MP3").write_bytes(mp3)
        (nested / "ignored.exe").write_bytes(mp3)
        names = {"Русские записи/Тест.MP3": "Тест \\\"голоса\\\""}
        (addon / "SoundNames.json").write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")
        before_names = (addon / "SoundNames.json").read_bytes()
        run_catalog(addon)
        c = Client(root=addon)
        check(len(c.a.soundList) == 3, "PS5.1 to Lua5.1 accepts uppercase MP3 with unicode path")
        sid = c.a.soundByFile["Русские записи/Тест.MP3".lower()]
        # Lua string.lower is ASCII; match the original Cyrillic path explicitly.
        if sid is None:
            sid = next(clip.id for _, clip in c.a.soundList.items() if clip.filename.endswith("Тест.MP3"))
        clip = c.a.clips[sid]
        cache = addon / "Media" / clip.file.replace("\\", "/")
        check(cache.read_bytes() == mp3, "MP3 cache preserves source bytes")
        check(clip.title == names["Русские записи/Тест.MP3"], "JSON titles survive Lua escaping")
        check((addon / "SoundNames.json").read_bytes() == before_names, "catalog preserves user JSON")
        c.a.db.slots[1] = c.lua.table_from({"kind": "sound", "id": sid})
        (nested / "Тест.MP3").rename(nested / "Новое.MP3")
        run_catalog(addon)
        c.lua.execute((addon / "Catalog.lua").read_text(encoding="utf-8"))
        c.call("LoadCatalog")
        c.a.db = c.call("Normalize", c.a.db)
        check(c.a.db.slots[1].kind == "empty" and not cache.exists(), "renaming clears slot and obsolete cache")
        (nested / "Новое.MP3").unlink()
        run_catalog(addon)
        c.lua.execute((addon / "Catalog.lua").read_text(encoding="utf-8"))
        c.call("LoadCatalog")
        check(len(c.a.soundList) == 2, "deleting sound removes catalog entry")
        check(hashlib.sha256((addon / "Sounds/Cat.wav").read_bytes()).digest() == hashlib.sha256((ADDON / "Sounds/Cat.wav").read_bytes()).digest(), "utility leaves original sounds intact")


def test_updates():
    import time
    c = Client()
    for candidate, installed, expected in [("1.10.0", "1.9.9", True), ("2.0.0", "1.99.99", True),
            ("1.2.4", "1.2.4", False), ("1.2.3", "1.2.4", False), ("bad", "1.2.4", False)]:
        check(c.call("IsNewerVersion", candidate, installed) == expected, f"version comparison {candidate} vs {installed}")
    check(not c.call("ShowUpdateStatus", False), "unconfigured GitHub check is explicit")
    with tempfile.TemporaryDirectory(prefix="scw-updates-") as directory:
        addon = Path(directory) / "SirusChatWheel"
        shutil.copytree(ADDON, addon)
        # Use a local HTTP stand-in, not an invented live SirusChatWheel repository.
        fixture = Path(directory) / "release.json"
        wrapper = Path(directory) / "invoke.ps1"
        ps_path = str(addon / "Check-Updates.ps1").replace("'", "''")
        fixture_path = str(fixture).replace("'", "''")
        def invoke(release, repository="example/SirusChatWheel", fail=False):
            fixture.write_text(json.dumps(release), encoding="utf-8")
            body = "throw 'simulated offline'" if fail else f"Get-Content -LiteralPath '{fixture_path}' -Raw -Encoding UTF8 | ConvertFrom-Json"
            command = f"& '{ps_path}' -Quiet"
            if repository is not None:
                command += " -Repository '" + repository.replace("'", "''") + "'"
            wrapper.write_text("function Invoke-RestMethod { param($Uri,$Headers,$UserAgent,$TimeoutSec)\n"
                "if ($Uri -ne 'https://api.github.com/repos/example/SirusChatWheel/releases/latest') { throw 'wrong endpoint' }\n"
                "if ($TimeoutSec -ne 8) { throw 'missing timeout' }\n" + body + "\n}\n" + command + "\nexit $LASTEXITCODE\n", encoding="utf-8")
            env = os.environ.copy()
            env["PSModulePath"] = str(PS.parent / "Modules")
            return subprocess.run([str(PS), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(wrapper)], capture_output=True, env=env)
        original = {name: (addon / name).read_bytes() for name in ["Core.lua", "Catalog.lua", "SoundNames.json", "Sounds/Cat.wav"]}
        release = {"tag_name": "v1.3.0", "draft": False, "prerelease": False}
        result = invoke(release, "https://github.com/example/SirusChatWheel.git")
        check(result.returncode == 0, "PS5.1 GitHub API schema and URL normalization")
        check(json.loads((addon / "UpdateConfig.json").read_text(encoding="utf-8"))["repository"] == "example/SirusChatWheel", "repository saved separately from WoW settings")
        c = Client(root=addon, epoch=int(time.time())-100)
        check(c.g.SirusChatWheelUpdateStatus.version == "1.3.0", "PowerShell result loads as Lua5.1")
        check(any("1.3.0" in event[1] for event in c.events("print")), "new release notification on login")
        check(not c.events("chat") and not c.events("play") and not c.events("packet"), "update notification stays local")
        c.log.clear()
        c.tick(86401)
        check(not c.call("ShowUpdateStatus", False) and len(c.events("print")) == 1, "stale check cannot claim up-to-date")
        release["tag_name"] = "v1.2.4"
        check(invoke(release, repository=None).returncode == 0, "saved repository reused")
        c = Client(root=addon, epoch=int(time.time())-100)
        c.log.clear()
        check(not c.call("ShowUpdateStatus", True) and not c.events("print"), "equal version stays quiet on login")
        c.call("ShowUpdateStatus", False)
        check(len(c.events("print")) == 1, "manual status reports timestamped check")
        check(invoke(release, fail=True).returncode != 0, "network failure reported")
        c = Client(root=addon, epoch=int(time.time())-100)
        check(c.g.SirusChatWheelUpdateStatus.state == "failed", "failure replaces stale success")
        release["tag_name"] = 'v1.3.0\"; error("injected")'
        check(invoke(release).returncode != 0, "untrusted release tag rejected")
        c = Client(root=addon, epoch=int(time.time())-100)
        check(c.g.SirusChatWheelUpdateStatus.state == "failed", "invalid tag never becomes Lua code")
        release["tag_name"], release["prerelease"] = "v1.3.0", True
        check(invoke(release).returncode != 0, "prerelease not advertised as stable")
        check(invoke(release, repository="https://invalid.example/a/b").returncode != 0, "non-GitHub source rejected")
        check(all((addon / name).read_bytes() == data for name, data in original.items()), "checking never replaces addon code, catalog, names or sounds")


if __name__ == "__main__":
    # A source checkout intentionally excludes generated installation files.
    # Create only missing defaults; preserve an existing working installation.
    if not (ADDON / "SoundNames.json").exists():
        shutil.copyfile(ADDON / "SoundNames.example.json", ADDON / "SoundNames.json")
    if not (ADDON / "Catalog.lua").exists():
        run_catalog(ADDON)
    if not (ADDON / "UpdateStatus.lua").exists():
        (ADDON / "UpdateStatus.lua").write_text("SirusChatWheelUpdateStatus = {}\n", encoding="utf-8")
    for test in (test_base, test_limits_and_network, test_delayed_say, test_send_failure, test_catalog, test_updates):
        try:
            test()
        except Exception as error:
            check(False, f"{test.__name__}: {error}")
    print(f"{checks - len(failures)}/{checks} checks passed; {len(failures)} failures")
    sys.exit(bool(failures))
