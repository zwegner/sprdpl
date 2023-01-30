import copy
import re

class LexError(SyntaxError):
    def __init__(self, msg, info=None):
        self.msg = msg
        self.info = info

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
    def __repr__(self):
        return 'Token(%s, %r, info=%s)' % (self.type, self.value, self.info)

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
        self.matcher = re.compile(regex, re.MULTILINE).match

    def lex_input(self, text, filename):
        match = self.matcher(text)
        lineno = 1
        last_newline = 0
        end = 0
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

            # If there's a newline in this token, bump the newline count, and save the position
            # of the last newline (so we know what column a given character is in)
            if '\n' in value:
                lineno += value.count('\n')
                last_newline = end - value.rfind('\n')
            match = self.matcher(text, end)

        # Check for invalid input--we didn't reach the end of the input
        if end != len(text):
            info = Info(filename, lineno, end, end - last_newline, 1)
            raise LexError('tokenizing error, invalid input', info=info)

    def input(self, text, filename=None):
        return LexerContext(text, self.lex_input(text, filename), filename)

class LexerContext:
    def __init__(self, text, token_stream, filename):
        self.text = text
        self.pos = 0

        # The token_stream argument is a generator from the lex_input() function above.
        # We iterate through it lazily, mostly so that lexing errors aren't raised until
        # we're actually parsing, not here in the constructor. This is kinda dumb.
        self.token_stream = iter(token_stream)
        self.token_cache = []

        # Variables to track the maximum position in the token stream we parsed to,
        # where that is in a file, and the set of token types that could've come next
        self.max_pos = 0
        self.max_info = None
        self.max_expected_tokens = set()

        self.filename = filename

    def get_source_line(self, info):
        start = self.text.rfind('\n', 0, info.textpos) + 1
        end = self.text.find('\n', info.textpos)
        # Special handling for the case where the last line doesn't have a trailing newline
        if end == -1:
            end = None
        return self.text[start:end]

    def token_at(self, pos):
        while self.token_stream and pos >= len(self.token_cache):
            try:
                self.token_cache.append(next(self.token_stream))
            except StopIteration:
                # Simple sentinel: take away the token stream when it's been consumed
                self.token_stream = None
        if pos >= len(self.token_cache):
            return None
        return self.token_cache[pos]

    def set_token_list(self, tokens):
        try:
            self.token_cache.append(self.token_stream.send(tokens))
        except StopIteration:
            # Simple sentinel: take away the token stream when it's been consumed
            self.token_stream = None

    def get_next_info(self):
        token = self.peek()
        if token:
            return token.info
        return Info(self.filename)

    # Basic wrappers to save/restore state. Right now this is just an index into the token stream.
    def get_state(self):
        return self.pos

    def restore_state(self, state):
        self.pos = state

    def peek(self):
        return self.token_at(self.pos)

    # Return whether we tried to parse past the end of the token stream. Useful for interactive
    # parsing.
    def got_to_end(self):
        return self.token_stream is None and self.max_pos == len(self.token_cache)

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

    # Kind of a silly function, provided for backwards compatibility
    def next(self):
        token = self.peek()
        return token and self.accept(token.type)

    def expect(self, token_type):
        token = self.accept(token_type)
        if not token:
            raise RuntimeError('got %s instead of %s' % (self.peek(), t))
        return token
