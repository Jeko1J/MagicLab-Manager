# Работа с Git

`main` — версия для передачи. `develop` — следующие изменения.
Ветки `codex/feature-*` используются для отдельных задач и сливаются
через merge-коммит. Наличие ветки само по себе не означает прохождения тестов.

## Новая задача

```powershell
git switch develop
git switch -c codex/feature-task-name
# Изменить код и запустить тесты.
git status
git diff
git add app/имя_файла.py tests/имя_теста.py
git diff --cached
git commit -m "Кратко описать сделанное изменение"
git switch develop
git merge --no-ff codex/feature-task-name
```

Перед выпуском проверьте тесты и сборку, затем слейте develop в main.
Исправления опубликованной версии оформляйте новыми коммитами.

## Публикация

Создайте пустой репозиторий GitHub без автоматически добавленных README
и лицензии. Выберите приватный доступ, если публикация кода или логотипа
не согласована. Подставьте адрес своего репозитория:

```powershell
git remote add origin https://github.com/USER/REPOSITORY.git
git push -u origin main
git push -u origin develop
```

Feature-ветки отправляются отдельно: `git push origin ИМЯ_ВЕТКИ`.
Локальные слияния не создают Pull Request на GitHub.
Автор и почта каждого коммита видны получателям репозитория.

Перед отправкой проверьте `git status`, `git diff --cached` и `git ls-files`.
Базы, фотографии клиентов, копии, выгрузки, отчёты, переписка и окружение
не должны попадать в репозиторий. Gitignore не удаляет уже отслеживаемые файлы.

## Просмотр истории

```powershell
git log --graph --oneline --all --decorate
git branch
git show HEAD
```
