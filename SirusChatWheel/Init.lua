local A = SirusChatWheel
BINDING_HEADER_SIRUSCHATWHEEL = "Sirus Chat Wheel"
BINDING_NAME_SIRUSCHATWHEEL_HOLD = "Колесо чата (удерживать)"

local events = CreateFrame("Frame")
events:RegisterEvent("ADDON_LOADED")
events:RegisterEvent("PLAYER_LOGIN")
events:RegisterEvent("PLAYER_REGEN_ENABLED")
events:RegisterEvent("PLAYER_LEAVING_WORLD")
events:RegisterEvent("UPDATE_BINDINGS")
events:SetScript("OnEvent", function(_, event, name)
    if event == "ADDON_LOADED" and name == "SirusChatWheel" then
        A:LoadCatalog()
        A.db = A:Normalize(SirusChatWheelDB)
        SirusChatWheelDB = A.db
        events:UnregisterEvent("ADDON_LOADED")
    elseif event == "PLAYER_LOGIN" then
        if not A.db then A:LoadCatalog(); A.db = A:Normalize(SirusChatWheelDB); SirusChatWheelDB = A.db end
        A:CreateSoundSystem()
        A:CreateWheel()
        A:CreateOptions()
        A.ready = true
        if not A.db.bindingInitialized then A:BindY(true) end
        if A.options.refresh then A.options.refresh() end
        A:Print("Удерживай " .. (GetBindingKey(A.binding) or "назначенную клавишу") ..
            ". Настройки: /scw. Проверка без отправки: /scw test.")
        A:ShowUpdateStatus(true)
        events:UnregisterEvent("PLAYER_LOGIN")
    elseif event == "PLAYER_REGEN_ENABLED" and A.pendingBind then
        A:BindY(false)
    elseif event == "PLAYER_LEAVING_WORLD" then
        A:CloseWheel(false)
        A.held = false
    elseif event == "UPDATE_BINDINGS" and A.active then
        A:CloseWheel(false)
        A.held = false
    end
end)

SLASH_SIRUSCHATWHEEL1 = "/scw"
SLASH_SIRUSCHATWHEEL2 = "/chatwheel"
SlashCmdList["SIRUSCHATWHEEL"] = function(message)
    if not A.ready then return end
    local command = string.lower(string.match(message or "", "^%s*(%S*)") or "")
    if command == "test" then
        A:CloseWheel(false)
        A.held = false
        A:OpenWheel(true)
    elseif command == "bind" then
        A:BindY(false)
    elseif command == "status" then
        local channel = A:ResolveChannel()
        A:Print("Версия " .. A.version .. "; клавиша: " .. (GetBindingKey(A.binding) or "нет") ..
            "; канал: " .. (channel and A:ChannelLabel(channel) or "RAID, но вы не в рейде") ..
            "; скрытие курсора: " .. (A.db.hideCursor and "вкл." or "выкл."))
    elseif command == "close" then
        A:CloseWheel(false)
        A.held = false
    elseif command == "sounds" then
        A:Print("Голосовых файлов: " .. #A.soundList .. ". Новые звуки входят в полные выпуски аддона.")
    elseif command == "update" then
        A:ShowUpdateStatus(false)
    else
        A:OpenOptions()
    end
end
