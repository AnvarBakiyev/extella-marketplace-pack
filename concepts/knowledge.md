# concept: Базы знаний (RAG, локально)

Локальный RAG на устройстве (nomic-embed-text через Ollama, вектор-стор ~/.extella_kp). Данные не уходят.

## kp_resolver()
Ставит движок: Ollama (brew) + `ollama pull nomic-embed-text`. Вызвать один раз перед первой сборкой.

## kp_ingest(name, folder)
Собирает базу из папки (.txt/.md/.pdf): чанки + эмбеддинги локально.

## kp_install_pack(pack_id)
Ставит ГОТОВУЮ базу: кодексы РК (adilet) или статьи Википедии. pack_id: nalog_rk/trud_rk/grazhd_rk/admin_rk/pred_rk/ugol_rk (право); pm/management/sales/strategy/hr/fin_acc/invest/personal_fin/programming/ai_ml/security/databases/health/first_aid/space/eco.

## kp_ask(name, question)
Отвечает по базе (top-k поиск + синтез Qwen). Возвращает answer + sources.

ВАЖНО: kp_* работают НА УСТРОЙСТВЕ (локальный Ollama) — вызывать через мост тулбара/устройство, не с облачного run_expert.
