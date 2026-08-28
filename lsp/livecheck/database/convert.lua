local sql_schema = [[
PRAGMA foreign_keys=OFF;
BEGIN TRANSACTION;
CREATE TABLE FORTH(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word TEXT UNIQUE NOT NULL,
    stack TEXT,
    description TEXT,
    example TEXT
);
]]

print(sql_schema)

local function parse_line(line)
    line = line:gsub("\n", "")

    -- Match pattern: ("word", "rest")
    local word, rest = line:match('%("([^"]+)",%s*"([^"]+)"%)')

    if word and rest then
        -- Match stack comment and description in rest
        local stack_comment, description = rest:match('(%([^)]-%))%s*(.*)')

        if stack_comment and description then
            return string.format(
                [[
INSERT INTO FORTH (word, stack, description, example) VALUES (
    '%s',
    '%s',
    '%s',
    ''
);
                ]],
                word, stack_comment, description
            )
        else
            return line
        end
    else
        return line
    end
end

-- Read input line by line and process
for line in io.lines() do
    print(parse_line(line))
end

-- Print COMMIT at the end
print("COMMIT;")
