# Academic data schema and importer

Этот каталог содержит схему PostgreSQL, миграции, temporal/provenance-модель, контракты, правила и классификацию предметов, а также CLI для проверки и импорта уже собранного bundle. HTTP API и сайт отсутствуют.

## Установка

Из этого каталога установите пакет в виртуальное окружение Python 3.11+:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

На Linux/macOS активируйте `.venv/bin/activate`.

## Проверка существующей выгрузки без БД

Из корня репозитория:

```powershell
academic-data bundle validate --input data/bmstu-2026
academic-data bundle import --input data/bmstu-2026 --dry-run
```

Dry-run валидирует и сопоставляет данные, не открывая соединение с PostgreSQL. Он не меняет схему или строки.

## Миграции и запись

CLI `academic-data db upgrade` применяет миграции к настроенной базе, а `bundle import --commit` записывает и публикует release. Не запускайте их против production без подготовленного резервного копирования и корректных настроек подключения. Примеры конфигурации и требования к целевому PostgreSQL описаны в `docs/data-model.md`, `docs/data-model-and-history.md`, `docs/import.md` и `docs/architecture.md`. DSN в репозитории отсутствуют.

## Ключевые части

- `migrations/versions/` — история схемы.
- `src/academic_data_service/infrastructure/database/` — SQLAlchemy-модели и доступ к БД.
- `domain/rules.py` — логика требований, включая AND/OR/AT_LEAST.
- `classification/` — предметная таксономия и адаптер для классификации JEV.
- `importer/` — проверка bundle, mapping и явный импорт.
- `contracts/v1/` — контракты данных.
