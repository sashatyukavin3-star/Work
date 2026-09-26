# Repo Agent Bot

Telegram-интерфейс к автономному coding agent. Бот принимает ссылку на GitHub-репозиторий, ведёт контекстный диалог о задаче, изучает и изменяет код, запускает проверки в отдельном Docker-контейнере, создаёт ветку и pull request, а затем отправляет отчёт, patch и доступные артефакты в Telegram.

> **Важно:** токен Telegram, опубликованный в чате или коммите, считается скомпрометированным. Выпустите новый токен через [@BotFather](https://t.me/BotFather) командой `/revoke`. Секреты задаются только через `.env`, который не коммитится.

## Что умеет первая версия

- публичные и приватные GitHub-репозитории;
- белый список Telegram user ID и репозиториев/владельцев;
- обычный диалог: ссылка отдельно или ссылка вместе с задачей;
- сохранение краткого контекста последующих сообщений;
- OpenAI-compatible API с function/tool calling (OpenAI, SambaNova или другой совместимый провайдер);
- инструменты агента для чтения, точечного редактирования и запуска команд;
- Docker sandbox без GitHub/Telegram/AI-токенов внутри;
- тесты/линтер/сборка по решению агента;
- commit, отдельная ветка `agent/telegram-*`, push и pull request;
- отправка артефактов до заданного размера и `.patch` в Telegram;
- `/status`, `/repo`, `/cancel`, `/reset`.

Сам текущий сеанс Arena не может постоянно работать внутри Telegram. Этот сервис воспроизводит поведение coding agent через выбранный вами AI API. Качество результата зависит от модели; модель должна поддерживать OpenAI-style tool calls.

## 1. Безопасно перевыпустите токен

1. Откройте `@BotFather`.
2. Выполните `/revoke`, выберите бота и получите новый токен.
3. Никому не отправляйте новый токен и не добавляйте его в Git.

Узнать свой числовой Telegram user ID можно у `@userinfobot`. Бот также показывает ID при попытке входа пользователя, которого нет в allowlist.

## 2. GitHub-доступ

Рекомендуется создать **fine-grained personal access token** только для нужных репозиториев:

- Repository access: только выбранные репозитории;
- Contents: Read and write;
- Pull requests: Read and write;
- Metadata: Read-only.

Ещё безопаснее GitHub App с короткоживущим installation token, но текущая версия ожидает готовый токен в `GITHUB_TOKEN`. Токен используется оркестратором для clone/push/PR и не передаётся AI или worker-контейнеру.

## 3. Настройка

```bash
cp .env.example .env
chmod 600 .env
```

Обязательные значения:

```dotenv
TELEGRAM_BOT_TOKEN=новый-токен-от-BotFather
TELEGRAM_ALLOWED_USERS=123456789
AI_API_KEY=...
AI_BASE_URL=https://api.openai.com/v1
AI_MODEL=gpt-4.1
GITHUB_TOKEN=github_pat_...
GITHUB_REPOSITORY_ALLOWLIST=my-login,my-org/exact-private-repo
```

Allowlist репозиториев принимает:

- `owner` — разрешить все репозитории владельца;
- `owner/repository` — разрешить ровно один репозиторий.

Пустой `TELEGRAM_ALLOWED_USERS` или `GITHUB_REPOSITORY_ALLOWLIST` никому ничего не разрешает.

### SambaNova

Укажите OpenAI-compatible endpoint и модель, доступные в вашем аккаунте, например:

```dotenv
AI_BASE_URL=https://api.sambanova.ai/v1
AI_MODEL=имя-модели-с-tool-calling
AI_API_KEY=...
```

Не каждая модель провайдера поддерживает tool calling — это обязательное требование этого агента.

## 4. Запуск на Linux-хосте (рекомендуется)

Нужны Python 3.11+, Git и Docker.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
set -a; . ./.env; set +a
repo-agent-bot
```

Бот использует long polling, поэтому публичный домен и webhook не требуются.

По умолчанию `SANDBOX_NETWORK=none`: worker не может скачать зависимости или отправить приватный код наружу. Для сборки с загрузкой пакетов можно поставить `SANDBOX_NETWORK=bridge`, **но только для доверенных репозиториев**. Даже без секретов prompt injection в содержимом чужого репозитория может попытаться передать исходный код наружу.

Образ worker по умолчанию — `ghcr.io/cirruslabs/flutter:stable`, потому что он умеет собирать Flutter/Android-проект из этого репозитория. Для другого стека задайте `SANDBOX_IMAGE`, например внутренний образ с Node, Go или Rust. AI-команды выполняются внутри этого одноразового образа.

## Запуск через Docker Compose

Compose запускает bot-контейнер, а тот создаёт изолированные worker-контейнеры через Docker socket. Укажите абсолютный каталог хоста:

```dotenv
HOST_DATA_DIR=/opt/repo-agent/data
```

Затем:

```bash
mkdir -p /opt/repo-agent/data
docker compose up -d --build
docker compose logs -f bot
```

Монтирование Docker socket даёт контейнеру оркестратора высокий уровень доступа к хосту. Не запускайте непроверенный образ самого бота и обязательно ограничьте Telegram/GitHub allowlist.

## Использование

Отправьте боту:

```text
https://github.com/acme/mobile-app
```

Затем обычную задачу:

```text
Проанализируй приложение, исправь критичные ошибки, добавь тесты и собери release APK.
```

Или одним сообщением:

```text
https://github.com/acme/mobile-app Добавь экран настроек и собери APK
```

Результат включает отчёт, проверки, список изменённых файлов, PR/ветку, patch и артефакты, явно указанные агентом.

## Ограничения и модель угроз

- Выполнение кода из репозитория всегда рискованно; Docker sandbox обязателен для недоверенного кода.
- Worker не получает секреты оркестратора, Docker socket или каталоги вне отдельного checkout.
- Для рассуждения модель получает прочитанные агентом фрагменты исходного кода. Для приватных проектов используйте AI-провайдера с подходящей политикой хранения данных или собственный endpoint.
- `SANDBOX_MODE=local` запускает команды прямо на сервере. Секретные переменные из окружения удаляются, но полноценной изоляции нет — используйте режим только в одноразовой VM и для доверенного кода.
- Файлы больше 10 МБ автоматически не добавляются в commit. Telegram-лимит настраивается через `MAX_TELEGRAM_ARTIFACT_MB`.
- Задача не переживает перезапуск процесса; в БД она будет отмечена как failed.
- Для production стоит заменить постоянный GitHub PAT на GitHub App installation tokens, добавить очередь задач и отдельные worker-ноды.

## Разработка

```bash
python -m pip install -e '.[dev]'
ruff check .
pytest
```

Flutter-приложение «Альтернативная жизнь» из исходного репозитория сохранено в `lib/` и продолжает собираться workflow `Build APK`. Код Telegram-сервиса находится в `repo_agent_bot/`.
