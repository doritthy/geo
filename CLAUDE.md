# CLAUDE.md — контекст проекта для новых сессий

## Что это

Веб-платформа **цифрового двойника строительства** для BI Group (Казахстан): BIM (IFC, RVT
через Autodesk APS), облака точек, фотограмметрия и ГИС в одной геопривязанной 3D-сцене
(CesiumJS). Разрабатывается по ТЗ заказчика. Рядом живёт старый модуль «Subsurface 3D»
(геология) — его не ломать.

Прочитать в первую очередь:
1. `docs/tz/TZ.md` — техническое задание (исходник `docs/tz/TZ_digital_twin_v1.docx`).
2. `docs/ROADMAP.md` — статус по каждому пункту ТЗ, следующие шаги, вопросы к заказчику.
3. `docs/TWIN.md` — архитектура двойника, геопривязка, API, ограничения.

Язык общения с пользователем и интерфейса — **русский**. Пользователь — R&D, не обязательно
разработчик: объяснять просто, честно говорить, что проверено, а что нет.

## Структура

```
apps/api/app/
  twin/            конвертеры → OGC 3D Tiles: ifc_convert.py, pointcloud_convert.py, mesh_convert.py,
                   tiles.py (writers glb/b3dm/pnts/tileset), georef.py (PROJ, ECEF, якорь, world matrix), jobs.py;
                   анализы: tile_reader.py (чтение своих тайлов), deviation.py, icp.py, analysis_jobs.py,
                   report.py (PDF); schedule.py (импорт графика, SPI)
  integrations/    aps.py (клиент APS), autodesk_service.py (импорт из ACC), secrets.py (шифрование токенов)
  routers/         assets.py (слои, тайлы, элементы, сравнение), annotations.py, documents.py,
                   crs.py, autodesk.py, analyses.py, issues.py, schedule.py, dashboard.py,
                   organization.py + старые геологические роутеры
  notify.py        email (SMTP; в тестах notify.outbox)
  push.py          Web Push (VAPID; в тестах push.outbox), подписки — routers/push.py
  progress.py      прогресс конвертаций → files.metadata.progress
  queue.py, worker.py  фоновые задачи: JOB_MODE=inline (BackgroundTasks) | queue (таблица jobs + воркер);
                   новые фоновые работы — только через queue.enqueue(kind, payload, background_tasks)
  parsers/         vector_parser.py (GeoJSON/KML/DXF/GPKG) + геологические парсеры
  jobs.py          диспетчер фоновой обработки загрузок (twin-категории → twin/jobs.py)
apps/api/scripts/make_demo_data.py   демо: здание IFC v1/v2 (IfcMapConversion, EPSG:32642), скан LAZ (плита 3 с прогибом 4 см),
                                     участок GeoJSON, график MS Project XML
apps/api/scripts/seed_demo.py        заливает демо в работающий инстанс через API (вкл. график и анализ)
apps/api/tests/  test_twin.py, test_autodesk.py (мок APS), test_analyses.py, test_issues.py, test_schedule.py,
                 twin_fixtures.py + старые тесты
apps/web/
  app/twin/[projectId]/page.tsx       рабочее место двойника
  app/twin/[projectId]/dashboard/     дашборд проекта
  components/twin/                    CesiumViewer.tsx (ядро сцены) + панели (Layers, Search, Issues, Annotations,
                                      Documents, Compare, Analysis, Schedule, Autodesk, Settings, Upload, Properties)
  lib/twin/                           api.ts, store.ts (zustand), types.ts, measure.ts, crs.ts (proj4)
infra/db/schema.sql + infra/db/twin.sql   схема (twin.sql идемпотентный, применяется вторым)
```

## Ключевые решения (не менять без причины)

- Все 3D-данные → **OGC 3D Tiles 1.0** (b3dm для BIM/mesh, pnts для облаков); тайлы раздаёт API
  (`/api/assets/{id}/tiles/...`) с проверкой доступа; клиент — CesiumJS с заголовком Authorization.
- BIM: 1 элемент IFC = 1 feature (batch table: GlobalId, IfcType, Name, Storey); раскраска/скрытие
  элементов на клиенте через `feature.color/show` при загрузке тайла (`styleContent`).
- Геопривязка: `absolute` (точный пересчёт в ECEF через PROJ) или `anchor` (локальная модель +
  lon/lat/height/heading/scale на клиенте через modelMatrix). Плоскость не используем — нужна
  точность для дорог/сетей.
- Без токена Cesium ion глобус поднимается до уровня площадки (`CustomHeightmapTerrainProvider`).
- Версии моделей — `scene_assets.version_group` + `version`; сравнение по GlobalId и хэшам.
  Связи с элементами (задачи графика) хранятся по `version_group` — переживают новые версии модели.
- Мировая матрица слоя = `alignment` (ICP) · (anchor | offset_enu) — одинаково на сервере
  (`georef.asset_world_matrix`) и в клиенте (`modelMatrixFor`). Менять только синхронно.
