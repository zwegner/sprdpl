import copy
import sys

from . import lex

class ParseError(SyntaxError):
    def __init__(self, tokenizer, msg, info=None):
        self.tokenizer = tokenizer
        self.msg = msg
        self.info = info
    def print_and_exit(self):
        info = self.info or self.tokenizer.peek().info
        print('%s(%s): parse error: %s' % (info.filename, info.lineno, self.msg), file=sys.stderr)
        print(self.tokenizer.get_source_line(info), file=sys.stderr)
        print(' ' * info.column + '^' * info.length, file=sys.stderr)
        sys.exit(1)

def merge_info_list(info):
    first = last = info
    while isinstance(first, list):
        for item in first:
            if item:
                first = item
                break
        else:
            return None
    while isinstance(last, list):
        for i in reversed(last):
            if i:
                last = i
                break
        else:
            assert False
    info = copy.copy(first)
    info.length = last.length + (last.textpos - first.textpos)
    return info

# ParseResult works like a tuple for the results of parsed rules, but with an
# additional .get_info(n...) method for getting line-number information out
class ParseResult:
    def __init__(self, ctx, items, info):
        self.ctx = ctx
        self.items = items
        self.info = info
    def __getitem__(self, n):
        return self.items[n]
    def get_info(self, *indices):
        info = self.info
        for index in indices:
            info = info[index]
        if isinstance(info, list):
            info = merge_info_list(info)
        return info
    def error(self, msg, *indices):
        raise ParseError(self.ctx.tokenizer, msg, self.get_info(*indices))
    def clone(self, items=None, info=None):
        return ParseResult(self.ctx, items or self.items, info or self.info)

class Context:
    def __init__(self, fn_table, tokenizer):
        self.fn_table = fn_table
        self.tokenizer = tokenizer

def unzip(results):
    return [[r[i] for r in results] for i in range(2)]

# Classes to represent grammar structure. These are hierarchically nested, and
# operate through the parse method, usually calling other rules' parse methods.

# Parse either a token or a nonterminal of the grammar
class Identifier:
    def __init__(self, name):
        self.name = name
    def parse(self, ctx):
        if self.name in ctx.fn_table:
            return ctx.fn_table[self.name].parse(ctx)
        # XXX check token name validity
        token = ctx.tokenizer.accept(self.name)
        if token:
            return (token.value, token.info)
        return None
    def __str__(self):
        return '"%s"' % self.name

# Parse a rule repeated at least <min> number of times (used for * and + in EBNF)
class Repeat:
    def __init__(self, item, min=0):
        self.item = item
        self.min = min
    def parse(self, ctx):
        results = []
        item = self.item.parse(ctx)
        while item:
            results.append(item)
            item = self.item.parse(ctx)
        if len(results) >= self.min:
            return unzip(results)
        return None
    def __str__(self):
        return 'rep(%s)' % self.item

# Parse a sequence of multiple consecutive rules
class Sequence:
    def __init__(self, items):
        self.items = items
    def parse(self, ctx):
        results = []
        pos = ctx.tokenizer.pos
        for item in self.items:
            result = item.parse(ctx)
            if not result:
                ctx.tokenizer.pos = pos
                return None
            results.append(result)
        return unzip(results)
    def __str__(self):
        return 'seq(%s)' % ','.join(map(str, self.items))

# Parse one of a choice of multiple rules
class Alternation:
    def __init__(self, items):
        self.items = items
    def parse(self, ctx):
        for item in self.items:
            result = item.parse(ctx)
            if result:
                return result
        return None
    def __str__(self):
        return 'alt(%s)' % ','.join(map(str, self.items))

# Either parse a rule or not
class Optional:
    def __init__(self, item):
        self.item = item
    def parse(self, ctx):
        return self.item.parse(ctx) or (None, None)
    def __str__(self):
        return 'opt(%s)' % self.item

# Parse a and then call a user-defined function on the result
class FnWrapper:
    def __init__(self, prod, fn):
        # Make sure top-level rules are a sequence. When we pass parse results
        # to the user-defined function, it must be returned in an array, so we
        # can use the ParseResult class and have access to the parse info
        if not isinstance(prod, Sequence):
            prod = Sequence([prod])
        self.prod = prod
        self.fn = fn
    def parse(self, ctx):
        result = self.prod.parse(ctx)
        if result:
            result, info = result
            result = self.fn(ParseResult(ctx, result, info))
            if isinstance(result, ParseResult):
                result, info = result.items, result.info
            else:
                info = merge_info_list(info)
            return (result, info)
        return None
    def __str__(self):
        return str(self.prod)

