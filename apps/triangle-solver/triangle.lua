local solaros = require("solaros")
local gfx = solaros.gfx

local KEY_BACKSPACE = 8
local KEY_TAB = 9
local KEY_LF = 10
local KEY_ENTER = 13
local KEY_SPACE = 32
local KEY_DELETE = 127
local KEY_C = 99
local KEY_N = 110
local KEY_Q = 113
local KEY_R = 114

local MARGIN = 8
local FIELD_H = 32
local PI = math.pi
local EPSILON = 0.000001

local fields = {
    {name = "A", kind = "angle", index = 1},
    {name = "B", kind = "angle", index = 2},
    {name = "C", kind = "angle", index = 3},
    {name = "a", kind = "side", index = 1},
    {name = "b", kind = "side", index = 2},
    {name = "c", kind = "side", index = 3},
}

local function radians(degrees)
    return degrees * PI / 180
end

local function degrees(radians_value)
    return radians_value * 180 / PI
end

local function clamp(value, low, high)
    return math.max(low, math.min(high, value))
end

local function copy_values(values)
    return {values[1], values[2], values[3]}
end

local function solve_sss(sides)
    local a, b, c = sides[1], sides[2], sides[3]
    if a + b <= c + EPSILON or a + c <= b + EPSILON or b + c <= a + EPSILON then
        return nil, "Sides fail triangle inequality"
    end

    local angles = {
        degrees(math.acos(clamp((b * b + c * c - a * a) / (2 * b * c), -1, 1))),
        degrees(math.acos(clamp((a * a + c * c - b * b) / (2 * a * c), -1, 1))),
        0,
    }
    angles[3] = 180 - angles[1] - angles[2]
    return {sides = copy_values(sides), angles = angles, kind = "SSS"}
end

local function solve_aas(sides, angles)
    local missing_angle = nil
    local known_side = nil
    for index = 1, 3 do
        if angles[index] == nil then
            missing_angle = index
        end
        if sides[index] ~= nil then
            known_side = index
        end
    end

    local solved_angles = copy_values(angles)
    local angle_sum = 0
    for index = 1, 3 do
        if solved_angles[index] ~= nil then
            angle_sum = angle_sum + solved_angles[index]
        end
    end
    solved_angles[missing_angle] = 180 - angle_sum
    if solved_angles[missing_angle] <= EPSILON then
        return nil, "Angles must total less than 180"
    end

    local scale = sides[known_side] / math.sin(radians(solved_angles[known_side]))
    local solved_sides = copy_values(sides)
    for index = 1, 3 do
        if solved_sides[index] == nil then
            solved_sides[index] = scale * math.sin(radians(solved_angles[index]))
        end
    end
    return {{sides = solved_sides, angles = solved_angles, kind = "ASA/AAS"}}
end

