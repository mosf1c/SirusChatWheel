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
    def __init__(self, player="Sender", root=ADDON, epoch=None, saved_path=None, realm=None):
        self.log = []
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.g = self.lua.globals()
        self.g.emit = lambda *args: self.log.append(args)
        self.lua.execute(MOCK)
        self.g.player = player
        if realm is not None:
            self.g.realmName = realm
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

    def use_channel(self, channel):
        self.a.db.channels = self.lua.table_from({key: key == channel for key in ("RAID", "PARTY", "SAY")})
        self.g.raid = channel == "RAID"
        self.g.partyRoster = self.lua.table_from(["Receiver" if self.g.player == "Sender" else "Sender"] if channel == "PARTY" else [])


def next_version(client):
    major, minor, _ = map(int, client.a.version.split("."))
    return f"{major}.{minor + 1}.0"


def pump(sender, receiver, sender_name=None):
    """Deliver queued wire messages after the caller's selected latency."""
    messages = sender.events("packet")[:]
    sender.log[:] = [event for event in sender.log if event[0] != "packet"]
    for _, prefix, packet, channel, target in messages:
        receiver.g.FireEvent("CHAT_MSG_ADDON", prefix, packet, channel, sender_name or sender.g.player)


def test_base():
    c = Client()
    check(c.lua.eval("_VERSION") == "Lua 5.1", "real Lua 5.1 runtime")
    check(c.a.ready and len(c.a.soundList) == BASE_SOUND_COUNT, "TOC startup and all bundled sounds")
    check(c.g.binding == c.a.binding, "first login binds Y")
    check(len(c.a.textChoices) == 14, "14 text choices")
    entries = c.call("BuildPickerEntries")
    check(entries[2].kind == "text" and entries[15].kind == "text" and entries[17].kind == "sound", "picker order")
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


def test_context_modes():
    channels = ("RAID", "PARTY", "SAY")
    for context in channels:
        for mask in range(8):
            c = Client()
            c.use_channel(context)
            enabled = {channel: bool(mask & (1 << i)) for i, channel in enumerate(channels)}
            c.a.db.channels = c.lua.table_from(enabled)
            expected = context if enabled[context] else None
            check(c.call("ResolveChannel") == expected, f"context {context} respects independent channel settings {mask}")
            if not enabled[context]:
                c.log.clear()
                check(not c.call("SendPhrase", 1) and not c.call("SendSound", c.a.soundList[1].id) and
                    not c.events("chat") and not c.events("packet") and not c.events("play") and len(c.a.db.soundUses) == 0,
                    f"disabled {context} never falls back, sends or consumes the voice limit {mask}")
    c = Client()
    for legacy, expected in [({}, (True, True, True)), ({"channel": "RAID", "fallbackSay": False}, (True, True, False)),
            ({"channel": "RAID", "fallbackSay": True}, (True, True, True)), ({"channel": "SAY"}, (False, False, True))]:
        source = c.lua.table_from(legacy)
        source.scale = 0.8
        normalized = c.call("Normalize", source)
        check(tuple(normalized.channels[name] for name in channels) == expected and normalized.channel is None and
            normalized.fallbackSay is None and normalized.scale == 0.8 and normalized.schema == 5, "legacy channel settings migrate: " + repr(legacy))
    source = c.lua.table_from({"channels": c.lua.table_from({name: False for name in channels})})
    check(not any(c.call("Normalize", source).channels[name] for name in channels), "normalization preserves all contexts disabled")
    for context in channels:
        c = Client()
        c.use_channel(context)
        c.call("SendPhrase", 1)
        check(len(c.events("chat")) == 1 and c.events("chat")[0][2] == context, "text sends once to the current context: " + context)
        for index in range(1, BASE_SOUND_COUNT + 1):
            sender, receiver = Client(), Client("Receiver", realm="ProxyEU Neverest x3 - 3.3.5a+")
            sender.use_channel(context)
            receiver.use_channel(context)
            clip = sender.a.soundList[index]
            check(sender.call("SendSound", clip.id), "voice accepted in current context: " + context + " " + clip.filename)
            if context == "SAY":
                receiver.call("HandleSayDiscovery", sender.events("chat")[0][1], "Sender")
                pump(receiver, sender)
            pump(sender, receiver)
            check(len(receiver.events("play")) == 1 and sender.events("chat")[0][2] == context,
                "every voice crosses the actual context transport: " + context + " " + clip.filename)
    c = Client()
    c.use_channel("PARTY")
    clip = c.a.soundList[1]
    packet = f"P|{clip.id}|party_foreign|{clip.digest}"
    check(not c.call("HandleAddonSound", c.a.prefix, packet, "PARTY", "Outsider"), "party sound rejects players outside the group")
    c.call("SetPlayerMuted", "Receiver", True)
    check(not c.call("HandleAddonSound", c.a.prefix, packet, "PARTY", "Receiver"), "party sound respects saved mutes")
    c.call("SetPlayerMuted", "Receiver", False)
    c.a.db.receiveSounds = False
    check(not c.call("HandleAddonSound", c.a.prefix, packet.replace("foreign", "disabled"), "PARTY", "Receiver"), "party sound respects receiving disabled")
    c = Client()
    c.use_channel("RAID")
    c.call("SendSound", c.a.soundList[1].id)
    c.use_channel("PARTY")
    c.call("SendSound", c.a.soundList[1].id)
    c.use_channel("SAY")
    check(not c.call("SendSound", c.a.soundList[1].id) and len(c.events("chat")) == 2 and len(c.a.db.soundUses) == 2,
        "switching contexts cannot reset the two-sound limit")


