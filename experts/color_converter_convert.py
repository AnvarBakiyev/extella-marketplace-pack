# expert: color_converter_convert
# description: Converts a color from HEX, RGB or HSL to all other formats. Params: color (color string), input_format (hex/rgb/hsl). Returns JSON with output_type json showing hex, rgb, hsl and hsv values.

def color_converter_convert(color='#FF5733', input_format='hex'):
    import colorsys, json, re
    try:
        color = color.strip()
        if input_format == 'hex':
            c = color.lstrip('#')
            if len(c) == 3: c = c[0]*2 + c[1]*2 + c[2]*2
            r, g, b = int(c[0:2],16)/255, int(c[2:4],16)/255, int(c[4:6],16)/255
        elif input_format == 'rgb':
            nums = [float(x.strip()) for x in re.split(r'[,\s]+', color) if x.strip()]
            r, g, b = nums[0]/255, nums[1]/255, nums[2]/255
        else:
            nums = [float(re.sub(r'[^\d.]', '', x)) for x in re.split(r'[,\s]+', color) if x.strip()]
            h, s, l = nums[0]/360, nums[1]/100, nums[2]/100
            r, g, b = colorsys.hls_to_rgb(h, l, s)
        ri, gi, bi = int(r*255), int(g*255), int(b*255)
        h, l, s = colorsys.rgb_to_hls(r, g, b)
        hv, sv, v = colorsys.rgb_to_hsv(r, g, b)
        result = {'hex': '#{:02X}{:02X}{:02X}'.format(ri,gi,bi), 'rgb': 'rgb({},{},{})'.format(ri,gi,bi), 'hsl': 'hsl({},{}%,{}%)'.format(round(h*360), round(s*100), round(l*100)), 'hsv': 'hsv({},{}%,{}%)'.format(round(hv*360), round(sv*100), round(v*100)), 'components': {'r': ri, 'g': gi, 'b': bi}}
        return json.dumps({'status': 'success', 'output_type': 'json', 'data': result})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