# Mini parser for our grammar specification language (basically EBNF)

# After either a parenthesized group or an identifier, we accept * and + for
# repeating the aforementioned item (either zero or more times, or one or more)
def parse_repeat(tokenizer, repeated):
    if tokenizer.accept('STAR'):
        return Repeat(repeated)
    elif tokenizer.accept('PLUS'):
        return Repeat(repeated, min=1)
    return repeated

def parse_rule_atom(tokenizer):
    # Parenthesized rules: just used for grouping
    if tokenizer.accept('LPAREN'):
        result = parse_rule_expr(tokenizer)
        tokenizer.expect('RPAREN')
        result = parse_repeat(tokenizer, result)
    # Bracketed rules are entirely optional
    elif tokenizer.accept('LBRACKET'):
        result = Optional(parse_rule_expr(tokenizer))
        tokenizer.expect('RBRACKET')
    # Otherwise, it must be a regular identifier
    else:
        token = tokenizer.expect('IDENTIFIER')
        result = parse_repeat(tokenizer, Identifier(token.value))
    return result

# Parse the concatenation of one or more expressions
def parse_rule_seq(tokenizer):
    items = []
    token = tokenizer.peek()
    while (token and token.type != 'RBRACKET' and token.type != 'RPAREN' and
            token.type != 'PIPE'):
        items.append(parse_rule_atom(tokenizer))
        token = tokenizer.peek()
    # Only return a sequence if there's multiple items, otherwise there's way
    # too many [0]s when extracting parsed items in complicated rules
    if len(items) > 1:
        return Sequence(items)
    return items[0] if items else None

# Top-level parser, parse any number of sequences, joined by the alternation
# operator, |
def parse_rule_expr(tokenizer):
    items = [parse_rule_seq(tokenizer)]
    while tokenizer.accept('PIPE'):
        items.append(parse_rule_seq(tokenizer))
    if len(items) > 1:
        return Alternation(items)
    return items[0]

# ...And a mini lexer too

rule_tokens = {
    'IDENTIFIER': r'[a-zA-Z_]+',
    'LBRACKET':   r'\[',
    'LPAREN':     r'\(',
    'PIPE':       r'\|',
    'RBRACKET':   r'\]',
    'RPAREN':     r'\)',
    'STAR':       r'\*',
    'PLUS':       r'\+',
    'WHITESPACE': (r' ', lambda t: None),
}
rule_lexer = lex.Lexer(rule_tokens)

# Decorator to add a function to a table of rules. We can't use lambda for
# multi-statement functions, and thus have all the functions directly inside a
# list, but this at least allows us to have the rule right by the function definition.
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
        # Finalize rules: any time we see a Alternation with just one rule, simplify it
        # to just the one rule. We keep every rule inside an alternation at the top level
        # in case it gets repeated (meaning that giving two different productions for a
        # rule is the same as giving them both as an alternation, like P1|P2). This just
        # undoes that.
        for rule, prod in self.fn_table.items():
            if isinstance(prod, Alternation) and len(prod.items) == 1:
                self.fn_table[rule] = prod.items[0]
        self.start = start

    def create_rule(self, rule, prod, fn):
        prod = parse_rule_expr(rule_lexer.input(prod))
        prod = FnWrapper(prod, fn) if fn else prod
        if rule not in self.fn_table:
            self.fn_table[rule] = Alternation([])
        self.fn_table[rule].items.append(prod)

    def parse(self, tokenizer):
        prod = self.fn_table[self.start]
        ctx = Context(self.fn_table, tokenizer)
        result = prod.parse(ctx)
        if not result:
            raise ParseError(tokenizer, 'bad parse')
        elif tokenizer.peek() is not None:
            message = ('bad token, expected one of the following: %s' %
                    ' '.join(tokenizer.max_expected_tokens))
            raise ParseError(tokenizer, message, info=tokenizer.max_info)
        result, info = result
        return result
