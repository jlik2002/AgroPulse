# Каталог обмена файлами

Сюда кладётся `private_features.csv` для batch-инференса, сюда же пишется
`submission.csv`. Каталог смонтирован в контейнер как `/app/data`.

Содержимое, кроме этого файла, в репозиторий не попадает.

```bash
docker compose run --rm --user "$(id -u):$(id -g)" api \
  python -m agropulse.cli predict \
    --input /app/data/private_features.csv \
    --output /app/data/submission.csv
```
