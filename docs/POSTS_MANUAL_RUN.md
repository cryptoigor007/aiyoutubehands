# Ручной прогон «Записи» на macOS

Чеклист для владельца канала / агента на Маке.

## Подготовка (один раз)

1. Safari → меню **Develop** → включить **Allow JavaScript from Apple Events**.
   Если меню Develop нет: Safari → Settings → Advanced → Show Develop menu.
2. Для картинки: **Системные настройки → Конфиденциальность и безопасность → Универсальный доступ**
   — добавить Terminal (или iTerm / ваш терминал / Python).
3. В `~/.config/aiyoutubehands/config.yaml` должен быть:
   ```yaml
   channel:
     expected_channel_id: "UC…"
   ```

## Тест 1 — dry-run (обязательно)

```bash
cd ~/aiyoutubehands-v0.2   # или путь к клону с веткой feat/community-posts
git checkout feat/community-posts
PYTHONPATH=src python -m aiyoutubehands.main post create --text-file /tmp/post.txt
```

Ожидание: план, URL с `show_create_dialog=1`, hash, фраза подтверждения. Safari не открывается.

## Тест 2 — текст без картинки

```bash
echo "Тестовая запись $(date +%H:%M)" > /tmp/post.txt
PYTHONPATH=src python -m aiyoutubehands.main post create \
  --text-file /tmp/post.txt --no-dry-run --yes
```

Ожидание: Safari открывает диалог, текст вставляется, кнопка «Опубликовать», пост на `/posts`.

## Тест 3 — с картинкой (квадрат 1080×1080, ≤16 МБ)

```bash
# подготовить квадратный JPG/PNG
PYTHONPATH=src python -m aiyoutubehands.main post create \
  --text-file /tmp/post.txt --image /path/to/square.jpg --no-dry-run --yes
```

Ожидание: либо пост **с** картинкой, либо явная ошибка (Accessibility / attach).  
**Не** должно быть молчаливого поста без картинки.

## Верификация успеха

Открыть вручную:
`https://www.youtube.com/channel/<CHANNEL_ID>/posts`

Пост должен быть виден. Ответ CLI «OK» сам по себе не доказательство.

## Если упало

| Симптом | Действие |
|---------|----------|
| osascript / Safari unavailable | Только macOS; проверьте Develop → Allow JS from Apple Events |
| placeholder / contenteditable timeout | Страница не догрузилась; увеличьте паузы или откройте URL вручную |
| «Не удалось опубликовать запись» | Сервер отклонил; проверьте текст/картинку вручную в Studio |
| Accessibility denied | Добавьте терминал в Универсальный доступ |
| Картинка не прикрепилась | Снять HAR ручного выбора или доработать System Events |

## Тесты (кроссплатформенные)

```bash
PYTHONPATH=src pytest tests/test_posts_js.py tests/test_posts_models.py tests/test_posts_cli.py -v
```
