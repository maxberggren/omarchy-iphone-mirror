-- iPhone Mirror Home gesture for Omarchy's Lua Hyprland config.
-- Installed by ./install-hypr.sh as ~/.config/hypr/iphone-mirror.lua and
-- loaded with require("hypr.iphone-mirror") from ~/.config/hypr/hyprland.lua.
-- Launcher keybindings are personal and stay in your own bindings.lua.

local mirror = os.getenv("HOME") .. "/.local/bin/iphone-mirror"

-- Press in the gap just below the mirror window, drag up, and release to press
-- Home (injected touches can't trigger the iOS home swipe). Throwing the cursor
-- to the bottom of the screen lands in that gap. Both binds are non-consuming,
-- so ordinary clicks are unaffected. Drags that start inside the window are
-- handled by the app itself (usb_input.py).
local mirror_drag_y = nil
local function mirror_window()
  local w = hl.get_windows({ class = "iphone-mirror" })[1]
  local ws = hl.get_active_workspace()
  if w and w.mapped and w.fullscreen == 0 and ws and w.workspace and w.workspace.id == ws.id then
    return w
  end
end
hl.bind("mouse:272", function()
  mirror_drag_y = nil
  pcall(function()
    local w, c = mirror_window(), hl.get_cursor_pos()
    if not w or not c then return end
    local bottom = w.at.y + w.size.y
    if c.x >= w.at.x and c.x <= w.at.x + w.size.x and c.y >= bottom and c.y <= bottom + 40 then
      mirror_drag_y = c.y
    end
  end)
end, { non_consuming = true, description = "iPhone Mirror home drag (press)" })
hl.bind("mouse:272", function()
  local start = mirror_drag_y
  mirror_drag_y = nil
  if not start then return end
  pcall(function()
    local c = hl.get_cursor_pos()
    if c and mirror_window() and start - c.y >= 80 then
      hl.exec_cmd(mirror .. " home")
    end
  end)
end, { release = true, non_consuming = true, description = "iPhone Mirror home drag (release)" })
