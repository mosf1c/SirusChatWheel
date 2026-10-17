local A = SirusChatWheel
local overlay, root, stick
local labels, sectors, speakers = {}, {}, {}
local positions = {
    {0, 127}, {171, 86}, {205, 0}, {171, -86},
    {0, -127}, {-171, -86}, {-205, 0}, {-171, 86},
}

local function Texture(parent, file, width, height, layer)
    local texture = parent:CreateTexture(nil, layer or "ARTWORK")
    texture:SetTexture(A.media .. file)
    texture:SetWidth(width)
    texture:SetHeight(height)
    texture:SetPoint("CENTER", parent, "CENTER", 0, 0)
    return texture
end

function A:RestoreCursor()
    if self.cursorChanged then
        self.cursorChanged = false
        if ResetCursor then pcall(ResetCursor) elseif SetCursor then pcall(SetCursor, nil) end
    end
end

function A:HideWheelCursor()
    if self.db.hideCursor and SetCursor and not self.cursorUnavailable then
        -- A mouse-enabled full-screen frame keeps the pointer off WorldFrame,
        -- whose native hover logic would otherwise override SetCursor.
        local ok, result = pcall(SetCursor, self.media .. "InvisibleCursor.blp")
        if ok and result ~= false then
            self.cursorChanged = true
        else
            self:RestoreCursor()
            self.cursorUnavailable = true
            self:Print("Не удалось скрыть курсор: " .. tostring(result))
        end
    end
end

function A:SampleWheel()
    local x, y = GetCursorPosition()
    local uiScale = UIParent:GetEffectiveScale()
    local dx = (x - self.originX) / uiScale * self.db.sensitivity
    local dy = (y - self.originY) / uiScale * self.db.sensitivity
    local index = self:GetSector(dx, dy, self.db.deadzone)
    if index and self:GetSlotText(index) == "" then index = nil end
    self.selected = index
    return dx, dy
end

function A:UpdateWheelVisual(dx, dy, elapsed)
    local distance = math.sqrt(dx * dx + dy * dy)
    local factor = distance > 57 and 57 / distance or 1
    local targetX, targetY = dx * factor, dy * factor
    local blend = math.min(1, elapsed * 28)
    self.stickX = self.stickX + (targetX - self.stickX) * blend
    self.stickY = self.stickY + (targetY - self.stickY) * blend
    stick:ClearAllPoints()
    stick:SetPoint("CENTER", root, "CENTER", self.stickX, self.stickY)
    for i = 1, 8 do
        if i == self.selected then
            sectors[i]:Show()
            labels[i]:SetTextColor(1, 0.86, 0.48)
        else
            sectors[i]:Hide()
            if self:GetSlotText(i) == "" then
                labels[i]:SetTextColor(0.4, 0.42, 0.46)
            else
                labels[i]:SetTextColor(0.96, 0.96, 0.98)
            end
        end
    end
end

