import sprdpl.lex

# ParseResult works like a tuple for the results of parsed rules, but with an
# additional .get_info(n) method for getting line-number information out
class ParseResult:
    def __init__(self, items, info):
        self.items = items
        self.info = info
    def __getitem__(self, n):
        return self.items[n]
    def get_info(self, n):
        return self.info[n]

# Dummy sentinel object
BAD_PARSE = object()

class Context:
    def __init__(self, fn_table, tokenizer):
        self.fn_table = fn_table
        self.tokenizer = tokenizer

# Classes to represent grammar structure. These are hierarchically nested, and
# operate through the parse method, usually calling other rules' parse methods.

# Parse either a token or a nonterminal of the grammar
class Identifier:
    def __init__(self, rule, name):
        self.rule = rule
        self.name = name
    def parse(self, ctx):
        if self.name in ctx.fn_table:
            return ctx.fn_table[self.name].parse(ctx)
        elif ctx.tokenizer.peek() is None:
            return BAD_PARSE
        # XXX check token name validity
        elif ctx.tokenizer.peek().type == self.name:
            t = ctx.tokenizer.next()
            return (t.value, t.info)
        return BAD_PARSE
    def __str__(self):
        return '"%s"' % self.name

# Parse a rule repeated at least <min> number of times (used for * and + in EBNF)
class Repeat:
    def __init__(self, rule, item, min=0):
        self.rule = rule
        self.item = item
        self.min = min
    def parse(self, ctx):
        results = []
        item = self.item.parse(ctx)
        while item is not BAD_PARSE:
            results.append(item)
            item = self.item.parse(ctx)
        if len(results) >= self.min:
            return ([item[0] for item in results], None)
        return BAD_PARSE
    def __str__(self):
        return 'rep(%s)' % self.item

# Parse a sequence of multiple consecutive rules
class Sequence:
    def __init__(self, rule, items):
        self.rule = rule
        self.items = items
    def parse(self, ctx):
        items = []
        pos = ctx.tokenizer.pos
        for item in self.items:
            r = item.parse(ctx)
            if r is BAD_PARSE:
                ctx.tokenizer.pos = pos
                return BAD_PARSE
            items.append(r)
        return [[item[i] for item in items] for i in range(2)]
    def __str__(self):
        return 'seq(%s)' % ','.join(map(str, self.items))

# Parse one of a choice of multiple rules
class Alternation:
    def __init__(self, rule, items):
        self.rule = rule
        self.items = items
    def parse(self, ctx):
        for item in self.items:
            r = item.parse(ctx)
            if r is not BAD_PARSE:
                return r
        return BAD_PARSE
    def __str__(self):
        return 'alt(%s)' % ','.join(map(str, self.items))

# Either parse a rule or not
class Optional:
    def __init__(self, rule, item):
        self.rule = rule
        self.item = item
    def parse(self, ctx):
        result = self.item.parse(ctx)
        return (None, None) if result is BAD_PARSE else result
    def __str__(self):
        return 'opt(%s)' % self.item

# Parse a rule, and then call a user-defined function on the result
class FnWrapper:
    def __init__(self, rule, prod, fn):
        # Make sure top-level rules are a sequence. When we pass parse results
        # to the user-defined function, it must be returned in an array, so we
        # can use the ParserResults class and have access to the parse info
        if not isinstance(prod, Sequence):
            prod = Sequence(rule, [prod])
        self.rule = rule
        self.prod = prod
        self.fn = fn
    def parse(self, ctx):
        result = self.prod.parse(ctx)
        if result is not BAD_PARSE:
            result, info = result
            return (self.fn(ParseResult(result, info)), None)
        return BAD_PARSE
    def __str__(self):
        return str(self.prod)

# Mini parser for our grammar specification language (basically EBNF)

def parse_repeat(rule, tokenizer, repeated):
    if tokenizer.accept('STAR'):
        return Repeat(rule, repeated)
    elif tokenizer.accept('PLUS'):
        return Repeat(rule, repeated, min=1)
    return repeated

def parse_rule_atom(rule, tokenizer):
    if tokenizer.accept('LPAREN'):
        r = parse_rule_expr(rule, tokenizer)
        tokenizer.expect('RPAREN')
        r = parse_repeat(rule, tokenizer, r)
    elif tokenizer.accept('LBRACKET'):
        r = Optional(rule, parse_rule_expr(rule, tokenizer))
        tokenizer.expect('RBRACKET')
    else:
        t = tokenizer.accept('IDENT')
        if t:
            r = parse_repeat(rule, tokenizer, Identifier(rule, t.value))
        else:
            raise RuntimeError('bad token: %s' % tokenizer.peek())
    return r

def parse_rule_seq(rule, tokenizer):
    r = []
    tok = tokenizer.peek()
    while tok and tok.type != 'RBRACKET' and tok.type != 'RPAREN' and tok.type != 'PIPE':
        r.append(parse_rule_atom(rule, tokenizer))
        tok = tokenizer.peek()
    if len(r) > 1:
        return Sequence(rule, r)
    return r[0] if r else None

def parse_rule_expr(rule, tokenizer):
    r = [parse_rule_seq(rule, tokenizer)]
    while tokenizer.accept('PIPE'):
        r.append(parse_rule_seq(rule, tokenizer))
    if len(r) > 1:
        return Alternation(rule, r)
    return r[0]

# ...And a mini lexer too

rule_tokens = {
    'IDENT': '[a-zA-Z_]+',
    'LBRACKET': '\[',
    'LPAREN': '\(',
    'PIPE': '\|',
    'RBRACKET': '\]',
    'RPAREN': '\)',
    'STAR': '\*',
    'PLUS': '\+',
    'WHITESPACE': ' ',
}
skip = {'WHITESPACE'}
rule_lexer = sprdpl.lex.Lexer(rule_tokens, skip)

# Decorator to add a function to a table of rules. Just because 'lambda' sucks.
def rule_fn(rule_table, rule, prod):
    def wrapper(fn):
        rule_table.append((rule, (prod, fn)))
        return fn
    return wrapper

class Parser:
    def __init__(self, rule_table, start):
        self.fn_table = {}
        for [rule, *prods] in rule_table:
            for prod in prods:
                fn = None
                if isinstance(prod, tuple):
                    prod, fn = prod
                self.create_rule(rule, prod, fn)
        self.start = start

    def create_rule(self, rule, prod, fn):
        prod = parse_rule_expr(rule, rule_lexer.input(prod))
        prod = FnWrapper(rule, prod, fn) if fn else prod
        if rule not in self.fn_table:
            self.fn_table[rule] = Alternation(rule, [])
        self.fn_table[rule].items.append(prod)

    def parse(self, tokenizer):
        prod = self.fn_table[self.start]
        result = prod.parse(Context(self.fn_table, tokenizer))
        if result is BAD_PARSE:
            raise RuntimeError('bad parse near token %s' % tokenizer.peek())
        elif tokenizer.peek() is not None:
            raise RuntimeError('parser did not consume entire input, near token %s' %
                tokenizer.peek())
        result, info = result
        return result
