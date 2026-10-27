-- This filter fixes a crash. A code block (text between ``` marks) can
-- hold characters like an en dash (–), curly quotes, or an arrow. pdfTeX
-- reads these characters in normal text, but it stops inside a code
-- block. It prints "Invalid UTF-8 byte sequence" and makes no PDF.
--
-- The filter changes these characters inside code only. It never changes
-- normal text. It writes one warning to stderr (the error stream) for
-- each changed character, so you can see what changed.
--
-- The map holds only characters that people write as plain ASCII in most
-- cases. For example, a dash becomes -, and three dots stay as three
-- dots. The code keeps its meaning.

--- Maps a character number to a plain ASCII string.
local MAP = {
  [0x2010] = "-", -- hyphen
  [0x2011] = "-", -- non-breaking hyphen
  [0x2012] = "-", -- figure dash
  [0x2013] = "-", -- en dash
  [0x2014] = "-", -- em dash
  [0x2018] = "'", -- left single quotation mark
  [0x2019] = "'", -- right single quotation mark
  [0x201A] = "'", -- single low-9 quotation mark
  [0x201B] = "'", -- single high-reversed-9 quotation mark
  [0x201C] = '"', -- left double quotation mark
  [0x201D] = '"', -- right double quotation mark
  [0x201E] = '"', -- double low-9 quotation mark
  [0x2026] = "...", -- horizontal ellipsis
  [0x00B7] = ".", -- middle dot
  [0x2192] = "->", -- rightwards arrow
  [0x2248] = "~", -- almost equal to
}

--- Replace the mapped characters in `text`.
---
--- @param text string  the code content
--- @return string      the code with every mapped character changed
--- @return table       the changed character numbers, sorted and without repeats
local function normalize(text)
  local out = {}
  local seen = {}
  local replaced = {}
  for _, cp in utf8.codes(text) do
    local mapped = MAP[cp]
    if mapped ~= nil then
      if not seen[cp] then
        seen[cp] = true
        replaced[#replaced + 1] = cp
      end
      out[#out + 1] = mapped
    else
      out[#out + 1] = utf8.char(cp)
    end
  end
  table.sort(replaced)
  return table.concat(out), replaced
end

--- Print one warning for each changed character.
local function warn(kind, replaced)
  for _, cp in ipairs(replaced) do
    io.stderr:write(
      string.format(
        "renderknecht: WARN: %s contains U+%04X, replaced with %q\n", kind, cp, MAP[cp]
      )
    )
  end
end

function Code(el)
  local text, replaced = normalize(el.text)
  if #replaced > 0 then
    warn("inline code", replaced)
    return pandoc.Code(text, el.attr)
  end
  return nil
end

function CodeBlock(el)
  local text, replaced = normalize(el.text)
  if #replaced > 0 then
    warn("code block", replaced)
    el.text = text
    return el
  end
  return nil
end
