# expert: bcrypt_hash_compute
# description: Inspired by bcrypt.js.

def bcrypt_hash_compute(password='', algorithm='scrypt'):
    import hashlib, json, secrets
    try:
        if algorithm=='scrypt': salt=secrets.token_hex(16); h=hashlib.scrypt(password.encode(),salt=salt.encode(),n=16384,r=8,p=1,dklen=64); return json.dumps({'status':'success','output_type':'json','data':{'hash':h.hex(),'salt':salt}})
        return json.dumps({'status':'success','output_type':'json','data':{'hash':hashlib.sha256(password.encode()).hexdigest()}})
    except Exception as e: return json.dumps({'status':'error','message':str(e)})
