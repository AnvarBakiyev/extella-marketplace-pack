# expert: compound_interest_compute
# description: Calculates compound interest with optional monthly contributions. Params: principal, annual_rate (%), years, compound_freq (daily/monthly/quarterly/annually), monthly_contribution (default 0). Returns

def compound_interest_compute(principal='10000', annual_rate='7', years='10', compound_freq='monthly', monthly_contribution='0'):
    import json
    try:
        p = float(principal)
        r = float(annual_rate) / 100
        t = int(years)
        mc = float(monthly_contribution)
        n_map = {'daily': 365, 'monthly': 12, 'quarterly': 4, 'annually': 1}
        n = n_map.get(compound_freq.lower(), 12)
        yearly = []
        balance = p
        for yr in range(1, t + 1):
            for _ in range(n):
                balance = balance * (1 + r / n)
                if mc > 0 and n > 1: balance += mc * (12 / n)
            if mc > 0 and n == 1: balance += mc * 12
            total_contributed = p + mc * 12 * yr
            yearly.append({'year': yr, 'balance': round(balance, 2), 'total_contributed': round(total_contributed, 2), 'interest_earned': round(balance - total_contributed, 2)})
        total_contributed = p + mc * 12 * t
        result = {'principal': p, 'annual_rate': float(annual_rate), 'years': t, 'compound_freq': compound_freq, 'monthly_contribution': mc, 'final_balance': round(balance, 2), 'total_contributed': round(total_contributed, 2), 'total_interest_earned': round(balance - total_contributed, 2), 'yearly_growth': yearly}
        return json.dumps({'status': 'success', 'output_type': 'json', 'data': result})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
