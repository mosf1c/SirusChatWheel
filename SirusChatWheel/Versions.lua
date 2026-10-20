local A = SirusChatWheel
A.versionPrefix = "SCWVER1"
local channels = { "RAID", "PARTY", "GUILD" }
local releaseURL = "https://github.com/mosf1c/SirusChatWheel/releases/latest"

local function ActiveChannel(channel)
    if channel == "RAID" then return GetNumRaidMembers() > 0 end
    if channel == "PARTY" then return GetNumRaidMembers() == 0 and GetNumPartyMembers() > 0 end
    return channel == "GUILD" and IsInGuild and IsInGuild() or false
end

function A:RefreshVersionTimer()
    local state = self.versionState
    local pending = state.checkAt or state.noticeAt or next(state.replies)
    if pending then self.versionFrame:Show() else self.versionFrame:Hide() end
end

function A:RequestPeerVersions(manual)
    local state = self.versionState
    if not state then return end
    local active = false
    for _, channel in ipairs(channels) do if ActiveChannel(channel) then active = true end end
    if manual then
        local status = SirusChatWheelUpdateStatus
        if type(status) == "table" and type(status.repository) == "string" and status.repository ~= "" then self:ShowUpdateStatus(false) end
        if state.latest then
            self:PrintPeerUpdate()
        else
            self:Print((active and "Проверка версий у игроков группы и гильдии. Ваша версия: " or
                "Для проверки у игроков вступите в группу или гильдию. Ваша версия: ") .. self.version .. ".")
        end
    end
    if active then
        local at = GetTime() + (manual and 1 or 5)
        state.checkAt = math.min(state.checkAt or at, at)
        self:RefreshVersionTimer()
    end
end

function A:PrintPeerUpdate()
    local latest = self.versionState.latest
    if not latest then return end
    self:Print("Обнаружена более новая версия " .. latest.version .. " — у вас " .. self.version ..
        ". Информация получена от игрока " .. latest.sender .. ".")
    self:Print("Скачать обновление: " .. releaseURL)
    self.updateNoticePrinted = true
end

function A:SendVersionPacket(kind, channel)
    if not SendAddonMessage or not ActiveChannel(channel) then return false end
    return pcall(SendAddonMessage, self.versionPrefix, kind .. "|" .. self.version, channel)
end

function A:HandleVersionPacket(prefix, packet, channel, sender)
    if prefix ~= self.versionPrefix or type(packet) ~= "string" or #packet > 19 or not ActiveChannel(channel) then return end
    local kind, version = string.match(packet, "^([QV])|([%d%.]+)$")
    if not kind or not self:IsValidVersion(version) then return end
    local key = self:PlayerIdentity(sender)
    if not key or key == self:PlayerIdentity(UnitName("player")) then return end
    -- Guild addon traffic is delivered only to members by the server. Group
    -- traffic is additionally checked against the current local roster.
    if channel ~= "GUILD" and not self:IsGroupPeer(sender, channel) then return end
    local state, now = self.versionState, GetTime()
    local count = 0
    for peer, at in pairs(state.peers) do
        if now - at >= 60 then state.peers[peer] = nil else count = count + 1 end
    end
    local at = state.peers[key]
    if (at and now - at < 10) or (not at and count >= 64) then return end
    state.peers[key] = now
    if self:IsNewerVersion(version, self.version) and
        (not state.latest or self:IsNewerVersion(version, state.latest.version)) then
        state.latest = { version = version, sender = string.match(sender, "^%s*(.-)%s*$") }
        if not self.updateNoticePrinted and not state.noticeAt then state.noticeAt = now + 4 end
    end
    if not self:IsNewerVersion(self.version, version) then
        -- A peer has already announced at least our version to this channel.
        state.replies[channel] = nil
    elseif kind == "Q" and not state.replies[channel] and now - (state.lastReply[channel] or -math.huge) >= 30 then
        -- Stagger answers; an equal or newer announcement cancels this reply.
        state.replies[channel] = now + 1 + math.random() * 2
    end
    self:RefreshVersionTimer()
end

function A:CreateVersionSystem()
    if self.versionFrame then return end
    self.versionState = { peers = {}, replies = {}, lastQuery = {}, lastReply = {} }
    local state = self.versionState
    local frame = CreateFrame("Frame")
    self.versionFrame = frame
    for _, event in ipairs({ "CHAT_MSG_ADDON", "PLAYER_ENTERING_WORLD", "RAID_ROSTER_UPDATE",
        "PARTY_MEMBERS_CHANGED", "PLAYER_GUILD_UPDATE", "GUILD_ROSTER_UPDATE" }) do frame:RegisterEvent(event) end
    frame:SetScript("OnEvent", function(_, event, ...)
        if event == "CHAT_MSG_ADDON" then self:HandleVersionPacket(...)
        else self:RequestPeerVersions(false) end
    end)
    frame:SetScript("OnUpdate", function()
        local now = GetTime()
        if state.checkAt and now >= state.checkAt then
            state.checkAt = nil
            for _, channel in ipairs(channels) do
                if now - (state.lastQuery[channel] or -math.huge) >= 60 and self:SendVersionPacket("Q", channel) then
                    state.lastQuery[channel] = now
                end
            end
        end
        for channel, at in pairs(state.replies) do
            if now >= at then
                state.replies[channel] = nil
                if self:SendVersionPacket("V", channel) then state.lastReply[channel] = now end
            end
        end
        if state.noticeAt and now >= state.noticeAt then
            state.noticeAt = nil
            if not self.updateNoticePrinted then self:PrintPeerUpdate() end
        end
        self:RefreshVersionTimer()
    end)
    frame:Hide()
    self:RequestPeerVersions(false)
end
