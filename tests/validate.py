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
BASE_SOUND_COUNT = sum(1 for p in (ADDON / "Sounds").rglob("*") if p.is_file() and p.suffix.lower() in {".wav", ".mp3", ".ogg"})
checks, failures = 0, []


def check(condition, message):
    global checks
    checks += 1
    if not condition:
        failures.append(message)
        print("FAIL:", message)


class Client:
    def __init__(self, player="Sender", root=ADDON, epoch=None, saved_path=None):
        self.log = []
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.g = self.lua.globals()
        self.g.emit = lambda *args: self.log.append(args)
        self.lua.execute(MOCK)
        self.g.player = player
        if epoch is not None:
            self.g.epoch = epoch
        if saved_path is not None:
            self.lua.execute(saved_path.read_text(encoding="utf-8-sig"), name="SavedVariables")
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
    check(c.a.ready and len(c.a.soundList) == BASE_SOUND_COUNT, "TOC startup and all bundled sounds")
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


def test_player_mutes():
    c = Client("Listener")
    sid = c.a.soundList[1].id
    digest = c.a.clips[sid].digest
    wire = lambda nonce: f"P|{sid}|{nonce}|{digest}"
    check(len(c.a.optionTabs) == 4 and c.a.optionTabs[4].text == "Игроки", "players tab is available")
    check(c.call("HandleAddonSound", c.a.prefix, wire("recent"), "RAID", "Sender"), "unmuted raid sender plays")
    row = c.a.playerOptions.rows[1]
    check(row.entry.name == "Sender-Sirus" and row.phrase.text == c.a.clips[sid].title, "recent list contains sender and last confirmed phrase")
    row.action.scripts.OnClick(row.action)
    check(c.call("IsPlayerMuted", "sender") and row.action.text == "Вернуть звук", "recent sender button mutes immediately ignoring case")
    before = len(c.events("play"))
    check(not c.call("HandleAddonSound", c.a.prefix, wire("muted"), "RAID", "Sender"), "muted raid packet does not play or queue")
    c.tick(10)
    check(len(c.events("play")) == before and not c.events("chat"), "mute adds no chat and no delayed playback")
    check(not c.call("HandleSayDiscovery", c.a.clips[sid].title, "Sender"), "muted say title sends no discovery query")
    check(not c.events("packet"), "muting does not create outgoing network traffic")
    # Settings drafts, defaults and Cancel cannot undo immediate player mutes.
    c.call("ApplyOptions")
    c.a.options.cancel()
    c.a.options.default()
    c.call("ApplyOptions")
    check(c.call("IsPlayerMuted", "Sender-Sirus"), "Save, Cancel and defaults preserve mutes")
    c.lua.execute('SirusChatWheelDB = SirusChatWheel:Copy(SirusChatWheel.db)')
    c.g.FireEvent("PLAYER_LEAVING_WORLD")
    normalized = c.call("Normalize", c.g.SirusChatWheelDB)
    check(normalized.mutedPlayers["sender-sirus"] == "Sender-Sirus", "mute survives SavedVariables normalization")
    ui = c.a.playerOptions
    ui.muted.scripts.OnClick(ui.muted)
    check(ui.rows[1].entry.name == "Sender-Sirus", "muted list includes saved sender")
    ui.rows[1].action.scripts.OnClick(ui.rows[1].action)
    check(not c.call("IsPlayerMuted", "Sender") and ui.rows[1].entry is None, "unmute button immediately removes saved entry")
    check(not c.call("HandleAddonSound", c.a.prefix, wire("muted"), "RAID", "Sender"), "muted packet is not replayed after unmute")
    check(c.call("HandleAddonSound", c.a.prefix, wire("resumed"), "RAID", "Sender"), "new raid sound works after unmute")
    ui.input.SetText(ui.input, "  КОРОЛЬ  ")
    ui.input.scripts.OnEnterPressed(ui.input)
    check(c.call("IsPlayerMuted", "король-SIRUS") and ui.input.GetText(ui.input) == "", "manual mute handles Cyrillic case and clears input")
    check(not c.call("IsPlayerMuted", "Король-OtherRealm"), "same nickname on another realm is independent")
    check(not c.call("HandleAddonSound", c.a.prefix, wire("foreign"), "RAID", "Sender-OtherRealm"), "raid identity cannot borrow membership from another realm")
    check(not c.call("SetPlayerMuted", "Listener", True)[0], "own character cannot be muted")
    for name in ("", "bad name", "|Hplayer:Someone|h", "bad\nname", "A" * 49):
        check(not c.call("SetPlayerMuted", name, True)[0], "invalid mute name rejected: " + repr(name))
    for i in range(8):
        check(c.call("SetPlayerMuted", "Player" + chr(65 + i), True)[0], "manual muted player added")
    c.call("ScrollPlayers", -1)
    check(c.g.FauxScrollFrame_GetOffset(ui.scroll) > 0 and ui.rows[5].entry is not None, "muted list scroll reaches entries beyond five rows")
    # Only queued clips from the newly muted sender are removed.
    q = Client("Listener")
    q.call("QueueClip", sid, False)
    q.call("HandleAddonSound", q.a.prefix, wire("queuedA"), "RAID", "Sender")
    q.call("HandleAddonSound", q.a.prefix, wire("queuedB"), "RAID", "Receiver")
    check(len(q.a.soundQueue) == 2, "two different remote senders queue behind local audio")
    q.call("SetPlayerMuted", "Sender", True)
    check(len(q.a.soundQueue) == 1 and q.a.soundQueue[1].sender == "receiver-sirus", "mute removes only that sender's queued audio")
    q.tick(10)
    check(len(q.events("play")) == 2, "other sender still plays after queue cleanup")
    # Cancel an outstanding say handshake when muting, and preserve outbound replies.
    s, r = Client(), Client("Receiver")
    s.a.db.channel = "SAY"
    s.call("SendSound", sid)
    r.call("HandleSayDiscovery", s.a.clips[sid].title, "Sender")
    request = r.events("packet")[0][2]
    check(bool(list(r.a.pendingQueries.items())), "say discovery has pending confirmation")
    r.call("SetPlayerMuted", "Sender", True)
    check(not list(r.a.pendingQueries.items()), "mute cancels pending say confirmation")
    pump(r, s)
    pump(s, r)
    check(not r.events("play"), "late say response after mute cannot play")
    outgoing = Client()
    outgoing.a.db.channel = "SAY"
    outgoing.call("SetPlayerMuted", "Receiver", True)
    outgoing.call("SendSound", sid)
    check(outgoing.call("HandleAddonSound", outgoing.a.prefix, request, "WHISPER", "Receiver-Sirus"), "mute does not prevent responding to others about own sounds")
    r.call("SetPlayerMuted", "Sender", False)
    s.tick(31)
    r.tick(31)
    s.call("SendSound", sid)
    r.call("HandleSayDiscovery", s.a.clips[sid].title, "Sender")
    pump(r, s)
    pump(s, r)
    check(len(r.events("play")) == 1, "say handshake works again after unmute")
    # Verify real Lua reload through SavedVariables, including malformed legacy values.
    with tempfile.TemporaryDirectory(prefix="scw-mutes-") as folder:
        saved = Path(folder) / "SirusChatWheel.lua"
        saved.write_text('SirusChatWheelDB={mutedPlayers={["sender-sirus"]="Sender-Sirus",bad=true}}', encoding="utf-8")
        restored = Client("Receiver", saved_path=saved)
        check(restored.call("IsPlayerMuted", "Sender"), "SavedVariables restore mute on a fresh client")
        check(len(list(restored.a.db.mutedPlayers.items())) == 1, "malformed saved mute entries are discarded")