local function solve_sas(sides, angles, known_angle)
    local solved_sides = copy_values(sides)
    local other = {}
    for index = 1, 3 do
        if solved_sides[index] ~= nil then
            other[#other + 1] = index
        end
    end

    local p = solved_sides[other[1]]
    local q = solved_sides[other[2]]
    solved_sides[known_angle] = math.sqrt(math.max(0,
        p * p + q * q - 2 * p * q * math.cos(radians(angles[known_angle]))))
    if solved_sides[known_angle] <= EPSILON then
        return nil, "Measurements collapse the triangle"
    end

    local solution, err = solve_sss(solved_sides)
    if solution == nil then
        return nil, err
    end
    solution.kind = "SAS"
    return {solution}
end

local function solve_ssa(sides, angles, known_angle)
    local other_side = nil
    local missing_side = nil
    for index = 1, 3 do
        if index ~= known_angle and sides[index] ~= nil then
            other_side = index
        elseif sides[index] == nil then
            missing_side = index
        end
    end

    local sine_value = sides[other_side] * math.sin(radians(angles[known_angle])) /
        sides[known_angle]
    if sine_value > 1 + EPSILON then
        return nil, "SSA measurements have no triangle"
    end
    sine_value = clamp(sine_value, -1, 1)

    local first = degrees(math.asin(sine_value))
    local candidates = {first}
    if math.abs(first - 90) > EPSILON then
        candidates[#candidates + 1] = 180 - first
    end

    local solutions = {}
    for _, other_angle in ipairs(candidates) do
        local final_angle = 180 - angles[known_angle] - other_angle
        if final_angle > EPSILON then
            local solved_angles = copy_values(angles)
            solved_angles[other_side] = other_angle
            solved_angles[missing_side] = final_angle
            local solved_sides = copy_values(sides)
            solved_sides[missing_side] = sides[known_angle] *
                math.sin(radians(final_angle)) / math.sin(radians(angles[known_angle]))
            solutions[#solutions + 1] = {
                sides = solved_sides,
                angles = solved_angles,
                kind = "SSA",
            }
        end
    end

    if #solutions == 0 then
        return nil, "SSA measurements have no triangle"
    end
    return solutions
end

local function solve_triangle(input)
    local sides = {nil, nil, nil}
    local angles = {nil, nil, nil}
    local side_count = 0
    local angle_count = 0

    for field_index, field in ipairs(fields) do
        local text = input[field_index]
        if text ~= "" then
            local value = tonumber(text)
            if value == nil then
                return nil, field.name .. " is not a number"
            elseif value <= 0 then
                return nil, field.name .. " must be greater than zero"
            elseif field.kind == "angle" and value >= 180 then
                return nil, field.name .. " must be less than 180 deg"
            end

            if field.kind == "side" then
                sides[field.index] = value
                side_count = side_count + 1
            else
                angles[field.index] = value
                angle_count = angle_count + 1
            end
        end
    end

    if side_count + angle_count ~= 3 then
        return nil, "Enter exactly 3 measurements"
    elseif side_count == 0 then
        return nil, "At least one side is required"
    end

    local known_angle_sum = 0
    for index = 1, 3 do
        known_angle_sum = known_angle_sum + (angles[index] or 0)
    end
    if angle_count >= 2 and known_angle_sum >= 180 - EPSILON then
        return nil, "Known angles must total less than 180"
    end

    if side_count == 3 then
        local solution, err = solve_sss(sides)
        if solution == nil then
            return nil, err
        end
        return {solution}
    elseif angle_count == 2 then
        return solve_aas(sides, angles)
    elseif angle_count == 1 and side_count == 2 then
        local known_angle = nil
        for index = 1, 3 do
            if angles[index] ~= nil then
                known_angle = index
                break
            end
        end
        if sides[known_angle] == nil then
            return solve_sas(sides, angles, known_angle)
        end
        return solve_ssa(sides, angles, known_angle)
    end

    return nil, "Unsupported measurement combination"
end

local function format_value(value)
    if value == nil then
        return "--"
    end
    if math.abs(value) < 0.0000001 then
        value = 0
    end
    return string.format("%.6g", value)
end

local function fitted(message, pixel_width)
    local max_chars = math.max(1, pixel_width // 7)
    if #message <= max_chars then
        return message
    elseif max_chars <= 3 then
        return message:sub(1, max_chars)
    end
    return message:sub(1, max_chars - 3) .. "..."
end

local function draw_triangle(solution, left, top, width, height)
    gfx.color(gfx.BLACK)
    gfx.rect(left, top, width, height)
    gfx.font(gfx.FONT_BOLD_14)
    gfx.text(left + 7, top + 17, "Triangle Solver")
    gfx.font(gfx.FONT_MONO_12)
    gfx.text(math.max(left + 110, left + width - 84), top + 17, "angles: deg")
    if solution == nil then
        local x1, y1 = left + 18, top + height - 18
        local x2, y2 = left + width - 18, top + height - 18
        local x3, y3 = left + width // 2, top + 35
        gfx.color(gfx.LIGHT)
        gfx.line(x1, y1, x2, y2)
        gfx.line(x2, y2, x3, y3)
        gfx.line(x3, y3, x1, y1)
        gfx.color(gfx.BLACK)
        gfx.text(left + 8, top + 34, "Enter 3 known values")
        return
    end

    local a, b, c = solution.sides[1], solution.sides[2], solution.sides[3]
    local ax = (c * c + a * a - b * b) / (2 * a)
    local ay = math.sqrt(math.max(0, c * c - ax * ax))
    local min_x = math.min(0, ax)
    local max_x = math.max(a, ax)
    local data_w = math.max(EPSILON, max_x - min_x)
    local data_h = math.max(EPSILON, ay)
    local label_pad = 22
    local content_top = top + 20
    local content_h = height - 20
    local scale = math.min((width - label_pad * 2) / data_w,
        (content_h - label_pad * 2) / data_h)
    local offset_x = left + (width - data_w * scale) // 2 - min_x * scale
    local base_y = top + height - label_pad
    local bx, by = math.floor(offset_x + 0.5), base_y
    local cx, cy = math.floor(offset_x + a * scale + 0.5), base_y
    local apex_x = math.floor(offset_x + ax * scale + 0.5)
    local apex_y = math.floor(base_y - ay * scale + 0.5)

    gfx.line(bx, by, cx, cy)
    gfx.line(cx, cy, apex_x, apex_y)
    gfx.line(apex_x, apex_y, bx, by)
    gfx.text(apex_x - 3, math.max(content_top + 13, apex_y - 5), "A")
    gfx.text(bx - 10, math.min(top + height - 4, by + 12), "B")
    gfx.text(cx + 3, math.min(top + height - 4, cy + 12), "C")
end

local function draw(input, selected, solutions, solution_index, status, w, h)
    gfx.clear(gfx.WHITE)
    local sketch_h = math.max(88, h // 2 - MARGIN - 2)
    local sketch_w = w - MARGIN * 2
    local fields_top = h // 2 + 4
    local gap = 6
    local field_w = (w - MARGIN * 2 - gap * 2) // 3
    local solution = solutions and solutions[solution_index] or nil
    draw_triangle(solution, MARGIN, MARGIN, sketch_w, sketch_h)

    for field_index, field in ipairs(fields) do
        local column = (field_index - 1) % 3
        local row = (field_index - 1) // 3
        local x = MARGIN + column * (field_w + gap)
        local y = fields_top + row * (FIELD_H + 5)
        local known = input[field_index] ~= ""
        local value = input[field_index]
        if not known and solution ~= nil then
            if field.kind == "side" then
                value = format_value(solution.sides[field.index])
            else
                value = format_value(solution.angles[field.index])
            end
        elseif value == "" then
            value = "--"
        end

        gfx.color(gfx.DARK)
        gfx.rect(x, y, field_w, FIELD_H)
        if field_index == selected then
            gfx.color(gfx.BLACK)
            gfx.rect(x + 2, y + 2, field_w - 4, FIELD_H - 4)
        end
        gfx.color(gfx.BLACK)
        gfx.font(gfx.FONT_MONO_12)
        gfx.text(x + 6, y + 13, field.name .. (known and "*" or " "))
        gfx.font(gfx.FONT_BOLD_14)
        gfx.text(x + 25, y + 22, fitted(value, field_w - 30))
    end

    local info_y = fields_top + (FIELD_H + 5) * 2 + 11
    gfx.color(gfx.BLACK)
    gfx.font(gfx.FONT_BOLD_14)
    local result_label = "Ready"
    if solution ~= nil then
        result_label = solution.kind
        if #solutions > 1 then
            result_label = result_label .. " solution " .. solution_index .. "/" .. #solutions
        end
    end
    gfx.text(MARGIN, info_y, result_label)
    gfx.font(gfx.FONT_MONO_12)
    gfx.text(MARGIN, info_y + 18, fitted(status, w - MARGIN * 2))
    gfx.text(MARGIN, h - 8, fitted("Arrows move | type | Enter solve | R reset | Q quit", w - MARGIN * 2))
    gfx.refresh()
end

gfx.begin()

local ok, err = pcall(function()
    local w, h = gfx.size()
    local input = {"", "", "", "", "", ""}
    local selected = 1
    local replace_on_type = true
    local solutions = nil
    local solution_index = 1
    local status = "Enter exactly 3 measurements"

    local function invalidate(message)
        solutions = nil
        solution_index = 1
        status = message or "Input changed; press Enter to solve"
    end

    local function redraw()
        draw(input, selected, solutions, solution_index, status, w, h)
    end

    redraw()
    while not solaros.should_exit() do
        local key = gfx.getch(250)
        if key ~= nil then
            local changed = false
            if key == gfx.KEY_ESCAPE or key == KEY_Q then
                break
            elseif key == gfx.KEY_LEFT then
                local row_start = selected <= 3 and 1 or 4
                selected = row_start + (selected - row_start + 2) % 3
                replace_on_type = true
                changed = true
            elseif key == gfx.KEY_RIGHT or key == KEY_TAB then
                local row_start = selected <= 3 and 1 or 4
                selected = row_start + (selected - row_start + 1) % 3
                replace_on_type = true
                changed = true
            elseif key == gfx.KEY_UP then
                selected = selected > 3 and selected - 3 or selected + 3
                replace_on_type = true
                changed = true
            elseif key == gfx.KEY_DOWN then
                selected = selected <= 3 and selected + 3 or selected - 3
                replace_on_type = true
                changed = true
            elseif key == KEY_ENTER or key == KEY_LF or key == KEY_SPACE then
                local result, solve_error = solve_triangle(input)
                if result == nil then
                    solutions = nil
                    status = solve_error
                else
                    solutions = result
                    solution_index = 1
                    if #solutions > 1 then
                        status = "Two triangles fit; press N to switch"
                    else
                        status = "Solved from the starred measurements"
                    end
                end
                replace_on_type = true
                changed = true
            elseif key == KEY_N and solutions ~= nil and #solutions > 1 then
                solution_index = solution_index % #solutions + 1
                status = "Showing alternate SSA triangle"
                changed = true
            elseif key == KEY_R then
                input = {"", "", "", "", "", ""}
                selected = 1
                replace_on_type = true
                invalidate("Enter exactly 3 measurements")
                changed = true
            elseif key == KEY_C or key == KEY_DELETE or key == gfx.KEY_DELETE then
                input[selected] = ""
                replace_on_type = true
                invalidate()
                changed = true
            elseif key == KEY_BACKSPACE then
                if replace_on_type then
                    input[selected] = ""
                else
                    input[selected] = input[selected]:sub(1, -2)
                end
                replace_on_type = false
                invalidate()
                changed = true
            elseif (key >= 48 and key <= 57) or key == 46 then
                local character = string.char(key)
                local current = replace_on_type and "" or input[selected]
                if #current < 11 and not (character == "." and current:find("%.") ~= nil) then
                    input[selected] = current .. character
                    replace_on_type = false
                    invalidate()
                    changed = true
                end
            end

            if changed then
                redraw()
            end
        end
    end
end)

gfx["end"]()

if not ok then
    error(err)
end
