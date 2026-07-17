# Как это устроено и как обновлять

`install-all.sh` — **единственная команда доставки** Extella коллеге (тулбар + эксперты + мост).

Полный процесс «как мёржить всё и всё вести» (три репо, каноны веток, чеклист релиза, аудит
«работает у всех») — в репо визарда: **`docs/RELEASE_AND_MERGE.md`**
(https://github.com/AnvarBakiyev/extella-adoption-wizard/blob/main/docs/RELEASE_AND_MERGE.md).

Команда для коллеги:
```bash
bash <(curl -fsSL https://raw.githubusercontent.com/AnvarBakiyev/extella-marketplace-pack/main/toolbar/install-all.sh)
```
