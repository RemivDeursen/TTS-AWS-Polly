local ADDON_NAME = ...

local frame = CreateFrame("Frame")
frame:RegisterEvent("PLAYER_LOGIN")
frame:RegisterEvent("PLAYER_LOGOUT")

local function ensureDatabase()
    RemTTS_WowlinkDB = RemTTS_WowlinkDB or {}
    RemTTS_WowlinkDB.version = 1
    RemTTS_WowlinkDB.player = UnitName("player")
    RemTTS_WowlinkDB.realm = GetRealmName()
end

local function printStatus()
    ensureDatabase()

    local player = RemTTS_WowlinkDB.player or "unknown"
    local realm = RemTTS_WowlinkDB.realm or "unknown"

    print("|cff33ff99RemTTS WoWLink|r helper loaded for " .. player .. "-" .. realm .. ".")
    print("|cff33ff99RemTTS WoWLink|r Toggle WoWLink in RemTTS, then use Scroll Lock as the capture switch.")
end

SLASH_REMTTSWOWLINK1 = "/remtts"
SLASH_REMTTSWOWLINK2 = "/wowlink"
SlashCmdList["REMTTSWOWLINK"] = function(message)
    local command = string.lower((message or ""):match("^%s*(.-)%s*$"))
    ensureDatabase()

    printStatus()
end

frame:SetScript("OnEvent", function(_, event)
    ensureDatabase()

    if event == "PLAYER_LOGIN" then
        printStatus()
    elseif event == "PLAYER_LOGOUT" then
        RemTTS_WowlinkDB.lastLogout = time()
    end
end)