def test_sound_messages():
    c = Client()
    expected = {"OldGod.wav": "Старый Бог", "Ambulance.wav": "Скорую! Скорую! ВРАЧА!",
        "NoExcuses.wav": "Да нет, друг, я не оправдываюсь"}
    clips = {clip.filename: clip for _, clip in c.a.soundList.items()}
    for filename, title in expected.items():
        check(filename in clips and clips[filename].title == title, "new recording and exact Russian title: " + filename)
    for channel in ("RAID", "SAY"):
        for clip in clips.values():
            sender, receiver = Client(), Client("Receiver")
            sender.a.db.channel = channel
            check(sender.call("SendSound", clip.id), "voice send accepted: " + channel + " " + clip.filename)
            chat = sender.events("chat")[0]
            check(chat[1] == "<" + clip.title + ">" and chat[2] == channel,
                "chat wraps the complete voice title in angle brackets: " + channel + " " + clip.filename)
            check(len(chat[1].encode("utf-8")) <= 255, "bracketed voice title fits the chat byte limit")
            if channel == "SAY":
                receiver.call("HandleSayDiscovery", chat[1], "Sender")
                check(not receiver.events("play"), "bracketed say message waits for hidden confirmation")
                pump(receiver, sender)
            pump(sender, receiver)
            check(len(receiver.events("play")) == 1, "bracketed message still synchronizes audio: " + channel + " " + clip.filename)
    # Older senders use bare titles; the hidden Q/R protocol remains compatible.
    sender, receiver = Client(), Client("Receiver")
    clip = sender.a.soundList[1]
    sender.a.db.channel = "SAY"
    sender.call("SendSound", clip.id)
    check(receiver.call("HandleSayDiscovery", clip.title, "Sender"), "legacy bare title is recognized")
    pump(receiver, sender)
    pump(sender, receiver)
    check(len(receiver.events("play")) == 1, "legacy bare title still requires and accepts hidden confirmation")
    sender, receiver = Client(), Client("Receiver")
    receiver.call("HandleSayDiscovery", "<" + clip.title + ">", "Sender")
    pump(receiver, sender)
    pump(sender, receiver)
    check(not receiver.events("play"), "typing a bracketed title alone cannot trigger playback")
    receiver.call("SetPlayerMuted", "Sender", True)
    receiver.log.clear()
    check(not receiver.call("HandleSayDiscovery", "<" + clip.title + ">", "Sender") and not receiver.events("packet"),
        "mute blocks bracketed say discovery without a query")


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
        check(len(c.a.soundList) == BASE_SOUND_COUNT + 1, "PS5.1 to Lua5.1 accepts uppercase MP3 with unicode path")
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
        check(len(c.a.soundList) == BASE_SOUND_COUNT, "deleting sound removes catalog entry")
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
        def invoke(release, repository="example/SirusChatWheel", fail=False, expected_repository="example/SirusChatWheel"):
            fixture.write_text(json.dumps(release), encoding="utf-8")
            body = "throw 'simulated offline'" if fail else f"Get-Content -LiteralPath '{fixture_path}' -Raw -Encoding UTF8 | ConvertFrom-Json"
            command = f"& '{ps_path}' -Quiet"
            if repository is not None:
                command += " -Repository '" + repository.replace("'", "''") + "'"
            wrapper.write_text("function Invoke-RestMethod { param($Uri,$Headers,$UserAgent,$TimeoutSec)\n"
                f"if ($Uri -ne 'https://api.github.com/repos/{expected_repository}/releases/latest') {{ throw 'wrong endpoint' }}\n"
                "if ($TimeoutSec -ne 8) { throw 'missing timeout' }\n" + body + "\n}\n" + command + "\nexit $LASTEXITCODE\n", encoding="utf-8")
            env = os.environ.copy()
            env["PSModulePath"] = str(PS.parent / "Modules")
            return subprocess.run([str(PS), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(wrapper)], capture_output=True, env=env)
        original = {name: (addon / name).read_bytes() for name in ["Core.lua", "Catalog.lua", "SoundNames.json", "Sounds/Cat.wav"]}
        major, minor, _ = map(int, c.a.version.split("."))
        newer_version = f"{major}.{minor + 1}.0"
        release = {"tag_name": "v" + newer_version, "draft": False, "prerelease": False}
        result = invoke(release, "https://github.com/example/SirusChatWheel.git")
        check(result.returncode == 0, "PS5.1 GitHub API schema and URL normalization")
        check(json.loads((addon / "UpdateConfig.json").read_text(encoding="utf-8"))["repository"] == "example/SirusChatWheel", "repository saved separately from WoW settings")
        c = Client(root=addon, epoch=int(time.time())-100)
        check(c.g.SirusChatWheelUpdateStatus.version == newer_version, "PowerShell result loads as Lua5.1")
        check(any(newer_version in event[1] for event in c.events("print")), "new release notification on login")
        check(not c.events("chat") and not c.events("play") and not c.events("packet"), "update notification stays local")
        c.log.clear()
        c.tick(86401)
        check(not c.call("ShowUpdateStatus", False) and len(c.events("print")) == 1, "stale check cannot claim up-to-date")
        release["tag_name"] = "v" + c.a.version
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
        (addon / "UpdateConfig.json").unlink()
        release["tag_name"], release["prerelease"] = "v1.3.0", False
        check(invoke(release, repository=None, expected_repository="mosf1c/SirusChatWheel").returncode == 0, "fresh install checks the publisher repository without configuration")
        check(not (addon / "UpdateConfig.json").exists(), "default repository needs no user configuration file")


