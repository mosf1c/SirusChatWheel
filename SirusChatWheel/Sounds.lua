local A = SirusChatWheel
A.prefix = "SCW12"

function A:LoadCatalog()
    self.clips, self.soundList, self.soundByFile, self.soundByTitle = {}, {}, {}, {}
    local source = SirusChatWheelSoundCatalog
    if type(source) ~= "table" or type(source.items) ~= "table" then return end
    for _, item in ipairs(source.items) do
        if type(item) == "table" and type(item.id) == "string" and
            string.match(item.id, "^s_%x%x%x%x%x%x%x%x%x%x%x%x%x%x%x%x$") and
            type(item.file) == "string" and string.match(item.file, "^Cache/s_%x+%.[a-z0-9]+$") and
            type(item.digest) == "string" and string.match(item.digest, "^%x%x%x%x%x%x%x%x%x%x%x%x%x%x%x%x$") then
            local extension = string.match(item.file, "%.([a-z0-9]+)$")
            local title = self:CleanPhrase(item.title)
            if #title > 216 then title = self:LimitUTF8(title, 216) .. " [" .. string.sub(item.id, 3) .. "]" end
            if (extension == "wav" or extension == "mp3" or extension == "ogg") and title ~= "" and not self.clips[item.id] then
                local clip = { id = item.id, title = title, file = string.gsub(item.file, "/", "\\"),
                    filename = type(item.filename) == "string" and item.filename or "",
                    digest = string.lower(item.digest), duration = tonumber(item.duration) or 3 }
                if clip.duration <= 0 or clip.duration ~= clip.duration or clip.duration == math.huge then clip.duration = 3 end
                self.clips[clip.id] = clip
                table.insert(self.soundList, clip)
                self.soundByFile[string.lower(clip.filename)] = clip.id
                self.soundByTitle[clip.title] = self.soundByTitle[clip.title] or {}
                table.insert(self.soundByTitle[clip.title], clip.id)
            end
        end
    end
end

function A:SoundWait(bucket, now)
    for i = #bucket, 1, -1 do
        if type(bucket[i]) ~= "number" or bucket[i] > now or now - bucket[i] >= 30 then table.remove(bucket, i) end
    end
    if #bucket < 2 then return 0 end
    local earliest = bucket[1]
    for i = 2, #bucket do earliest = math.min(earliest, bucket[i]) end
    return math.max(1, math.ceil(earliest + 30 - now))
end

function A:Nonce()
    self.nonceCounter = (self.nonceCounter or 0) + 1
    self.sessionNonce = self.sessionNonce or tostring(math.random(100000, 999999))
    return self.sessionNonce .. "_" .. tostring(math.floor(GetTime() * 1000)) .. "_" .. tostring(self.nonceCounter)
end

function A:IsGroupPeer(sender, channel)
    local name = self:PlayerIdentity(sender)
    if not name then return false end
    if channel == "RAID" then
        for i = 1, GetNumRaidMembers() do
            if name == self:PlayerIdentity(GetRaidRosterInfo(i)) then return true end
        end
    elseif channel == "PARTY" then
        for i = 1, GetNumPartyMembers() do
            if name == self:PlayerIdentity(UnitName("party" .. i)) then return true end
        end
    end
    return false
end

function A:SendPacket(packet, channel, target)
    if not SendAddonMessage or #packet > 230 then return false end
    local ok = pcall(SendAddonMessage, self.prefix, packet, channel, target)
    return ok
end

function A:PlayClipNow(id)
    local clip = self.clips[id]
    if not clip or not PlaySoundFile then return false end
    local ok, result = pcall(PlaySoundFile, self.media .. clip.file)
    if not ok or result == false then
        if not self.soundErrorPrinted then
            self:Print("Звук не воспроизводится. Обновите каталог файлов и проверьте звуковые эффекты WoW.")
            self.soundErrorPrinted = true
        end
        return false
    end
    self.soundBusyUntil = GetTime() + clip.duration + 0.06
    return true
