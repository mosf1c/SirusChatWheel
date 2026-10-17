-- WoW 3.3.5a / Lua 5.1. No runtime libraries required.
SirusChatWheel = {}
local A = SirusChatWheel
A.version = "1.2.4"
A.binding = "SIRUSCHATWHEEL_HOLD"
A.media = "Interface\\AddOns\\SirusChatWheel\\Media\\"
A.speakerMarkup = "|T" .. A.media .. "Speaker.tga:18:18:0:0|t "
A.directions = { "Вверх", "Вверх-вправо", "Вправо", "Вниз-вправо",
    "Вниз", "Вниз-влево", "Влево", "Вверх-влево" }
A.textChoices = {
    "Хорошо сыграно!", "Спасибо!", "Прошу прощения", "Подтверждаю",
    "Не сдавайтесь!", "Тяжелый пул", "Помогите!", "Назад!", "Атакуем!",
    "Закончилась мана", "Полечите", "GG, WP!",
}
A.defaults = {
    channel = "RAID", fallbackSay = false, hideCursor = true, receiveSounds = true,
    scale = 1, sensitivity = 1, deadzone = 16, dim = 0.16,
}

function A:Copy(source)
    local result = {}
    for key, value in pairs(source) do
        result[key] = type(value) == "table" and self:Copy(value) or value
    end
    return result
end

local function Clamp(value, low, high, fallback)
    value = tonumber(value)
    if not value or value ~= value then return fallback end
    return math.max(low, math.min(high, value))
end

function A:LimitUTF8(text, maxBytes)
    if #text <= maxBytes then return text end
    local finish = maxBytes
    while finish > 0 do
        local nextByte = string.byte(text, finish + 1)
        if not nextByte or nextByte < 128 or nextByte >= 192 then break end
        finish = finish - 1
    end
    return string.sub(text, 1, finish)
end

function A:CleanPhrase(text)
    if type(text) ~= "string" then return "" end
    text = string.gsub(text, "[%z\1-\31\127]", " ")
    text = string.gsub(text, "|", "")
    text = string.gsub(text, "^%s+", "")
    text = string.gsub(text, "%s+$", "")
    return self:LimitUTF8(text, 240)
end

function A:DefaultSlots()
    local texts = { "Атакуем!", "Хорошо сыграно!", "Подтверждаю", "Полечите",
        "Назад!", "Закончилась мана", "", "" }
    local slots = {}
    for i = 1, 8 do slots[i] = { kind = texts[i] == "" and "empty" or "text", text = texts[i] } end
    for index, file in pairs({ [7] = "cat.wav", [8] = "dog.wav" }) do
        local id = self.soundByFile and self.soundByFile[file]
        if id then slots[index] = { kind = "sound", id = id } end
    end
    return slots
end

function A:NormalizeSlot(slot)
    if type(slot) ~= "table" then return { kind = "empty" } end
    if slot.kind == "sound" then
        if self.clips and self.clips[slot.id] then return { kind = "sound", id = slot.id } end
        return { kind = "empty" } -- missing/renamed sound never falls back to old text
    end
    if slot.kind == "text" then
        local text = self:CleanPhrase(slot.text)
        return { kind = text == "" and "empty" or "text", text = text }
    end
    return { kind = "empty" }
end

function A:Normalize(source)
    local db = type(source) == "table" and self:Copy(source) or {}
    db.channel = db.channel == "SAY" and "SAY" or "RAID"
    for _, key in ipairs({ "fallbackSay", "hideCursor", "receiveSounds" }) do
        if db[key] == nil then db[key] = self.defaults[key] end
        db[key] = db[key] == true
    end
    db.scale = Clamp(db.scale, 0.65, 1.4, 1)
    db.sensitivity = Clamp(db.sensitivity, 0.5, 3, 1)
    db.deadzone = Clamp(db.deadzone, 6, 40, 16)
    db.dim = Clamp(db.dim, 0, 0.6, 0.16)
    local defaults = self:DefaultSlots()
    if type(db.slots) ~= "table" then
        db.slots = {}
        local phrases = type(db.phrases) == "table" and db.phrases or nil
        local sounds = type(db.sounds) == "table" and db.sounds or nil
        for i = 1, 8 do
            local oldSound = sounds and sounds[i]
            if oldSound and oldSound ~= "" then
                local file = oldSound == "cat" and "cat.wav" or oldSound == "dog" and "dog.wav" or nil
                local id = file and self.soundByFile[file]
                db.slots[i] = id and { kind = "sound", id = id } or { kind = "empty" }
            elseif phrases and phrases[i] ~= nil then
                db.slots[i] = { kind = "text", text = phrases[i] }
            else db.slots[i] = defaults[i] end
        end
    end
    for i = 1, 8 do db.slots[i] = self:NormalizeSlot(db.slots[i]) end
    db.phrases, db.sounds = nil, nil
    local uses, now = {}, time()
    if type(db.soundUses) == "table" then
        for _, at in ipairs(db.soundUses) do
            if type(at) == "number" and at <= now and now - at < 30 then table.insert(uses, at) end
        end
    end
    db.soundUses = uses
    db.schema = 3
    return db
