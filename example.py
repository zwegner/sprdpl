# Simple calculator program written using SPRDPL
import decimal

from . import lex
from . import parse

num_type = decimal.Decimal

table = {
    'PLUS':       r'\+',
    'MINUS':      r'-',
    'TIMES':      r'\*',
    'DIVIDE':     r'/',
    'POWER':      r'\^',
    'NUMBER':     (r'[0-9]+(\.[0-9]*)?|\.[0-9]+', lambda t: t.copy(value=num_type(t.value))),
    'LPAREN':     r'\(',
    'RPAREN':     r'\)',
    'WHITESPACE': (r' +', lambda t: None),
}
lexer = lex.Lexer(table)

def reduce_binop(p):
    r = p[0]
    for item in p[1]:
        if item[0] == '+':
            r = r + item[1]
        elif item[0] == '-':
            r = r - item[1]
        elif item[0] == '*':
            r = r * item[1]
        elif item[0] == '/':
            r = r / item[1]
    return r

rules = [
    ['atom', 'NUMBER', ('LPAREN expr RPAREN', lambda p: p[1])],
    ['factor', ('atom POWER factor', lambda p: p[0] ** p[2]), 'atom',
        ('MINUS factor', lambda p: -p[1])],
    ['term', ('factor ((TIMES|DIVIDE) factor)*', reduce_binop)],
    ['expr', ('term ((PLUS|MINUS) term)*', reduce_binop)],
]
parser = parse.Parser(rules, 'expr')

while True:
    try:
        line = input('>>> ')
    except EOFError:
        break
    try:
        result = parser.parse(lexer.input(line, filename='<stdin>'))
    except parse.ParseError as e:
        e.print()
    else:
        print('%s' % result)
