# Mutators

Every mutant changes one line. Group names are the names `# mutation: ignore=<group>,<group>` accepts.

| Group | Change |
|---|---|
| `cmp` | `==` to `!=`, `!=` to `==`, `<` to `<=`, `<=` to `<`, `>` to `>=`, `>=` to `>` |
| `arith` | binary `+` to `-`, `-` to `+`, `*` to `/`, `/` to `*`; `+=` to `-=`, `-=` to `+=`, `*=` to `/=`, `/=` to `*=` |
| `logic` | `and` to `or`, `or` to `and`, `&&` to `\|\|`, `\|\|` to `&&` |
| `not` | `not x` to `x`, `!x` to `x` |
| `bool` | `true` to `false`, `false` to `true` |
| `num` | integer `n` to `n + 1`, float `f` to `f + 1.0` |
| `if` | `if cond:` and `elif cond:` to `if not (cond):` |
| `del` | a statement line to `pass`, indentation kept |

## Never mutated
- Text inside string literals (`"..."`, `'...'`, triple-quoted, `&"..."`, `^"..."`) and comments.
- Declaration lines and their continuation lines: `func`, `static func`, `class`, `class_name`, `extends`, `signal`, `enum`, and any line starting with `@`. Default argument values and `@export` defaults are therefore not mutated.
- `**`, `<<`, `>>`, `->`, `%`, bitwise operators, unary `+` and `-`.
- Numbers inside identifiers (`p1`, `Vector2i`), hex and binary literals, exponent floats (`1e5`).

## Statement deletion never removes
- `return`, `var`, `const`, `static`, `pass`, `break`, `continue`, `breakpoint`.
- Block headers (`if`, `elif`, `else`, `for`, `while`, `match`) and any line ending in `:`.
- A line that is part of a multi-line statement or a multi-line string.

## Ignoring a line
```gdscript
var cap := 100  # mutation: ignore
if hp > 0:  # mutation: ignore=cmp,num
```
The first form skips every group on the line. Use it for equivalent mutants: changes that cannot alter behavior, where a survivor is not a missing test.
