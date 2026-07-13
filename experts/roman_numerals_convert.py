# expert: roman_numerals_convert
# description: Classic Roman numeral conversion — used in clocks, book chapters, movie credits, and outline numbering. Convert both directions instantly.

def roman_numerals_convert(value='', direction='to_roman'):
    import json, re
    vals = [(1000,'M'),(900,'CM'),(500,'D'),(400,'CD'),(100,'C'),(90,'XC'),(50,'L'),(40,'XL'),(10,'X'),(9,'IX'),(5,'V'),(4,'IV'),(1,'I')]
    rmap = {'I':1,'V':5,'X':10,'L':50,'C':100,'D':500,'M':1000}
    try:
        if direction == 'to_roman':
            n = int(value); result = ''
            for v, s in vals:
                while n >= v: result += s; n -= v
        else:
            s = value.upper().strip(); n = 0; prev = 0
            for ch in reversed(s):
                v = rmap.get(ch, 0)
                if v < prev: n -= v
                else: n += v; prev = v
            result = str(n)
        return json.dumps({'status':'success','output_type':'text','data':result})
    except Exception as e: return json.dumps({'status':'error','message':str(e)})