end

function A:GetSlotText(index, db)
    db = db or self.db
    local slot = db and db.slots and db.slots[index]
    if not slot then return "" end
    if slot.kind == "sound" then return self.clips[slot.id] and self.clips[slot.id].title or "" end
    return slot.kind == "text" and slot.text or ""
end

function A:IsSoundSlot(index, db)
    db = db or self.db
    local slot = db and db.slots and db.slots[index]
    return slot and slot.kind == "sound" and self.clips[slot.id] ~= nil or false
end

function A:SlotMarkup(index, db, maxBytes)
    local text = self:GetSlotText(index, db)
    if maxBytes then text = self:LimitUTF8(text, maxBytes) end
    if text == "" then return "" end
    return (self:IsSoundSlot(index, db) and self.speakerMarkup or "") .. text
end

function A:Print(message)
    if DEFAULT_CHAT_FRAME then DEFAULT_CHAT_FRAME:AddMessage("|cffefd38dSirus Chat Wheel:|r " .. tostring(message)) end
end

function A:ShowError(message)
    if UIErrorsFrame then UIErrorsFrame:AddMessage(message, 1, 0.12, 0.12, 1, 4)
    else self:Print(message) end
end

function A:ResolveChannel()
    if self.db.channel == "SAY" then return "SAY" end
    if GetNumRaidMembers() > 0 then return "RAID" end
    if self.db.fallbackSay then return "SAY" end
    return nil
end

function A:ChannelLabel(channel)
    return channel == "RAID" and "Рейд /raid" or "Сказать /say"
end

local function Atan2(y, x)
    if math.atan2 then return math.atan2(y, x) end
    if x > 0 then return math.atan(y / x) end
    if x < 0 then return math.atan(y / x) + (y >= 0 and math.pi or -math.pi) end
    if y > 0 then return math.pi / 2 end
    if y < 0 then return -math.pi / 2 end
    return 0
end

function A:GetSector(dx, dy, deadzone)
    if dx * dx + dy * dy < deadzone * deadzone then return nil end
    local angle = (Atan2(dx, dy) + 2 * math.pi) % (2 * math.pi)
    return math.floor((angle + math.pi / 8) / (math.pi / 4)) % 8 + 1
end

function A:SendPhrase(index)
    if type(index) ~= "number" or index % 1 ~= 0 or index < 1 or index > 8 then return false end
    local text = self:GetSlotText(index)
    if text == "" then return false end
    if self:IsSoundSlot(index) then return self:SendSound(self.db.slots[index].id) end
    local channel = self:ResolveChannel()
    if not channel then self:ShowError("Вы не в рейде. Выберите /say или включите /say вне рейда."); return false end
    local now = GetTime()
    if self.lastTextSent and now - self.lastTextSent < 0.8 then return false end
    local ok, err = pcall(SendChatMessage, self:CleanPhrase(text), channel)
    if not ok then self:Print("Ошибка отправки: " .. tostring(err)); return false end
    self.lastTextSent = now
    return true
end

function A:BindY(quiet)
    if InCombatLockdown() then
        self.pendingBind = true
        if not quiet then self:Print("Клавиша Y будет назначена после боя.") end
        return false
    end
    local previous = GetBindingAction("Y")
    local success = SetBinding("Y", self.binding)
    if success then
        if self.db.previousY == nil then self.db.previousY = previous or "" end
        SaveBindings(GetCurrentBindingSet())
        self.db.bindingInitialized = true
        self.pendingBind = nil
        if not quiet then self:Print("Y назначена на колесо чата.") end
    else self:Print("Не удалось назначить Y. Используйте «Назначение клавиш».") end
    return success and true or false
end

function A:HandleKey(state)
    if not self.ready then return end
    if state == "down" then
        if self.held then return end
        if GetCurrentKeyBoardFocus and GetCurrentKeyBoardFocus() then return end
        self.held = true
        if not self.active then self:OpenWheel(false) end
    elseif state == "up" then
        self.held = false
        if self.active then self:CloseWheel(true) end
    end
end