function A:CreateWheel()
    overlay = CreateFrame("Frame", "SirusChatWheelOverlay", UIParent)
    overlay:SetAllPoints(UIParent)
    overlay:SetFrameStrata("FULLSCREEN_DIALOG")
    overlay:SetFrameLevel(100)
    overlay:EnableMouse(true)
    overlay:Hide()
    self.overlay = overlay
    tinsert(UISpecialFrames, "SirusChatWheelOverlay")

    local dim = overlay:CreateTexture(nil, "BACKGROUND")
    dim:SetAllPoints(overlay)
    dim:SetTexture(0, 0, 0, 1)
    self.dimTexture = dim

    root = CreateFrame("Frame", nil, overlay)
    root:SetWidth(640)
    root:SetHeight(416)
    root:SetPoint("CENTER", overlay, "CENTER", 0, 0)
    root:EnableMouse(false)
    self.wheelRoot = root
    Texture(root, "Halo.tga", 330, 330, "BACKGROUND")
    Texture(root, "Ring.tga", 174, 174)
    for i = 1, 8 do
        sectors[i] = Texture(root, "Sector" .. i .. ".tga", 174, 174, "OVERLAY")
        sectors[i]:Hide()
        local label = root:CreateFontString(nil, "OVERLAY", "GameFontHighlightLarge")
        local font, size, flags = label:GetFont()
        if font and size then label:SetFont(font, size * 1.4, flags or "") end
        label:SetWidth(182)
        label:SetHeight(66)
        label:SetPoint("CENTER", root, "CENTER", positions[i][1], positions[i][2])
        label:SetJustifyH("CENTER")
        label:SetJustifyV("MIDDLE")
        label:SetShadowOffset(1, -2)
        label:SetShadowColor(0, 0, 0, 1)
        labels[i] = label
        -- A separate texture stays at the centre of the whole text block,
        -- instead of following the first line like an inline |T icon.
        local speaker = Texture(root, "Speaker.tga", 18, 18, "OVERLAY")
        speaker:ClearAllPoints()
        speaker:SetPoint("RIGHT", label, "LEFT", -6, 0)
        speaker:Hide()
        speakers[i] = speaker
    end
    stick = Texture(root, "Stick.tga", 30, 30, "OVERLAY")

    overlay:SetScript("OnEnter", function() if A.active then A:HideWheelCursor() end end)
    overlay:SetScript("OnLeave", function() A:RestoreCursor() end)
    overlay:SetScript("OnMouseDown", function()
        -- Capture clicks instead of interacting with the world or rotating the camera.
        A:CloseWheel(false)
    end)
    overlay:SetScript("OnHide", function()
        -- Esc, hidden UIParent, and unexpected external hides always cancel.
        if A.active then A:CloseWheel(false) else A:RestoreCursor() end
    end)
    overlay:SetScript("OnUpdate", function(_, elapsed)
        if not A.active then return end
        if GetTime() - A.openedAt > 12 then
            A:CloseWheel(false)
            A.held = false
            return
        end
        if GetCurrentKeyBoardFocus and GetCurrentKeyBoardFocus() then
            A:CloseWheel(false)
            return
        end
        local dx, dy = A:SampleWheel()
        A:UpdateWheelVisual(dx, dy, elapsed)
        A:HideWheelCursor()
    end)
end

function A:OpenWheel(preview)
    if not self.ready or self.active then return end
    if not UIParent:IsShown() then return end
    -- Cursor-held items / targeting spells must remain usable, not be swallowed.
    if CursorHasItem and CursorHasItem() then return end
    if SpellIsTargeting and SpellIsTargeting() then return end
    if GetCurrentKeyBoardFocus and GetCurrentKeyBoardFocus() then return end
    if self.picker then self.picker:Hide() end
    self.wasMouselooking = IsMouselooking and IsMouselooking() or false
    self.rightWasDown = IsMouseButtonDown and IsMouseButtonDown("RightButton") or false
    if self.wasMouselooking and MouselookStop then MouselookStop() end
    self.originX, self.originY = GetCursorPosition()
    self.stickX, self.stickY = 0, 0
    self.selected = nil
    self.preview = preview and true or false
    self.openedAt = GetTime()
    root:SetScale(self.db.scale)
    self.dimTexture:SetAlpha(self.db.dim)
    for i = 1, 8 do
        labels[i]:SetText(self:LimitUTF8(self:GetSlotText(i), 70))
        if self:IsSoundSlot(i) then speakers[i]:Show() else speakers[i]:Hide() end
    end
    self.active = true
    overlay:Show()
    self:UpdateWheelVisual(0, 0, 1)
    self:HideWheelCursor()
end

function A:CloseWheel(send)
    if not self.active then return end
    -- Sample again on key-up: the last mouse move can occur between render frames.
    if send then self:SampleWheel() end
    local index, wasPreview = self.selected, self.preview
    self.active = false
    self.preview = false
    self.selected = nil
    overlay:Hide()
    self:RestoreCursor()
    if self.wasMouselooking and MouselookStart then
        local stillRightDown = IsMouseButtonDown and IsMouseButtonDown("RightButton")
        if not self.rightWasDown or stillRightDown then MouselookStart() end
    end
    self.wasMouselooking = false
    if send and not wasPreview and index then self:SendPhrase(index) end
end
