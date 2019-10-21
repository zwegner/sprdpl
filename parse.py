import copy
import sys

from . import lex

class ParseError(SyntaxError):
    def __init__(self, tokenizer, msg, info=None):
        self.tokenizer = tokenizer
        self.msg = msg
        self.info = info
    def print(self):
        info = self.info or self.tokenizer.get_next_info()
        source_info = '%s(%s): ' % (info.filename, info.lineno) if info.filename else ''
        print('%sparse error: %s' % (source_info, self.msg), file=sys.stderr)
        line = self.tokenizer.get_source_line(info)
        if line.strip():
            print(line, file=sys.stderr)
            print(' ' * info.column + '^' * info.length, file=sys.stderr)

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
        self._ctx = ctx
        self.user_context = ctx.user_context
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
    def set_token_list(self, tokens):
        self._ctx.tokenizer.set_token_list(tokens)
    def error(self, msg, *indices):
        raise ParseError(self._ctx.tokenizer, msg, self.get_info(*indices))
    def clone(self, items=None, info=None):
        return ParseResult(self._ctx, items or self.items, info or self.info)

class Context:
    def __init__(self, rule_table, tokenizer, user_context=None):
        self.rule_table = rule_table
        self.tokenizer = tokenizer
        self.user_context = user_context

def unzip(results):
    return [[r[i] for r in results] for i in range(2)]

# Classes to represent grammar structure. These are hierarchically nested, and
# operate through the parse method, usually calling other rules' parse methods.

# Parse either a token or a nonterminal of the grammar
class Identifier:
    def __init__(self, name):
        self.name = name
    def parse(self, ctx):
        if self.name in ctx.rule_table:
            return ctx.rule_table[self.name].parse(ctx)
        # XXX check token name validity
        token = ctx.tokenizer.accept(self.name)
        if token:
            return (token.value, token.info)
        return None
    def __str__(self):
        return '"%s"' % self.name

# Parse a rule repeated at least <min> number of times (used for * and + in EBNF)
class Repeat:
    def __init__(self, item, min_reps=0):
        self.item = item
        self.min_reps = min_reps
    def parse(self, ctx):
        results = []
        item = self.item.parse(ctx)
        state = ctx.tokenizer.get_state()
        while item:
            results.append(item)
            item = self.item.parse(ctx)
        if len(results) >= self.min_reps:
            return unzip(results)
        ctx.tokenizer.restore_state(state)
        return None
    def __str__(self):
        return 'rep(%s)' % self.item

# Parse a sequence of multiple consecutive rules
class Sequence:
    def __init__(self, items):
        self.items = items
    def parse(self, ctx):
        results = []
        state = ctx.tokenizer.get_state()
        for item in self.items:
            result = item.parse(ctx)
            if not result:
                ctx.tokenizer.restore_state(state)
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

# Parse a rule and then call a user-defined function on the result
class FnWrapper:
    def __init__(self, rule, fn):
        # Make sure top-level rules are a sequence. When we pass parse results
        # to the user-defined function, it must be returned in an array, so we
        # can use the ParseResult class and have access to the parse info
        if not isinstance(rule, Sequence):
            rule = Sequence([rule])
        self.rule = rule
        self.fn = fn
    def parse(self, ctx):
        result = self.rule.parse(ctx)
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
        return str(self.rule)

# Mini parser for our grammar specification language (basically EBNF)

# After either a parenthesized group or an identifier, we accept * and + for
# repeating the aforementioned item (either zero or more times, or one or more)
def parse_repeat(tokenizer, repeated):
    if tokenizer.accept('STAR'):
        return Repeat(repeated)
    elif tokenizer.accept('PLUS'):
        return Repeat(repeated, min_reps=1)
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
# multi-statement functions, and thus we can't have all the functions directly inside a
# list, but this at least allows us to have the rule right by the function definition,
# without resorting to weird things like PLY's docstring handling
def rule_fn(rule_table, name, rule):
    def wrapper(fn):
        rule_table.append((name, (rule, fn)))
        return fn
    return wrapper

class Parser:
    def __init__(self, rule_table, start):
        self.rule_table = {}
        for [name, *rules] in rule_table:
            for rule in rules:
                fn = None
                if isinstance(rule, tuple):
                    rule, fn = rule
                self.create_rule(name, rule, fn)
        # Finalize rules: any time we see a alternation with just one rule, simplify it
        # to just the one rule. We keep every top-level rules inside alternations in case
        # it gets repeated, so we take that out where it's not necessary now.
        for name, rule in self.rule_table.items():
            if isinstance(rule, Alternation) and len(rule.items) == 1:
                self.rule_table[name] = rule.items[0]
        self.start = start

    def create_rule(self, name, rule, fn):
        # Parse the EBNF grammar specification for this rule
        rule = parse_rule_expr(rule_lexer.input(rule))

        # Wrap the rule in an FnWrapper class if the user has provided a handling function
        rule = FnWrapper(rule, fn) if fn else rule

        # Add the rule to our rule table. We store all top-level rules inside alternations, so
        # that adding two different rules for the same name is the same as adding them both inside
        # an alternation. For example, this:
        #   name: rule_1
        #   name: rule_2
        # ...is equivalent to:
        #   name: rule_1 | rule_2
        if name not in self.rule_table:
            self.rule_table[name] = Alternation([])
        self.rule_table[name].items.append(rule)

    def parse(self, tokenizer, start=None, user_context=None, lazy=False):
        rule = self.rule_table[start or self.start]
        ctx = Context(self.rule_table, tokenizer, user_context=user_context)
        try:
            result = rule.parse(ctx)
        except lex.LexError as e:
            # Kinda hacky, wrap LexErrors in ParseErrors since we don't have access to the
            # LexerContext where they are created
            raise ParseError(tokenizer, e.msg, e.info)

        fail = (not result or tokenizer.peek() is not None)

        # If we're in lazy mode, check if we didn't parse a full element but could have. If
        # there was a parse error, we will have given up before reaching the end of the token stream.
        if lazy and fail and tokenizer.got_to_end():
            return None

        if fail:
            message = ('bad token, expected one of the following: %s' %
                    ' '.join(sorted(tokenizer.max_expected_tokens)))
            raise ParseError(tokenizer, message, info=tokenizer.max_info)

        result, info = result
        return result
