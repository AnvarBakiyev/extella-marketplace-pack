# expert: ipaddr_js_parse
# description: Inspired by ipaddr.js — a JavaScript library for parsing, validating, and manipulating IPv4 and IPv6 addresses.

def ipaddr_js_parse(ip=''):
    import json, ipaddress
    try:
        addr = ipaddress.ip_address(ip.strip())
        return json.dumps({'status':'success','output_type':'json','data':{'ip':str(addr),'version':addr.version,'is_private':addr.is_private,'is_global':addr.is_global,'is_loopback':addr.is_loopback}})
    except Exception as e: return json.dumps({'status':'error','message':str(e)})
