-- Deterministic API stand-in: this does not render or run the Sirus client.
now, epoch, player = 100, 1700000000, "Sender"
cursorX, cursorY, focus, combat, raid = 400, 300, nil, false, true
frames, UISpecialFrames, SlashCmdList = {}, {}, {}
tinsert = table.insert
local methods = {}
local function widget(name, parent, kind)
    local w = { name = name, parent = parent, kind = kind, shown = true,
        scripts = {}, events = {}, children = {}, points = {}, scale = 1 }
    setmetatable(w, { __index = methods })
    if name then _G[name] = w end
    if parent then table.insert(parent.children, w) end
    table.insert(frames, w)
    return w
end
function methods:GetName() return self.name end
function methods:SetScript(event, fn) self.scripts[event] = fn end
function methods:RegisterEvent(event) self.events[event] = true end
function methods:UnregisterEvent(event) self.events[event] = nil end
function methods:Show() self.shown = true end
function methods:Hide()
    local was = self.shown; self.shown = false
    if was and self.scripts.OnHide then self.scripts.OnHide(self) end
end
function methods:IsShown() return self.shown end
function methods:GetEffectiveScale() return self.scale end
function methods:GetFont() return self.font or "mock.ttf", self.size or 16, "" end
function methods:SetFont(font, size) self.font, self.size = font, size end
function methods:SetText(text) self.text = text end
function methods:GetText() return self.text or "" end
function methods:SetAutoFocus(value) self.autoFocus = value end
function methods:SetMaxLetters(value) self.maxLetters = value end
function methods:ClearFocus() focus = nil end
function methods:SetTexture(...) self.texture = {...} end
function methods:SetPoint(...) self.points[#self.points + 1] = {...} end
function methods:ClearAllPoints() self.points = {} end
function methods:SetWidth(value) self.width = value end
function methods:SetHeight(value) self.height = value end
function methods:SetScale(value) self.scale = value end
function methods:SetAlpha(value) self.alpha = value end
function methods:SetTextColor(...) self.color = {...} end
function methods:SetChecked(value) self.checked = value end
function methods:GetChecked() return self.checked end
function methods:Enable() self.disabled = false end
function methods:Disable() self.disabled = true end
function methods:SetValue(value)
    self.value = math.max(0, math.min(self.max or 10000, value))
    if self.scripts.OnValueChanged then self.scripts.OnValueChanged(self, self.value) end
end
function methods:GetValue() return self.value or 0 end
function methods:SetMinMaxValues(low, high) self.min, self.max = low, high end
function methods:CreateTexture(name) return widget(name, self, "Texture") end
function methods:CreateFontString(name) return widget(name, self, "FontString") end
for _, name in ipairs({"EnableMouse", "EnableMouseWheel", "SetFrameStrata", "SetFrameLevel",
    "SetAllPoints", "SetJustifyH", "SetJustifyV", "SetShadowOffset", "SetShadowColor",
    "SetClampedToScreen", "SetBackdrop", "SetWordWrap", "SetFontObject", "SetValueStep"}) do
    methods[name] = function() end
end
function CreateFrame(kind, name, parent, template)
    local w = widget(name, parent, kind)
    if template == "UICheckButtonTemplate" then widget(name .. "Text", w, "FontString") end
    if template == "OptionsSliderTemplate" then
        for _, suffix in ipairs({"Low", "High", "Text"}) do widget(name .. suffix, w, "FontString") end
    end
    if template == "FauxScrollFrameTemplate" then
        local bar = widget(name .. "ScrollBar", w, "Slider")
        bar:SetScript("OnValueChanged", function(_, value)
            if w.scripts.OnVerticalScroll then w.scripts.OnVerticalScroll(w, value) end
        end)
    end
    return w
end
function FireEvent(event, ...)
    for _, frame in ipairs(frames) do
        if frame.events[event] and frame.scripts.OnEvent then frame.scripts.OnEvent(frame, event, ...) end
    end
end
function Tick(seconds)
    now = now + seconds
    for _, frame in ipairs(frames) do
        if frame.shown and frame.scripts.OnUpdate then frame.scripts.OnUpdate(frame, seconds) end
    end
end
function FauxScrollFrame_Update(frame, count, visible, height)
    _G[frame:GetName() .. "ScrollBar"].max = math.max(0, (count-visible)*height)
end
function FauxScrollFrame_GetOffset(frame) return frame.offset or 0 end
function FauxScrollFrame_SetOffset(frame, value) frame.offset = value end
function FauxScrollFrame_OnVerticalScroll(frame, offset, height, update)
    frame.offset = math.floor(offset / height + 0.5); update()
end
function InterfaceOptions_AddCategory() end
function InterfaceOptionsFrame_OpenToCategory() end
UIParent = widget("UIParent")
GameFontHighlightSmall = widget("GameFontHighlightSmall")
DEFAULT_CHAT_FRAME = { AddMessage = function(_, text) emit("print", text) end }
UIErrorsFrame = { AddMessage = function(_, text, r, g, b) emit("error", text, r, g, b) end }
function GetTime() return now end
function time() return math.floor(epoch + now) end
function GetCursorPosition() return cursorX, cursorY end
function GetCurrentKeyBoardFocus() return focus end
function InCombatLockdown() return combat end
function UnitName(unit) return unit == "player" and player or "Receiver" end
function GetRealmName() return "Sirus" end
function GetNumRaidMembers() return raid and 2 or 0 end
function GetRaidRosterInfo(i) return i == 1 and "Sender" or "Receiver" end
function GetNumPartyMembers() return 0 end
function GetBindingAction() return binding or "TOGGLEACHIEVEMENT" end
function SetBinding(_, value) binding = value; return true end
function SaveBindings() end
function GetCurrentBindingSet() return 1 end
function GetBindingKey() return binding and "Y" or nil end
function SetCursor(path) cursor = path; return true end
function ResetCursor() cursor = nil end
function CursorHasItem() return false end
function SpellIsTargeting() return false end
function IsMouselooking() return false end
function IsMouseButtonDown() return false end
function PlaySoundFile(path) emit("play", path); return true end
function SendChatMessage(text, channel) emit("chat", text, channel) end
function SendAddonMessage(prefix, packet, channel, target) emit("packet", prefix, packet, channel, target) end