- Раскраска элементов из разных режимов (сравнение, отклонения, 4D) идёт через
  `store.elementColors` → `styleContent` в `CesiumViewer`.
- Результаты анализов — обычные `scene_assets` с `stats.analysis_id` (по умолчанию скрыты).
- Cesium зафиксирован: `cesium@1.140.0` + `overrides` для `@cesium/engine@24.0.0`,
  `@cesium/widgets@14.5.0` (иначе несовместимые версии ломают сборку). Ассеты копирует
  `scripts/copy-cesium.js` (postinstall) в `public/cesium` (в .gitignore).

## Команды

```bash
# Бэкенд-тесты (нужен Postgres с PostGIS на 127.0.0.1:5432, роль subsurface/subsurface;
# S3 поднимается автоматически через moto)
cd apps/api && python -m pytest -q

# Фронтенд
cd apps/web && npm install && npx tsc --noEmit && npx next build

# Весь стек
docker compose up --build        # web :3000, api :8000 (/docs — Swagger)
docker compose exec api python scripts/make_demo_data.py /app/demo_data

# Демо в работающий инстанс
python scripts/make_demo_data.py /tmp/demo && python scripts/seed_demo.py --data /tmp/demo

# Валидация тайлов
npx 3d-tiles-validator@0.6.0 --tilesetFile <dir>/tileset.json
```

В облачной песочнице Claude: Postgres ставится `apt-get install postgresql-16-postgis-3`,
`service postgresql start`, создать роль `subsurface` (SUPERUSER, пароль subsurface).
Python-зависимости — в venv (`pip install -r requirements.txt -r requirements-dev.txt`).

## Грабли, на которые уже наступали

- **pnts + RTC_CENTER**: не задавать тайлу `transform`, если позиции уже относительно
  RTC_CENTER — смещение применится дважды (облако улетает). Есть регрессионный тест.
- **Cookies Model Derivative** (`signedcookies`) выставлены на домен CDN — cookie jar httpx их
  отбрасывает; пересылаем `Set-Cookie` вручную.
- **x-ads-force** не использовать для версий ACC — удалит их derivatives.
- Ключ бакета OSS — только `[a-z0-9_]`.
- В песочнице `pkill -f <шаблон>` убивает и собственный shell, если шаблон есть в команде —
  искать PID через `ps`.
- После правок бэкенда перезапускать uvicorn (или `--reload`), иначе проверяется старый код.
- IfcOpenShell тесселирует многопоточно — порядок элементов/треугольников между запусками разный;
  алгоритмы не должны зависеть от порядка (была нестабильность ICP).
- При добавлении таблиц: дописать в `infra/db/twin.sql` (идемпотентно), в модели, и в список
  TRUNCATE в `tests/conftest.py`; локальную demo-БД обновить `psql -f infra/db/twin.sql`.
- Docker Hub в песочнице отдаёт 429 — базовые образы через `mirror.gcr.io/library/...`;
  внутри сборки pip не доверяет CA прокси (только в песочнице, у пользователя всё нормально).
- Headless Chromium для скриншотов: `/opt/pw-browsers/chromium` с `--headless=new`,
  `--use-angle=swiftshader`; в dev-режиме объект `window.__twin` даёт доступ к viewer и тайлсетам.

## Прогресс длинных задач

Конвертеры вызывают `app.progress.report("Этап", доля)` в своих циклах; задача оборачивается в
`progress.track(file_id)`. Запись идёт отдельной транзакцией в `files.metadata.progress` (не чаще 1 раза/с),
UI (`LayersPanel` → `FileProgress`) показывает этап и полосу. Новые этапы — добавить перевод в `i18n.kk.ts`.

## Локализация (ru / kk)

- Исходный язык UI — русский. Каждую новую строку интерфейса оборачивайте в `tr('…')` из `@/lib/i18n`
  и добавляйте перевод в `apps/web/lib/i18n.kk.ts` (ключ = русский текст). Нет перевода — показывается русский.
- Язык хранится в cookie `lang`; смена — перезагрузка страницы (`setLang`). Сервер всегда рендерит русский,
  поэтому при `lang=kk` `app/layout.tsx` оборачивает страницу в `LangGate` (рендер только после mount — без hydration mismatch).
- `tr()` вызывается при рендере или на уровне модуля (язык фиксирован на время жизни страницы).

## Правила работы

- Ветка разработки задаётся в сессии; коммиты с понятными сообщениями, пушить по завершении.
- Перед пушем: `pytest`, `tsc --noEmit`, `next build`; для UI — проверка в браузере со скриншотами.
- Новые пункты ТЗ — обновлять таблицу статусов и журнал в `docs/ROADMAP.md` в том же коммите.
- Не утверждать, что выполнен критерий ТЗ, если он не измерен на реальных данных.
