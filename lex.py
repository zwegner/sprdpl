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
        self.max_info = None
        self.max_expected_tokens = set()

    def get_source_line(self, info):
        start = self.text.rfind('\n', 0, info.textpos) + 1
        end = self.text.find('\n', info.textpos)
        return self.text[start:end]

    def token_at(self, pos):
        if pos >= len(self.tokens):
            return None
        return self.tokens[pos]

    # Basic wrappers to save/restore state. Right now this is just an index into the token stream.
    def get_state(self):
        return self.pos

    def restore_state(self, state):
        self.pos = state

    def peek(self):
        return self.token_at(self.pos)

    def get_max_token(self):
        return self.token_at(self.max_pos)

    def accept(self, token_type):
        token = self.peek()

        # Before we check whether this token is acceptable to the grammar, update the lexer
        # info about the furthest we were able to parse. We maintain a set of expected tokens
        # that could occur at this furthest point, so we can give the user a useful error message.
        if self.pos >= self.max_pos:
            if self.pos > self.max_pos:
                self.max_pos = self.pos
                self.max_info = token and token.info
                # Minor optimzation: only reallocate the token set if it's nonempty
                if self.max_expected_tokens:
                    self.max_expected_tokens = set()
            if token_type != None:
                self.max_expected_tokens.add(token_type)

        # Now check if this is the expected token type, and move forward in the token stream if so
        if token and token.type == token_type:
            self.pos += 1
            return token
        return None

    def expect(self, token_type):
        token = self.accept(token_type)
        if not token:
            raise RuntimeError('got %s instead of %s' % (self.peek(), t))
        return token