def test_option_actions():
    c = Client()
    c.a.db.scale, c.a.db.sensitivity, c.a.db.deadzone = 0.8, 1.6, 25
    c.a.db.soundUses = c.lua.table_from([c.g.time() - 1, c.g.time()])
    c.call("RefreshOptions")
    c.call("SetPlayerMuted", "Receiver", True)
    c.call("SelectSlot", 1, c.lua.table_from({"kind": "text", "text": "DRAFT"}))
    raid, party, say = c.g.SirusChatWheelChannelRaid, c.g.SirusChatWheelChannelParty, c.g.SirusChatWheelChannelSay
    raid.SetChecked(raid, False)
    raid.scripts.OnClick(raid)
    say.SetChecked(say, False)
    say.scripts.OnClick(say)
    check(not c.a.options.draft.channels.RAID and c.a.options.draft.channels.PARTY and not c.a.options.draft.channels.SAY,
        "context checkboxes edit their values independently")
    reset = c.g.SirusChatWheelResetWheel
    reset.scripts.OnClick(reset)
    draft = c.a.options.draft
    check((draft.scale, draft.sensitivity, draft.deadzone) == (1, 1, 16) and draft.slots[1].text == "DRAFT" and
        not draft.channels.RAID and draft.channels.PARTY and not draft.channels.SAY, "reset changes only the three wheel values in the draft")
    check(c.a.db.scale == 0.8 and len(c.a.db.soundUses) == 2 and c.call("IsPlayerMuted", "Receiver"), "reset leaves applied settings, rate limit and mutes intact")
    c.a.options.cancel()
    check(c.a.options.draft.scale == 0.8 and c.a.options.draft.slots[1].text != "DRAFT" and c.a.options.draft.channels.RAID,
        "Cancel discards reset, channel and phrase drafts")
    reset.scripts.OnClick(reset)
    c.a.options.okay()
    check((c.a.db.scale, c.a.db.sensitivity, c.a.db.deadzone) == (1, 1, 16) and len(c.a.db.soundUses) == 2,
        "global OK applies the reset and preserves the voice limit")
    c.g.SirusChatWheelSliderscale.SetValue(c.g.SirusChatWheelSliderscale, 1.2)
    preview = next(w for _, w in c.a.options.children.items() if w.text == "Проверить колесо")
    c.log.clear()
    preview.scripts.OnClick(preview)
    check(c.a.active and c.a.preview and abs(c.a.db.scale - 1.2) < 1e-9, "preview keeps its existing behavior of applying the draft")
    c.call("CloseWheel", True)
    c.a.options.cancel()
    check(abs(c.a.db.scale - 1.2) < 1e-9 and not c.events("chat") and not c.events("packet") and not c.events("play") and
        c.call("IsPlayerMuted", "Receiver"), "preview sends nothing and Cancel does not undo its already applied settings")


