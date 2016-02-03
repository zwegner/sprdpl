import copy
import re

# Info means basically filename/line number, used for reporting errors
class Info:
    def __init__(self, filename, lineno=1, textpos=0, column=0, length=0):
        self.filename = filename
        self.lineno = lineno
        self.textpos = textpos
        self.column = column
        self.length = length
    def __str__(self):
        return 'Info("%s", %s, %s, %s)' % (self.filename, self.lineno, self.column, self.length)

class Token:
    def __init__(self, type, value, info=None):
        self.type = type
        self.value = value
        self.info = info
    def copy(self, type=None, value=None, info=None):
        c = copy.copy(self)
        if type is not None:  c.type = type
        if value is not None: c.value = value
        if info is not None:  c.info = info
        return c
    def __str__(self):
        return 'Token(%s, "%s", info=%s)' % (self.type, self.value, self.info)

class Lexer:
    def __init__(self, token_list):
        self._set_token_list(token_list)

    # This is used for setting the list of accepted tokens, either when the lexer
    # is first created, or when updating them while lexing is in flight (for supporting DSLs and such)
    def _set_token_list(self, token_list):
        self.token_fns = {}
        # If the token list is actually a dict, sort by longest regex first
        if isinstance(token_list, dict):
            token_list = sorted(token_list.items(), key=lambda item: -len(item[1]))
        sorted_tokens = []
        for k, v in token_list:
            if isinstance(v, tuple):
                v, fn = v
                self.token_fns[k] = fn
            sorted_tokens.append([k, v])
        regex = '|'.join('(?P<%s>%s)' % (k, v) for k, v in sorted_tokens)
        self.matcher = re.compile(regex).match

    def lex_input(self, text, filename):
        match = self.matcher(text)
        lineno = 1
        last_newline = 0
        while match is not None:
            type = match.lastgroup
            value = match.group(type)
            start, end = match.start(), match.end()

            token = Token(type, value)
            if type in self.token_fns:
                token = self.token_fns[type](token)
            # If the token isn't skipped, set the info and add it to the tokens list
            if token:
                token.info = Info(filename, lineno, start, start - last_newline, end - start)
                # This is actually a coroutine--check if the consumer has provided a new
                # set of tokens to accept.
                new_token_list = (yield token)
                if new_token_list:
                    self._set_token_list(new_token_list)

            if '\n' in value:
                lineno += value.count('\n')
                last_newline = end - value.rfind('\n')
            match = self.matcher(text, end)

    def input(self, text, filename=None):
        return LexerContext(text, self.lex_input(text, filename))

class LexerContext:
    def __init__(self, text, tokens):
        self.text = text
        self.tokens = list(tokens)
        self.pos = 0
        self.max_pos = 0

    def get_source_line(self, info):
        start = self.text.rfind('\n', 0, info.textpos) + 1
        end = self.text.find('\n', info.textpos)
        return self.text[start:end]

    def get_current_line(self):
        return self.get_source_line(self.peek().info)

    def token_at(self, pos):
        if pos >= len(self.tokens):
            return None
        return self.tokens[pos]

    def peek(self):
        return self.token_at(self.pos)

    def get_max_token(self):
        return self.token_at(self.max_pos)

    def next(self):
        token = self.peek()
        self.pos += 1
        self.max_pos = max(self.max_pos, self.pos)
        return token

    def accept(self, t):
        if self.peek() and self.peek().type == t:
            return self.next()
        return None

    def expect(self, t):
        if not self.peek() or self.peek().type != t:
            raise RuntimeError('got %s instead of %s' % (self.peek(), t))
        return self.next()
