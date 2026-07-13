# expert: net_pay_calc
# description: Salary net pay estimator — calculate approximate take-home pay after income tax and social contributions. Useful for job offers and budgeting.

def net_pay_calc(gross_annual='60000', tax_rate='25'):
    import json
    try:
        g, r = float(gross_annual), float(tax_rate)/100
        tax = round(g*r,2); net = round(g-tax,2)
        return json.dumps({'status':'success','output_type':'json','data':{'gross_annual':g,'tax':tax,'net_annual':net,'net_monthly':round(net/12,2)}})
    except Exception as e: return json.dumps({'status':'error','message':str(e)})