def test_player_mutes():
    c = Client("Listener")
    sid = c.a.soundList[1].id
    digest = c.a.clips[sid].digest
    wire = lambda nonce: f"P|{sid}|{nonce}|{digest}"
    check(len(c.a.optionTabs) == 3 and c.a.optionTabs[3].text == "Игроки", "players tab is available")
    check(c.call("HandleAddonSound", c.a.prefix, wire("recent"), "RAID", "Sender"), "unmuted raid sender plays")
    row = c.a.playerOptions.rows[1]
    check(row.entry.name == "Sender-Neverest x3" and row.phrase.text == c.a.clips[sid].title, "recent list contains sender and last confirmed phrase")
    row.action.scripts.OnClick(row.action)
    check(c.call("IsPlayerMuted", "sender") and row.action.text == "Вернуть звук", "recent sender button mutes immediately ignoring case")
    before = len(c.events("play"))
    check(not c.call("HandleAddonSound", c.a.prefix, wire("muted"), "RAID", "Sender"), "muted raid packet does not play or queue")
    c.tick(10)
    check(len(c.events("play")) == before and not c.events("chat"), "mute adds no chat and no delayed playback")
    check(not c.call("HandleSayDiscovery", c.a.clips[sid].title, "Sender"), "muted say title sends no discovery query")
    check(not any(p[1] == c.a.prefix for p in c.events("packet")), "muting does not create outgoing sound traffic")
    # Settings drafts, defaults and Cancel cannot undo immediate player mutes.
    c.call("ApplyOptions")
    c.a.options.cancel()
    c.a.options.default()
    c.call("ApplyOptions")
    check(c.call("IsPlayerMuted", "Sender-Neverest x3"), "Save, Cancel and defaults preserve mutes")
    c.lua.execute('SirusChatWheelDB = SirusChatWheel:Copy(SirusChatWheel.db)')
    c.g.FireEvent("PLAYER_LEAVING_WORLD")
    normalized = c.call("Normalize", c.g.SirusChatWheelDB)
    check(normalized.mutedPlayers["sender-neverestx3"] == "Sender-Neverest x3", "mute survives SavedVariables normalization")
    ui = c.a.playerOptions
    ui.muted.scripts.OnClick(ui.muted)
    check(ui.rows[1].entry.name == "Sender-Neverest x3", "muted list includes saved sender")
    ui.rows[1].action.scripts.OnClick(ui.rows[1].action)
    check(not c.call("IsPlayerMuted", "Sender") and ui.rows[1].entry is None, "unmute button immediately removes saved entry")
    check(not c.call("HandleAddonSound", c.a.prefix, wire("muted"), "RAID", "Sender"), "muted packet is not replayed after unmute")
    check(c.call("HandleAddonSound", c.a.prefix, wire("resumed"), "RAID", "Sender"), "new raid sound works after unmute")
    ui.input.SetText(ui.input, "  КОРОЛЬ  ")
    ui.input.scripts.OnEnterPressed(ui.input)
    check(c.call("IsPlayerMuted", "король-NEVEREST X3") and ui.input.GetText(ui.input) == "", "manual mute handles Cyrillic case and clears input")
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
    check(len(q.a.soundQueue) == 1 and q.a.soundQueue[1].sender == "receiver-neverestx3", "mute removes only that sender's queued audio")
    q.tick(10)
    check(len(q.events("play")) == 2, "other sender still plays after queue cleanup")
    # Cancel an outstanding say handshake when muting, and preserve outbound replies.
    s, r = Client(), Client("Receiver")
    s.use_channel("SAY")
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
    outgoing.use_channel("SAY")
    outgoing.call("SetPlayerMuted", "Receiver", True)
    outgoing.call("SendSound", sid)
    check(outgoing.call("HandleAddonSound", outgoing.a.prefix, request, "WHISPER", "Receiver-Neverest x3"), "mute does not prevent responding to others about own sounds")
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
        saved.write_text('SirusChatWheelDB={mutedPlayers={["sender-neverestx3"]="Sender-Neverestx3",bad=true}}', encoding="utf-8")
        restored = Client("Receiver", saved_path=saved)
        check(restored.call("IsPlayerMuted", "Sender"), "SavedVariables restore mute on a fresh client")
        check(len(list(restored.a.db.mutedPlayers.items())) == 1, "malformed saved mute entries are discarded")


