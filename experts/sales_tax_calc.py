# expert: sales_tax_calc
# description: Everyday sales tax calculator — add tax to a price or extract the pre-tax amount. Used by shoppers, freelancers, and small businesses worldwide.

def sales_tax_calc(amount='100', tax_rate='8.25', mode='add'):
    import json
    try:
        a, r = float(amount), float(tax_rate)/100
        if mode == 'add': tax = round(a*r,2); total = round(a+tax,2)
        else: total = a; base = round(a/(1+r),2); tax = round(a-base,2)
        return json.dumps({'status':'success','output_type':'json','data':{'subtotal':a if mode=='add' else base,'tax':tax,'total':total}})
    except Exception as e: return json.dumps({'status':'error','message':str(e)})
