# Порядок выпуска версии

Файл для того, кто ведёт разработку пака. В архив реестра не уезжает —
`docs/release/` исключён в `.comfyignore`.

Порядок шагов здесь не косметический: каждый пункт «сначала это, потом то»
оплачен конкретной поломкой, они перечислены в конце.

## Шаги

1. **`CHANGELOG.md` — новый раздел сверху.** Заголовок строго
   `## X.Y.Z (ГГГГ-ММ-ДД)`. По этому заголовку воркфлоу публикации вырезает
   текст для страницы релиза на GitHub: раздел от заголовка до следующего
   `## `. Формат заголовка сломается — релиз выйдет с пустым описанием.

2. **Номер версии в пяти местах.**
   - `pyproject.toml` (`version = "X.Y.Z"`)
   - `common/brand.py` (`EXTENSION_VERSION = "X.Y.Z"`)
   - `frontend/package.json` (`version = "X.Y.Z"`)
   - `frontend/package-lock.json` (в корне и в `packages[""]` — проще всего выполнить `npm install` в `frontend/`)
   - `docs/index.html` (версия в шапке и футере)

3. **Синхронизация контрактов (если менялись ноды или виджеты).**
   - Файлы в `common/contracts/nodes/` **никогда не должны импортировать** `comfy` или модули с рантайм-зависимостями (тяжелые движки). Контракты должны быть легковесными (Pydantic).
   - Если менялись виджеты или добавлялись ноды:
     ```bash
     cd frontend && npm run gen:contracts
     ```
   - Проверить совпадение `min_size` в Python-контракте и `minSize` в TypeScript-файле ноды.

4. **Сборка фронтенда — строго ПОСЛЕ смены номера и генерации контрактов.**

   ```bash
   cd frontend && npm run build
   ```

   Порядок именно такой, потому что `npm run build` записывает в
   `dist/.source-hash` отпечаток того, из чего собран бандл, а в этот
   отпечаток входят и `package-lock.json`, и сгенерированные `contracts.ts/json`.
   Соберёте до смены номера или генерации — отпечаток окажется от старых файлов,
   и проверка `check:bundle` покраснеет в CI.

5. **Проверки (до коммита).**

   - Python тесты и линтер:
     ```powershell
     ruff check .
     python -m pytest tests/ -v --tb=short -q
     python tools/preflight_check.py
     python tools/scan_node_conflicts.py
     ```
   - Frontend тесты и аудит контрактов/бандла:
     ```powershell
     cd frontend
     npm run check:contracts
     npm run check:bundle
     npm run lint
     npm test
     ```

6. **Коммит.** Собранный `frontend/dist` (`.js`, `.js.map`, `.source-hash`) и
   сгенерированные контракты идут в том же коммите, что и смена версии, —
   они лежат в гите и именно они уезжают в реестр.

7. **Тег и пуш.**

   ```bash
   git tag -a vX.Y.Z -m "Release X.Y.Z"
   git push origin main && git push origin vX.Y.Z
   ```

8. **Дальше воркфлоу сам.** Пуш тега `v*` запускает
   `.github/workflows/publish.yml`: он собирает фронтенд заново, публикует
   пакет в реестр ComfyUI и создаёт релиз на GitHub с текстом из
   `CHANGELOG.md`. Ничего вручную создавать не нужно.

9. **Проверить результат.**

   - CI на `main` зелёный и воркфлоу публикации отработал:
     https://github.com/FiL-Design-Ai/FiL_Design_ImageMind/actions
   - Релиз появился на GitHub:
     https://github.com/FiL-Design-Ai/FiL_Design_ImageMind/releases
   - Проверить статус версии в реестре:

     ```powershell
     curl -s https://api.comfy.org/nodes/FiL_Design_ImageMind/versions
     ```

     У новой версии сначала появляется `"status": "NodeVersionStatusPending"`.
     Это нормально: архив уже в CDN, а сканер безопасности Comfy Org проводит
     аудит. Через некоторое время статус станет `NodeVersionStatusActive`.
     Если появился `NodeVersionStatusFlagged` — значит, сработал фильтр
     безопасности (см. грабли ниже).

## Грабли, уже стоившие выпуска

- **Сборка до смены номера версии.** Номер версии попадает в
  `package-lock.json`, лок входит в отпечаток исходников, отпечаток
  сверяется в CI. Релиз 1.1.2 вышел с красным CI ровно поэтому: бандл был
  собран правильный, но отпечаток описывал предыдущий лок.

- **Сорсмап должен уезжать в архив.** `frontend/dist/fil_design_imagemind.js` —
  это минифицированный код, а `frontend/src/` в архив не идёт. Без
  карты (`.js.map`) реестр видит нечитаемый код и помечает версию как
  подозрительную (`NodeVersionStatusFlagged`): 1.0.0 карту возил и остался Active,
  1.1.0 первым её исключил и получил Flagged, 1.1.1 унаследовал.
  В `.comfyignore` стоит явный запрет на исключение `.map`.

- **Импорт ComfyUI в модулях контрактов.** Скрипт `scripts/dump_contracts.py`
  запускается в CI на легковесном раннере без ComfyUI и Torch (`npm run check:contracts`).
  Если модуль из `common/contracts/nodes/` сделает прямой или косвенный импорт
  из `comfy` (например, импортируя константы из тяжелого вычислительного модуля
  вроде `krea2_engine.py`), проверка в CI упадет с `ModuleNotFoundError: No module named 'comfy'`.
  Контракты должны быть изолированными и легковесными!

- **Синхронизация списков моделей.** В `common/config.py` список
  `RECOMMENDED_VISION_MODELS[provider]` обязан быть строгим подмножеством
  `RECOMMENDED_MODELS[provider]`. Иначе упадет юнит-тест
  `test_the_curated_vision_set_stays_inside_the_curated_list`.

- **Изоляция тестов от API-ключей.** В тестах рантайма (`tests/test_provider_runtime.py`)
  всегда используйте `monkeypatch` для `get_api_key` и `HTTPClient`.
  В окружении GitHub Actions ключей нет в переменных окружения, и неотмоканный
  вызов вернет статус `configured` с пустым списком моделей вместо fallback.

- **Тег — это не релиз.** Тег только помечает коммит. Страница релиза на
  GitHub создаётся отдельно шагом в `publish.yml` на основе `CHANGELOG.md`.

- **Страница издателя в реестре кэширует / показывает Pending.**
  После публикации версия попадает в статус `NodeVersionStatusPending`. До тех пор,
  пока сканер Comfy Org не сменит его на `NodeVersionStatusActive`, на витрине
  в поле `latest_version` отображается предыдущая стабильная версия.

- **Версию из реестра нельзя перевыпустить.** Опубликованная версия
  неизменяема. Повторный пуш того же тега в git упадет в `publish.yml`
  с ошибкой существования версии. Ошиблись — бампаем патч-номер (`1.1.5`).
  Старую при необходимости можно пометить устаревшей: публичная карточка пакета →
  у версии `More` → тумблер `Deprecate version`.