def test_sirus_realms():
    direct = "Neverest x3 - 3.3.5a+"
    routes = [direct, "Proxy Neverest x3 - 3.3.5a+", "ProxyEU Neverest x3 - 3.3.5a+"]
    c = Client("Listener", realm=routes[2])
    aliases = routes + ["Neverest x3", "Neverestx3", "ProxyEUNeverestx3", "proxyneverestx3",
        "  proxyEU   NEVEREST   X3 - 3.3.5a+  ", "ProxyRU Neverest x3 - 4.4.0",
        "ProxySEA2 Neverest x3 - 3.3.6b+", "Neverest x3 - 3.3.5a+-test"]
    for realm in aliases:
        result = c.call("PlayerIdentity", "КОРОЛЬ-" + realm)
        check(result is not None and result[0] == "король-neverestx3", "same world across route/build/name variants: " + realm)
    check(c.call("PlayerIdentity", "Король")[1] == "Король-Neverest x3", "nickname-only lookup uses the cleaned current world")
    for realm, expected in [("Scourge x2 - 3.3.5a+", "scourgex2"), ("ProxyEU Sirus x5 - 3.3.5a+", "sirusx5"),
            ("Neverest x4 - 3.3.5a+", "neverestx4"), ("New World x9 - 4.4.0b+", "newworldx9"),
            ("Новый Мир x4 - 3.3.5a+", "новыймирx4"), ("Some.Realm+", "some.realm+")]:
        check(c.call("PlayerIdentity", "Король-" + realm)[0] == "король-" + expected,
            "other and future world names stay distinct: " + realm)
    for realm in ["", " - 3.3.5a+", "Neverest\n x3", "Neverest\x00x3", "Neverest|cffff0000", "R" * 101]:
        check(c.call("PlayerIdentity", "Sender-" + realm) is None, "invalid world data rejected: " + repr(realm))
    check(not c.call("SetPlayerMuted", "Listener-" + direct, True)[0], "changing proxy spelling cannot bypass self-mute protection")
    sid = c.a.soundList[1].id
    digest = c.a.clips[sid].digest
    for source_realm in routes:
        speaker = "Sender-" + source_realm
        c.call("RememberSpeaker", speaker, c.a.clips[sid])
    check(len(c.a.recentSpeakers) == 1 and c.a.recentSpeakers[1].name == "Sender-Neverest x3", "recent speakers merge routes and show a clean world name")
    c.call("SetPlayerMuted", "Sender-" + routes[1], True)
    check(all(c.call("IsPlayerMuted", "Sender-" + realm) for realm in routes), "mute follows the character across proxy changes")
    check(not c.call("IsPlayerMuted", "Sender-Scourge x2 - 3.3.5a+"), "mute does not affect a namesake on a different world")
    c.call("SetPlayerMuted", "Sender-" + direct, False)
    check(not c.call("IsPlayerMuted", "Sender-" + routes[2]), "unmute works through another route")
    for i, source_realm in enumerate(routes):
        c.call("HandleAddonSound", c.a.prefix, f"P|{sid}|route_{i}|{digest}", "RAID", "Sender-" + source_realm)
    check(len(c.a.remoteUses["sender-neverestx3"]) == 2 and len(c.a.seenPacketOrder) == 2,
        "changing route cannot bypass the incoming two-sound limit")
    outsider = f"P|{sid}|wrong_world|{digest}"
    check(not c.call("HandleAddonSound", c.a.prefix, outsider, "RAID", "Sender-Scourge x2 - 3.3.5a+"),
        "same nickname on another world cannot borrow raid membership")

    with tempfile.TemporaryDirectory(prefix="scw-world-migration-") as directory:
        saved = Path(directory) / "SirusChatWheel.lua"
        saved.write_text('SirusChatWheelDB={scale=1.2,slots={{kind="text",text="KEEP"}},mutedPlayers={'
            'old="Sender-ProxyEUNeverestx3",full="Sender-Proxy Neverest x3 - 3.3.5a+",'
            'plain="Sender-Neverest x3",other="Sender-Scourge x2 - 3.3.5a+"}}', encoding="utf-8")
        restored = Client("Receiver", saved_path=saved, realm=routes[2])
        check(len(list(restored.a.db.mutedPlayers.items())) == 2 and
            restored.a.db.mutedPlayers["sender-neverestx3"] == "Sender-Neverest x3", "legacy mute names migrate and merge proxy duplicates")
        check(restored.call("IsPlayerMuted", "Sender") and restored.call("IsPlayerMuted", "Sender-Scourge x2"),
            "mute migration preserves both current-world and foreign-world entries")
        check(restored.a.db.scale == 1.2 and restored.a.db.slots[1].text == "KEEP", "identity migration preserves other settings")

    # Every shipped recording crosses all direct/proxy combinations in both
    # public channels. The transport preserves the sender's reported address.
    for source_realm in routes:
        for target_realm in routes:
            for channel in ["RAID", "SAY"]:
                for index in range(1, BASE_SOUND_COUNT + 1):
                    sender = Client(realm=source_realm)
                    receiver = Client("Receiver", realm=target_realm)
                    sender.use_channel(channel)
                    clip = sender.a.soundList[index]
                    sender.call("SendSound", clip.id)
                    if channel == "SAY":
                        receiver.call("HandleSayDiscovery", sender.events("chat")[0][1], "Sender-" + source_realm)
                        pump(receiver, sender, "Receiver-" + target_realm)
                    pump(sender, receiver, "Sender-" + source_realm)
                    check(len(receiver.events("play")) == 1 and receiver.a.recentSpeakers[1].name == "Sender-Neverest x3",
                        "shipped voice across world routes: " + channel + " " + clip.filename + " " + source_realm + " -> " + target_realm)
    for channel in ["RAID", "PARTY", "GUILD"]:
        older = Client(realm=direct)
        newer = Client("Receiver", realm=routes[2])
        newer.a.version = next_version(older)
        for client in [older, newer]:
            client.log.clear()
            if channel == "GUILD":
                client.g.guild = True
                client.g.raid = False
            elif channel == "PARTY":
                client.g.raid = False
                client.g.partyRoster = client.lua.table_from(["Receiver" if client is older else "Sender"])
        older.tick(5)
        pump(older, newer, "Sender-" + direct)
        newer.tick(4)
        pump(newer, older, "Receiver-" + routes[2])
        older.tick(4)
        check(older.a.updateNoticePrinted and older.a.versionState.latest.sender == "Receiver-Neverest x3" and
            any(newer.a.version in p[1] for p in older.events("print")), "update discovery across a proxy uses a clean source name: " + channel)


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
            sender.use_channel(channel)
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
    sender.use_channel("SAY")
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


