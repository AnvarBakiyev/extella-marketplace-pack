# expert: diff_checker_compare
# description: Computes unified diff between two text inputs. Params: text_a (original text), text_b (modified text), context_lines (lines of context around changes, default 3). Returns JSON with output_type text co

def diff_checker_compare(text_a='', text_b='', context_lines='3'):
    import difflib, json
    try:
        lines_a = text_a.splitlines(keepends=True)
        lines_b = text_b.splitlines(keepends=True)
        diff = list(difflib.unified_diff(lines_a, lines_b, fromfile='Original (A)', tofile='Modified (B)', n=int(context_lines)))
        if not diff:
            result = '(no differences found — texts are identical)'
        else:
            result = ''.join(diff)
        return json.dumps({'status': 'success', 'output_type': 'text', 'data': result})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
