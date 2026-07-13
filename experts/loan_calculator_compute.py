# expert: loan_calculator_compute
# description: Calculates loan EMI and total interest. Params: principal (loan amount), annual_rate (interest rate in %), years (loan term). Returns JSON with output_type json containing monthly_payment, total_inter

def loan_calculator_compute(principal='200000', annual_rate='5.5', years='20'):
    import json
    try:
        p = float(principal)
        r = float(annual_rate) / 100 / 12
        n = int(years) * 12
        if r == 0:
            emi = round(p / n, 2)
        else:
            emi = round(p * r * (1 + r)**n / ((1 + r)**n - 1), 2)
        total = round(emi * n, 2)
        total_interest = round(total - p, 2)
        yearly = []
        balance = p
        for yr in range(1, min(int(years) + 1, 31)):
            yr_interest = 0; yr_principal = 0
            for _ in range(12):
                i = round(balance * r, 2)
                pp = min(emi - i, balance)
                balance -= pp
                yr_interest += i; yr_principal += pp
                if balance <= 0: break
            yearly.append({'year': yr, 'principal_paid': round(yr_principal, 2), 'interest_paid': round(yr_interest, 2), 'balance': round(max(0, balance), 2)})
            if balance <= 0: break
        result = {'principal': p, 'annual_rate': float(annual_rate), 'years': int(years), 'monthly_payment': emi, 'total_amount': total, 'total_interest': total_interest, 'yearly_schedule': yearly}
        return json.dumps({'status': 'success', 'output_type': 'json', 'data': result})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
