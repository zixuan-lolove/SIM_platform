-- Pandoc Lua filter for pandoc 2.9.x
-- Always override table column widths with smart proportional widths.
-- Key insight: description columns need 35-50% of available width.

local function get_widths(ncols)
  -- All fractions are relative to total text width.
  -- Pandoc scales these to account for inter-column spacing (~8-10%).
  -- So 0.50 becomes ~0.45\columnwidth in the LaTeX output.

  if ncols == 3 then
    -- label | status | description     or     item | status | references
    return {0.22, 0.23, 0.55}
  elseif ncols == 4 then
    -- Two common patterns:
    --   Checklist: id | item | location | description
    --   Bugs:      id | location | description | impact
    -- Both need heavy space in cols 3+4. Give each 36%.
    return {0.08, 0.18, 0.37, 0.37}
  elseif ncols == 5 then
    return {0.10, 0.20, 0.22, 0.28, 0.20}
  elseif ncols == 6 then
    return {0.08, 0.18, 0.18, 0.22, 0.22, 0.12}
  else
    local w = 1.0 / ncols
    local widths = {}
    for i = 1, ncols do widths[i] = w end
    return widths
  end
end

function Table(table)
  if not table.widths then return table end
  local ncols = #table.widths
  if ncols == 0 then return table end

  table.widths = get_widths(ncols)

  return table
end
