local A = SirusChatWheel
local cyrillicLower = {}
for upper, lower in string.gmatch("АаБбВвГгДдЕеЁёЖжЗзИиЙйКкЛлМмНнОоПпРрСсТтУуФфХхЦцЧчШшЩщЪъЫыЬьЭэЮюЯя", "(..)(..)") do
    cyrillicLower[upper] = lower
end

local function Lower(text)
    -- Lower only ASCII bytes before mapping UTF-8 Cyrillic. The host C locale
    -- must never lowercase individual bytes inside a multi-byte character.
    text = string.gsub(text, "[A-Z]", string.lower)
    return string.gsub(text, "[\194-\244][\128-\191]+", cyrillicLower)
end

function A:NormalizeRealm(value)
    if type(value) ~= "string" or #value > 100 or string.find(value, "[%z\1-\31\127|]") then return end
    local realm = string.gsub(value, "%s+", " ")
    realm = string.match(realm, "^%s*(.-)%s*$")
    -- Connection labels and the client build are not separate game worlds.
    realm = string.gsub(realm, "%s*%-%s*%d+%.%d+%.%d+[%w%.%+%-]*$", "")
    local route = string.match(Lower(realm), "^proxy[%w_%-]*%s+")
    if route then
        realm = string.sub(realm, #route + 1)
    elseif string.match(realm, "[xX]%d+$") then
        -- Older saved names removed all spaces, including the route separator.
        for _, prefix in ipairs({ "proxyeu", "proxyru", "proxyus", "proxy" }) do
            if string.sub(Lower(realm), 1, #prefix) == prefix then
                realm = string.sub(realm, #prefix + 1)
                break
            end
        end
    end
    realm = string.match(realm, "^%s*(.-)%s*$")
    realm = string.gsub(realm, "([^%s])[xX](%d+)$", "%1 x%2")
    if realm == "" then return end
    return realm
end

function A:PlayerIdentity(value)
    if type(value) ~= "string" or #value > 150 or string.find(value, "[%z\1-\31\127|]") then return end
    value = string.match(value, "^%s*(.-)%s*$")
    local character, realm = string.match(value, "^([^%-]+)%-(.+)$")
    character = character or value
    if #character == 0 or #character > 48 or not string.match(character, "^[%a\128-\255]+$") then return end
    realm = self:NormalizeRealm(realm or (GetRealmName and GetRealmName()))
    if not realm then return end
    local key = Lower(character) .. "-" .. string.gsub(Lower(realm), "%s+", "")
    -- Keep the realm in saved values so another realm on this account cannot
    -- reinterpret an unqualified nickname after a reload.
    return key, character .. "-" .. realm
end

function A:NormalizeMutedPlayers(source)
    local result = {}
    if type(source) == "table" then
        for _, value in pairs(source) do
            local key, name = self:PlayerIdentity(value)
            if key then result[key] = name end
        end
    end
    return result
end

function A:IsPlayerMuted(name)
    local key = self:PlayerIdentity(name)
    return key and self.db and self.db.mutedPlayers and self.db.mutedPlayers[key] ~= nil or false
end

function A:SetPlayerMuted(name, muted)
    local key, display = self:PlayerIdentity(name)
    if not key then return false, "Укажите ник или Ник-Сервер." end
    if muted and key == self:PlayerIdentity(UnitName("player")) then return false, "Это ваш персонаж." end
    self.db.mutedPlayers[key] = muted and display or nil
    if muted then
        for i = #(self.soundQueue or {}), 1, -1 do
            local entry = self.soundQueue[i]
            if entry.remote and entry.sender == key then table.remove(self.soundQueue, i) end
        end
        for nonce, query in pairs(self.pendingQueries or {}) do
            if query.sender == key then self.pendingQueries[nonce] = nil end
        end
    end
    if self.RefreshPlayers then self:RefreshPlayers() end
    return true, display
end

function A:RememberSpeaker(name, clip)
    local key, display = self:PlayerIdentity(name)
    if not key then return end
    self.recentSpeakers = self.recentSpeakers or {}
    for i = #self.recentSpeakers, 1, -1 do
        if self.recentSpeakers[i].key == key then table.remove(self.recentSpeakers, i) end
    end
    table.insert(self.recentSpeakers, 1, { key = key, name = display, title = clip.title })
    if #self.recentSpeakers > 30 then table.remove(self.recentSpeakers) end
    if self.RefreshPlayers then self:RefreshPlayers() end
end

function A:GetPlayerEntries(mutedOnly)
    if not mutedOnly then return self.recentSpeakers or {} end
    local entries = {}
    for key, name in pairs(self.db.mutedPlayers) do
        table.insert(entries, { key = key, name = name })
    end
    table.sort(entries, function(a, b) return a.key < b.key end)
    return entries
end

local function Label(parent, text, x, y, width, font)
    local label = parent:CreateFontString(nil, "ARTWORK", font or "GameFontHighlightSmall")
    label:SetPoint("TOPLEFT", parent, "TOPLEFT", x, y)
    label:SetWidth(width); label:SetJustifyH("LEFT"); label:SetText(text)
    return label
end

local function Button(parent, text, x, y, width)
    local button = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
    button:SetPoint("TOPLEFT", parent, "TOPLEFT", x, y)
    button:SetWidth(width); button:SetHeight(24); button:SetText(text)
    return button
end

function A:RefreshPlayers()
    local ui = self.playerOptions
    if not ui then return end
    local entries = self:GetPlayerEntries(ui.mutedOnly)
    FauxScrollFrame_Update(ui.scroll, #entries, 5, 30)
    local offset = math.min(FauxScrollFrame_GetOffset(ui.scroll) or 0, math.max(0, #entries - 5))
    FauxScrollFrame_SetOffset(ui.scroll, offset)
    if #entries == 0 then
        ui.empty:SetText(ui.mutedOnly and "Заглушённых игроков нет." or "Здесь появятся отправители голосовых фраз.\nТакже можно добавить ник вручную.")
    else ui.empty:SetText("") end
    for i, row in ipairs(ui.rows) do
        row.entry = entries[offset + i]
        if not row.entry then row:Hide()
        else
            row:Show()
            local muted = self:IsPlayerMuted(row.entry.name)
            row.name:SetText(row.entry.name)
            row.phrase:SetText(row.entry.title or "Звуки отключены")
            row.action:SetText(muted and "Вернуть звук" or "Заглушить")
        end
    end
end

function A:ScrollPlayers(delta)
    local bar = _G[self.playerOptions.scroll:GetName() .. "ScrollBar"]
    bar:SetValue(bar:GetValue() - delta * 30 * 3)
end

function A:CreatePlayersPage(page)
    local ui = { rows = {}, mutedOnly = false }
    self.playerOptions = ui
    Label(page, "Отключить звуки игрока по нику (или Ник-Сервер):", 0, 0, 375)
    ui.input = CreateFrame("EditBox", "SirusChatWheelMuteName", page, "InputBoxTemplate")
    ui.input:SetPoint("TOPLEFT", page, "TOPLEFT", 6, -23)
    ui.input:SetWidth(235); ui.input:SetHeight(24)
    ui.input:SetAutoFocus(false); ui.input:SetMaxLetters(100)
    ui.input:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    ui.add = Button(page, "Заглушить", 250, -23, 122)
    local function AddName()
        local ok, value = A:SetPlayerMuted(ui.input:GetText(), true)
        if ok then
            ui.input:SetText(""); ui.input:ClearFocus()
            A.options.status:SetText("Звуки отключены: " .. value)
        else A.options.status:SetText(value) end
    end
    ui.add:SetScript("OnClick", AddName)
    ui.input:SetScript("OnEnterPressed", AddName)
    ui.recent = Button(page, "Недавние", 0, -57, 180)
    ui.muted = Button(page, "Заглушённые", 190, -57, 182)
    local function SelectList(mutedOnly)
        ui.mutedOnly = mutedOnly
        if mutedOnly then ui.muted:Disable(); ui.recent:Enable()
        else ui.recent:Disable(); ui.muted:Enable() end
        FauxScrollFrame_SetOffset(ui.scroll, 0)
        _G[ui.scroll:GetName() .. "ScrollBar"]:SetValue(0)
        A:RefreshPlayers()
    end
    ui.recent:SetScript("OnClick", function() SelectList(false) end)
    ui.muted:SetScript("OnClick", function() SelectList(true) end)
    ui.recent:Disable()
    ui.scroll = CreateFrame("ScrollFrame", "SirusChatWheelPlayersScroll", page, "FauxScrollFrameTemplate")
    ui.scroll:SetPoint("TOPLEFT", page, "TOPLEFT", 0, -90)
    ui.scroll:SetWidth(350); ui.scroll:SetHeight(150)
    ui.scroll:SetScript("OnVerticalScroll", function(self, offset)
        FauxScrollFrame_OnVerticalScroll(self, offset, 30, function() A:RefreshPlayers() end)
    end)
    ui.empty = Label(page, "", 0, -100, 350, "GameFontDisableSmall")
    for i = 1, 5 do
        local row = CreateFrame("Frame", nil, page)
        row:SetPoint("TOPLEFT", page, "TOPLEFT", 0, -90 - (i - 1) * 30)
        row:SetWidth(350); row:SetHeight(30)
        row:EnableMouseWheel(true)
        row:SetScript("OnMouseWheel", function(_, delta) A:ScrollPlayers(delta) end)
        row.name = Label(row, "", 0, -1, 238)
        row.name:SetHeight(14); row.name:SetWordWrap(false)
        row.phrase = Label(row, "", 0, -16, 238, "GameFontDisableSmall")
        row.phrase:SetHeight(12); row.phrase:SetWordWrap(false)
        row.action = Button(row, "", 242, -2, 108)
        row.action:SetScript("OnClick", function()
            local entry = row.entry
            if not entry then return end
            local muted = not A:IsPlayerMuted(entry.name)
            local ok, value = A:SetPlayerMuted(entry.name, muted)
            if ok then A.options.status:SetText((muted and "Звуки отключены: " or "Звуки включены: ") .. value)
            else A.options.status:SetText(value) end
        end)
        ui.rows[i] = row
    end
    Label(page, "Отключаются только звуки игрока. Его сообщения в чате остаются видимыми.", 0, -247, 375, "GameFontDisableSmall")
    page:SetScript("OnShow", function() A:RefreshPlayers() end)
    self:RefreshPlayers()
end
