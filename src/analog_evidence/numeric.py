"""Bounded Decimal expression evaluator; deliberately no eval/exec."""
import re
from decimal import Decimal, DecimalException, localcontext


class NumericError(ValueError):
    pass


TOKEN = re.compile(r'\s*(?:(\d+(?:\.\d*)?|\.\d+)([eE][+-]?\d+)?([A-Za-z]+)?|([A-Za-z_]\w*)|([()+*/-]))')
SUFFIX = {
    'spectre': {'T':12,'G':9,'M':6,'K':3,'k':3,'m':-3,'u':-6,'n':-9,'p':-12,'f':-15,'a':-18},
    'cdl': {'t':12,'g':9,'meg':6,'k':3,'m':-3,'u':-6,'n':-9,'p':-12,'f':-15,'a':-18},
}


def scalar(expr, dialect, environment=None, stack=()):
    if not isinstance(expr, str) or len(expr)>4096 or len(stack)>32:
        raise NumericError('expression budget exceeded')
    environment = environment or {}
    tokens=[]; pos=0
    while pos<len(expr.rstrip()):
        m=TOKEN.match(expr,pos)
        if not m: raise NumericError('unsupported expression')
        number, exponent, suffix, name, op=m.groups(); pos=m.end()
        if number:
            e=int((exponent or 'e0')[1:])
            if abs(e)>100: raise NumericError('exponent outside static subset')
            key=(suffix or '').lower() if dialect=='cdl' else (suffix or '')
            if key and key not in SUFFIX[dialect]: raise NumericError('unsupported suffix')
            tokens.append(Decimal(number)*(Decimal(10)**(e+SUFFIX[dialect].get(key,0))))
        else: tokens.append(name or op)
    if not tokens or len(tokens)>512: raise NumericError('empty or oversized expression')
    index=0
    def atom(depth=0):
        nonlocal index
        if depth>32 or index>=len(tokens): raise NumericError('missing operand or nesting limit')
        t=tokens[index];index+=1
        if isinstance(t, Decimal): return t
        if t in ('+','-'): return atom(depth+1)*(1 if t=='+' else -1)
        if t=='(':
            n=expression(depth+1)
            if index>=len(tokens) or tokens[index]!=')': raise NumericError('unbalanced parentheses')
            index+=1;return n
        if isinstance(t,str) and t in environment:
            if t in stack: raise NumericError('cyclic parameter')
            value=environment[t]
            return value if isinstance(value,Decimal) else scalar(value,dialect,environment,stack+(t,))
        raise NumericError('unresolved symbol')
    def product(depth):
        nonlocal index
        n=atom(depth)
        while index<len(tokens) and tokens[index] in ('*','/'):
            op=tokens[index];index+=1;r=atom(depth)
            n=n*r if op=='*' else n/r
        return n
    def expression(depth):
        nonlocal index
        n=product(depth)
        while index<len(tokens) and tokens[index] in ('+','-'):
            op=tokens[index];index+=1;r=product(depth)
            n=n+r if op=='+' else n-r
        return n
    try:
        with localcontext() as ctx:
            ctx.prec=50
            result=expression(0)
        if index!=len(tokens) or not result.is_finite() or abs(result.adjusted())>200:
            raise NumericError('unsupported expression remainder or magnitude')
        return result
    except (DecimalException, ZeroDivisionError, RecursionError) as exc:
        raise NumericError(str(exc)) from exc


def decimal_text(value):
    if value==0:return '0'
    text=format(value, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text
