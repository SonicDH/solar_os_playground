local solaros = require("solaros")
local gfx = solaros.gfx
local tui = solaros.tui

local target = "display0"
local w, h = gfx.width(), gfx.height()
local palette = { gfx.BLACK, gfx.DARK, gfx.LIGHT, gfx.WHITE }
local max_iter = 32

gfx.begin(target)
local ok, err = pcall(function()
    gfx.clear(gfx.WHITE)
    for py = 0, h - 1 do
        local cy = (py - h / 2) * 3.0 / h
        for px = 0, w - 1 do
            local cx = (px - w * 0.70) * 3.5 / h
            local x, y = 0.0, 0.0
            local i = 0
            while x * x + y * y <= 4.0 and i < max_iter do
                local xx = x * x - y * y + cx
                y = 2.0 * x * y + cy
                x = xx
                i = i + 1
            end
            local band
            if i == max_iter then
                band = 1
            else
                band = 2 + (i % 3)
            end
            gfx.color(palette[band])
            gfx.pixel(px, py)
        end
        if py % 4 == 3 then
            gfx.present()
        end
    end
    gfx.present()
end)
gfx["end"]()
if not ok then error(err) end
