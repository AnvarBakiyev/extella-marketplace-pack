# expert: lorem_ipsum_generator_generate
# description: Generates Lorem Ipsum placeholder text. Params: unit (paragraphs/sentences/words), count (1-20), start_with_lorem (bool). Returns JSON with output_type text.

def lorem_ipsum_generator_generate(unit='paragraphs', count='3', start_with_lorem='true'):
    import random, json
    words = ['lorem','ipsum','dolor','sit','amet','consectetur','adipiscing','elit','sed','do','eiusmod','tempor','incididunt','ut','labore','et','dolore','magna','aliqua','enim','ad','minim','veniam','quis','nostrud','exercitation','ullamco','laboris','nisi','aliquip','ex','ea','commodo','consequat','duis','aute','irure','in','reprehenderit','voluptate','velit','esse','cillum','eu','fugiat','nulla','pariatur','excepteur','sint','occaecat','cupidatat','non','proident','sunt','culpa','qui','officia','deserunt','mollit','anim','id','est','laborum','curabitur','pretium','tincidunt','lacus','nunc','pulvinar','sapien','ligula','eget','semper','urna','interdum','libero']
    def make_sentence(n):
        w = [random.choice(words) for _ in range(n)]
        return w[0].capitalize() + ' ' + ' '.join(w[1:]) + '.'
    def make_paragraph():
        return ' '.join(make_sentence(random.randint(10, 20)) for _ in range(random.randint(4, 7)))
    start = str(start_with_lorem).lower() in ('true', '1', 'yes')
    n = min(max(int(count), 1), 20)
    if unit == 'words':
        wlist = [random.choice(words) for _ in range(n)]
        if start: wlist[0] = 'Lorem'
        result = ' '.join(wlist)
    elif unit == 'sentences':
        sents = [make_sentence(random.randint(8, 18)) for _ in range(n)]
        if start: sents[0] = 'Lorem ipsum dolor sit amet, consectetur adipiscing elit.'
        result = ' '.join(sents)
    else:
        paras = [make_paragraph() for _ in range(n)]
        if start: paras[0] = 'Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.'
        result = '\n\n'.join(paras)
    return json.dumps({'status': 'success', 'output_type': 'text', 'data': result})
