SPRDPL (Simple Python Recursive-Descent Parsing Library)
========================================================

SPRDPL (pronounced "spur-DIPple") is a very simple framework for creating lexers and recursive
descent parsers. It aims for brevity and readability, providing a reasonably-featured parser
and lexer in about 500 lines of code (if whitespace and comments are excluded, just over 300
lines).

# Features
* Very simple, Pythonic code with pretty decent performance
* Pretty-ish error messages (through `ParseError.print`)
* Self-modifying parsers/lexers
* Lazy parsing support for interactive use

# Usage

Using `sprdpl` looks a little something like this:
```python
table = {
    'PLUS':       r'\+',
    'MINUS':      r'-',
    'TIMES':      r'\*',
    'DIVIDE':     r'/',
    'POWER':      r'\^',
    'NUMBER':     (r'[0-9]+(\.[0-9]*)?|\.[0-9]+',
        lambda t: t.copy(value=num_type(t.value))),
    'LPAREN':     r'\(',
    'RPAREN':     r'\)',
    'WHITESPACE': (r'[ \t\n]+', lambda t: None),
}
lexer = lex.Lexer(table)

rules = [
    ['atom', 'NUMBER', ('LPAREN expr RPAREN', lambda p: p[1])],
    ['factor', ('atom POWER factor', lambda p: p[0] ** p[2]),
        'atom', ('MINUS factor', lambda p: -p[1])],
    ['term', ('factor ((TIMES|DIVIDE) factor)*', reduce_binop)],
    ['expr', ('term ((PLUS|MINUS) term)*', reduce_binop)],
]
parser = parse.Parser(rules, 'expr')

result = parser.parse(lexer.input(line))
```
A very simple calculator example (from which this code is taken) is provided in `example.py`.

The lexer is constructed with a list of token name/regular expression pairs, specified
with Python's regex syntax. A transformation function can optionally be provided, allowing
the token to hold any Python value (like the `NUMBER` example above).

The parser works by translating an EBNF-like grammar directly into a recursive descent
parser.

More documentation coming soon (maybe).

# Handling ambiguity
Haha, that's a good one! Right now, in the interests of laziness/simplicity, there are basically
no sanity checks on the soundness of your grammar (or the soundness of this library). You get
what you pay for I guess.

Ambiguity is handled more-or-less on a greedy basis, like a recursive descent parser would: each
of the possibilities in an alternation (i.e. `rule_1 | rule_2`) are tried in series, with backtracking
in case the rule didn't parse. Right now the lexer/parser keep all input in memory to support infinite
backtracking.

# Speed
There's no solid benchmarks at the moment. There are only a few known uses of this library,
all written by me.

The best example of a reasonably complicated parser right now is my semi-dormant programming
language [Mutagen](https://github.com/zwegner/mutagen). As a small anecdotal data point it was
faster when it originally replaced PLY for the aforementioned Mutagen parser. I don't
remember how much faster, sorry.
