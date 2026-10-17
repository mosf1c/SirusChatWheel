local A = SirusChatWheel

local function VersionParts(value)
    if type(value) ~= "string" or #value > 17 then return nil end
    local major, minor, patch = string.match(value, "^(%d+)%.(%d+)%.(%d+)$")
    if not major then return nil end
    return tonumber(major), tonumber(minor), tonumber(patch)
end

function A:IsNewerVersion(candidate, installed)
    local a, b, c = VersionParts(candidate)
    local x, y, z = VersionParts(installed)
    if not a or not x then return false end
    if a ~= x then return a > x end
    if b ~= y then return b > y end
    return c > z
end

function A:ShowUpdateStatus(automatic)
    local status = SirusChatWheelUpdateStatus
    if type(status) ~= "table" or not status.repository or status.repository == "" then
        if not automatic then self:Print("Проверка GitHub: запустите Check-Updates.cmd в папке аддона и выполните /reload.") end
        return false
    end
    local repository = status.repository
    if type(repository) ~= "string" or not string.match(repository, "^[%w%-]+/[%w_%.%-]+$") then return false end
    local at = tonumber(status.checkedAt)
    if not at or at ~= at or at < 0 or at > time() + 60 then return false end
    if status.state ~= "ok" then
        if not automatic then self:Print("Последняя проверка GitHub не удалась. Запустите Check-Updates.cmd повторно.") end
        return false
    end
    if not VersionParts(status.version) then return false end
    local age = math.max(0, time() - at)
    if age > 86400 then
        if not automatic then self:Print("Результат проверки GitHub старше суток. Запустите Check-Updates.cmd и выполните /reload.") end
        return false
    end
    local newer = self:IsNewerVersion(status.version, self.version)
    if automatic and not newer then return false end
    local checked = date and date("%d.%m.%Y %H:%M", at) or tostring(at)
    if newer then
        self:Print("Доступна версия " .. status.version .. " (у вас " .. self.version .. "). Проверено: " .. checked .. ".")
        self:Print("https://github.com/" .. repository .. "/releases/latest — скопируйте папку из архива в Interface\\AddOns с заменой файлов.")
    else
        self:Print("По проверке GitHub от " .. checked .. " новее версии " .. self.version .. " нет.")
    end
    return newer
end