end

function A:CanQueueClip()
    return #(self.soundQueue or {}) < 8
end

function A:QueueClip(id, remote, sender)
    if not self.clips[id] or not self.soundFrame then return false end
    if remote and (not self.db.receiveSounds or self:IsPlayerMuted(sender)) then return false end
    self.soundQueue = self.soundQueue or {}
    if #self.soundQueue == 0 and GetTime() >= (self.soundBusyUntil or 0) then return self:PlayClipNow(id) end
    if not self:CanQueueClip() then return false end
    table.insert(self.soundQueue, { id = id, remote = remote and true or false, sender = self:PlayerIdentity(sender) })
    self.soundFrame:Show()
    return true
end

function A:SendSound(id)
    local clip = self.clips[id]
    if not clip then return false end
    self.db.soundUses = type(self.db.soundUses) == "table" and self.db.soundUses or {}
    local now = time()
    local wait = self:SoundWait(self.db.soundUses, now)
    if wait > 0 then self:ShowError("Использовать звуки можно через " .. wait .. " с"); return false end
    local channel = self:ResolveChannel()
    if not channel then self:ShowError("Вы не в рейде. Выберите /say или включите /say вне рейда."); return false end
    if not self:CanQueueClip() then self:ShowError("Дождитесь окончания очереди звуков."); return false end
    local action = { id = id, nonce = self:Nonce(), digest = clip.digest,
        at = GetTime(), channel = channel, requests = {} }
    self:PruneNetwork()
    self.recentSoundActions = self.recentSoundActions or {}
    table.insert(self.recentSoundActions, action)
    table.insert(self.db.soundUses, now)
    -- The name remains visible; playback requires a separate hidden command.
    local ok, err = pcall(SendChatMessage, clip.title, channel)
    if not ok then
        table.remove(self.db.soundUses)
        table.remove(self.recentSoundActions)
        self:Print("Ошибка отправки: " .. tostring(err))
        return false
    end
    if channel == "RAID" then self:SendPacket("P|" .. id .. "|" .. action.nonce .. "|" .. clip.digest, "RAID") end
    self:QueueClip(id, false)
    return true
end

