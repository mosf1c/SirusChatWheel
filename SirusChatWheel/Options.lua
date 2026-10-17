local A = SirusChatWheel
local panel, pages, selectors, listenButtons, checks, sliders
local picker, scroll, rows
local rowHeight, visibleRows = 24, 16

local function Text(parent, text, x, y, width, font)
    local label = parent:CreateFontString(nil, "ARTWORK", font or "GameFontHighlightSmall")
    label:SetPoint("TOPLEFT", parent, "TOPLEFT", x, y)
    label:SetWidth(width)
    label:SetJustifyH("LEFT")
    label:SetText(text)
    return label
end

local function Button(parent, text, width, name)
    local button = CreateFrame("Button", name, parent, "UIPanelButtonTemplate")
    button:SetWidth(width); button:SetHeight(24); button:SetText(text)
    return button
end

local function Check(parent, suffix, label, y, callback)
    local check = CreateFrame("CheckButton", "SirusChatWheel" .. suffix, parent, "UICheckButtonTemplate")
    check:SetWidth(24); check:SetHeight(24)
    check:SetPoint("TOPLEFT", parent, "TOPLEFT", 0, y)
    _G[check:GetName() .. "Text"]:SetText(label)
    _G[check:GetName() .. "Text"]:SetFontObject(GameFontHighlightSmall)
    check:SetScript("OnClick", callback)
    return check
end

local function Slider(parent, key, title, y, low, high, step, format)
    local name = "SirusChatWheelSlider" .. key
    local slider = CreateFrame("Slider", name, parent, "OptionsSliderTemplate")
    slider:SetPoint("TOPLEFT", parent, "TOPLEFT", 8, y)
    slider:SetWidth(270); slider:SetHeight(16)
    slider:SetMinMaxValues(low, high); slider:SetValueStep(step)
    _G[name .. "Low"]:SetText(tostring(low)); _G[name .. "High"]:SetText(tostring(high))
    slider:SetScript("OnValueChanged", function(_, value)
        if type(value) ~= "number" then return end
        value = math.floor(value / step + 0.5) * step
        _G[name .. "Text"]:SetText(title .. ": " .. string.format(format, value))
        if not panel.loading and panel.draft then panel.draft[key] = value end
    end)
    return slider
end

