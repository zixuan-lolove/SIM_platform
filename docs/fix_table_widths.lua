-- Pandoc Lua filter: set proportional column widths on all tables
-- This ensures both minipage widths and longtable column specs match

local function get_widths(num_cols)
  if num_cols == 3 then
    return {0.12, 0.28, 0.60}
  elseif num_cols == 4 then
    return {0.08, 0.20, 0.28, 0.44}
  else
    -- equal widths
    local w = {}
    for i = 1, num_cols do
      w[i] = 1.0 / num_cols
    end
    return w
  end
end

function Table(tbl)
  local widths = get_widths(#tbl.colspecs)
  -- Set column widths as fraction of total
  tbl.colspecs = pandoc.List.map(tbl.colspecs, function(spec, i)
    -- Set width as proportion of total (pandoc handles textwidth calc)
    spec[2] = widths[i]
    return spec
  end)
  return tbl
end