function A:PruneNetwork()
    local now = GetTime()
    self.pendingQueries = self.pendingQueries or {}
    self.seenPackets = self.seenPackets or {}
    self.remoteUses = self.remoteUses or {}
    self.queryThrottle = self.queryThrottle or {}
    for key, value in pairs(self.pendingQueries) do if now - value.at > 6 then self.pendingQueries[key] = nil end end
    for key, value in pairs(self.seenPackets) do if now - value > 60 then self.seenPackets[key] = nil end end
    for key, value in pairs(self.queryThrottle) do
        if now - (value[#value] or 0) > 8 then self.queryThrottle[key] = nil end
    end
    for i = #(self.recentSoundActions or {}), 1, -1 do
        if now - self.recentSoundActions[i].at > 6 then table.remove(self.recentSoundActions, i) end
    end
    for key, value in pairs(self.remoteUses) do
        self:SoundWait(value, now)
        if #value == 0 then self.remoteUses[key] = nil end
    end
end

function A:HandleSayDiscovery(message, sender)
    if not self.ready or not self.db.receiveSounds or type(message) ~= "string" then return false end
    if self:IsPlayerMuted(sender) then return false end
    local name = self:PlayerIdentity(sender)
    if not name or name == self:PlayerIdentity(UnitName("player")) then return false end
    local ids = self.soundByTitle[self:CleanPhrase(message)]
    if not ids then return false end
    self:PruneNetwork()
    local now = GetTime()
    local queries = self.queryThrottle[name] or {}
    for i = #queries, 1, -1 do if now - queries[i] >= 1 then table.remove(queries, i) end end
    if #queries >= 2 then return false end
    table.insert(queries, now)
    self.queryThrottle[name] = queries
    -- This query cannot play a sound. The speaker must confirm a recent accepted
    -- wheel action with a hidden response matching both clip and query nonce.
    for _, id in ipairs(ids) do
        local clip = self.clips[id]
        local nonce = self:Nonce()
        self.pendingQueries[nonce] = { peer = name, sender = self:PlayerIdentity(sender), id = id, at = now }
        self:SendPacket("Q|" .. id .. "|" .. nonce .. "|" .. clip.digest, "WHISPER", sender)
    end
    return true
end

function A:HandleAddonSound(prefix, packet, channel, sender)
    if not self.ready or prefix ~= self.prefix or type(packet) ~= "string" or #packet > 230 then return false end
    if type(sender) ~= "string" or sender == "" then return false end
    local name = self:PlayerIdentity(sender)
    if not name or name == self:PlayerIdentity(UnitName("player")) then return false end
    local kind, id, nonce, digest, query = string.match(packet, "^([PQR])|([a-z0-9_]+)|([a-zA-Z0-9_]+)|([a-f0-9]+)|?([a-zA-Z0-9_]*)$")
    if not kind or #nonce > 64 or #query > 64 or #digest ~= 16 then return false end
    local clip = self.clips[id]
    if not clip or clip.digest ~= digest then return false end
    self:PruneNetwork()
    local now = GetTime()
    if kind == "Q" then
        if channel ~= "WHISPER" or query ~= "" then return false end
        for _, action in ipairs(self.recentSoundActions or {}) do
            if action.channel == "SAY" and action.id == id and not action.requests[name] then
                action.requests[name] = true
                return self:SendPacket("R|" .. id .. "|" .. action.nonce .. "|" .. digest .. "|" .. nonce, "WHISPER", sender)
            end
        end
        return false
    end
    if not self.db.receiveSounds then return false end
    if kind == "P" then
        if query ~= "" or not self:IsGroupPeer(sender, channel) then return false end
    elseif kind == "R" then
        local pending = self.pendingQueries[query]
        if channel ~= "WHISPER" or not pending or pending.peer ~= name or pending.id ~= id or now - pending.at > 6 then return false end
        self.pendingQueries[query] = nil
    end
    local key = name .. ":" .. nonce
    if self.seenPackets[key] then return false end
    self.seenPackets[key] = now
    self:RememberSpeaker(sender, clip)
    if self:IsPlayerMuted(sender) then return false end
    self.remoteUses[name] = self.remoteUses[name] or {}
    if self:SoundWait(self.remoteUses[name], now) > 0 then return false end
    if not self:CanQueueClip() then return false end
    table.insert(self.remoteUses[name], now)
    return self:QueueClip(id, true, sender)
end

function A:CreateSoundSystem()
    if self.soundFrame then return end
    self.soundQueue = {}
    self.soundFrame = CreateFrame("Frame")
    self.soundFrame:Hide()
    self.soundFrame:SetScript("OnUpdate", function()
        if GetTime() < (A.soundBusyUntil or 0) then return end
        local nextClip = table.remove(A.soundQueue, 1)
        while nextClip and (not A.clips[nextClip.id] or nextClip.remote and
            (not A.db.receiveSounds or A.db.mutedPlayers[nextClip.sender])) do nextClip = table.remove(A.soundQueue, 1) end
        if nextClip then A:PlayClipNow(nextClip.id) end
        if #A.soundQueue == 0 then A.soundFrame:Hide() end
    end)
    self.soundEvents = CreateFrame("Frame")
    self.soundEvents:RegisterEvent("CHAT_MSG_ADDON")
    self.soundEvents:RegisterEvent("CHAT_MSG_SAY")
    self.soundEvents:SetScript("OnEvent", function(_, event, ...)
        if event == "CHAT_MSG_ADDON" then A:HandleAddonSound(...)
        elseif event == "CHAT_MSG_SAY" then A:HandleSayDiscovery(...) end
    end)
end