function A:BuildPickerEntries()
    local entries = { { heading = "Текстовые фразы" } }
    for _, text in ipairs(self.textChoices) do table.insert(entries, { kind = "text", text = text }) end
    table.insert(entries, { heading = "Голосовые записи (" .. #self.soundList .. ")" })
    for _, clip in ipairs(self.soundList) do table.insert(entries, { kind = "sound", id = clip.id, text = clip.title }) end
    return entries
end

function A:RefreshPicker()
    if not picker or not picker.entries then return end
    FauxScrollFrame_Update(scroll, #picker.entries, visibleRows, rowHeight)
    local offset = FauxScrollFrame_GetOffset(scroll) or 0
    for i = 1, visibleRows do
        local row = rows[i]
        local entry = picker.entries[offset + i]
        row.entry = entry
        if not entry then row:Hide()
        else
            row:Show()
            if entry.heading then
                row.label:SetText(entry.heading); row.label:SetTextColor(1, 0.82, 0.35); row:Disable()
            else
                row:Enable()
                row.label:SetText((entry.kind == "sound" and self.speakerMarkup or "") .. entry.text)
                row.label:SetTextColor(0.96, 0.96, 0.98)
            end
        end
    end
end

function A:ScrollPicker(delta)
    local bar = _G[scroll:GetName() .. "ScrollBar"]
    bar:SetValue(bar:GetValue() - delta * rowHeight * 3)
end

function A:SelectSlot(index, selection)
    if not panel or not panel.draft or type(index) ~= "number" or index < 1 or index > 8 then return end
    panel.draft.slots[index] = self:NormalizeSlot(selection)
    self:UpdateSlotControl(index)
    if picker then picker:Hide() end
    panel.status:SetText("Нажми «Сохранить», чтобы применить выбор.")
end

function A:CreatePicker()
    picker = CreateFrame("Frame", "SirusChatWheelPicker", UIParent)
    picker:SetWidth(340); picker:SetHeight(424)
    picker:SetFrameStrata("DIALOG"); picker:SetFrameLevel(120)
    picker:SetClampedToScreen(true); picker:EnableMouse(true)
    picker:EnableMouseWheel(true)
    picker:SetScript("OnMouseWheel", function(_, delta) A:ScrollPicker(delta) end)
    picker:SetBackdrop({ bgFile = "Interface\\DialogFrame\\UI-DialogBox-Background",
        edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border", tile = true, tileSize = 16, edgeSize = 12,
        insets = { left = 4, right = 4, top = 4, bottom = 4 } })
    picker:Hide(); self.picker = picker
    tinsert(UISpecialFrames, "SirusChatWheelPicker")
    Text(picker, "Выбор фразы", 12, -11, 200, "GameFontNormal")
    local clear = Button(picker, "Очистить", 85)
    clear:SetHeight(20); clear:SetPoint("TOPRIGHT", picker, "TOPRIGHT", -12, -7)
    clear:SetScript("OnClick", function() A:SelectSlot(picker.index, { kind = "empty" }) end)
    scroll = CreateFrame("ScrollFrame", "SirusChatWheelPickerScroll", picker, "FauxScrollFrameTemplate")
    scroll:SetPoint("TOPLEFT", picker, "TOPLEFT", 10, -32)
    scroll:SetPoint("BOTTOMRIGHT", picker, "BOTTOMRIGHT", -32, 8)
    scroll:SetScript("OnVerticalScroll", function(self, offset)
        FauxScrollFrame_OnVerticalScroll(self, offset, rowHeight, function() A:RefreshPicker() end)
    end)
    rows = {}
    self.pickerRows = rows
    for i = 1, visibleRows do
        local row = CreateFrame("Button", "SirusChatWheelPickerRow" .. i, picker)
        row:SetWidth(292); row:SetHeight(rowHeight)
        row:EnableMouseWheel(true)
        row:SetScript("OnMouseWheel", function(_, delta) A:ScrollPicker(delta) end)
        row:SetPoint("TOPLEFT", picker, "TOPLEFT", 12, -32 - (i - 1) * rowHeight)
        local highlight = row:CreateTexture(nil, "HIGHLIGHT")
        highlight:SetAllPoints(row); highlight:SetTexture(1, 1, 1, 0.12)
        row.label = row:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
        row.label:SetPoint("LEFT", row, "LEFT", 5, 0)
        row.label:SetWidth(279); row.label:SetHeight(20)
        row.label:SetJustifyH("LEFT"); row.label:SetWordWrap(false)
        row:SetScript("OnClick", function(self)
            local entry = self.entry
            if entry and not entry.heading then A:SelectSlot(picker.index, entry) end
        end)
        rows[i] = row
    end
    picker:SetScript("OnHide", function() picker.index = nil end)
end

function A:OpenPicker(index)
    if picker:IsShown() and picker.index == index then picker:Hide(); return end
    picker.index = index; picker.entries = self:BuildPickerEntries()
    picker:ClearAllPoints(); picker:SetPoint("TOPLEFT", selectors[index], "BOTTOMLEFT", 0, -2)
    FauxScrollFrame_SetOffset(scroll, 0)
    local scrollbar = _G[scroll:GetName() .. "ScrollBar"]
    scrollbar:SetValue(0)
    picker:Show(); self:RefreshPicker()
end

function A:UpdateSlotControl(index)
    local markup = self:SlotMarkup(index, panel.draft, 180)
    selectors[index].label:SetText(markup == "" and "Пустой слот" or markup)
    selectors[index].label:SetTextColor(markup == "" and 0.5 or 0.96, markup == "" and 0.5 or 0.96, markup == "" and 0.5 or 0.98)
    if self:IsSoundSlot(index, panel.draft) then listenButtons[index]:Enable() else listenButtons[index]:Disable() end
end

function A:RefreshOptions()
    if not panel then return end
    panel.loading = true
    panel.draft = self:Copy(panel.defaultDraft or self.db)
    for i = 1, 8 do self:UpdateSlotControl(i) end
    checks.raid:SetChecked(panel.draft.channel == "RAID"); checks.say:SetChecked(panel.draft.channel == "SAY")
    checks.fallback:SetChecked(panel.draft.fallbackSay); checks.hide:SetChecked(panel.draft.hideCursor)
    checks.receive:SetChecked(panel.draft.receiveSounds)
    for key, slider in pairs(sliders) do slider:SetValue(panel.draft[key]) end
    panel.loading = false
    panel.bindingText:SetText("Клавиша: " .. (GetBindingKey(self.binding) or "не назначена"))
    self:RefreshPlayers()
end

function A:ApplyOptions()
    if not panel or not panel.draft then return end
    panel.draft.bindingInitialized = self.db.bindingInitialized
    panel.draft.previousY = self.db.previousY
    panel.draft.soundUses = self:Copy(type(self.db.soundUses) == "table" and self.db.soundUses or {})
    -- Player mutes apply immediately, independently of the settings draft.
    panel.draft.mutedPlayers = self:Copy(self.db.mutedPlayers)
    self.db = self:Normalize(panel.draft); SirusChatWheelDB = self.db
    self.cursorUnavailable, self.soundErrorPrinted, panel.defaultDraft = nil, nil, nil
    if picker then picker:Hide() end
    self:RefreshOptions(); panel.status:SetText("Настройки сохранены.")
end

function A:CreateOptions()
    panel = CreateFrame("Frame", "SirusChatWheelOptions", UIParent)
    panel.name = "Sirus Chat Wheel"; panel:Hide(); self.options = panel
    Text(panel, "Sirus Chat Wheel", 16, -16, 370, "GameFontNormalLarge")
    Text(panel, "Нажми на фразу и выбери текст или голосовую запись.", 16, -42, 380)
    pages, selectors, listenButtons, checks, sliders = {}, {}, {}, {}, {}
    self.selectors = selectors
    local tabs, titles = {}, { "Фразы", "Параметры", "Звуки", "Игроки" }
    self.optionTabs = tabs
    for i = 1, #titles do
        pages[i] = CreateFrame("Frame", nil, panel)
        pages[i]:SetPoint("TOPLEFT", panel, "TOPLEFT", 16, -105)
        pages[i]:SetPoint("BOTTOMRIGHT", panel, "BOTTOMRIGHT", -16, 54)
        tabs[i] = Button(panel, titles[i], 90)
        tabs[i]:SetPoint("TOPLEFT", panel, "TOPLEFT", 16 + (i - 1) * 96, -68)
        local index = i
        tabs[i]:SetScript("OnClick", function()
            for j = 1, #titles do
                if j == index then pages[j]:Show(); tabs[j]:Disable() else pages[j]:Hide(); tabs[j]:Enable() end
            end
            if picker then picker:Hide() end
        end)
    end
    pages[2]:Hide(); pages[3]:Hide(); pages[4]:Hide(); tabs[1]:Disable()
    for i = 1, 8 do
        local index = i; local y = -(i - 1) * 31
        Text(pages[1], i .. ". " .. self.directions[i], 0, y - 6, 110)
        local selector = Button(pages[1], "", 220, "SirusChatWheelSlot" .. i)
        selector:SetPoint("TOPLEFT", pages[1], "TOPLEFT", 126, y)
        selector.label = selector:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
        selector.label:SetPoint("LEFT", selector, "LEFT", 8, 0)
        selector.label:SetWidth(187); selector.label:SetHeight(20); selector.label:SetJustifyH("LEFT")
        selector.label:SetWordWrap(false)
        local arrow = selector:CreateTexture(nil, "OVERLAY")
        arrow:SetTexture("Interface\\Buttons\\UI-ScrollBar-ScrollDownButton-Up")
        arrow:SetWidth(16); arrow:SetHeight(16); arrow:SetPoint("RIGHT", selector, "RIGHT", -4, 0)
        selector:SetScript("OnClick", function() A:OpenPicker(index) end)
        selectors[i] = selector
        local listen = Button(pages[1], ">", 25, "SirusChatWheelListen" .. i)
        listen:SetPoint("TOPLEFT", pages[1], "TOPLEFT", 351, y)
        listen:SetScript("OnClick", function()
            local slot = panel.draft.slots[index]
            if slot.kind == "sound" then A:QueueClip(slot.id, false) end
        end)
        listenButtons[i] = listen
    end
    Text(pages[1], "Значок динамика — голосовая запись. Кнопка > — прослушать без отправки.", 0, -248, 370, "GameFontDisableSmall")
    checks.raid = Check(pages[2], "ChannelRaid", "Рейд (/raid)", 0, function()
        panel.draft.channel = "RAID"; checks.raid:SetChecked(true); checks.say:SetChecked(false)
    end)
    checks.say = Check(pages[2], "ChannelSay", "Сказать (/say)", -28, function()
        panel.draft.channel = "SAY"; checks.say:SetChecked(true); checks.raid:SetChecked(false)
    end)
    checks.fallback = Check(pages[2], "FallbackSay", "Вне рейда отправлять в /say", -58, function(self) panel.draft.fallbackSay = self:GetChecked() and true or false end)
    checks.hide = Check(pages[2], "HideCursor", "Скрывать обычный курсор при выборе", -86, function(self) panel.draft.hideCursor = self:GetChecked() and true or false end)
    checks.receive = Check(pages[2], "ReceiveSounds", "Воспроизводить звуки других игроков", -114, function(self) panel.draft.receiveSounds = self:GetChecked() and true or false end)
    sliders.scale = Slider(pages[2], "scale", "Размер колеса", -154, 0.65, 1.4, 0.05, "%.2f")
    sliders.sensitivity = Slider(pages[2], "sensitivity", "Чувствительность мыши", -197, 0.5, 3, 0.1, "%.1f")
    sliders.deadzone = Slider(pages[2], "deadzone", "Зона отмены в центре", -240, 6, 40, 1, "%.0f")
    local bind = Button(pages[2], "Назначить Y", 100)
    bind:SetPoint("TOPRIGHT", pages[2], "TOPRIGHT", -3, -155)
    bind:SetScript("OnClick", function() A:BindY(false); panel.bindingText:SetText("Клавиша: " .. (GetBindingKey(A.binding) or "не назначена")) end)
    Text(pages[2], "Y заменит\nтекущее\nназначение.", 295, -188, 76, "GameFontDisableSmall")
    Text(pages[3], "Голосовые записи", 0, 0, 370, "GameFontNormal")
    Text(pages[3], "Все звуки уже входят в полный архив аддона.\n\nЧтобы получить новые записи, закрой игру и скопируй папку SirusChatWheel из нового выпуска в Interface\\AddOns с заменой файлов.\n\nПосле запуска игры выбери новую запись на вкладке «Фразы».", 0, -30, 365)
    Text(pages[3], "Настройки секторов сохраняются в WTF. Запись, исключённая из нового выпуска, оставляет пустой слот.\n\nЛимит: 2 звука за 30 с. Для совместного воспроизведения у игроков должны быть одинаковые файлы.", 0, -182, 365, "GameFontDisableSmall")
    local apply = Button(panel, "Сохранить", 115)
    apply:SetPoint("BOTTOMLEFT", panel, "BOTTOMLEFT", 16, 14); apply:SetScript("OnClick", function() A:ApplyOptions() end)
    local preview = Button(panel, "Проверить колесо", 145)
    preview:SetPoint("BOTTOMLEFT", panel, "BOTTOMLEFT", 139, 14)
    preview:SetScript("OnClick", function() A:ApplyOptions(); A.held = false; A:OpenWheel(true) end)
    panel.status = Text(panel, "", 0, 0, 380, "GameFontDisableSmall")
    panel.status:ClearAllPoints(); panel.status:SetPoint("BOTTOMLEFT", panel, "BOTTOMLEFT", 16, 43)
    panel.bindingText = Text(panel, "", 0, 0, 380, "GameFontDisableSmall")
    panel.bindingText:ClearAllPoints(); panel.bindingText:SetPoint("BOTTOMLEFT", panel, "BOTTOMLEFT", 16, 0)
    panel.okay = function() A:ApplyOptions() end
    panel.cancel = function() panel.defaultDraft = nil; A:RefreshOptions(); panel.status:SetText("") end
    panel.refresh = function() A:RefreshOptions(); panel.status:SetText("") end
    panel.default = function()
        local defaults = A:Copy(A.defaults)
        defaults.bindingInitialized, defaults.previousY = A.db.bindingInitialized, A.db.previousY
        panel.defaultDraft = A:Normalize(defaults); A:RefreshOptions()
    end
    panel:SetScript("OnHide", function() if picker then picker:Hide() end end)
    self:CreatePlayersPage(pages[4])
    self:CreatePicker(); self:RefreshOptions(); InterfaceOptions_AddCategory(panel)
end

function A:OpenOptions()
    if not self.ready then return end
    self:CloseWheel(false); self.held = false
    InterfaceOptionsFrame_OpenToCategory(panel); InterfaceOptionsFrame_OpenToCategory(panel)
end