def test_bounded_history():
    c = Client("Receiver")
    sid = c.a.soundList[1].id
    digest = c.a.clips[sid].digest
    c.lua.execute('refreshCount=0; local original=SirusChatWheel.RefreshPlayers; SirusChatWheel.RefreshPlayers=function(self) refreshCount=refreshCount+1; return original(self) end')
    for i in range(300):
        c.call("HandleAddonSound", c.a.prefix, f"P|{sid}|burst_{i}|{digest}", "RAID", "Sender")
    check(len(list(c.a.seenPackets.items())) == 2 and len(c.a.seenPacketOrder) == 2, "300 commands retain only two accepted playback tokens")
    check(c.g.refreshCount == 2, "rate-limited commands do not refresh player UI")
    check(len(c.a.remoteUses["sender-neverestx3"]) == 2, "history optimization preserves two sounds per rolling 30 seconds")
    check(not c.call("HandleAddonSound", c.a.prefix, f"P|{sid}|burst_0|{digest}", "RAID", "Sender"), "accepted command remains protected from replay")
    c.tick(61)
    c.call("PruneNetwork")
    check(not list(c.a.seenPackets.items()) and not list(c.a.seenPacketPeers.items()) and len(c.a.seenPacketOrder) == 0, "minute-old history and peer counters expire together")
    check(c.call("HandleAddonSound", c.a.prefix, f"P|{sid}|after_expiry|{digest}", "RAID", "Sender"), "new sound works after history expiration")
    muted = Client("Receiver")
    muted.call("SetPlayerMuted", "Sender", True)
    muted.lua.execute('refreshCount=0; SirusChatWheel.RefreshPlayers=function() refreshCount=refreshCount+1 end')
    for i in range(300):
        muted.call("HandleAddonSound", muted.a.prefix, f"P|{sid}|muted_{i}|{digest}", "RAID", "Sender")
    check(len(muted.a.seenPacketOrder) == muted.a.networkLimits.mutedPerPeer and not muted.events("play"), "muted sender cannot fill history or play audio")
    check(muted.g.refreshCount == 0, "muted command bursts do not refresh UI")
    muted.call("SetPlayerMuted", "Sender", False)
    check(muted.call("HandleAddonSound", muted.a.prefix, f"P|{sid}|unmuted_fresh|{digest}", "RAID", "Sender"), "muted burst reserves room for immediate unmute")
    full = Client("Receiver")
    full.call("PruneNetwork")
    count = full.a.networkLimits.seen
    for i in range(count):
        full.call("RememberPacket", "key" + str(i), "peer" + str(i), full.g.now)
    check(len(full.a.seenPacketOrder) == count and len(list(full.a.seenPackets.items())) == count, "global packet history has a fixed capacity")
    check(not full.call("RememberPacket", "overflow", "another", full.g.now), "full history rejects new tokens without discarding live replay protection")
    check(full.a.seenPackets["key0"] is not None, "oldest live token survives history overflow")
    full.tick(61)
    full.call("PruneNetwork")
    check(full.call("RememberPacket", "overflow", "another", full.g.now), "expired history releases capacity")
    per_peer = Client("Receiver")
    per_peer.call("PruneNetwork")
    for i in range(30):
        per_peer.call("RememberPacket", "peer_key" + str(i), "one_peer", per_peer.g.now)
    check(len(per_peer.a.seenPacketOrder) == per_peer.a.networkLimits.seenPerPeer, "one sender has a separate history cap")
    waiting = Client("Receiver")
    title = waiting.a.soundList[1].title
    for i in range(100):
        name = "Nearby" + chr(65 + i // 26) + chr(65 + i % 26)
        waiting.call("HandleSayDiscovery", "<" + title + ">", name)
    check(len(list(waiting.a.pendingQueries.items())) <= waiting.a.networkLimits.pending, "say confirmation queue is bounded across senders")
    check(len(list(waiting.a.queryThrottle.items())) <= waiting.a.networkLimits.peers, "say sender tracking has a fixed capacity")
    waiting.tick(9)
    waiting.call("PruneNetwork")
    check(not list(waiting.a.pendingQueries.items()) and not list(waiting.a.queryThrottle.items()), "expired say tracking releases all capacity")
    speaker = Client()
    speaker.use_channel("SAY")
    speaker.call("SendSound", sid)
    for i in range(100):
        name = "Nearby" + chr(65 + i // 26) + chr(65 + i % 26)
        speaker.call("HandleAddonSound", speaker.a.prefix, f"Q|{sid}|ask_{i}|{digest}", "WHISPER", name)
    action = speaker.a.recentSoundActions[1]
    check(len(list(action.requests.items())) == speaker.a.networkLimits.peers and len(speaker.events("packet")) == speaker.a.networkLimits.peers,
        "outbound confirmation recipients and responses are bounded")


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
    c.use_channel("SAY")
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
    c.use_channel("SAY")
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
    c.use_channel("SAY")
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
    check(not any(p[1] == c.a.prefix for p in c.events("packet")), "expired SAY actions cannot confirm manual chat")


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


def test_peer_versions():
    def packets(c, kind=None):
        return [p for p in c.events("packet") if p[1] == c.a.versionPrefix and (kind is None or p[2].startswith(kind + "|"))]

    def receive(c, version, sender="Receiver", channel="RAID", kind="V"):
        c.g.FireEvent("CHAT_MSG_ADDON", c.a.versionPrefix, kind + "|" + version, channel, sender)

    c = Client()
    future = next_version(c)
    c.tick(5)
    check(len(packets(c, "Q")) == 1 and packets(c)[0][3] == "RAID", "login queries peer versions after startup")
    check(not c.a.versionFrame.IsShown(c.a.versionFrame), "version timer sleeps when idle")
    c.g.guild = True
    for _ in range(20):
        c.g.FireEvent("RAID_ROSTER_UPDATE")
        c.g.FireEvent("PLAYER_GUILD_UPDATE", "player")
    c.tick(5)
    check(len(packets(c, "Q")) == 2 and packets(c)[-1][3] == "GUILD", "roster bursts coalesce and query only a new channel")
    c.g.raid = False
    c.g.partyRoster = c.lua.table_from(["Receiver"])
    c.g.FireEvent("PARTY_MEMBERS_CHANGED")
    c.tick(5)
    check(packets(c)[-1][3] == "PARTY", "party discovery uses PARTY outside a raid")
    c.g.FireEvent("PLAYER_ENTERING_WORLD")
    c.tick(5)
    check(len(packets(c, "Q")) == 3, "repeated world and roster events respect the query cooldown")
    receive(c, future, channel="PARTY")
    c.tick(4)
    check(c.a.updateNoticePrinted and c.a.versionState.latest.sender == "Receiver-Neverest x3", "a current party member can announce a newer version")

    c = Client()
    c.log.clear()
    for version, sender, channel in [("9.0.0", "Outsider", "RAID"), ("9.0.0", "Receiver", "WHISPER"),
            ("9.0.0", "Receiver", "GUILD"), ("9.0.0", "Sender", "RAID"),
            ("1.6.0-beta", "Receiver", "RAID"), ("9.0.0|extra", "Receiver", "RAID"),
            ("9.0.0\n", "Receiver", "RAID"), ("999999999999999.0.0", "Receiver", "RAID")]:
        receive(c, version, sender, channel)
    c.g.FireEvent("CHAT_MSG_ADDON", "wrong", "V|9.0.0", "RAID", "Receiver")
    check(c.a.versionState.latest is None and not list(c.a.versionState.peers.items()), "invalid, foreign, self and unsupported-channel announcements are ignored")
    receive(c, c.a.version)
    c.tick(4)
    check(not c.events("print"), "equal versions produce no update notification")

    c = Client()
    c.log.clear()
    c.g.guild = True
    receive(c, future)
    receive(c, "2.0.0", "Newest", "GUILD")
    check(not c.events("print"), "newer announcements are collected before notifying")
    c.tick(4)
    notices = c.events("print")
    check(len(notices) == 2 and "2.0.0" in notices[0][1] and "Newest" in notices[0][1] and c.a.version in notices[0][1], "notice names the highest observed version, installed version and actual source")
    check("https://github.com/mosf1c/SirusChatWheel/releases/latest" in notices[1][1], "notification links to the publisher releases")
    check(not c.events("chat") and not c.events("play") and not c.events("packet"), "peer update notice stays private and silent")
    receive(c, "3.0.0", "Another", "GUILD")
    c.tick(5)
    check(len(c.events("print")) == 2 and c.a.versionState.latest.version == "3.0.0", "later newer announcements do not repeat the automatic notice")
    c.call("RequestPeerVersions", True)
    check("3.0.0" in c.events("print")[-2][1] and "Another" in c.events("print")[-2][1], "manual check can show the newest peer information")

    old, new = Client(), Client("Receiver")
    new.a.version = future
    old.log.clear()
    new.log.clear()
    old.tick(5)
    pump(old, new)
    new.tick(4)
    check(len(packets(new, "V")) == 1, "newer peer answers an older client's query")
    pump(new, old)
    old.tick(4)
    check(any(future in p[1] and "Receiver" in p[1] for p in old.events("print")), "two independent clients complete version discovery over actual addon events")
    check(not new.events("print") and not old.events("chat") and not new.events("chat"), "newer client stays quiet and version exchange creates no public chat")

    c = Client()
    c.g.guild = True
    receive(c, "1.0.0", "Older", "GUILD", "Q")
    check(c.a.versionState.replies.GUILD is not None, "older query schedules a staggered reply")
    receive(c, c.a.version, "Equal", "GUILD")
    c.tick(4)
    check(not packets(c, "V"), "equal announcement suppresses duplicate guild replies")
    c = Client()
    c.g.guild = True
    for i in range(200):
        name = "Peer" + chr(65 + i // 26) + chr(65 + i % 26)
        receive(c, "1.0.0", name, "GUILD", "Q")
    check(len(list(c.a.versionState.peers.items())) == 64 and len(list(c.a.versionState.replies.items())) == 1, "peer bursts have bounded history and one pending reply per channel")
    c.tick(4)
    check(len(packets(c, "V")) == 1, "many old peers produce one channel announcement")
    c.tick(10)
    receive(c, "1.0.0", "PeerAA", "GUILD", "Q")
    c.tick(4)
    check(len(packets(c, "V")) == 1, "reply cooldown limits repeated requests")
    c.tick(61)
    receive(c, "1.0.0", "Fresh", "GUILD", "Q")
    check(len(list(c.a.versionState.peers.items())) == 1, "expired version peer history releases capacity")

    c = Client()
    c.g.raid = False
    c.log.clear()
    c.tick(5)
    c.call("RequestPeerVersions", True)
    check(not packets(c) and len(c.events("print")) == 1 and not c.a.versionFrame.IsShown(c.a.versionFrame), "solo check explains peer availability without claiming GitHub is up to date")
    check(not c.a.updateNoticePrinted, "no newer peer leaves automatic notification available")
    c = Client()
    receive(c, future)
    c.tick(4)
    check(c.a.updateNoticePrinted, "a fresh login can notify again")
    c = Client()
    c.log.clear()
    c.g.SirusChatWheelUpdateStatus = c.lua.table_from({"repository": "mosf1c/SirusChatWheel", "state": "ok", "version": future, "checkedAt": c.g.time()})
    c.call("ShowUpdateStatus", True)
    receive(c, "2.0.0")
    c.tick(4)
    check(len(c.events("print")) == 2, "a prior automatic GitHub cache notice suppresses a second automatic peer notice")


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
            check(not any(name.startswith("SirusChatWheel/Sounds/") for name in archive.namelist()), "player ZIP excludes duplicate author audio")
            check(not any(name in archive.namelist() for name in ["SirusChatWheel/SoundNames.json", "SirusChatWheel/Update-Sounds.cmd", "SirusChatWheel/Watch-Sounds.cmd"]), "author names and catalog helpers stay in source checkout")
            check("SirusChatWheel/ReleaseInfo.json" in archive.namelist(), "player package identifies its ready catalog")
            check(sum(name.startswith("SirusChatWheel/Media/Cache/") for name in archive.namelist()) == BASE_SOUND_COUNT, "player ZIP has one ready file per sound")
            archive.extractall(addons)
        target = addons / "SirusChatWheel"
        c = Client(root=target)
        check(c.a.ready and len(c.a.soundList) == BASE_SOUND_COUNT, "fresh user installs by copying without running scripts")
        check(not (target / "Sounds").exists(), "fresh installation contains no second audio folder")
        cat, dog = c.a.soundByFile["cat.wav"], c.a.soundByFile["dog.wav"]
        saved = game / "WTF/Account/example/SavedVariables/SirusChatWheel.lua"
        saved.parent.mkdir(parents=True)
        saved.write_text('SirusChatWheelDB = {channel="SAY",scale=1.2,sensitivity=1.3,deadzone=20,bindingInitialized=true,'
            'slots={{kind="sound",id="' + cat + '"},{kind="text",text="KEEP"},{kind="sound",id="' + dog + '"}},'
            'mutedPlayers={["sender-neverestx3"]="Sender-Neverestx3"},soundUses={1700000090,1700000095}}', encoding="utf-8")
        saved_bytes = saved.read_bytes()
        config = target / "UpdateConfig.json"
        config.write_bytes(b'{"repository":"user/repo"}')
        # Reproduce legacy files left by copying over a release from before 1.5.1.
        (target / "Sounds").mkdir()
        shutil.copy2(source / "Sounds/Dog.wav", target / "Sounds/Dog.wav")
        (target / "Update-Sounds.cmd").write_text("legacy helper", encoding="utf-8")
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
            check(sum(name.startswith("SirusChatWheel/Media/Cache/") for name in archive.namelist()) == BASE_SOUND_COUNT + 2, "new publisher WAV and MP3 files enter the ZIP once as ready cache")
            check(not any(name.startswith("SirusChatWheel/Sounds/") for name in archive.namelist()), "updates do not reintroduce duplicate audio sources")
            check(not any("ignore.exe" in name for name in archive.namelist()), "non-audio files are excluded")
            archive.extractall(addons)  # Ordinary copy with replacement; no helper runs.
        c = Client(root=target, saved_path=saved)
        check(c.a.ready and len(c.a.soundList) == BASE_SOUND_COUNT + 2, "copying a new ZIP immediately exposes the new sound set")
        check(c.a.db.slots[1].kind == "sound" and c.a.db.slots[1].id == cat, "existing sound sector keeps its stable file ID")
        check(c.call("GetSlotText", 1) == "Обновлённый кот", "new title and audio content replace the old release")
        check(c.a.db.slots[2].text == "KEEP" and c.a.db.slots[3].id == dog, "other sector assignments survive copying")
        check(c.a.db.channels.SAY and not c.a.db.channels.RAID and c.a.db.scale == 1.2 and c.a.db.sensitivity == 1.3 and c.a.db.deadzone == 20, "channel and wheel settings survive copying")
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
        blocked = subprocess.run([str(PS), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(target / "SoundCatalog.ps1")], capture_output=True, env=env)
        check(blocked.returncode != 0, "legacy catalog rebuild helper is blocked inside ready player package")
        check((target / "Catalog.lua").read_bytes() == catalog_bytes, "legacy source leftovers cannot replace the ready release catalog")
        # A one-time clean folder replacement removes legacy duplicates while
        # account settings stay outside AddOns and load into the new package.
        legacy = (game / "old-addon").resolve()
        check(target.resolve().is_relative_to(addons.resolve()) and legacy.is_relative_to(game.resolve()), "clean replacement paths stay inside the temporary test game")
        target.rename(legacy)
        with zipfile.ZipFile(release) as archive:
            archive.extractall(addons)
        clean = Client(root=target, saved_path=saved)
        check(clean.a.ready and not (target / "Sounds").exists(), "clean replacement removes old source audio folder")
        check(clean.a.db.slots[1].id == cat and clean.a.db.slots[2].text == "KEEP" and clean.a.db.slots[3].kind == "empty", "clean replacement restores sector assignments and excludes removed sound")
        check(clean.call("IsPlayerMuted", "Sender") and len(clean.a.db.soundUses) == 2, "clean replacement restores mutes and rate limit")
        check(saved.read_bytes() == saved_bytes and clean.a.db.channels.SAY and not clean.a.db.channels.RAID, "clean replacement leaves WTF file and channel intact")


if __name__ == "__main__":
    # A source checkout intentionally excludes generated installation files.
    # Create only missing defaults; preserve an existing working installation.
    if not (ADDON / "Catalog.lua").exists():
        run_catalog(ADDON)
    if not (ADDON / "UpdateStatus.lua").exists():
        (ADDON / "UpdateStatus.lua").write_text("SirusChatWheelUpdateStatus = {}\n", encoding="utf-8")
    for test in (test_base, test_context_modes, test_option_actions, test_player_mutes, test_sirus_realms, test_sound_messages, test_bounded_history, test_limits_and_network, test_delayed_say, test_send_failure, test_catalog, test_updates, test_peer_versions, test_full_release_copy):
        try:
            test()
        except Exception as error:
            check(False, f"{test.__name__}: {error}")
    print(f"{checks - len(failures)}/{checks} checks passed; {len(failures)} failures")
    sys.exit(bool(failures))
