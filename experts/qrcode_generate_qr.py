# expert: qrcode_generate_qr
# description: Generates a QR code PNG image from text or URL using the qrserver.com API. Params: data — text or URL to encode; size — image width/height in pixels (default 300); fill_hex — QR module color as hex wi

def qrcode_generate_qr(data="",size="300",fill_hex="000000",back_hex="FFFFFF",ecl="M"):
    import urllib.request, urllib.parse, base64, json
    try:
        params = urllib.parse.urlencode({"size":size+"x"+size,"data":data,"color":fill_hex,"bgcolor":back_hex,"ecc":ecl})
        url = "https://api.qrserver.com/v1/create-qr-code/?"+params
        r = urllib.request.urlopen(url,timeout=15)
        b64 = base64.b64encode(r.read()).decode()
        return json.dumps({"status":"success","output_type":"image_base64","data":b64,"filename":"qrcode.png"})
    except Exception as e:
        return json.dumps({"status":"error","message":str(e)})