def test_full_release_copy():
    import importlib.util
    import zipfile
    import wave
    spec = importlib.util.spec_from_file_location("scw_build_release", ROOT / "tools/build_release.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    with tempfile.TemporaryDirectory(prefix="scw-copy-") as directory:
        base = Path(directory)
        source = base / "source/SirusChatWheel"
        shutil.copytree(ADDON, source)
        (source / "UpdateConfig.json").write_text('{"repository":"local/config"}', encoding="utf-8")
        builder.ADDON, builder.DIST = source, base / "dist"
        release = builder.build()
        check(list(builder.DIST.iterdir()) == [release], "publisher builds exactly one complete ZIP")
        game = base / "My game"
        addons = game / "Interface/AddOns"
        addons.mkdir(parents=True)
        with zipfile.ZipFile(release) as archive:
            check(archive.testzip() is None, "full release ZIP integrity")
            check(not any("Install." in name for name in archive.namelist()), "release requires no installer")
            check("SirusChatWheel/Catalog.lua" in archive.namelist(), "ready catalog is included")
            check(not any("UpdateConfig.json" in name for name in archive.namelist()), "release excludes local GitHub configuration")
            archive.extractall(addons)
        target = addons / "SirusChatWheel"
        c = Client(root=target)
        check(c.a.ready and len(c.a.soundList) == BASE_SOUND_COUNT, "fresh user installs by copying without running scripts")
        cat, dog = c.a.soundByFile["cat.wav"], c.a.soundByFile["dog.wav"]
        saved = game / "WTF/Account/example/SavedVariables/SirusChatWheel.lua"
        saved.parent.mkdir(parents=True)
        saved.write_text('SirusChatWheelDB = {channel="SAY",scale=1.2,sensitivity=1.3,deadzone=20,bindingInitialized=true,'
            'slots={{kind="sound",id="' + cat + '"},{kind="text",text="KEEP"},{kind="sound",id="' + dog + '"}},'
            'mutedPlayers={["sender-sirus"]="Sender-Sirus"},soundUses={1700000090,1700000095}}', encoding="utf-8")
        saved_bytes = saved.read_bytes()
        config = target / "UpdateConfig.json"
        config.write_bytes(b'{"repository":"user/repo"}')
        # The author changes a sound in place and adds two new sounds to the next ZIP.
        def wav(path, byte):
            path.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(path), "wb") as output:
                output.setparams((1, 2, 44100, 0, "NONE", "not compressed"))
                output.writeframes(bytes([byte, 0]) * 4410)
        wav(source / "Sounds/Cat.wav", 1)
        new_wav = "Новые/Сигнал.wav"
        new_mp3 = "New/Voice.MP3"
        wav(source / "Sounds" / new_wav, 2)
        (source / "Sounds/New").mkdir()
        mp3 = (b"\xff\xfb\x90\x00" + bytes(413)) * 4
        (source / "Sounds" / new_mp3).write_bytes(mp3)
        (source / "Sounds/ignore.exe").write_bytes(b"NOT AUDIO")
        names = json.loads((source / "SoundNames.json").read_text(encoding="utf-8-sig"))
        names.update({"Cat.wav": "Обновлённый кот", new_wav: "Новый сигнал", new_mp3: "Новый голос"})
        (source / "SoundNames.json").write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")
        names_bytes = (source / "SoundNames.json").read_bytes()
        release = builder.build()
        check((source / "SoundNames.json").read_bytes() == names_bytes, "build preserves publisher names")
        with zipfile.ZipFile(release) as archive:
            check("SirusChatWheel/Sounds/" + new_wav in archive.namelist() and "SirusChatWheel/Sounds/" + new_mp3 in archive.namelist(), "all newly added publisher WAV and MP3 files enter the ZIP")
            check(not any("ignore.exe" in name for name in archive.namelist()), "non-audio files are excluded")
            archive.extractall(addons)  # Ordinary copy with replacement; no helper runs.
        c = Client(root=target, saved_path=saved)
        check(c.a.ready and len(c.a.soundList) == BASE_SOUND_COUNT + 2, "copying a new ZIP immediately exposes the new sound set")
        check(c.a.db.slots[1].kind == "sound" and c.a.db.slots[1].id == cat, "existing sound sector keeps its stable file ID")
        check(c.call("GetSlotText", 1) == "Обновлённый кот", "new title and audio content replace the old release")
        check(c.a.db.slots[2].text == "KEEP" and c.a.db.slots[3].id == dog, "other sector assignments survive copying")
        check(c.a.db.channel == "SAY" and c.a.db.scale == 1.2 and c.a.db.sensitivity == 1.3 and c.a.db.deadzone == 20, "channel and wheel settings survive copying")
        check(len(c.a.db.soundUses) == 2, "copying an update does not reset the voice rate limit")
        check(c.call("IsPlayerMuted", "Sender"), "copying an update preserves player mutes")
        check(saved.read_bytes() == saved_bytes, "copying never replaces WTF settings")
        check(config.read_bytes() == b'{"repository":"user/repo"}', "copying preserves optional local GitHub configuration")
        new_clips = {clip.filename: clip for _, clip in c.a.soundList.items()}
        for filename in (new_wav, new_mp3):
            clip = new_clips[filename]
            cache = target / "Media" / clip.file.replace("\\", "/")
            check(cache.read_bytes() == (source / "Sounds" / filename).read_bytes(), "copied release includes ready cache for " + filename)
            check(c.call("QueueClip", clip.id, False), "new audio reaches the playback API without rebuilding " + filename)
        c.tick(10)
        check(len(c.events("play")) == 2, "both newly packaged sounds play through the queue")
        # A removed release entry stays unavailable even if copy leaves its old file behind.
        (source / "Sounds/Dog.wav").unlink()
        release = builder.build()
        with zipfile.ZipFile(release) as archive:
            archive.extractall(addons)
        c = Client(root=target, saved_path=saved)
        check((target / "Sounds/Dog.wav").exists(), "test reproduces an old file left behind by merging folders")
        check(c.a.soundByFile["dog.wav"] is None and c.a.db.slots[3].kind == "empty", "new catalog excludes removed audio and clears its sector despite leftover files")
        check(c.a.db.slots[1].id == cat and c.a.db.slots[2].text == "KEEP", "removing one sound leaves other assignments intact")
        # The optional launch helper must not re-scan obsolete files left by merging.
        catalog_bytes = (target / "Catalog.lua").read_bytes()
        fake_game = game / "WoW.exe"
        fake_game.write_bytes(b"LAUNCH TEST STAND-IN")
        wrapper = base / "launch.ps1"
        script_path = str(target / "SoundCatalog.ps1").replace("'", "''")
        game_path = str(fake_game).replace("'", "''")
        wrapper.write_text("function Start-Process { param($FilePath,$WorkingDirectory,[switch]$PassThru) }\n"
            f"& '{script_path}' -LaunchGame -SkipCatalogUpdate -GamePath '{game_path}'\nexit $LASTEXITCODE\n", encoding="utf-8")
        env = os.environ.copy()
        env["PSModulePath"] = str(PS.parent / "Modules")
        launched = subprocess.run([str(PS), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(wrapper)], capture_output=True, env=env)
        check(launched.returncode == 0, "optional launch helper uses the packaged catalog")
        check((target / "Catalog.lua").read_bytes() == catalog_bytes, "launching cannot restore excluded old audio into the catalog")


if __name__ == "__main__":
    # A source checkout intentionally excludes generated installation files.
    # Create only missing defaults; preserve an existing working installation.
    if not (ADDON / "Catalog.lua").exists():
        run_catalog(ADDON)
    if not (ADDON / "UpdateStatus.lua").exists():
        (ADDON / "UpdateStatus.lua").write_text("SirusChatWheelUpdateStatus = {}\n", encoding="utf-8")
    for test in (test_base, test_player_mutes, test_sound_messages, test_limits_and_network, test_delayed_say, test_send_failure, test_catalog, test_updates, test_full_release_copy):
        try:
            test()
        except Exception as error:
            check(False, f"{test.__name__}: {error}")
    print(f"{checks - len(failures)}/{checks} checks passed; {len(failures)} failures")
    sys.exit(bool(failures))
